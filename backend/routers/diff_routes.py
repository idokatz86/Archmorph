from error_envelope import ArchmorphException
"""
Architecture Diff & Version Comparison routes.

Version snapshots and diffing for analysis results.
"""

from fastapi import APIRouter, Depends, Request, Query
from functools import partial
from pydantic import Field
from strict_models import StrictBaseModel
from typing import Optional
import logging

from database import SessionLocal
from durable_purge_fence import PurgeFenceUnavailableError, PurgedScopeError
from routers.shared import limiter, persist_diagram_mutation_async, require_diagram_access, verify_api_key
from starlette.concurrency import run_in_threadpool
from versioning import compare_versions, create_version, get_version

logger = logging.getLogger(__name__)

router = APIRouter()


def _transient_call(function, /, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (PurgeFenceUnavailableError, PurgedScopeError) as exc:
        raise ArchmorphException(404, "Diagram not found") from exc


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


async def _durable_call_async(request: Request, diagram_id: str, function):
    return await run_in_threadpool(partial(_durable_call, request, diagram_id, function))


class SaveVersionRequest(StrictBaseModel):
    label: Optional[str] = Field(None, max_length=200)


class BranchRequest(StrictBaseModel):
    label: Optional[str] = Field(None, max_length=200)


@router.post("/api/diagrams/{diagram_id}/versions/save", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def save_version(
    request: Request,
    diagram_id: str,
    body: Optional[SaveVersionRequest] = None,
    _auth=Depends(verify_api_key),
    analysis=Depends(require_diagram_access),
):
    """Save current analysis state as a new version snapshot."""
    label = body.label if body else None
    from routers.shared import has_canonical_durable_principal

    if has_canonical_durable_principal(request):
        result = await persist_diagram_mutation_async(
            request,
            diagram_id,
            analysis,
            label=label or "manual-version",
        )
        version = result.version
        return {
            "version": version.version_number,
            "version_number": version.version_number,
            "diagram_id": diagram_id,
            "label": version.label,
            "created_at": version.created_at.isoformat(),
        }
    version = _transient_call(create_version, diagram_id, analysis, message=label)
    return {
        "version": version.version_number,
        "version_number": version.version_number,
        "diagram_id": diagram_id,
        "label": version.message,
        "created_at": version.created_at.isoformat(),
        "compatibility": "transient-anonymous-or-sample-version-store",
    }


# ─────────────────────────────────────────────────────────────
# Diff
# ─────────────────────────────────────────────────────────────

@router.get("/api/diagrams/{diagram_id}/diff", dependencies=[Depends(require_diagram_access)])
@limiter.limit("20/minute")
async def diff_versions(
    request: Request,
    diagram_id: str,
    v1: int = Query(..., ge=1),
    v2: int = Query(..., ge=1),
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Compare two version snapshots and return a structured diff."""
    if v1 == v2:
        raise ArchmorphException(400, "Cannot diff a version with itself")

    from workspace_store import compare_analysis_versions

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
        diff = _transient_call(compare_versions, diagram_id, v1, v2)
        diff["compatibility"] = "transient-anonymous-or-sample-version-store"
    if "error" in diff:
        raise ArchmorphException(404, "One or both versions not found")
    return diff


# ─────────────────────────────────────────────────────────────
# What-If Branching
# ─────────────────────────────────────────────────────────────

@router.post("/api/diagrams/{diagram_id}/versions/{version}/branch", dependencies=[Depends(require_diagram_access)])
@limiter.limit("10/minute")
async def branch_version(
    request: Request,
    diagram_id: str,
    version: int,
    body: Optional[BranchRequest] = None,
    _auth=Depends(verify_api_key),
    _session=Depends(require_diagram_access),
):
    """Fork a version for what-if analysis."""
    label = body.label if body else None
    from workspace_store import get_analysis_version

    durable = await _durable_call_async(
        request,
        diagram_id,
        lambda db, user, analysis: (
            user,
            int(analysis.current_version or 0),
            get_analysis_version(
                db,
                analysis_id=analysis.id,
                version_number=version,
                owner_user_id=user["owner_user_id"],
                tenant_id=user["tenant_id"],
            ),
        ),
    )
    if durable is not None:
        _user, current_version, source = durable
        if source is None:
            raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
        import json

        result = await persist_diagram_mutation_async(
            request,
            diagram_id,
            json.loads(source.snapshot),
            label=label or f"Branch from version {version}",
            expected_version=current_version,
            restored_from=version,
        )
        branched = result.version
        return {
            "version": branched.version_number,
            "version_number": branched.version_number,
            "diagram_id": diagram_id,
            "label": branched.label,
            "created_at": branched.created_at.isoformat(),
            "branched_from": version,
        }
    source = _transient_call(get_version, diagram_id, version)
    if source is None:
        raise ArchmorphException(404, f"Version {version} not found for diagram {diagram_id}")
    branched = _transient_call(
        create_version,
        diagram_id,
        source.snapshot,
        message=label or f"Branch from version {version}",
    )
    return {
        "version": branched.version_number,
        "version_number": branched.version_number,
        "diagram_id": diagram_id,
        "label": branched.message,
        "created_at": branched.created_at.isoformat(),
        "branched_from": version,
        "compatibility": "transient-anonymous-or-sample-version-store",
    }
