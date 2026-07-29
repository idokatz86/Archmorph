"""PostgreSQL-canonical, owner/tenant-scoped project repository."""

from __future__ import annotations

import json
import secrets
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.tenant import TeamMember
from models.workspace import (
    Analysis,
    AnalysisVersion,
    DiagramLifecycle,
    ProjectMember,
    SourceAsset,
    Workspace,
)


PROJECT_ID_PREFIX = "proj"
PROJECT_ID_BYTES = 18
PROJECT_CACHE_VERSION = 1
PROJECT_ROLES = frozenset({"viewer", "editor"})
PROJECT_READ_ROLES = frozenset({"owner", "admin", "viewer", "editor"})
PROJECT_EDIT_ROLES = frozenset({"owner", "admin", "editor"})
PROJECT_MANAGE_ROLES = frozenset({"owner", "admin"})


def generate_project_id() -> str:
    """Return a server-generated project identifier with at least 144 bits."""
    return f"{PROJECT_ID_PREFIX}-{secrets.token_urlsafe(PROJECT_ID_BYTES)}"


def _project_query(
    db: Session,
    *,
    project_id: str,
    owner_user_id: str,
    tenant_id: str,
):
    return db.query(Workspace).filter(
        Workspace.id == project_id,
        Workspace.owner_user_id == owner_user_id,
        Workspace.tenant_id == tenant_id,
        Workspace.status == "active",
        Workspace.is_default.is_(False),
    )


def resolve_project_access(
    db: Session,
    *,
    project_id: str,
    caller_user_id: str,
    tenant_id: str,
    lock_authorization: bool = False,
) -> Optional[tuple[Workspace, str]]:
    """Resolve owner or current member access without consulting Redis."""
    project_query = db.query(Workspace).filter(
        Workspace.id == project_id,
        Workspace.tenant_id == tenant_id,
        Workspace.status == "active",
        Workspace.is_default.is_(False),
    )
    if lock_authorization:
        project_query = project_query.with_for_update(read=True)
    project = project_query.first()
    if project is None:
        return None
    if project.owner_user_id == caller_user_id:
        return project, "owner"
    tenant_admin_query = db.query(TeamMember.id).filter(
        TeamMember.org_id == tenant_id,
        TeamMember.user_id == caller_user_id,
        TeamMember.role.in_(("owner", "admin")),
        TeamMember.is_active.is_(True),
    )
    if lock_authorization:
        tenant_admin_query = tenant_admin_query.with_for_update(read=True)
    tenant_admin = tenant_admin_query.first()
    if tenant_admin is not None:
        return project, "admin"
    member_query = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.project_owner_user_id == project.owner_user_id,
        ProjectMember.tenant_id == tenant_id,
        ProjectMember.member_user_id == caller_user_id,
        ProjectMember.role.in_(PROJECT_ROLES),
    )
    if lock_authorization:
        member_query = member_query.with_for_update(read=True)
    member = member_query.first()
    if member is None:
        return None
    return project, member.role


def require_project_access(
    db: Session,
    *,
    project_id: str,
    caller_user_id: str,
    tenant_id: str,
    allowed_roles: frozenset[str],
    lock_authorization: bool = False,
) -> Optional[tuple[Workspace, str]]:
    resolved = resolve_project_access(
        db,
        project_id=project_id,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        lock_authorization=lock_authorization,
    )
    if resolved is None or resolved[1] not in allowed_roles:
        return None
    return resolved


def _analysis_query(
    db: Session,
    *,
    project_id: str,
    owner_user_id: str,
    tenant_id: str,
):
    return db.query(Analysis).filter(
        Analysis.workspace_id == project_id,
        Analysis.owner_user_id == owner_user_id,
        Analysis.tenant_id == tenant_id,
    )


def _diagram_summary(analysis: Analysis) -> Dict[str, Any]:
    return {
        "diagram_id": analysis.diagram_id,
        "project_id": analysis.workspace_id,
        "filename": analysis.title,
        "size": None,
        "status": "analyzed" if int(analysis.current_version or 0) > 0 else "uploaded",
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "updated_at": analysis.updated_at.isoformat() if analysis.updated_at else None,
        "services_detected": int(analysis.services_detected or 0),
        "source_provider": analysis.source_cloud,
        "target_provider": analysis.target_cloud,
    }


def _project_version(analyses: List[Analysis]) -> int:
    """Create a monotonic-enough cache freshness marker from durable versions."""
    return sum(int(item.current_version or 0) for item in analyses) + len(analyses)


def _cache_project(
    project_store: Any,
    project: Dict[str, Any],
    *,
    owner_user_id: str,
    tenant_id: str,
) -> bool:
    if project_store is None:
        return False
    payload = {
        **project,
        "_cache_contract_version": PROJECT_CACHE_VERSION,
        "_owner_user_id": owner_user_id,
        "_tenant_id": tenant_id,
    }

    def _same_scope_and_not_newer(current: Any) -> bool:
        if current is None:
            return True
        if not isinstance(current, dict):
            return False
        try:
            current_version = int(current.get("project_version", -1))
        except (TypeError, ValueError):
            return False
        return bool(
            current.get("_cache_contract_version") == PROJECT_CACHE_VERSION
            and current.get("_owner_user_id") == owner_user_id
            and current.get("_tenant_id") == tenant_id
            and current_version <= int(project["project_version"])
        )

    try:
        updated, _current = project_store.update_if(
            project["project_id"],
            _same_scope_and_not_newer,
            lambda _current: payload,
        )
        return bool(updated)
    except Exception:
        return False


def create_project(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: str,
    name: str = "Architecture Project",
) -> Workspace:
    """Create a project with a server-generated, collision-retried identity."""
    if not owner_user_id or not tenant_id:
        raise ValueError("Project creation requires owner and tenant")
    last_error: Optional[IntegrityError] = None
    for _attempt in range(5):
        project = Workspace(
            id=generate_project_id(),
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            name=name,
            status="active",
            is_default=False,
        )
        db.add(project)
        try:
            db.commit()
            db.refresh(project)
            return project
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    raise RuntimeError("Unable to allocate a unique project identity") from last_error


def acquire_project(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: str,
    project_id: Optional[str] = None,
    name: str = "Architecture Project",
) -> Workspace:
    """Return an authorized existing project or create a server-owned one."""
    if project_id:
        project = _project_query(
            db,
            project_id=project_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ).first()
        if project is not None:
            return project
    return create_project(
        db,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        name=name,
    )


def get_project(
    db: Session,
    project_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
    project_store: Any = None,
    allowed_roles: frozenset[str] = PROJECT_READ_ROLES,
) -> Optional[Dict[str, Any]]:
    """Load an authorized project from PostgreSQL and refresh cache projection."""
    resolved = require_project_access(
        db,
        project_id=project_id,
        caller_user_id=owner_user_id,
        tenant_id=tenant_id,
        allowed_roles=allowed_roles,
    )
    if resolved is None:
        return None
    project, role = resolved
    analyses = (
        _analysis_query(
            db,
            project_id=project_id,
            owner_user_id=project.owner_user_id,
            tenant_id=tenant_id,
        )
        .order_by(Analysis.diagram_id.asc())
        .all()
    )
    diagrams = [_diagram_summary(item) for item in analyses if item.diagram_id]
    project_version = _project_version(analyses)
    result = {
        "project_id": project.id,
        "role": role,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "project_version": project_version,
        "diagram_ids": [item["diagram_id"] for item in diagrams],
        "diagrams": diagrams,
        "combined_analysis": None,
        "combined_status": (
            "empty"
            if not diagrams
            else "ready"
            if all(item["status"] == "analyzed" for item in diagrams)
            else "stale"
        ),
    }
    _cache_project(
        project_store,
        result,
        owner_user_id=project.owner_user_id,
        tenant_id=tenant_id,
    )
    return result


def register_diagram(
    db: Session,
    *,
    project_id: str,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    filename: Optional[str],
    content_type: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
    content_hash: Optional[str] = None,
) -> Analysis:
    """Register durable project membership after authorizing its project."""
    project = _project_query(
        db,
        project_id=project_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    ).first()
    if project is None:
        raise ValueError("Project not found")
    if db.query(Analysis.id).filter(Analysis.diagram_id == diagram_id).first() is not None:
        raise ValueError("Diagram identity collision")
    analysis = Analysis(
        workspace_id=project.id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        diagram_id=diagram_id,
        title=filename,
        status="uploaded",
        current_version=0,
    )
    db.add(analysis)
    source_asset = SourceAsset(
        workspace_id=project.id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        filename=filename or "uploaded-diagram",
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        content_hash=content_hash,
        diagram_id=diagram_id,
    )
    db.add(source_asset)
    db.flush()
    analysis.source_asset_id = source_asset.id
    lifecycle = db.query(DiagramLifecycle).filter(
        DiagramLifecycle.diagram_id == diagram_id,
        DiagramLifecycle.owner_user_id == owner_user_id,
        DiagramLifecycle.tenant_id == tenant_id,
    ).first()
    if lifecycle is None:
        db.add(DiagramLifecycle(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            workspace_id=project.id,
            generation=1,
            state="active",
        ))
    elif lifecycle.state == "active":
        lifecycle.workspace_id = project.id
    else:
        raise ValueError("Diagram identity has been purged")
    db.commit()
    db.refresh(analysis)
    return analysis


def get_project_id_for_diagram(
    db: Session,
    diagram_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
) -> Optional[str]:
    analysis = db.query(Analysis).filter(
        Analysis.diagram_id == diagram_id,
        Analysis.owner_user_id == owner_user_id,
        Analysis.tenant_id == tenant_id,
    ).first()
    return analysis.workspace_id if analysis else None


def resolve_diagram_access(
    db: Session,
    diagram_id: str,
    *,
    caller_user_id: str,
    tenant_id: str,
    allowed_roles: frozenset[str],
) -> Optional[tuple[Analysis, Workspace, str]]:
    """Resolve a diagram through its current canonical project membership."""
    row = db.query(Analysis, Workspace).join(
        Workspace,
        Workspace.id == Analysis.workspace_id,
    ).filter(
        Analysis.diagram_id == diagram_id,
        Analysis.tenant_id == tenant_id,
        Workspace.tenant_id == tenant_id,
        Workspace.status == "active",
    ).first()
    if row is None:
        return None
    analysis, project = row
    if project.owner_user_id == caller_user_id and "owner" in allowed_roles:
        role = "owner"
    else:
        if project.is_default:
            return None
        resolved = require_project_access(
            db,
            project_id=project.id,
            caller_user_id=caller_user_id,
            tenant_id=tenant_id,
            allowed_roles=allowed_roles,
        )
        if resolved is None:
            return None
        _resolved_project, role = resolved
    if analysis.owner_user_id != project.owner_user_id:
        return None
    return analysis, project, role


def resolve_diagram_principal(
    db: Session,
    diagram_id: str,
    *,
    caller_user_id: str,
    tenant_id: str,
    allowed_roles: frozenset[str],
) -> Optional[Dict[str, str]]:
    resolved = resolve_diagram_access(
        db,
        diagram_id,
        caller_user_id=caller_user_id,
        tenant_id=tenant_id,
        allowed_roles=allowed_roles,
    )
    if resolved is None:
        return None
    _analysis, project, role = resolved
    return {
        "owner_user_id": project.owner_user_id,
        "tenant_id": tenant_id,
        "caller_user_id": caller_user_id,
        "project_role": role,
    }


def load_project_analyses(
    db: Session,
    project_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
    allowed_roles: frozenset[str] = PROJECT_READ_ROLES,
) -> List[Dict[str, Any]]:
    """Load only current durable snapshots belonging to the authorized project."""
    resolved = require_project_access(
        db,
        project_id=project_id,
        caller_user_id=owner_user_id,
        tenant_id=tenant_id,
        allowed_roles=allowed_roles,
    )
    if resolved is None:
        return []
    project, _role = resolved
    rows = (
        db.query(Analysis, AnalysisVersion)
        .join(
            AnalysisVersion,
            (AnalysisVersion.analysis_id == Analysis.id)
            & (AnalysisVersion.version_number == Analysis.current_version),
        )
        .filter(
            Analysis.workspace_id == project_id,
            Analysis.owner_user_id == project.owner_user_id,
            Analysis.tenant_id == tenant_id,
            Analysis.current_version > 0,
        )
        .order_by(Analysis.diagram_id.asc())
        .all()
    )
    return [json.loads(version.snapshot) for _analysis, version in rows]


def list_project_members(
    db: Session,
    project_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
) -> Optional[List[Dict[str, Any]]]:
    resolved = require_project_access(
        db,
        project_id=project_id,
        caller_user_id=owner_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_MANAGE_ROLES,
    )
    if resolved is None:
        return None
    project, _role = resolved
    return [
        member.to_dict()
        for member in db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.project_owner_user_id == project.owner_user_id,
            ProjectMember.tenant_id == tenant_id,
        )
        .order_by(ProjectMember.member_user_id.asc())
        .all()
    ]


def add_project_member(
    db: Session,
    project_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
    member_user_id: str,
    role: str,
) -> Optional[ProjectMember]:
    """Add/update a member only after durable same-tenant directory verification."""
    if role not in PROJECT_ROLES:
        raise ValueError("Invalid project role")
    if not member_user_id or member_user_id == owner_user_id:
        raise ValueError("Invalid project member")
    directory_member = db.query(TeamMember.id).filter(
        TeamMember.org_id == tenant_id,
        TeamMember.user_id == member_user_id,
        TeamMember.is_active.is_(True),
    ).first()
    if directory_member is None:
        raise ValueError("Foreign or unknown tenant member")
    resolved = require_project_access(
        db,
        project_id=project_id,
        caller_user_id=owner_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_MANAGE_ROLES,
    )
    if resolved is None:
        return None
    project, _role = resolved
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.member_user_id == member_user_id,
    ).first()
    if member is None:
        member = ProjectMember(
            project_id=project_id,
            project_owner_user_id=project.owner_user_id,
            tenant_id=tenant_id,
            member_user_id=member_user_id,
            role=role,
        )
        db.add(member)
    else:
        if (
            member.project_owner_user_id != project.owner_user_id
            or member.tenant_id != tenant_id
        ):
            raise ValueError("Foreign project member")
        member.role = role
    db.commit()
    db.refresh(member)
    return member


def remove_project_member(
    db: Session,
    project_id: str,
    member_user_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
) -> Optional[bool]:
    resolved = require_project_access(
        db,
        project_id=project_id,
        caller_user_id=owner_user_id,
        tenant_id=tenant_id,
        allowed_roles=PROJECT_MANAGE_ROLES,
    )
    if resolved is None:
        return None
    project, _role = resolved
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project_id,
        ProjectMember.project_owner_user_id == project.owner_user_id,
        ProjectMember.tenant_id == tenant_id,
        ProjectMember.member_user_id == member_user_id,
    ).first()
    if member is None:
        return False
    db.delete(member)
    db.commit()
    return True


__all__ = [
    "PROJECT_EDIT_ROLES",
    "PROJECT_MANAGE_ROLES",
    "PROJECT_READ_ROLES",
    "acquire_project",
    "add_project_member",
    "create_project",
    "generate_project_id",
    "get_project",
    "get_project_id_for_diagram",
    "list_project_members",
    "load_project_analyses",
    "register_diagram",
    "remove_project_member",
    "require_project_access",
    "resolve_diagram_access",
    "resolve_diagram_principal",
    "resolve_project_access",
]
