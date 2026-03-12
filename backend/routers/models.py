from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from database import get_db
from routers.auth import get_current_user
from rbac import RequireRole
from models.model_registry import ModelEndpoint

router = APIRouter(prefix="/api/models", tags=["Model Registry"])

class ModelEndpointCreateSchema(BaseModel):
    name: str
    provider: str
    model_version: str
    connection_config: Dict[str, Any]
    capabilities: Optional[Dict[str, Any]] = {}
    pricing: Optional[Dict[str, float]] = {}

class ModelEndpointResponseSchema(BaseModel):
    id: str
    name: str
    provider: str
    model_version: str
    is_active: bool
    capabilities: Dict[str, Any]
    pricing: Dict[str, Any]
    
    class Config:
        from_attributes = True

@router.post("/", response_model=ModelEndpointResponseSchema, status_code=status.HTTP_201_CREATED)
def register_model(payload: ModelEndpointCreateSchema, db: Session = Depends(get_db), user: dict = Depends(RequireRole(['admin', 'super_admin']))):
    org_id = user.get("org_id", "default_org")
    
    endpoint = ModelEndpoint(
        organization_id=org_id,
        name=payload.name,
        provider=payload.provider,
        model_version=payload.model_version,
        connection_config=payload.connection_config,
        capabilities=payload.capabilities,
        pricing=payload.pricing
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint

@router.get("/", response_model=List[ModelEndpointResponseSchema])
def list_models(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    org_id = user.get("org_id", "default_org")
    return db.query(ModelEndpoint).filter(ModelEndpoint.organization_id == org_id).all()

@router.delete("/{model_id}")
def delete_model(model_id: str, db: Session = Depends(get_db), user: dict = Depends(RequireRole(['admin', 'super_admin']))):
    org_id = user.get("org_id", "default_org")
    endpoint = db.query(ModelEndpoint).filter(
        ModelEndpoint.id == model_id,
        ModelEndpoint.organization_id == org_id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Model endpoint not found")
        
    db.delete(endpoint)
    db.commit()
    return {"status": "success"}
