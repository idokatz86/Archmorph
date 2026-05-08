from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import ConfigDict
from strict_models import StrictBaseModel

from database import get_db
from routers.shared import require_authenticated_user_context
from rbac import RequireRole
from models.model_registry import ModelEndpoint

router = APIRouter(prefix="/api/models", tags=["Model Registry"])

class ModelEndpointCreateSchema(StrictBaseModel):
    name: str
    provider: str
    model_version: str
    connection_config: Dict[str, Any]
    capabilities: Optional[Dict[str, Any]] = {}
    pricing: Optional[Dict[str, float]] = {}

class ModelEndpointResponseSchema(StrictBaseModel):
    id: str
    name: str
    provider: str
    model_version: str
    is_active: bool
    capabilities: Dict[str, Any]
    pricing: Dict[str, Any]
    
    model_config = ConfigDict(from_attributes=True)

@router.post("/", response_model=ModelEndpointResponseSchema, status_code=status.HTTP_201_CREATED)
def register_model(payload: ModelEndpointCreateSchema, db: Session = Depends(get_db), user: dict = Depends(RequireRole(['admin', 'super_admin']))):
    org_id = user.tenant_id
    
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
def list_models(db: Session = Depends(get_db), user: dict = Depends(require_authenticated_user_context)):
    org_id = user["org_id"]
    return db.query(ModelEndpoint).filter(ModelEndpoint.organization_id == org_id).all()

@router.delete("/{model_id}")
def delete_model(model_id: str, db: Session = Depends(get_db), user: dict = Depends(RequireRole(['admin', 'super_admin']))):
    org_id = user.tenant_id
    endpoint = db.query(ModelEndpoint).filter(
        ModelEndpoint.id == model_id,
        ModelEndpoint.organization_id == org_id
    ).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Model endpoint not found")
        
    db.delete(endpoint)
    db.commit()
    return {"status": "success"}
