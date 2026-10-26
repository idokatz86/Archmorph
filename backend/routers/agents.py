from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from actor_context import ActorContext, require_actor_context
from database import get_db
from models.agent import Agent, AgentVersion
from pydantic import ConfigDict
from services.tenant_service import roles_have_permission
from strict_models import StrictBaseModel
import uuid
import datetime


def utc_now_naive() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

router = APIRouter(prefix="/agents", tags=["agents"])

AGENT_READ_PERMISSION = "analysis:read"
AGENT_EDIT_PERMISSION = "analysis:create"
AGENT_DELETE_PERMISSION = "analysis:delete"


def require_agent_permission(actor: ActorContext, permission: str) -> None:
    if not roles_have_permission(actor.roles, permission):
        raise HTTPException(status_code=403, detail="Insufficient tenant permissions")


def tenant_agent_query(db: Session, actor: ActorContext):
    return db.query(Agent).filter(Agent.organization_id == str(actor.tenant_id))


def get_tenant_agent(
    db: Session,
    actor: ActorContext,
    agent_id: str,
    *,
    include_archived: bool = False,
) -> Agent:
    query = tenant_agent_query(db, actor).filter(Agent.id == agent_id)
    if not include_archived:
        query = query.filter(Agent.status != "archived")
    agent = query.first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

# Pydantic schemas
class ModelConfigSchema(StrictBaseModel):
    provider: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str

class MemoryConfigSchema(StrictBaseModel):
    short_term: dict
    long_term: dict

class AgentCreateSchema(StrictBaseModel):
    name: str
    description: Optional[str] = None
    organization_id: Optional[str] = None
    model_config_data: Optional[ModelConfigSchema] = None
    tools: List[dict] = []
    data_sources: List[dict] = []
    memory_config: Optional[MemoryConfigSchema] = None

class AgentUpdateSchema(StrictBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model_config_data: Optional[ModelConfigSchema] = None
    tools: Optional[List[dict]] = None
    data_sources: Optional[List[dict]] = None
    memory_config: Optional[MemoryConfigSchema] = None

class AgentResponseSchema(StrictBaseModel):
    id: str
    name: str
    description: Optional[str]
    version: str
    status: str
    organization_id: str

    model_config = ConfigDict(from_attributes=True)

@router.post("", response_model=AgentResponseSchema, status_code=201)
def create_agent(
    agent_data: AgentCreateSchema,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    tenant_id = str(actor.tenant_id)
    if agent_data.organization_id and agent_data.organization_id != tenant_id:
        raise HTTPException(status_code=403, detail="Organization does not match authenticated tenant")
    require_agent_permission(actor, AGENT_EDIT_PERMISSION)

    new_agent = Agent(
        id=str(uuid.uuid4()),
        organization_id=tenant_id,
        name=agent_data.name,
        description=agent_data.description,
        version="1.0.0",
        status="draft",
        model_config_data=agent_data.model_config_data.model_dump() if agent_data.model_config_data else {},
        tools=agent_data.tools,
        data_sources=agent_data.data_sources,
        memory_config=agent_data.memory_config.model_dump() if agent_data.memory_config else {},
        created_by=actor.actor_id,
    )

    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    
    # Save initial version
    version_record = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=new_agent.id,
        version=new_agent.version,
        config_snapshot={
            "model_config_data": new_agent.model_config_data,
            "tools": new_agent.tools,
            "data_sources": new_agent.data_sources,
            "memory_config": new_agent.memory_config
        },
        created_by=actor.actor_id,
    )
    db.add(version_record)
    db.commit()

    return new_agent

@router.get("", response_model=List[AgentResponseSchema])
def list_agents(
    organization_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    actor: ActorContext = Depends(require_actor_context),
):
    if organization_id and organization_id != str(actor.tenant_id):
        raise HTTPException(status_code=403, detail="Organization does not match authenticated tenant")
    require_agent_permission(actor, AGENT_READ_PERMISSION)
    agents = (
        tenant_agent_query(db, actor)
        .filter(Agent.status != "archived")
        .offset(skip)
        .limit(limit)
        .all()
    )
    return agents

@router.get("/{agent_id}", response_model=AgentResponseSchema)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    agent = get_tenant_agent(db, actor, agent_id)
    require_agent_permission(actor, AGENT_READ_PERMISSION)
    return agent

@router.put("/{agent_id}", response_model=AgentResponseSchema)
def update_agent(
    agent_id: str,
    agent_data: AgentUpdateSchema,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    agent = get_tenant_agent(db, actor, agent_id)
    require_agent_permission(actor, AGENT_EDIT_PERMISSION)

    # Bump version simplistic logic: bump minor
    parts = agent.version.split('.')
    minor = int(parts[1]) + 1
    new_version = f"{parts[0]}.{minor}.{parts[2]}"

    if agent_data.name is not None:
        agent.name = agent_data.name
    if agent_data.description is not None:
        agent.description = agent_data.description
    if agent_data.model_config_data is not None:
        agent.model_config_data = agent_data.model_config_data.model_dump()
    if agent_data.tools is not None:
        agent.tools = agent_data.tools
    if agent_data.data_sources is not None:
        agent.data_sources = agent_data.data_sources
    if agent_data.memory_config is not None:
        agent.memory_config = agent_data.memory_config.model_dump()
        
    agent.version = new_version
    agent.updated_at = utc_now_naive()
    db.commit()
    db.refresh(agent)
    
    # Save new version history
    version_record = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version=new_version,
        config_snapshot={
            "model_config_data": agent.model_config_data,
            "tools": agent.tools,
            "data_sources": agent.data_sources,
            "memory_config": agent.memory_config
        },
        created_by=actor.actor_id,
    )
    db.add(version_record)
    db.commit()

    return agent

@router.delete("/{agent_id}")
def archive_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    agent = get_tenant_agent(db, actor, agent_id, include_archived=True)
    require_agent_permission(actor, AGENT_DELETE_PERMISSION)
    
    agent.status = "archived"
    db.commit()
    return {"message": "Agent archived successfully"}

@router.patch("/{agent_id}/status")
def update_agent_status(
    agent_id: str,
    status: str = Query(...),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    if status not in ["draft", "active", "paused", "archived"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    agent = get_tenant_agent(db, actor, agent_id, include_archived=True)
    require_agent_permission(actor, AGENT_DELETE_PERMISSION)
        
    agent.status = status
    db.commit()
    return {"message": f"Agent status changed to {status}"}

@router.get("/{agent_id}/versions")
def list_agent_versions(
    agent_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    get_tenant_agent(db, actor, agent_id, include_archived=True)
    require_agent_permission(actor, AGENT_READ_PERMISSION)
    versions = (
        db.query(AgentVersion)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .filter(
            AgentVersion.agent_id == agent_id,
            Agent.organization_id == str(actor.tenant_id),
        )
        .order_by(AgentVersion.created_at.desc())
        .limit(200)
        .all()
    )
    return versions

@router.post("/{agent_id}/clone")
def clone_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(require_actor_context),
):
    agent = get_tenant_agent(db, actor, agent_id, include_archived=True)
    require_agent_permission(actor, AGENT_EDIT_PERMISSION)
        
    new_agent = Agent(
        id=str(uuid.uuid4()),
        organization_id=agent.organization_id,
        name=agent.name + " (Clone)",
        description=agent.description,
        version="1.0.0",
        status="draft",
        model_config_data=agent.model_config_data,
        tools=agent.tools,
        data_sources=agent.data_sources,
        memory_config=agent.memory_config,
        created_by=actor.actor_id,
    )
    
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)
    
    version_record = AgentVersion(
        id=str(uuid.uuid4()),
        agent_id=new_agent.id,
        version=new_agent.version,
        config_snapshot={
            "model_config_data": new_agent.model_config_data,
            "tools": new_agent.tools,
            "data_sources": new_agent.data_sources,
            "memory_config": new_agent.memory_config
        },
        created_by=actor.actor_id,
    )
    db.add(version_record)
    db.commit()

    return new_agent
