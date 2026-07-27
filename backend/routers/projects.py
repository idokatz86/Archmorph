"""Project routes backed by owner/tenant-scoped PostgreSQL state."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request

from database import get_db
from error_envelope import ArchmorphException
from iac_generator import generate_iac_code
from project_merge import merge_project_analyses
from project_store import (
    add_project_member,
    get_project,
    list_project_members,
    load_project_analyses,
    remove_project_member,
)
from routers.iac_routes import _check_architecture_blockers
from routers.shared import (
    PROJECT_STORE,
    get_request_durable_principal,
    limiter,
    verify_api_key_or_user_session,
)
from strict_models import StrictBaseModel
from usage_metrics import record_event, record_funnel_step

router = APIRouter()


class ProjectMemberRequest(StrictBaseModel):
    """A directory-verified project member assignment."""

    user_id: str
    role: Literal["viewer", "editor"] = "viewer"


def _principal(request: Request) -> dict:
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise ArchmorphException(401, "Authenticated tenant context is required")
    return principal


def _not_found() -> ArchmorphException:
    return ArchmorphException(404, "Project not found")


def _combined_analysis_for_project(db, project_id: str, principal: dict) -> dict:
    project = get_project(
        db,
        project_id,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
        project_store=PROJECT_STORE,
    )
    if project is None:
        raise _not_found()
    analyses = load_project_analyses(
        db,
        project_id,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
    )
    if not analyses:
        raise ArchmorphException(404, "No analyzed diagrams found for this project")
    return merge_project_analyses(project_id, analyses)


@router.get("/api/projects/{project_id}")
@limiter.limit("30/minute")
async def get_project_status(
    request: Request,
    project_id: str,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    """Return authorized project metadata and durable diagram status."""
    principal = _principal(request)
    project = get_project(
        db,
        project_id,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
        project_store=PROJECT_STORE,
    )
    if project is None:
        raise _not_found()
    return project


@router.get("/api/projects/{project_id}/analysis")
@limiter.limit("15/minute")
async def get_project_analysis(
    request: Request,
    project_id: str,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    """Return a deterministic merge of authorized durable analysis snapshots."""
    combined = _combined_analysis_for_project(db, project_id, _principal(request))
    record_event("project_analysis_merged", {
        "project_id": project_id,
        "diagrams": len(combined.get("source_diagram_ids", [])),
        "services": combined.get("services_detected", 0),
    })
    return combined


@router.post("/api/projects/{project_id}/generate")
@limiter.limit("5/minute")
async def generate_project_iac(
    request: Request,
    project_id: str,
    format: Literal["terraform", "bicep"] = "terraform",
    force: bool = False,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    """Generate IaC only from authorized, PostgreSQL-canonical analyses."""
    combined = _combined_analysis_for_project(db, project_id, _principal(request))
    _check_architecture_blockers(f"project-{project_id}", combined, force)
    try:
        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=combined,
            iac_format=format,
            params=combined.get("iac_parameters", {}),
        )
    except Exception as exc:
        raise ArchmorphException(500, "Project IaC generation failed. Please try again.") from exc
    record_event(f"project_iac_generated_{format}", {"project_id": project_id})
    record_funnel_step(f"project-{project_id}", "iac_generate")
    return {"project_id": project_id, "format": format, "code": code, "analysis": combined}


@router.get("/api/projects/{project_id}/members")
@limiter.limit("30/minute")
async def get_project_members(
    request: Request,
    project_id: str,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    principal = _principal(request)
    members = list_project_members(
        db,
        project_id,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
    )
    if members is None:
        raise _not_found()
    return {"project_id": project_id, "members": members}


@router.put("/api/projects/{project_id}/members/{member_user_id}")
@limiter.limit("20/minute")
async def put_project_member(
    request: Request,
    project_id: str,
    member_user_id: str,
    body: ProjectMemberRequest,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    principal = _principal(request)
    if body.user_id != member_user_id:
        raise ArchmorphException(400, "Path and body member identity must match")
    try:
        member = add_project_member(
            db,
            project_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
            member_user_id=member_user_id,
            role=body.role,
        )
    except ValueError as exc:
        raise ArchmorphException(400, "Member must belong to the project tenant") from exc
    if member is None:
        raise _not_found()
    return {"project_id": project_id, "member": member.to_dict()}


@router.delete("/api/projects/{project_id}/members/{member_user_id}")
@limiter.limit("20/minute")
async def delete_project_member(
    request: Request,
    project_id: str,
    member_user_id: str,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    principal = _principal(request)
    removed = remove_project_member(
        db,
        project_id,
        member_user_id,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
    )
    if removed is None:
        raise _not_found()
    if not removed:
        raise ArchmorphException(404, "Project member not found")
    return {"project_id": project_id, "member_user_id": member_user_id, "status": "removed"}
