"""
Sub-Agent Orchestrator — Multi-agent workflow engine (HLD §5.6).

Enables parent agents to spawn and coordinate child agent executions
via directed acyclic graphs (DAGs). Supports sequential chains,
fan-out/fan-in patterns, and conditional branching.

Security: Each sub-agent inherits the parent's org_id isolation.
          Circuit breakers prevent runaway cascades.
          Total depth is hard-capped.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Configuration limits
# ─────────────────────────────────────────────────────────────
MAX_DAG_DEPTH = 3          # Maximum parent→child nesting depth
MAX_STEPS_PER_WORKFLOW = 10  # Maximum steps in a single workflow
MAX_CONCURRENT_BRANCHES = 5  # Maximum parallel fan-out branches
STEP_TIMEOUT_SECONDS = 60    # Per-step timeout


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"


@dataclass
class StepResult:
    step_id: str
    status: StepStatus
    output: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    tokens_used: int = 0


@dataclass
class WorkflowStep:
    """A single step in a workflow DAG."""
    id: str
    agent_id: str
    input_template: str  # Message template with {prev_output} placeholders
    depends_on: List[str] = field(default_factory=list)  # Step IDs this depends on
    condition: Optional[str] = None  # "always" | "on_success" | "on_failure"
    timeout_seconds: int = STEP_TIMEOUT_SECONDS

    def __post_init__(self):
        if not self.condition:
            self.condition = "on_success"


@dataclass
class Workflow:
    """A DAG of agent execution steps."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_agent_id: str = ""
    organization_id: str = ""
    steps: List[WorkflowStep] = field(default_factory=list)
    shared_context: Dict[str, Any] = field(default_factory=dict)
    depth: int = 0  # Current nesting depth
    status: WorkflowStatus = WorkflowStatus.PENDING


class SubAgentOrchestrator:
    """
    Executes multi-agent workflows defined as step DAGs.

    Usage:
        orchestrator = SubAgentOrchestrator(agent_executor=my_execute_fn, org_id="org-123")
        workflow = Workflow(
            parent_agent_id="agent-001",
            organization_id="org-123",
            steps=[
                WorkflowStep(id="s1", agent_id="agent-research", input_template="Research: {query}"),
                WorkflowStep(id="s2", agent_id="agent-writer", input_template="Write based on: {s1_output}", depends_on=["s1"]),
            ]
        )
        results = await orchestrator.execute(workflow)
    """

    def __init__(
        self,
        agent_executor: Callable,
        org_id: str,
    ):
        """
        Parameters
        ----------
        agent_executor : callable
            Async function with signature:
            async def execute(agent_id: str, message: str, org_id: str) -> dict
            Must return {"output": str, "tokens": int, "status": str}
        org_id : str
            Organization ID for tenant isolation.
        """
        self._execute = agent_executor
        self._org_id = org_id

    def _validate_workflow(self, workflow: Workflow) -> None:
        """Validate DAG structure before execution."""
        if workflow.depth >= MAX_DAG_DEPTH:
            raise ValueError(
                f"Workflow depth {workflow.depth} exceeds maximum {MAX_DAG_DEPTH}. "
                f"Sub-agents cannot spawn unbounded child workflows."
            )

        if len(workflow.steps) > MAX_STEPS_PER_WORKFLOW:
            raise ValueError(
                f"Workflow has {len(workflow.steps)} steps, maximum is {MAX_STEPS_PER_WORKFLOW}."
            )

        if len(workflow.steps) == 0:
            raise ValueError("Workflow must have at least one step.")

        # Validate DAG (no cycles)
        step_ids = {s.id for s in workflow.steps}
        for step in workflow.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.id}' depends on unknown step '{dep}'.")
                if dep == step.id:
                    raise ValueError(f"Step '{step.id}' cannot depend on itself.")

        # Check for cycles via topological sort attempt
        self._topological_sort(workflow.steps)

    def _topological_sort(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        """Return steps in topological order. Raises ValueError on cycle."""
        in_degree = {s.id: len(s.depends_on) for s in steps}
        step_map = {s.id: s for s in steps}
        dependents = {s.id: [] for s in steps}

        for step in steps:
            for dep in step.depends_on:
                dependents[dep].append(step.id)

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        ordered = []

        while queue:
            sid = queue.pop(0)
            ordered.append(step_map[sid])
            for dependent_id in dependents[sid]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(ordered) != len(steps):
            raise ValueError("Workflow DAG contains a cycle.")

        return ordered

    def _resolve_template(
        self,
        template: str,
        step_results: Dict[str, StepResult],
        shared_context: Dict[str, Any],
    ) -> str:
        """Resolve {placeholders} in step input templates."""
        resolved = template

        # Replace {step_id_output} with actual outputs
        for step_id, result in step_results.items():
            placeholder = f"{{{step_id}_output}}"
            output_str = str(result.output or "") if result.status == StepStatus.COMPLETED else "(step failed)"
            resolved = resolved.replace(placeholder, output_str)

        # Replace {shared.key} with shared context
        for key, value in shared_context.items():
            resolved = resolved.replace(f"{{shared.{key}}}", str(value))

        # Replace {prev_output} with the most recent completed step
        completed = [r for r in step_results.values() if r.status == StepStatus.COMPLETED]
        if completed:
            last_output = str(completed[-1].output or "")
            resolved = resolved.replace("{prev_output}", last_output)

        return resolved

    def _should_execute(self, step: WorkflowStep, step_results: Dict[str, StepResult]) -> bool:
        """Check if step's condition is met based on dependency results."""
        if not step.depends_on:
            return True

        for dep_id in step.depends_on:
            dep_result = step_results.get(dep_id)
            if not dep_result:
                return False

            if step.condition == "on_success" and dep_result.status != StepStatus.COMPLETED:
                return False
            if step.condition == "on_failure" and dep_result.status not in (StepStatus.FAILED, StepStatus.TIMED_OUT):
                return False
            # "always" runs regardless of dependency status

        return True

    async def _execute_step(
        self,
        step: WorkflowStep,
        step_results: Dict[str, StepResult],
        shared_context: Dict[str, Any],
    ) -> StepResult:
        """Execute a single workflow step with timeout."""
        start = time.perf_counter()

        if not self._should_execute(step, step_results):
            return StepResult(step_id=step.id, status=StepStatus.SKIPPED)

        message = self._resolve_template(step.input_template, step_results, shared_context)

        try:
            result = await asyncio.wait_for(
                self._execute(
                    agent_id=step.agent_id,
                    message=message,
                    org_id=self._org_id,
                ),
                timeout=step.timeout_seconds,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)

            return StepResult(
                step_id=step.id,
                status=StepStatus.COMPLETED,
                output=result.get("output", ""),
                duration_ms=duration_ms,
                tokens_used=result.get("tokens", 0),
            )

        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.warning("Step %s timed out after %dms", step.id, duration_ms)
            return StepResult(
                step_id=step.id,
                status=StepStatus.TIMED_OUT,
                error=f"Step timed out after {step.timeout_seconds}s",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error("Step %s failed: %s", step.id, exc)
            return StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                error=str(exc)[:500],
                duration_ms=duration_ms,
            )

    async def execute(self, workflow: Workflow) -> Dict[str, Any]:
        """Execute a workflow DAG and return aggregated results.

        Steps are executed in topological order. Steps with no remaining
        dependencies are executed concurrently (fan-out capped at
        MAX_CONCURRENT_BRANCHES).
        """
        self._validate_workflow(workflow)
        workflow.status = WorkflowStatus.RUNNING

        step_results: Dict[str, StepResult] = {}
        ordered_steps = self._topological_sort(workflow.steps)
        step_map = {s.id: s for s in ordered_steps}

        # Group steps by execution wave (steps whose deps are all resolved)
        remaining = set(s.id for s in ordered_steps)
        total_tokens = 0
        total_duration = 0

        while remaining:
            # Find steps ready to execute (all deps resolved)
            ready = []
            for sid in list(remaining):
                step = step_map[sid]
                if all(dep not in remaining for dep in step.depends_on):
                    ready.append(step)

            if not ready:
                # Deadlock — should not happen after topological sort
                logger.error("Workflow deadlock detected: remaining=%s", remaining)
                break

            # Cap concurrent fan-out
            batch = ready[:MAX_CONCURRENT_BRANCHES]

            # Execute batch concurrently
            tasks = [
                self._execute_step(step, step_results, workflow.shared_context)
                for step in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=False)

            for result in results:
                step_results[result.step_id] = result
                remaining.discard(result.step_id)
                total_tokens += result.tokens_used
                total_duration += result.duration_ms

        # Determine overall status
        statuses = [r.status for r in step_results.values()]
        if all(s == StepStatus.COMPLETED for s in statuses):
            workflow.status = WorkflowStatus.COMPLETED
        elif all(s in (StepStatus.FAILED, StepStatus.TIMED_OUT) for s in statuses):
            workflow.status = WorkflowStatus.FAILED
        elif any(s == StepStatus.FAILED for s in statuses):
            workflow.status = WorkflowStatus.PARTIALLY_COMPLETED
        else:
            workflow.status = WorkflowStatus.COMPLETED

        return {
            "workflow_id": workflow.id,
            "status": workflow.status.value,
            "steps": {
                sid: {
                    "status": r.status.value,
                    "output": r.output,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                    "tokens_used": r.tokens_used,
                }
                for sid, r in step_results.items()
            },
            "total_tokens": total_tokens,
            "total_duration_ms": total_duration,
            "depth": workflow.depth,
        }
