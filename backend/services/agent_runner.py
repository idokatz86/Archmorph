import asyncio
import json
import time
from contextlib import suppress
from typing import Awaitable, TypeVar

from actor_context import ActorContext
from models.agent import Agent
from models.execution import Execution
from database import SessionLocal
from services.execution_state import transition_execution
from services.model_router import ModelRouter
from services.tool_registry import tool_registry


ResultT = TypeVar("ResultT")


class ExecutionCancellationRequested(Exception):
    """Raised when the persisted execution state requests cooperative cancellation."""


class AgentRunner:
    """
    Executes an AI Agent run asynchronously.
    """

    def __init__(self, execution_id: str, actor_context: ActorContext):
        self.execution_id = execution_id
        self.actor_context = actor_context

    def _cancellation_requested(self) -> bool:
        db = SessionLocal()
        try:
            status = db.query(Execution.status).filter(
                Execution.id == self.execution_id,
                Execution.organization_id == str(self.actor_context.tenant_id),
            ).scalar()
            return status in {"cancel_requested", "cancelled"}
        finally:
            db.close()

    def _raise_if_cancellation_requested(self) -> None:
        if self._cancellation_requested():
            raise ExecutionCancellationRequested

    def _acknowledge_cancellation(self) -> bool:
        db = SessionLocal()
        try:
            return transition_execution(
                db,
                self.execution_id,
                from_statuses=("cancel_requested",),
                to_status="cancelled",
                organization_id=str(self.actor_context.tenant_id),
            )
        finally:
            db.close()

    async def _run_cancellable(self, operation: Awaitable[ResultT]) -> ResultT:
        operation_task = asyncio.ensure_future(operation)
        try:
            while True:
                done, _ = await asyncio.wait({operation_task}, timeout=0.05)
                if operation_task in done:
                    return await operation_task
                if self._cancellation_requested():
                    operation_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await operation_task
                    raise ExecutionCancellationRequested
        except asyncio.CancelledError:
            operation_task.cancel()
            with suppress(asyncio.CancelledError):
                await operation_task
            raise

    async def run(self):
        organization_id = str(self.actor_context.tenant_id)

        # ── Phase 1: load execution + agent, then release DB ──
        db = SessionLocal()
        try:
            claimed = transition_execution(
                db,
                self.execution_id,
                from_statuses=("queued",),
                to_status="running",
                organization_id=organization_id,
            )
            if not claimed:
                print(f"[AgentRunner] Execution {self.execution_id} is not runnable.")
                return

            execution = db.query(Execution).filter(
                Execution.id == self.execution_id,
                Execution.organization_id == organization_id,
            ).one()

            agent = db.query(Agent).filter(
                Agent.id == execution.agent_id,
                Agent.organization_id == organization_id,
            ).first()
            if not agent:
                transition_execution(
                    db,
                    self.execution_id,
                    from_statuses=("running",),
                    to_status="failed",
                    organization_id=organization_id,
                    values={"error_message": "Agent not found"},
                )
                return

            # Snapshot all data needed for model call — then close DB
            input_data = execution.input_data or {}
            messages = input_data.get("messages", [])
            session_token = input_data.get("session_token")
            sys_msg = (
                agent.model_config_data.get("system_prompt", "You are a helpful assistant.")
                if agent.model_config_data
                else "You are a helpful assistant."
            )
            temperature = (
                agent.model_config_data.get("temperature", 0.7)
                if agent.model_config_data
                else 0.7
            )
            agent_tools = agent.tools or []
        finally:
            db.close()  # release before any model call

        # ── Phase 2: model calls (no DB session held) ──
        db2 = SessionLocal()
        try:
            model_client = ModelRouter(db2, organization_id).route("default")
        finally:
            db2.close()

        llm_messages = [{"role": "system", "content": sys_msg}] + messages

        # Setup Tools
        formatted_tools = list(tool_registry.get_schemas())
        for tool in agent_tools:
            existing_names = [t.get("function", {}).get("name") for t in formatted_tools]
            if tool.get("function", {}).get("name") not in existing_names:
                formatted_tools.append(tool)

        start_time = time.time()

        try:
            # Execute Model via abstracted Client
            self._raise_if_cancellation_requested()
            response = await self._run_cancellable(
                model_client.chat(
                    messages=llm_messages,
                    tools=formatted_tools if formatted_tools else None,
                    temperature=temperature,
                )
            )

            # Simple tool calling execution loop
            message = response.choices[0].message
            content = message.content or ""

            # Check if it called a tool — execute all tool calls concurrently
            if getattr(message, 'tool_calls', None):
                async def _run_tool(tool_call):
                    self._raise_if_cancellation_requested()
                    return await self._run_cancellable(
                        tool_registry.execute(
                            tool_call.function.name,
                            tool_call.function.arguments,
                            actor_context=self.actor_context,
                            session_token=session_token,
                        )
                    )

                tool_results = await asyncio.gather(
                    *[_run_tool(tc) for tc in message.tool_calls],
                    return_exceptions=True,
                )
                if any(
                    isinstance(result, ExecutionCancellationRequested)
                    for result in tool_results
                ):
                    raise ExecutionCancellationRequested

                llm_messages.append(message)
                for tc, result_json in zip(message.tool_calls, tool_results):
                    if isinstance(result_json, Exception):
                        result_json = json.dumps({"error": f"{tc.function.name} failed: {result_json}"})
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": result_json,
                    })

                # Second call to get final response
                self._raise_if_cancellation_requested()
                response = await self._run_cancellable(
                    model_client.chat(
                        messages=llm_messages,
                        temperature=temperature,
                    )
                )
                message = response.choices[0].message
                content = message.content or ""

            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)

            prompt_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
            completion_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0

            # ── Phase 3: write result back to DB ──
            db3 = SessionLocal()
            try:
                completed = transition_execution(
                    db3,
                    self.execution_id,
                    from_statuses=("running",),
                    to_status="completed",
                    organization_id=organization_id,
                    values={
                        "output_data": {"message": content},
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                        "duration_ms": duration_ms,
                        "steps": [
                            {
                                "type": "llm_call",
                                "duration": duration_ms,
                                "tokens": prompt_tokens + completion_tokens,
                            }
                        ],
                    },
                )
            finally:
                db3.close()

            if completed:
                print(f"[AgentRunner] Finished execution {self.execution_id}")
            elif self._acknowledge_cancellation():
                print(f"[AgentRunner] Cancelled execution {self.execution_id}")
            else:
                print(f"[AgentRunner] Execution {self.execution_id} was no longer running.")

        except ExecutionCancellationRequested:
            self._acknowledge_cancellation()
            print(f"[AgentRunner] Cancelled execution {self.execution_id}")
        except Exception as e:
            db4 = SessionLocal()
            try:
                failed = transition_execution(
                    db4,
                    self.execution_id,
                    from_statuses=("running",),
                    to_status="failed",
                    organization_id=organization_id,
                    values={"error_message": str(e)},
                )
            finally:
                db4.close()
            if failed:
                print(
                    f"[AgentRunner] Failed execution {self.execution_id} "
                    f"error_type={type(e).__name__}"
                )
            else:
                self._acknowledge_cancellation()
