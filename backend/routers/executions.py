from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict

from database import get_db
from routers.auth import get_current_user
from models.agent import Agent
from models.execution import Execution
from services.agent_runner import AgentRunner
from fastapi import BackgroundTasks

router = APIRouter(prefix="/api/executions", tags=["Executions"])

class ExecutionInputSchema(BaseModel):
    agent_id: str
    messages: List[Dict[str, Any]]
    thread_id: Optional[str] = None
    stream: bool = False

class ExecutionResponseSchema(BaseModel):
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
    db: Session = Depends(get_db), 
    user: dict = Depends(get_current_user)
):
    """
    Start a new execution for a specific agent.
    """
    org_id = user.get("org_id", "default_org")
    
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
    session_token = user.get("session_token")
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
    runner = AgentRunner(execution_id=execution.id)
    background_tasks.add_task(runner.run)
    
    return execution

@router.get("/{execution_id}", response_model=ExecutionResponseSchema)
async def get_execution(
    execution_id: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    org_id = user.get("org_id", "default_org")
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
    user: dict = Depends(get_current_user)
):
    org_id = user.get("org_id", "default_org")
    execution = db.query(Execution).filter(
        Execution.id == execution_id,
        Execution.organization_id == org_id
    ).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    
    if execution.status in ["completed", "failed", "cancelled"]:
        raise HTTPException(status_code=400, detail="Execution is already finished")
        
    execution.status = "cancelled"
    db.commit()
    db.refresh(execution)
    
    return {"status": "success", "message": "Execution cancelled"}
