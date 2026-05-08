from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from pydantic import ConfigDict
from strict_models import StrictBaseModel

from database import get_db
from routers.shared import require_authenticated_user_context
from models.agent import Agent
from models.memory import AgentMemoryDocument, AgentEpisodicMemory, AgentEntityMemory

router = APIRouter(prefix="/api/agents/{agent_id}/memory", tags=["Agent Memory"])

class DocumentResponseSchema(StrictBaseModel):
    id: str
    filename: str
    file_type: str
    status: str
    chunk_count: int
    
    model_config = ConfigDict(from_attributes=True)

class EpisodeResponseSchema(StrictBaseModel):
    id: str
    summary: str
    importance_score: float
    tags: List[str]
    
    model_config = ConfigDict(from_attributes=True)

class EntityResponseSchema(StrictBaseModel):
    id: str
    entity_name: str
    entity_type: str
    attributes: Dict[str, Any]
    
    model_config = ConfigDict(from_attributes=True)

def _get_agent_verified(agent_id: str, db: Session, user: dict):
    org_id = user["org_id"]
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.organization_id == org_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@router.get("/documents", response_model=List[DocumentResponseSchema])
def list_documents(agent_id: str, db: Session = Depends(get_db), user: dict = Depends(require_authenticated_user_context)):
    _get_agent_verified(agent_id, db, user)
    docs = db.query(AgentMemoryDocument).filter(AgentMemoryDocument.agent_id == agent_id).all()
    return docs

@router.delete("/documents/{doc_id}")
def delete_document(agent_id: str, doc_id: str, db: Session = Depends(get_db), user: dict = Depends(require_authenticated_user_context)):
    _get_agent_verified(agent_id, db, user)
    doc = db.query(AgentMemoryDocument).filter(AgentMemoryDocument.agent_id == agent_id, AgentMemoryDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    # also we would want to prune from vector store
    db.delete(doc)
    db.commit()
    return {"status": "success", "message": "Document removed"}

@router.get("/episodes", response_model=List[EpisodeResponseSchema])
def list_episodes(agent_id: str, db: Session = Depends(get_db), user: dict = Depends(require_authenticated_user_context)):
    _get_agent_verified(agent_id, db, user)
    episodes = db.query(AgentEpisodicMemory).filter(AgentEpisodicMemory.agent_id == agent_id).all()
    return episodes

@router.get("/entities", response_model=List[EntityResponseSchema])
def list_entities(agent_id: str, db: Session = Depends(get_db), user: dict = Depends(require_authenticated_user_context)):
    _get_agent_verified(agent_id, db, user)
    entities = db.query(AgentEntityMemory).filter(AgentEntityMemory.agent_id == agent_id).all()
    return entities

@router.delete("/")
def clear_memory(agent_id: str, db: Session = Depends(get_db), user: dict = Depends(require_authenticated_user_context)):
    _get_agent_verified(agent_id, db, user)
    db.query(AgentMemoryDocument).filter(AgentMemoryDocument.agent_id == agent_id).delete()
    db.query(AgentEpisodicMemory).filter(AgentEpisodicMemory.agent_id == agent_id).delete()
    db.query(AgentEntityMemory).filter(AgentEntityMemory.agent_id == agent_id).delete()
    db.commit()
    # also call vector store to prune vectors by agent_id
    return {"status": "success", "message": "All memory cleared"}
