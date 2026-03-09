from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from database import get_db
from auth import get_current_user
from models.policy import AgentPolicy, AgentPolicyBinding

router = APIRouter(prefix="/api/policies", tags=["Policies"])

class PolicyCreateSchema(BaseModel):
    name: str
    description: Optional[str] = None
    policy_type: str
    rules: Dict[str, Any]
    enforcement_level: str = "block"

class PolicyResponseSchema(BaseModel):
    id: str
    name: str
    description: Optional[str]
    policy_type: str
    rules: Dict[str, Any]
    enforcement_level: str
    is_active: bool
    
    class Config:
        from_attributes = True

@router.post("/", response_model=PolicyResponseSchema, status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyCreateSchema, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    org_id = user.get("org_id", "default_org")
    
    policy = AgentPolicy(
        organization_id=org_id,
        name=payload.name,
        description=payload.description,
        policy_type=payload.policy_type,
        rules=payload.rules,
        enforcement_level=payload.enforcement_level
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy

@router.get("/", response_model=List[PolicyResponseSchema])
def list_policies(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    org_id = user.get("org_id", "default_org")
    return db.query(AgentPolicy).filter(AgentPolicy.organization_id == org_id).all()

@router.post("/{policy_id}/bind/{agent_id}")
def bind_policy(policy_id: str, agent_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    org_id = user.get("org_id", "default_org")
    # Verify policy
    policy = db.query(AgentPolicy).filter(AgentPolicy.id == policy_id, AgentPolicy.organization_id == org_id).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    binding = AgentPolicyBinding(agent_id=agent_id, policy_id=policy_id)
    db.add(binding)
    db.commit()
    return {"status": "success"}

@router.post("/{policy_id}/unbind/{agent_id}")
def unbind_policy(policy_id: str, agent_id: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    org_id = user.get("org_id", "default_org")
    binding = db.query(AgentPolicyBinding).join(AgentPolicy).filter(
        AgentPolicyBinding.agent_id == agent_id,
        AgentPolicyBinding.policy_id == policy_id,
        AgentPolicy.organization_id == org_id
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Binding not found")
        
    db.delete(binding)
    db.commit()
    return {"status": "success"}
