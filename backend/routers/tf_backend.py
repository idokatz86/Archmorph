import json
import logging
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from database import get_db
from models.deployment_state import DeploymentState
from error_envelope import ArchmorphException
from routers.shared import get_store, require_authenticated_user

LOCK_STORE = get_store("tf_locks", maxsize=500, ttl=3600)
OWNER_STORE = get_store("tf_state_owners", maxsize=2000, ttl=86400 * 30)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/terraform/state", tags=["Terraform State Backend"])


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def get_deployment_state(db: Session, project_id: str, environment: str):
    state = db.query(DeploymentState).filter(
        DeploymentState.project_id == project_id,
        DeploymentState.environment == environment
    ).first()
    if not state:
        state = DeploymentState(project_id=project_id, environment=environment, state_json={})
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _state_owner_key(project_id: str, environment: str) -> str:
    return f"{project_id}_{environment}"


def _enforce_state_owner(project_id: str, environment: str, user) -> None:
    key = _state_owner_key(project_id, environment)
    owner = OWNER_STORE.get(key)
    if owner is None:
        OWNER_STORE[key] = {
            "owner_user_id": user.id,
            "tenant_id": user.tenant_id,
        }
        return
    if owner.get("owner_user_id") != user.id or owner.get("tenant_id") != user.tenant_id:
        raise ArchmorphException(403, "Forbidden: state ownership mismatch")

@router.get("/{project_id}/{environment}")
async def get_tf_state(
    project_id: str,
    environment: str,
    db: Session = Depends(get_db),
    user=Depends(require_authenticated_user),
):
    _enforce_state_owner(project_id, environment, user)
    state = get_deployment_state(db, project_id, environment)
    if not state.state_json:
        return Response(content="{}", media_type="application/json")
    return Response(content=json.dumps(state.state_json), media_type="application/json")

@router.post("/{project_id}/{environment}")
async def update_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_authenticated_user),
):
    _enforce_state_owner(project_id, environment, user)
    state = get_deployment_state(db, project_id, environment)
    
    lock_id = request.query_params.get("ID")
    
    lock_key = f"{project_id}_{environment}"
    existing_lock = LOCK_STORE.get(lock_key)
    
    if existing_lock and existing_lock.get("ID") != lock_id:
        raise ArchmorphException(
            status_code=status.HTTP_423_LOCKED,
            message="State is locked by another process.",
            context={"lock_info": existing_lock}
        )
    
    payload = await request.json()
    
    state.previous_state_json = state.state_json
    state.state_json = payload
    state.updated_at = utc_now_naive()
    
    db.commit()
    return Response(status_code=200)

@router.api_route("/{project_id}/{environment}", methods=["LOCK"])
async def lock_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_authenticated_user),
):
    _enforce_state_owner(project_id, environment, user)
    state = get_deployment_state(db, project_id, environment)
    
    body = await request.body()
    lock_info = json.loads(body) if body else {}
    req_lock_id = lock_info.get("ID")
    
    lock_key = f"{project_id}_{environment}"
    existing_lock = LOCK_STORE.get(lock_key)
    
    if existing_lock:
        if existing_lock.get("ID") != req_lock_id:
            return Response(
                content=json.dumps(existing_lock),
                status_code=status.HTTP_423_LOCKED,
                media_type="application/json"
            )
        else:
            return Response(status_code=200)
            
    LOCK_STORE.set(lock_key, lock_info)
    
    state.lock_id = req_lock_id
    state.lock_info = lock_info
    state.locked_at = utc_now_naive()
    db.commit()
    
    return Response(status_code=200)

@router.api_route("/{project_id}/{environment}", methods=["UNLOCK", "UNLOCR"])
async def unlock_tf_state(
    project_id: str,
    environment: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_authenticated_user),
):
    _enforce_state_owner(project_id, environment, user)
    state = get_deployment_state(db, project_id, environment)
    
    body = await request.body()
    lock_info = json.loads(body) if body else {}
    req_lock_id = lock_info.get("ID")
    
    lock_key = f"{project_id}_{environment}"
    existing_lock = LOCK_STORE.get(lock_key)
    
    if existing_lock and existing_lock.get("ID") != req_lock_id:
        return Response(
            content=json.dumps(existing_lock),
            status_code=status.HTTP_423_LOCKED,
            media_type="application/json"
        )
        
    LOCK_STORE.delete(lock_key)
    
    state.lock_id = None
    state.lock_info = None
    state.locked_at = None
    db.commit()
    
    return Response(status_code=200)

@router.post("/{project_id}/{environment}/rollback")
async def rollback_state(
    project_id: str,
    environment: str,
    db: Session = Depends(get_db),
    user=Depends(require_authenticated_user),
):
    _enforce_state_owner(project_id, environment, user)
    state = get_deployment_state(db, project_id, environment)
    if not state.previous_state_json:
        raise ArchmorphException(
            status_code=400,
            message="No previous state available to rollback."
        )
    
    current_state = state.state_json
    state.state_json = state.previous_state_json
    state.previous_state_json = current_state
    db.commit()
    
    return {"status": "rolled_back", "environment": environment}
