from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import ConfigDict
from strict_models import StrictBaseModel

from actor_context import ActorContext, require_actor_context, require_actor_permission
from database import get_db
from routers.shared import get_bearer_token_from_headers
from models.agent import Agent
from models.execution import Execution
from services.agent_runner import AgentRunner
from services.execution_state import transition_execution
from fastapi import BackgroundTasks

router = APIRouter(prefix="/api/executions", tags=["Executions"])


class ExecutionInputSchema(StrictBaseModel):
    agent_id: str
    messages: List[Dict[str, Any]]
    thread_id: Optional[str] = None
    stream: bool = False

class ExecutionResponseSchema(StrictBaseModel):
    id: str
    agent_id: str
    thread_id: Optional[str] = None
    status: str
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

@router.post("/", response_model=ExecutionResponseSchema, status_code=status.HTTP_202_ACCEPTED)
async def start_execution(
    payload: ExecutionInputSchema,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    """
    Start a new execution for a specific agent.
    """
    require_actor_permission(actor, "analysis:create")
    org_id = str(actor.tenant_id)
    
    # 1. Fetch Agent (validate ownership)
    agent = db.query(Agent).filter(
        Agent.id == payload.agent_id,
        Agent.organization_id == org_id
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    if agent.status != "active":
        raise HTTPException(status_code=400, detail="Agent is not active")

    # 2. Create Execution Record
    session_token = get_bearer_token_from_headers(dict(request.headers))
    input_data = {"messages": payload.messages}
    if session_token:
        input_data["session_token"] = session_token

    execution = Execution(
        agent_id=payload.agent_id,
        organization_id=org_id,
        thread_id=payload.thread_id,
        status="queued",
        input_data=input_data,
        output_data=None
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    
    # 3. Schedule Background Execution
    runner = AgentRunner(execution_id=execution.id, actor_context=actor)
    background_tasks.add_task(runner.run)
    
    return execution

@router.get("/{execution_id}", response_model=ExecutionResponseSchema)
async def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    require_actor_permission(actor, "analysis:read")
    org_id = str(actor.tenant_id)
    execution = db.query(Execution).filter(
        Execution.id == execution_id,
        Execution.organization_id == org_id
    ).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    return execution

@router.post("/{execution_id}/cancel")
async def cancel_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    require_actor_permission(actor, "analysis:delete")
    org_id = str(actor.tenant_id)
    cancelled_immediately = transition_execution(
        db,
        execution_id,
        from_statuses=("queued",),
        to_status="cancelled",
        organization_id=org_id,
    )
    if cancelled_immediately:
        return {"status": "success", "message": "Execution cancelled"}

    cancellation_requested = transition_execution(
        db,
        execution_id,
        from_statuses=("running",),
        to_status="cancel_requested",
        organization_id=org_id,
    )
    if cancellation_requested:
        return {"status": "success", "message": "Execution cancellation requested"}

    exists = db.query(Execution.id).filter(
        Execution.id == execution_id,
        Execution.organization_id == org_id,
    ).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Execution not found")
    raise HTTPException(status_code=400, detail="Execution is already finished")
