from error_envelope import ArchmorphException
"""
Architecture Versioning routes (v2.9.0).
"""

from fastapi import APIRouter, Depends, Header, Query, Request
from functools import partial
from typing import Optional

from database import SessionLocal
from routers.shared import (
    SESSION_STORE,
    limiter,
    persist_diagram_mutation_async,
    require_api_read_or_user_session,
    require_api_write_or_user_session,
    require_diagram_access,
)
from starlette.concurrency import run_in_threadpool
from routers.workspaces import _expected_version
from versioning import (
    create_version, get_version_history, get_version,
    restore_version, compare_versions,
)
from workspace_store import (
    AnalysisVersionConflictError,
    compare_analysis_versions,
    get_analysis_version,
    list_analysis_versions,
    restore_analysis_version,
)

router = APIRouter()


def _durable_call(request: Request, diagram_id: str, function):
    from routers.shared import get_request_durable_principal, has_canonical_durable_principal

    principal = get_request_durable_principal(request)
    if not has_canonical_durable_principal(request):
        return None
    from workspace_store import get_analysis_by_diagram

    db = SessionLocal()
    try:
        analysis = get_analysis_by_diagram(
            db,
            diagram_id=diagram_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
        )
        if analysis is None and principal["owner_api_key_id"] is None:
            from project_store import PROJECT_READ_ROLES, resolve_diagram_access

            member_access = resolve_diagram_access(
                db,
                diagram_id,
                caller_user_id=principal["owner_user_id"],
                tenant_id=principal["tenant_id"],
                allowed_roles=PROJECT_READ_ROLES,
            )
            if member_access is not None:
                analysis, project, role = member_access
                principal = {
                    **principal,
                    "caller_user_id": principal["owner_user_id"],
                    "owner_user_id": project.owner_user_id,
                    "project_role": role,
                }
        if analysis is None:
            raise ArchmorphException(404, "Diagram not found")
        return function(db, principal, analysis)
    finally:
        db.close()


def _require_edit_role(principal: dict) -> None:
    role = principal.get("project_role")
    if role is not None and role not in {"owner", "admin", "editor"}:
        raise ArchmorphException(404, "Diagram not found")


def _restore_durable_version(
    db,
    principal: dict,
    analysis,
    *,
    version_number: int,
    expected_version: int,
    idempotency_key: str,
):
    _require_edit_role(principal)
    return restore_analysis_version(
        db,
        analysis_id=analysis.id,
        version_number=version_number,
        owner_user_id=principal["owner_user_id"],
        tenant_id=principal["tenant_id"],
        session_store=SESSION_STORE,
        cache_owner_api_key_id=principal["owner_api_key_id"],
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


async def _durable_call_async(request: Request, diagram_id: str, function):
    return await run_in_threadpool(
        partial(_durable_call, request, diagram_id, function)
    )


@router.post(
    "/api/diagrams/{diagram_id}/versions",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("10/minute")
async def create_version_endpoint(
    request: Request,
    diagram_id: str,
    message: Optional[str] = None,
    _auth=Depends(require_api_write_or_user_session),
    analysis=Depends(require_diagram_access),
):
    """Create a new version of an architecture analysis."""
    from routers.shared import has_canonical_durable_principal

    if has_canonical_durable_principal(request):
        result = await persist_diagram_mutation_async(
            request,
            diagram_id,
            analysis,
            label=message or "manual-version",
        )
        return result.version.to_dict()
    version = create_version(diagram_id=diagram_id, snapshot=analysis, message=message)
    return {
        **version.to_dict(),
        "compatibility": "transient-anonymous-or-sample-version-store",
    }


@router.get(
    "/api/diagrams/{diagram_id}/versions",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("30/minute")
async def get_version_history_endpoint(
    request: Request,
    diagram_id: str,
    _auth=Depends(require_api_read_or_user_session),
    _session=Depends(require_diagram_access),
):
    """Get version history for a diagram."""
    result = await _durable_call_async(
        request,
        diagram_id,
        lambda db, user, analysis: {
            "diagram_id": diagram_id,
            "current_version": analysis.current_version,
            "versions": list_analysis_versions(
                db,
                analysis_id=analysis.id,
                owner_user_id=user["owner_user_id"],
                tenant_id=user["tenant_id"],
            ),
        },
    )
    if result is None:
        return {**get_version_history(diagram_id), "compatibility": "transient-anonymous-or-sample-version-store"}
    versions = result["versions"]
    return {
            "diagram_id": result["diagram_id"],
            "current_version": result["current_version"],
            "total_versions": len(versions),
            "versions": versions,
            "timeline": [
                {
                    "version": item["version_number"],
                    "timestamp": item["created_at"],
                    "message": item["label"],
                    "changes_count": 0,
                }
                for item in versions
            ],
        }


@router.get("/api/diagrams/{diagram_id}/versions/{version_number}", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def get_version_endpoint(
    request: Request,
    diagram_id: str,
    version_number: int,
    _auth=Depends(require_api_read_or_user_session),
    _session=Depends(require_diagram_access),
):
    """Get a specific version of an architecture."""
    version = await _durable_call_async(
        request,
        diagram_id,
        lambda db, user, analysis: get_analysis_version(
            db,
            analysis_id=analysis.id,
            version_number=version_number,
            owner_user_id=user["owner_user_id"],
            tenant_id=user["tenant_id"],
        ),
    )
    if version is None:
        version = get_version(diagram_id, version_number)
        if not version:
            raise ArchmorphException(404, f"Version {version_number} not found")
        return {
            **version.to_dict(),
            "compatibility": "transient-anonymous-or-sample-version-store",
        }
    return version.to_dict(include_snapshot=True)


@router.post(
    "/api/diagrams/{diagram_id}/versions/{version_number}/restore",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("10/minute")
async def restore_version_endpoint(
    request: Request,
    diagram_id: str,
    version_number: int,
    if_match: str = Header(..., alias="If-Match"),
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=8, max_length=200
    ),
    _auth=Depends(require_api_write_or_user_session),
    _session=Depends(require_diagram_access),
):
    """Restore a previous version, creating a new version from it."""
    try:
        restored = await _durable_call_async(
            request,
            diagram_id,
            partial(
                _restore_durable_version,
                expected_version=_expected_version(if_match),
                idempotency_key=idempotency_key,
                version_number=version_number,
            ),
        )
    except AnalysisVersionConflictError as exc:
        raise ArchmorphException(409, str(exc)) from exc
    if restored is None:
        snapshot = restore_version(diagram_id, version_number)
        if not snapshot:
            raise ArchmorphException(404, f"Version {version_number} not found")
        SESSION_STORE[diagram_id] = snapshot
        return {
            "success": True,
            "restored_from": version_number,
            "compatibility": "transient-anonymous-or-sample-version-store",
        }
    return {
        "success": True,
        "restored_from": version_number,
        "new_version": restored.to_dict(),
    }


@router.get("/api/diagrams/{diagram_id}/versions/compare", dependencies=[Depends(require_diagram_access)])
@limiter.limit("30/minute")
async def compare_versions_endpoint(
    request: Request,
    diagram_id: str,
    v1: int = Query(..., description="First version number"),
    v2: int = Query(..., description="Second version number"),
    _auth=Depends(require_api_read_or_user_session),
    _session=Depends(require_diagram_access),
):
    """Compare two versions of an architecture."""
    diff = await _durable_call_async(
        request,
        diagram_id,
        lambda db, user, analysis: compare_analysis_versions(
            db,
            analysis_id=analysis.id,
            owner_user_id=user["owner_user_id"],
            tenant_id=user["tenant_id"],
            version_a=v1,
            version_b=v2,
        ),
    )
    if diff is None:
        return {
            **compare_versions(diagram_id, v1, v2),
            "compatibility": "transient-anonymous-or-sample-version-store",
        }
    return diff
