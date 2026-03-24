"""
Archmorph Agent PaaS — Proof of Concept Router (Issue #397).

Demonstrates the core AI Agent Platform-as-a-Service capabilities:
  - Agent registry (CRUD + tool attachment)
  - Execution engine with ReAct loop (Reason → Act → Observe)
  - RAG integration for grounded responses
  - Cost tracking per execution

Uses in-memory storage (dict-based) — same pattern as SESSION_STORE.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from agent_tools import (
    BUILTIN_TOOLS,
    execute_tool,
    get_tool_schemas,
)

from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent-paas", tags=["Agent PaaS PoC"])

# ─────────────────────────────────────────────────────────────
# Stores — Redis-backed in production (#494)
# ─────────────────────────────────────────────────────────────
AGENT_STORE = get_store("paas_agents", maxsize=500, ttl=0)  # No TTL for agents
EXECUTION_STORE = get_store("paas_executions", maxsize=1000, ttl=86400)  # 24h TTL

# GPT-4o pricing (per 1M tokens)
MODEL_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
}

MAX_REACT_ITERATIONS = 3


# ─────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    model: str = "gpt-4o"
    system_prompt: str = "You are a helpful AI assistant."
    rag_collections: List[str] = []

class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    rag_collections: Optional[List[str]] = None
    status: Optional[str] = None

class ToolAttach(BaseModel):
    tool_name: str

class ExecuteRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)

class AgentResponse(BaseModel):
    id: str
    name: str
    model: str
    system_prompt: str
    tools: List[str]
    rag_collections: List[str]
    status: str
    created_at: str
    updated_at: str

class ExecutionResponse(BaseModel):
    id: str
    agent_id: str
    user_message: str
    response: str
    tool_calls_made: List[Dict[str, Any]]
    token_usage: Dict[str, int]
    cost_usd: float
    execution_time_ms: float
    rag_context_used: bool
    created_at: str

class CostSummary(BaseModel):
    total_executions: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float
    per_agent: List[Dict[str, Any]]


# ─────────────────────────────────────────────────────────────
# Agent CRUD
# ─────────────────────────────────────────────────────────────

@router.post("/agents", response_model=AgentResponse, status_code=201)
async def create_agent(payload: AgentCreate):
    """Create a new agent with name, model, and system prompt."""
    now = datetime.now(timezone.utc).isoformat()
    agent_id = str(uuid.uuid4())
    agent = {
        "id": agent_id,
        "name": payload.name,
        "model": payload.model,
        "system_prompt": payload.system_prompt,
        "tools": [],
        "rag_collections": payload.rag_collections,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
    }
    AGENT_STORE[agent_id] = agent
    logger.info("Agent created: %s (%s)", str(payload.name).replace('\n', '').replace('\r', ''), agent_id)
    return agent


@router.get("/agents", response_model=List[AgentResponse])
async def list_agents():
    """List all agents (excludes archived)."""
    return [a for a in AGENT_STORE.values() if a["status"] != "archived"]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """Get a single agent by ID."""
    agent = AGENT_STORE.get(agent_id)
    if not agent or agent["status"] == "archived":
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, payload: AgentUpdate):
    """Update an agent's configuration."""
    agent = AGENT_STORE.get(agent_id)
    if not agent or agent["status"] == "archived":
        raise HTTPException(status_code=404, detail="Agent not found")

    if payload.name is not None:
        agent["name"] = payload.name
    if payload.model is not None:
        agent["model"] = payload.model
    if payload.system_prompt is not None:
        agent["system_prompt"] = payload.system_prompt
    if payload.rag_collections is not None:
        agent["rag_collections"] = payload.rag_collections
    if payload.status is not None:
        if payload.status not in ("draft", "active", "paused", "archived"):
            raise HTTPException(status_code=400, detail="Invalid status")
        agent["status"] = payload.status

    agent["updated_at"] = datetime.now(timezone.utc).isoformat()
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Archive an agent (soft delete)."""
    agent = AGENT_STORE.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent["status"] = "archived"
    agent["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"message": "Agent archived", "id": agent_id}


# ─────────────────────────────────────────────────────────────
# Tool attachment
# ─────────────────────────────────────────────────────────────

@router.post("/agents/{agent_id}/tools", status_code=201)
async def attach_tool(agent_id: str, payload: ToolAttach):
    """Attach a built-in tool to an agent."""
    agent = AGENT_STORE.get(agent_id)
    if not agent or agent["status"] == "archived":
        raise HTTPException(status_code=404, detail="Agent not found")

    if payload.tool_name not in BUILTIN_TOOLS:
        available = list(BUILTIN_TOOLS.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool '{payload.tool_name}'. Available: {available}",
        )

    if payload.tool_name in agent["tools"]:
        raise HTTPException(status_code=409, detail="Tool already attached")

    agent["tools"].append(payload.tool_name)
    agent["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {"message": f"Tool '{payload.tool_name}' attached", "tools": agent["tools"]}


@router.get("/agents/{agent_id}/tools")
async def list_agent_tools(agent_id: str):
    """List tools attached to an agent."""
    agent = AGENT_STORE.get(agent_id)
    if not agent or agent["status"] == "archived":
        raise HTTPException(status_code=404, detail="Agent not found")

    tools_detail = []
    for tool_name in agent["tools"]:
        schema = BUILTIN_TOOLS.get(tool_name, {})
        tools_detail.append({
            "name": tool_name,
            "description": schema.get("function", {}).get("description", ""),
        })
    return {"agent_id": agent_id, "tools": tools_detail}


# ─────────────────────────────────────────────────────────────
# Execution engine with ReAct loop
# ─────────────────────────────────────────────────────────────

def _calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate USD cost from token counts."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-4o"])
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def _fetch_rag_context(collection_ids: List[str], query: str) -> Optional[str]:
    """Search RAG collections for relevant context. Returns None if unavailable."""
    try:
        from rag_pipeline import VectorStore

        store = VectorStore.instance()
        results = store.search(query=query, collection_ids=collection_ids, top_k=3)
        if not results:
            return None

        context_parts = []
        for r in results:
            text = r.get("text", "")
            source = r.get("source_document", "unknown")
            score = r.get("score", 0)
            if text:
                context_parts.append(f"[Source: {source} | Relevance: {score:.2f}]\n{text}")

        if context_parts:
            return (
                "=== Retrieved Context (RAG) ===\n"
                + "\n---\n".join(context_parts)
                + "\n=== End Context ===\n"
            )
    except Exception as exc:
        logger.warning("RAG context retrieval failed (non-fatal): %s", exc)

    return None


@router.post("/agents/{agent_id}/execute", response_model=ExecutionResponse)
async def execute_agent(agent_id: str, payload: ExecuteRequest):
    """Execute an agent with a user message using a ReAct loop.

    1. Load agent config (system prompt, tools, RAG collections)
    2. If RAG collections configured, search for relevant context
    3. Build messages array: system prompt + RAG context + user message
    4. Call OpenAI with function calling (if tools attached)
    5. ReAct loop (max 3 iterations): tool calls → observe → re-call
    6. Track token usage and calculate cost
    """
    agent = AGENT_STORE.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent["status"] not in ("active", "draft"):
        raise HTTPException(status_code=400, detail=f"Agent status is '{agent['status']}', must be 'active' or 'draft'")

    start_time = time.perf_counter()
    execution_id = str(uuid.uuid4())

    # ── 1. Build system message ──
    system_content = agent["system_prompt"]

    # ── 2. RAG context injection ──
    rag_context_used = False
    if agent["rag_collections"]:
        rag_context = await asyncio.to_thread(
            _fetch_rag_context, agent["rag_collections"], payload.message
        )
        if rag_context:
            system_content += (
                "\n\nUse the following retrieved context to ground your response. "
                "Cite sources when possible.\n\n" + rag_context
            )
            rag_context_used = True

    # ── 3. Build messages ──
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": payload.message},
    ]

    # ── 4. Prepare tool schemas ──
    tool_schemas = get_tool_schemas(agent["tools"]) if agent["tools"] else None

    # ── 5. ReAct loop ──
    total_prompt_tokens = 0
    total_completion_tokens = 0
    tool_calls_made: List[Dict[str, Any]] = []

    client = get_openai_client()
    deployment = AZURE_OPENAI_DEPLOYMENT
    final_response = ""

    for iteration in range(MAX_REACT_ITERATIONS + 1):
        try:
            kwargs: Dict[str, Any] = {
                "model": deployment,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2048,
            }
            if tool_schemas and iteration < MAX_REACT_ITERATIONS:
                kwargs["tools"] = tool_schemas
                kwargs["tool_choice"] = "auto"

            completion = await asyncio.to_thread(
                lambda: openai_retry(client.chat.completions.create)(**kwargs)
            )
        except Exception as exc:
            logger.error("OpenAI call failed during agent execution: %s", exc)
            raise HTTPException(status_code=502, detail=f"AI model call failed: {exc}")

        # Track tokens
        usage = completion.usage
        if usage:
            total_prompt_tokens += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens

        choice = completion.choices[0]

        # ── Check for tool calls ──
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            # Add assistant message with tool calls to history
            messages.append(choice.message.model_dump())

            for tool_call in choice.message.tool_calls:
                fn_name = tool_call.function.name
                fn_args_str = tool_call.function.arguments

                try:
                    fn_args = json.loads(fn_args_str)
                except json.JSONDecodeError:
                    fn_args = {}

                # Execute the mock tool
                tool_result = await asyncio.to_thread(execute_tool, fn_name, fn_args)

                tool_calls_made.append({
                    "iteration": iteration + 1,
                    "tool": fn_name,
                    "arguments": fn_args,
                    "result_preview": tool_result[:200],
                })

                # Add tool result to messages for next iteration
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

            logger.info(
                "ReAct iteration %d: %d tool call(s)",
                iteration + 1,
                len(choice.message.tool_calls),
            )
            continue

        # ── Final text response ──
        final_response = choice.message.content or ""
        break
    else:
        # Exhausted iterations — use whatever we have
        if not final_response:
            final_response = "(Agent reached maximum tool-call iterations without producing a final response.)"

    # ── 6. Cost calculation ──
    model_key = agent["model"]
    cost = _calculate_cost(model_key, total_prompt_tokens, total_completion_tokens)

    # ── 6b. Record in central cost meter (Issue #392) ──
    try:
        from cost_metering import CostMeter
        CostMeter.instance().record(
            model=model_key,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            execution_id=execution_id,
            agent_id=agent_id,
            caller="agent_paas",
        )
    except Exception:
        pass  # Cost metering must never break execution

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # ── 7. Store execution record ──
    execution = {
        "id": execution_id,
        "agent_id": agent_id,
        "user_message": payload.message,
        "response": final_response,
        "tool_calls_made": tool_calls_made,
        "token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
        "cost_usd": cost,
        "execution_time_ms": round(elapsed_ms, 2),
        "rag_context_used": rag_context_used,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    EXECUTION_STORE[execution_id] = execution

    logger.info(
        "Agent execution complete: agent=%s exec=%s tools=%d tokens=%d cost=$%.6f time=%.0fms",
        str(agent_id).replace('\n', '').replace('\r', ''),
        execution_id,
        len(tool_calls_made),
        total_prompt_tokens + total_completion_tokens,
        cost,
        elapsed_ms,
    )

    return execution


# ─────────────────────────────────────────────────────────────
# Execution history
# ─────────────────────────────────────────────────────────────

@router.get("/agents/{agent_id}/executions", response_model=List[ExecutionResponse])
async def list_agent_executions(agent_id: str):
    """List past executions for an agent."""
    agent = AGENT_STORE.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return [e for e in EXECUTION_STORE.values() if e["agent_id"] == agent_id]


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_execution(execution_id: str):
    """Get details of a specific execution."""
    execution = EXECUTION_STORE.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


# ─────────────────────────────────────────────────────────────
# Cost tracking
# ─────────────────────────────────────────────────────────────

@router.get("/cost/summary", response_model=CostSummary)
async def cost_summary():
    """Get aggregate cost summary across all executions."""
    total_prompt = 0
    total_completion = 0
    total_cost = 0.0
    agent_costs: Dict[str, Dict[str, Any]] = {}

    for ex in EXECUTION_STORE.values():
        usage = ex["token_usage"]
        total_prompt += usage["prompt_tokens"]
        total_completion += usage["completion_tokens"]
        total_cost += ex["cost_usd"]

        aid = ex["agent_id"]
        if aid not in agent_costs:
            agent_name = AGENT_STORE.get(aid, {}).get("name", "unknown")
            agent_costs[aid] = {
                "agent_id": aid,
                "agent_name": agent_name,
                "executions": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_cost_usd": 0.0,
            }
        agent_costs[aid]["executions"] += 1
        agent_costs[aid]["prompt_tokens"] += usage["prompt_tokens"]
        agent_costs[aid]["completion_tokens"] += usage["completion_tokens"]
        agent_costs[aid]["total_cost_usd"] += ex["cost_usd"]

    # Round per-agent costs
    for ac in agent_costs.values():
        ac["total_cost_usd"] = round(ac["total_cost_usd"], 6)

    return {
        "total_executions": len(EXECUTION_STORE),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "total_cost_usd": round(total_cost, 6),
        "per_agent": list(agent_costs.values()),
    }


# ─────────────────────────────────────────────────────────────
# Available tools catalog
# ─────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_available_tools():
    """List all built-in tools available for attachment."""
    return {
        "tools": [
            {
                "name": name,
                "description": schema["function"]["description"],
                "parameters": schema["function"]["parameters"],
            }
            for name, schema in BUILTIN_TOOLS.items()
        ]
    }
