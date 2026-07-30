"""
Archmorph Workspace Store — durable CRUD layer for workspaces, analyses,
analysis versions, artifacts, and decisions (Issue #1129).

Design principles
-----------------
* **PostgreSQL is canonical**: authenticated analysis state is committed to
    the SQLAlchemy-backed database before the shared session cache is updated.
* **One write boundary**: ``persist_analysis_state`` owns workspace/analysis/
    version creation and cache refresh. Compatibility helpers delegate to it.
* **Session compatibility**: API-key, anonymous, and sample flows can remain
    cache-only; authenticated durable flows can hydrate a lost cache from SQL.
* **Ownership / tenant enforcement**: every write and read validates
  ``owner_user_id`` (and optionally ``tenant_id``) before proceeding.
* **Retention policy**:
  - transient  → Redis / in-memory session store (existing SESSION_STORE)
  - workspace  → tables in this module (Workspace … Decision)
  - audit      → audit_log table (handled by audit_logging.py)

Thread-safety
-------------
All public functions use the SQLAlchemy session as a unit of work; callers
are responsible for providing/closing the session.  In tests, an in-memory
SQLite session is used.

Usage example::

    from database import get_db
    from workspace_store import create_workspace, create_analysis, save_analysis_version

    db = next(get_db())
    ws = create_workspace(db, owner_user_id="u1", name="My migration")
    analysis = create_analysis(db, workspace_id=ws.id, owner_user_id="u1",
                               diagram_id="diag-123", source_cloud="aws",
                               target_cloud="azure")
    version = save_analysis_version(db, analysis_id=analysis.id,
                                    owner_user_id="u1", snapshot={...})
"""

import hashlib
import json as _json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, exists, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from log_sanitizer import safe
from models.workspace import (
    Analysis,
    AnalysisMutationReceipt,
    AnalysisRestoreReceipt,
    AnalysisVersion,
    Artifact,
    Decision,
    DecisionSeverity,
    DecisionStatus,
    DecisionType,
    DiagramLifecycle,
    MigrationReplay,
    MigrationReplayEvent,
    ProjectMember,
    PurgeOperation,
    RestoreGrant,
    SourceAsset,
    TenantRehomeAudit,
    TenantRehomeAlias,
    Workspace,
    WorkspaceStatus,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

MAX_VERSIONS_PER_ANALYSIS = 50
MAX_WORKSPACES_PER_USER = 500
WORKSPACE_STATUSES = frozenset(status.value for status in WorkspaceStatus)
DECISION_TYPES = frozenset(value.value for value in DecisionType)
DECISION_SEVERITIES = frozenset(value.value for value in DecisionSeverity)
DECISION_STATUSES = frozenset(value.value for value in DecisionStatus)


class DurableAnalysisPersistenceError(RuntimeError):
    """Raised when canonical analysis state cannot be committed."""


class AnalysisCacheWriteError(RuntimeError):
    """Raised when a required cache refresh fails after a durable commit."""


class AnalysisVersionConflictError(RuntimeError):
    """Raised when an optimistic mutation targets an obsolete durable version."""


class CanonicalWriteDeniedError(ValueError):
    """Raised when canonical state is absent, inactive, or outside caller scope."""


@dataclass(frozen=True)
class AnalysisWriteResult:
    """Result of one canonical analysis persistence operation."""

    analysis: Analysis
    version: AnalysisVersion
    cache_updated: bool
    artifact: Optional[Artifact] = None
    idempotent_replay: bool = False


def _short_hash(data: str) -> str:
    """Return a 16-char hex digest of *data* for content-addressed dedup."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]  # codeql[py/weak-sensitive-data-hashing]


def _full_hash(data: bytes) -> str:
    """Return full 64-char SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def _tenant_matches(column, tenant_id: Optional[str]):
    return column.is_(None) if tenant_id is None else column == tenant_id


def _redact_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Remove internal ownership/session fields before durable storage or API return."""
    redacted = dict(snapshot or {})
    for key in list(redacted):
        if key.startswith("_owner_") or key in {
            "_analysis_version",
            "_tenant_id",
            "export_capability",
            "exportCapability",
        }:
            redacted.pop(key, None)
    return redacted


def _serialize_snapshot(snapshot: Dict[str, Any]) -> str:
    """Return deterministic JSON for hashes, idempotency, and durable snapshots."""
    return _json.dumps(
        _redact_snapshot(snapshot),
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )


def snapshot_payload_hash(snapshot: Dict[str, Any]) -> str:
    """Return the full deterministic hash used by restore grants."""
    # Deterministic content-integrity digest, not password verification material.
    return hashlib.sha256(_serialize_snapshot(snapshot).encode("utf-8")).hexdigest()  # codeql[py/weak-sensitive-data-hashing]


def _require_durable_identity(owner_user_id: str, tenant_id: Optional[str]) -> None:
    """Reject implicit or incomplete identity on authenticated durable writes."""
    if not owner_user_id or not tenant_id:
        raise ValueError("Authenticated durable analysis records require owner_user_id and tenant_id")


def _lock_workspace_mutation(db: Session, workspace_id: str) -> None:
    """Serialize lifecycle transitions and writes for one canonical workspace."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:material, 0))"),
            {"material": f"workspace-mutation:{workspace_id}"},
        )


def _lock_workspace_mutations(db: Session, workspace_ids: List[str]) -> None:
    """Acquire multi-workspace advisory locks in deterministic order."""
    for workspace_id in sorted(set(workspace_ids)):
        _lock_workspace_mutation(db, workspace_id)


def _lock_active_workspace(
    db: Session,
    workspace_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str],
) -> Workspace:
    """Lock and reload the authoritative workspace, denying every inactive state."""
    _lock_workspace_mutation(db, workspace_id)
    query = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.owner_user_id == owner_user_id,
        _tenant_matches(Workspace.tenant_id, tenant_id),
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    workspace = query.one_or_none()
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE.value:
        raise CanonicalWriteDeniedError("Canonical state not found")
    return workspace


def _lock_active_analysis(
    db: Session,
    analysis_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str],
) -> tuple[Analysis, Workspace]:
    """Lock workspace first, then analysis and lifecycle, for one write unit."""
    identity = (
        db.query(Analysis.workspace_id)
        .filter(
            Analysis.id == analysis_id,
            Analysis.owner_user_id == owner_user_id,
            _tenant_matches(Analysis.tenant_id, tenant_id),
        )
        .one_or_none()
    )
    if identity is None:
        raise CanonicalWriteDeniedError("Canonical state not found")
    workspace = _lock_active_workspace(
        db,
        identity.workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    query = db.query(Analysis).filter(
        Analysis.id == analysis_id,
        Analysis.workspace_id == workspace.id,
        Analysis.owner_user_id == owner_user_id,
        _tenant_matches(Analysis.tenant_id, tenant_id),
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    analysis = query.one_or_none()
    if analysis is None:
        raise CanonicalWriteDeniedError("Canonical state not found")
    if analysis.diagram_id is not None and tenant_id is not None:
        _ensure_active_lifecycle(
            db,
            diagram_id=analysis.diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            workspace_id=workspace.id,
        )
    return analysis, workspace


def _assert_active_workspace(workspace: Workspace) -> None:
    """Final transaction-boundary assertion while the workspace row remains locked."""
    if workspace.status != WorkspaceStatus.ACTIVE.value:
        raise CanonicalWriteDeniedError("Canonical state not found")


# ─────────────────────────────────────────────────────────────
# Workspace CRUD
# ─────────────────────────────────────────────────────────────

def create_workspace(
    db: Session,
    *,
    owner_user_id: str,
    name: str,
    tenant_id: Optional[str] = None,
    description: Optional[str] = None,
    source_cloud: str = "aws",
    target_cloud: str = "azure",
    is_default: bool = False,
) -> Workspace:
    """Create and persist a new Workspace."""
    if is_default:
        existing = (
            db.query(Workspace)
            .filter(
                Workspace.owner_user_id == owner_user_id,
                _tenant_matches(Workspace.tenant_id, tenant_id),
                Workspace.is_default.is_(True),
            )
            .first()
        )
        if existing is not None:
            return existing
    values = {
        "id": str(uuid.uuid4()),
        "owner_user_id": owner_user_id,
        "tenant_id": tenant_id,
        "name": name,
        "description": description,
        "source_cloud": source_cloud,
        "target_cloud": target_cloud,
        "is_default": is_default,
    }
    if is_default and db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        insert = postgresql_insert(Workspace).values(**values)
        insert = insert.on_conflict_do_nothing()
        db.execute(insert)
        db.commit()
        existing = (
            db.query(Workspace)
            .filter(
                Workspace.owner_user_id == owner_user_id,
                _tenant_matches(Workspace.tenant_id, tenant_id),
                Workspace.is_default.is_(True),
            )
            .first()
        )
        if existing is None:
            raise RuntimeError("default workspace upsert did not elect a row")
        return existing

    ws = Workspace(**values)
    db.add(ws)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not is_default:
            raise
        existing = (
            db.query(Workspace)
            .filter(
                Workspace.owner_user_id == owner_user_id,
                _tenant_matches(Workspace.tenant_id, tenant_id),
                Workspace.is_default.is_(True),
            )
            .first()
        )
        if existing is None:
            raise
        return existing
    db.refresh(ws)
    logger.info("workspace_created workspace_id=%s owner=%s", ws.id, owner_user_id)
    return ws


def get_workspace(
    db: Session,
    workspace_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[Workspace]:
    """Return a workspace if it belongs to *owner_user_id* (and tenant when given)."""
    q = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.owner_user_id == owner_user_id,
        Workspace.status != "deleting",
    )
    q = q.filter(_tenant_matches(Workspace.tenant_id, tenant_id))
    return q.first()


def list_workspaces(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List workspaces for a user with optional tenant/status filters."""
    if status is not None and status not in WORKSPACE_STATUSES:
        raise ValueError(f"Unsupported workspace status: {status}")
    q = db.query(Workspace).filter(
        Workspace.owner_user_id == owner_user_id,
        Workspace.status != "deleting",
    )
    q = q.filter(_tenant_matches(Workspace.tenant_id, tenant_id))
    if status:
        q = q.filter(Workspace.status == status)
    total = q.count()
    items = q.order_by(Workspace.updated_at.desc()).offset(offset).limit(limit).all()
    return {
        "workspaces": [w.to_dict() for w in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def update_workspace(
    db: Session,
    workspace_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    **fields: Any,
) -> Optional[Workspace]:
    """Update allowed fields on a workspace. Returns None when not found/forbidden."""
    requested_status = fields.get("status")
    if requested_status is not None:
        if requested_status not in {
            WorkspaceStatus.ACTIVE.value,
            WorkspaceStatus.ARCHIVED.value,
        }:
            raise ValueError(
                f"Unsupported workspace status transition: {requested_status}"
            )
    _lock_workspace_mutation(db, workspace_id)
    query = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.owner_user_id == owner_user_id,
        _tenant_matches(Workspace.tenant_id, tenant_id),
        Workspace.status != WorkspaceStatus.DELETING.value,
    )
    if db.get_bind().dialect.name == "postgresql":
        if requested_status == WorkspaceStatus.ACTIVE.value:
            from sqlalchemy import text

            lock_material = f"workspace-default:{owner_user_id}:{tenant_id or '<none>'}"
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:material, 0))"),
                {"material": lock_material},
            )
        query = query.with_for_update()
    ws = query.first()
    if ws is None:
        return None
    allowed = {"name", "description", "status", "source_cloud", "target_cloud"}
    for k, v in fields.items():
        if k in allowed:
            setattr(ws, k, v)
    if requested_status == WorkspaceStatus.ARCHIVED.value and ws.is_default:
        ws.is_default = False
    elif requested_status == WorkspaceStatus.ACTIVE.value:
        default_exists = db.query(Workspace.id).filter(
            Workspace.owner_user_id == owner_user_id,
            _tenant_matches(Workspace.tenant_id, tenant_id),
            Workspace.status == WorkspaceStatus.ACTIVE.value,
            Workspace.is_default.is_(True),
            Workspace.id != ws.id,
        ).first()
        if default_exists is None:
            ws.is_default = True
    db.commit()
    db.refresh(ws)
    return ws


def delete_workspace(
    db: Session,
    workspace_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> bool:
    """Delete a workspace and its cascaded records. Returns True when deleted."""
    ws = get_workspace(db, workspace_id, owner_user_id=owner_user_id, tenant_id=tenant_id)
    if ws is None:
        return False
    db.delete(ws)
    db.commit()
    return True


# ─────────────────────────────────────────────────────────────
# SourceAsset CRUD
# ─────────────────────────────────────────────────────────────

def create_source_asset(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    filename: str,
    content_type: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
    content_hash: Optional[str] = None,
    diagram_id: Optional[str] = None,
    source_cloud: Optional[str] = None,
) -> SourceAsset:
    """Record metadata for an uploaded source asset."""
    workspace = _lock_active_workspace(
        db,
        workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )

    asset = SourceAsset(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        filename=filename,
        content_type=content_type,
        file_size_bytes=file_size_bytes,
        content_hash=content_hash,
        diagram_id=diagram_id,
        source_cloud=source_cloud,
    )
    db.add(asset)
    _assert_active_workspace(workspace)
    db.commit()
    db.refresh(asset)
    logger.debug("source_asset_created asset_id=%s workspace=%s", asset.id, workspace_id)
    return asset


def get_source_asset(
    db: Session,
    asset_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[SourceAsset]:
    """Return a source asset owned by *owner_user_id*."""
    return (
        db.query(SourceAsset)
        .filter(
            SourceAsset.id == asset_id,
            SourceAsset.owner_user_id == owner_user_id,
            _tenant_matches(SourceAsset.tenant_id, tenant_id),
        )
        .first()
    )


def list_source_assets(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List source assets in a workspace."""
    q = db.query(SourceAsset).filter(
        SourceAsset.workspace_id == workspace_id,
        SourceAsset.owner_user_id == owner_user_id,
        _tenant_matches(SourceAsset.tenant_id, tenant_id),
    )
    total = q.count()
    items = q.order_by(SourceAsset.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "source_assets": [a.to_dict() for a in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─────────────────────────────────────────────────────────────
# Analysis CRUD
# ─────────────────────────────────────────────────────────────

def create_analysis(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    diagram_id: Optional[str] = None,
    source_asset_id: Optional[str] = None,
    title: Optional[str] = None,
    source_cloud: str = "aws",
    target_cloud: str = "azure",
    status: str = "completed",
    services_detected: int = 0,
    confidence_avg: Optional[float] = None,
) -> Analysis:
    """Create and persist an Analysis record."""
    workspace = _lock_active_workspace(
        db,
        workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )

    if source_asset_id is not None:
        source_asset = get_source_asset(db, source_asset_id, owner_user_id=owner_user_id, tenant_id=tenant_id)
        if source_asset is None or source_asset.workspace_id != workspace_id:
            raise ValueError(f"Source asset {source_asset_id!r} not found or access denied")

    analysis = Analysis(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        diagram_id=diagram_id,
        source_asset_id=source_asset_id,
        title=title or f"{source_cloud.upper()} → {target_cloud.upper()} migration",
        source_cloud=source_cloud,
        target_cloud=target_cloud,
        status=status,
        services_detected=services_detected,
        confidence_avg=confidence_avg,
        current_version=0,
    )
    db.add(analysis)
    if diagram_id is not None and tenant_id is not None:
        lifecycle = _get_lifecycle(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        if lifecycle is None:
            db.add(DiagramLifecycle(
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                generation=1,
                state="active",
            ))
        elif lifecycle.state == "active":
            lifecycle.workspace_id = workspace_id
        else:
            raise ValueError("Diagram has been purged")
    _assert_active_workspace(workspace)
    db.commit()
    db.refresh(analysis)
    logger.info(
        "analysis_created analysis_id=%s workspace=%s diagram=%s",
        safe(analysis.id),
        safe(workspace_id),
        safe(diagram_id or ""),
    )
    return analysis


def get_analysis_record(
    db: Session,
    analysis_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[Analysis]:
    """Return an owned analysis, including resolved legacy-ID read-through."""
    q = db.query(Analysis).filter(
        Analysis.id == analysis_id,
        Analysis.owner_user_id == owner_user_id,
    )
    q = q.filter(_tenant_matches(Analysis.tenant_id, tenant_id))
    analysis = q.first()
    if analysis is not None:
        return analysis

    from schema_compatibility import alias_read_through_enabled

    if not alias_read_through_enabled() or tenant_id is None:
        return None
    alias = db.query(TenantRehomeAlias).filter(
        TenantRehomeAlias.source_owner_user_id == owner_user_id,
        TenantRehomeAlias.source_tenant_id == tenant_id,
        TenantRehomeAlias.entity_type == "analysis",
        TenantRehomeAlias.source_entity_id == analysis_id,
        TenantRehomeAlias.status == "resolved",
        TenantRehomeAlias.target_owner_user_id.is_not(None),
        TenantRehomeAlias.target_tenant_id.is_not(None),
        TenantRehomeAlias.target_entity_id.is_not(None),
    ).one_or_none()
    if alias is None:
        return None
    return db.query(Analysis).filter(
        Analysis.id == alias.target_entity_id,
        Analysis.owner_user_id == alias.target_owner_user_id,
        Analysis.tenant_id == alias.target_tenant_id,
    ).one_or_none()


def list_analyses_in_workspace(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List all analyses in a workspace."""
    q = db.query(Analysis).filter(
        Analysis.workspace_id == workspace_id,
        Analysis.owner_user_id == owner_user_id,
        _tenant_matches(Analysis.tenant_id, tenant_id),
    )
    total = q.count()
    items = q.order_by(Analysis.updated_at.desc()).offset(offset).limit(limit).all()
    return {
        "analyses": [a.to_dict() for a in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─────────────────────────────────────────────────────────────
# AnalysisVersion CRUD
# ─────────────────────────────────────────────────────────────

def save_analysis_version(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    snapshot: Dict[str, Any],
    label: Optional[str] = None,
    restored_from: Optional[int] = None,
) -> AnalysisVersion:
    """Append a new immutable version snapshot for *analysis_id*.

    Also updates ``Analysis.current_version`` and trims old versions when the
    per-analysis cap is exceeded.
    """
    snapshot = _redact_snapshot(snapshot)
    snapshot_json = _serialize_snapshot(snapshot)
    content_hash = _short_hash(snapshot_json)
    mappings = snapshot.get("mappings", [])
    confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
    services_detected = snapshot.get("services_detected", len(mappings))
    confidence_avg = round(sum(confidences) / len(confidences), 4) if confidences else None

    last_integrity_error: Optional[IntegrityError] = None
    for _attempt in range(3):
        analysis, workspace = _lock_active_analysis(
            db,
            analysis_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )

        max_version = (
            db.query(func.max(AnalysisVersion.version_number))
            .filter(AnalysisVersion.analysis_id == analysis_id)
            .scalar()
            or 0
        )
        new_version_number = max(int(analysis.current_version or 0), int(max_version)) + 1
        version = AnalysisVersion(
            analysis_id=analysis_id,
            version_number=new_version_number,
            label=label or f"v{new_version_number}",
            snapshot=snapshot_json,
            content_hash=content_hash,
            created_by=owner_user_id,
            restored_from=restored_from,
        )
        db.add(version)
        analysis.current_version = new_version_number
        analysis.services_detected = services_detected
        if confidence_avg is not None:
            analysis.confidence_avg = confidence_avg

        try:
            _assert_active_workspace(workspace)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            last_integrity_error = exc
            continue

        db.refresh(version)
        _trim_old_versions(db, analysis_id)
        logger.debug(
            "analysis_version_saved analysis_id=%s version=%d hash=%s",
            analysis_id,
            new_version_number,
            content_hash,
        )
        return version

    assert last_integrity_error is not None
    raise last_integrity_error


def _trim_old_versions(db: Session, analysis_id: str) -> None:
    """Delete oldest versions while preserving every transitive lineage ancestor."""
    analysis_identity = (
        db.query(Analysis.owner_user_id, Analysis.tenant_id)
        .filter(Analysis.id == analysis_id)
        .one_or_none()
    )
    if analysis_identity is None:
        return
    try:
        analysis, workspace = _lock_active_analysis(
            db,
            analysis_id,
            owner_user_id=analysis_identity.owner_user_id,
            tenant_id=analysis_identity.tenant_id,
        )
    except CanonicalWriteDeniedError:
        db.rollback()
        return
    query = db.query(AnalysisVersion).filter(
        AnalysisVersion.analysis_id == analysis_id
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    versions = query.order_by(AnalysisVersion.version_number.asc()).all()
    excess = len(versions) - MAX_VERSIONS_PER_ANALYSIS
    if excess <= 0:
        return

    by_number = {int(version.version_number): version for version in versions}
    protected_numbers = {
        int(analysis.current_version or 0),
        int(versions[-1].version_number),
    }
    for version in versions:
        ancestor = version.restored_from
        seen = {int(version.version_number)}
        while ancestor is not None:
            ancestor_number = int(ancestor)
            if ancestor_number in seen:
                logger.error(
                    "analysis_version_lineage_cycle analysis_id=%s version=%s",
                    safe(analysis_id),
                    version.version_number,
                )
                protected_numbers.update(seen)
                break
            seen.add(ancestor_number)
            protected_numbers.add(ancestor_number)
            parent = by_number.get(ancestor_number)
            if parent is None:
                logger.error(
                    "analysis_version_lineage_missing analysis_id=%s ancestor=%s",
                    safe(analysis_id),
                    ancestor_number,
                )
                break
            ancestor = parent.restored_from

    protected_numbers.update(
        int(source_version)
        for (source_version,) in db.query(AnalysisRestoreReceipt.source_version)
        .filter(AnalysisRestoreReceipt.analysis_id == analysis_id)
        .all()
    )
    referenced_version_ids: set[str] = set()
    for version_id_column, analysis_id_column in (
        (Artifact.version_id, Artifact.analysis_id),
        (Decision.version_id, Decision.analysis_id),
        (
            AnalysisRestoreReceipt.restored_version_id,
            AnalysisRestoreReceipt.analysis_id,
        ),
        (MigrationReplay.version_id, MigrationReplay.analysis_id),
    ):
        referenced_version_ids.update(
            str(version_id)
            for (version_id,) in db.query(version_id_column)
            .filter(
                analysis_id_column == analysis_id,
                version_id_column.is_not(None),
            )
            .all()
        )

    candidate_ids: list[str] = []
    for version in versions:
        if len(candidate_ids) >= excess:
            break
        if (
            int(version.version_number) in protected_numbers
            or str(version.id) in referenced_version_ids
        ):
            continue
        candidate_ids.append(str(version.id))

    if candidate_ids:
        restored_child = aliased(AnalysisVersion)
        protected_tuple = tuple(sorted(protected_numbers))
        statement = delete(AnalysisVersion).where(
            AnalysisVersion.analysis_id == analysis_id,
            AnalysisVersion.id.in_(candidate_ids),
            AnalysisVersion.version_number.notin_(protected_tuple),
            ~exists().where(
                restored_child.analysis_id == analysis_id,
                restored_child.restored_from == AnalysisVersion.version_number,
            ),
            ~exists().where(
                Artifact.analysis_id == analysis_id,
                Artifact.version_id == AnalysisVersion.id,
            ),
            ~exists().where(
                Decision.analysis_id == analysis_id,
                Decision.version_id == AnalysisVersion.id,
            ),
            ~exists().where(
                AnalysisRestoreReceipt.analysis_id == analysis_id,
                or_(
                    AnalysisRestoreReceipt.restored_version_id == AnalysisVersion.id,
                    AnalysisRestoreReceipt.source_version
                    == AnalysisVersion.version_number,
                ),
            ),
            ~exists().where(
                MigrationReplay.analysis_id == analysis_id,
                MigrationReplay.version_id == AnalysisVersion.id,
            ),
        )
        # Concurrent retention transactions can select the same candidates.
        # A Core set delete is intentionally tolerant when another transaction
        # already removed some or all rows; canonical ORM updates remain strict.
        db.execute(statement.execution_options(synchronize_session="fetch"))
    _assert_active_workspace(workspace)
    db.commit()


def list_analysis_versions(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List version metadata (no snapshot) for an analysis."""
    # Ownership check
    analysis = (
        db.query(Analysis)
        .filter(
            Analysis.id == analysis_id,
            Analysis.owner_user_id == owner_user_id,
            _tenant_matches(Analysis.tenant_id, tenant_id),
        )
        .first()
    )
    if analysis is None:
        return []
    versions = (
        db.query(AnalysisVersion)
        .filter(AnalysisVersion.analysis_id == analysis_id)
        .order_by(AnalysisVersion.version_number.asc())
        .all()
    )
    return [v.to_dict() for v in versions]


def get_analysis_version(
    db: Session,
    *,
    analysis_id: str,
    version_number: int,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[AnalysisVersion]:
    """Return a version including snapshot; returns None when not found/forbidden."""
    analysis = (
        db.query(Analysis)
        .filter(
            Analysis.id == analysis_id,
            Analysis.owner_user_id == owner_user_id,
            _tenant_matches(Analysis.tenant_id, tenant_id),
        )
        .first()
    )
    if analysis is None:
        return None
    return (
        db.query(AnalysisVersion)
        .filter(
            AnalysisVersion.analysis_id == analysis_id,
            AnalysisVersion.version_number == version_number,
        )
        .first()
    )


def restore_analysis_version(
    db: Session,
    *,
    analysis_id: str,
    version_number: int,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    session_store: Any = None,
    cache_owner_api_key_id: Optional[str] = None,
    expected_version: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> Optional[AnalysisVersion]:
    """Restore a previous version by creating a new version from it.

    ``session_store`` remains accepted for API compatibility. Cache refresh is
    delegated to the same durable-first write boundary used by active analysis
    completion paths.

    Returns the new version record, or None when the source version is not found.
    """
    if expected_version is None:
        raise AnalysisVersionConflictError("Version restore requires expected_version")
    if not idempotency_key:
        raise ValueError("Version restore requires an Idempotency-Key")
    receipt_tenant_id = tenant_id or "__tenantless__"

    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    intent_hash = hashlib.sha256(
        _json.dumps(
            {
                "analysis_id": analysis_id,
                "source_version": version_number,
                "expected_version": expected_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    analysis, workspace = _lock_active_analysis(
        db,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )

    existing_receipt = db.query(AnalysisRestoreReceipt).filter(
        AnalysisRestoreReceipt.owner_user_id == owner_user_id,
        AnalysisRestoreReceipt.tenant_id == receipt_tenant_id,
        AnalysisRestoreReceipt.analysis_id == analysis_id,
        AnalysisRestoreReceipt.idempotency_key_hash == key_hash,
    ).first()
    if existing_receipt is not None:
        if existing_receipt.intent_hash != intent_hash:
            raise AnalysisVersionConflictError("Idempotency-Key was already used for a different restore intent")
        return db.query(AnalysisVersion).filter(
            AnalysisVersion.id == existing_receipt.restored_version_id,
            AnalysisVersion.analysis_id == analysis_id,
        ).one()
    current_version = int(analysis.current_version or 0)
    if current_version != expected_version:
        raise AnalysisVersionConflictError(
            f"Expected version {expected_version}, current version is {current_version}"
        )
    source = db.query(AnalysisVersion).filter(
        AnalysisVersion.analysis_id == analysis_id,
        AnalysisVersion.version_number == version_number,
    ).first()
    if source is None:
        return None
    snapshot = _json.loads(source.snapshot)
    new_version = _stage_analysis_version(
        db,
        analysis=analysis,
        owner_user_id=owner_user_id,
        snapshot=snapshot,
        label=f"restored-from-v{version_number}",
        restored_from=version_number,
    )
    db.flush()
    db.add(AnalysisRestoreReceipt(
        owner_user_id=owner_user_id,
        tenant_id=receipt_tenant_id,
        analysis_id=analysis_id,
        idempotency_key_hash=key_hash,
        intent_hash=intent_hash,
        source_version=version_number,
        expected_version=expected_version,
        restored_version_id=new_version.id,
        restored_version_number=new_version.version_number,
    ))
    try:
        _assert_active_workspace(workspace)
        db.commit()
    except IntegrityError:
        db.rollback()
        _analysis, workspace = _lock_active_analysis(
            db,
            analysis_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        receipt = db.query(AnalysisRestoreReceipt).filter(
            AnalysisRestoreReceipt.owner_user_id == owner_user_id,
            AnalysisRestoreReceipt.tenant_id == receipt_tenant_id,
            AnalysisRestoreReceipt.analysis_id == analysis_id,
            AnalysisRestoreReceipt.idempotency_key_hash == key_hash,
        ).one_or_none()
        if receipt is None:
            raise
        if receipt.intent_hash != intent_hash:
            raise AnalysisVersionConflictError(
                "Idempotency-Key was already used for a different restore intent"
            )
        _assert_active_workspace(workspace)
        db.commit()
        return (
            db.query(AnalysisVersion)
            .filter(
                AnalysisVersion.id == receipt.restored_version_id,
                AnalysisVersion.analysis_id == analysis_id,
            )
            .one()
        )
    db.refresh(new_version)
    if session_store is not None and analysis.diagram_id:
        try:
            existing = session_store.get(analysis.diagram_id) if hasattr(session_store, "get") else None
            if isinstance(existing, dict) and existing.get("_owner_user_id") not in (None, owner_user_id):
                return new_version
            session_store.set(
                analysis.diagram_id,
                {**snapshot, "_owner_user_id": owner_user_id, "_tenant_id": tenant_id},
            )
        except Exception as exc:
            logger.warning("legacy_session_restore_failed error_type=%s", type(exc).__name__)
    return new_version


# ─────────────────────────────────────────────────────────────
# Artifact CRUD
# ─────────────────────────────────────────────────────────────

def create_artifact(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    artifact_type: str,
    version_id: Optional[str] = None,
    source_asset_id: Optional[str] = None,
    format: Optional[str] = None,
    content: Optional[str] = None,
    storage_url: Optional[str] = None,
    commit: bool = True,
) -> Artifact:
    """Record a generated artifact."""
    analysis, workspace = _lock_active_analysis(
        db,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if version_id is not None:
        version = (
            db.query(AnalysisVersion)
            .filter(
                AnalysisVersion.id == version_id,
                AnalysisVersion.analysis_id == analysis_id,
            )
            .first()
        )
        if version is None:
            raise ValueError(f"Version {version_id!r} not found for analysis")
    content_hash: Optional[str] = None
    size_bytes: Optional[int] = None
    if content:
        content_hash = _full_hash(content.encode("utf-8"))
        size_bytes = len(content.encode("utf-8"))

    if version_id is not None and content_hash is not None:
        existing = (
            db.query(Artifact)
            .filter(
                Artifact.version_id == version_id,
                Artifact.artifact_type == artifact_type,
                Artifact.content_hash == content_hash,
            )
            .first()
        )
        if existing is not None:
            if commit:
                _assert_active_workspace(workspace)
                db.commit()
            return existing

    artifact = Artifact(
        analysis_id=analysis_id,
        version_id=version_id,
        source_asset_id=source_asset_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        artifact_type=artifact_type,
        format=format,
        content=content,
        storage_url=storage_url,
        content_hash=content_hash,
        size_bytes=size_bytes,
    )
    db.add(artifact)
    if commit:
        _assert_active_workspace(workspace)
        db.commit()
        db.refresh(artifact)
    else:
        db.flush()
    logger.info(
        "artifact_created artifact_id=%s analysis=%s type=%s",
        artifact.id,
        analysis_id,
        artifact_type,
    )
    return artifact


def get_artifact(
    db: Session,
    artifact_id: str,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
) -> Optional[Artifact]:
    """Return an artifact owned by *owner_user_id*."""
    return (
        db.query(Artifact)
        .filter(
            Artifact.id == artifact_id,
            Artifact.owner_user_id == owner_user_id,
            _tenant_matches(Artifact.tenant_id, tenant_id),
        )
        .first()
    )


def list_artifacts(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    artifact_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List artifacts for an analysis."""
    # Ownership check
    analysis = (
        db.query(Analysis)
        .filter(
            Analysis.id == analysis_id,
            Analysis.owner_user_id == owner_user_id,
            _tenant_matches(Analysis.tenant_id, tenant_id),
        )
        .first()
    )
    if analysis is None:
        return {"artifacts": [], "total": 0, "limit": limit, "offset": offset}

    q = db.query(Artifact).filter(
        Artifact.analysis_id == analysis_id,
        Artifact.owner_user_id == owner_user_id,
        _tenant_matches(Artifact.tenant_id, tenant_id),
    )
    if artifact_type:
        q = q.filter(Artifact.artifact_type == artifact_type)
    total = q.count()
    items = q.order_by(Artifact.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "artifacts": [a.to_dict() for a in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─────────────────────────────────────────────────────────────
# Decision CRUD
# ─────────────────────────────────────────────────────────────

def create_decision(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    decision_type: str,
    title: str,
    description: Optional[str] = None,
    severity: Optional[str] = None,
    status: str = DecisionStatus.OPEN.value,
    version_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Decision:
    """Record a risk or architectural decision."""
    analysis, workspace = _lock_active_analysis(
        db,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if decision_type not in DECISION_TYPES:
        raise ValueError("Unsupported decision type")
    if severity is not None and severity not in DECISION_SEVERITIES:
        raise ValueError("Unsupported decision severity")
    if status not in DECISION_STATUSES:
        raise ValueError("Unsupported decision status")
    if version_id is not None:
        version = db.query(AnalysisVersion.id).filter(
            AnalysisVersion.id == version_id,
            AnalysisVersion.analysis_id == analysis_id,
        ).first()
        if version is None:
            raise ValueError(f"Version {version_id!r} not found for analysis")
    decision = Decision(
        analysis_id=analysis_id,
        version_id=version_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        decision_type=decision_type,
        title=title,
        description=description,
        severity=severity,
        status=status,
        extra_data=_json.dumps(metadata or {}),
    )
    db.add(decision)
    _assert_active_workspace(workspace)
    db.commit()
    db.refresh(decision)
    return decision


def list_decisions(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    decision_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List decisions for an analysis."""
    analysis = (
        db.query(Analysis)
        .filter(
            Analysis.id == analysis_id,
            Analysis.owner_user_id == owner_user_id,
            _tenant_matches(Analysis.tenant_id, tenant_id),
        )
        .first()
    )
    if analysis is None:
        return []
    q = db.query(Decision).filter(
        Decision.analysis_id == analysis_id,
        Decision.owner_user_id == owner_user_id,
        _tenant_matches(Decision.tenant_id, tenant_id),
    )
    if decision_type:
        q = q.filter(Decision.decision_type == decision_type)
    return [d.to_dict() for d in q.order_by(Decision.created_at.desc()).all()]


# ─────────────────────────────────────────────────────────────
# Canonical analysis write boundary and session-cache bridge
# ─────────────────────────────────────────────────────────────

def _get_analysis_by_diagram(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    for_update: bool = False,
) -> Optional[Analysis]:
    query = (
        db.query(Analysis)
        .join(Workspace, Workspace.id == Analysis.workspace_id)
        .outerjoin(
            DiagramLifecycle,
            (DiagramLifecycle.diagram_id == Analysis.diagram_id)
            & (DiagramLifecycle.owner_user_id == Analysis.owner_user_id)
            & (DiagramLifecycle.tenant_id == Analysis.tenant_id),
        )
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE.value,
            or_(DiagramLifecycle.id.is_(None), DiagramLifecycle.state == "active"),
        )
    )
    if for_update:
        query = query.with_for_update(of=Analysis)
    return query.first()


def _get_lifecycle(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    for_update: bool = False,
) -> Optional[DiagramLifecycle]:
    query = db.query(DiagramLifecycle).filter(
        DiagramLifecycle.diagram_id == diagram_id,
        DiagramLifecycle.owner_user_id == owner_user_id,
        DiagramLifecycle.tenant_id == tenant_id,
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _ensure_active_lifecycle(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    workspace_id: str,
) -> DiagramLifecycle:
    lifecycle = _get_lifecycle(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    if lifecycle is None:
        lifecycle = DiagramLifecycle(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            generation=1,
            state="active",
        )
        db.add(lifecycle)
        db.flush()
    elif lifecycle.state != "active":
        raise ValueError("Diagram has been purged")
    else:
        lifecycle.workspace_id = workspace_id
    return lifecycle


def _resolve_workspace_id(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: str,
    snapshot: Dict[str, Any],
    workspace_id: Optional[str],
) -> str:
    if workspace_id is not None:
        workspace = _lock_active_workspace(
            db,
            workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        return workspace.id

    workspace_id = (
        db.query(Workspace)
        .with_entities(Workspace.id)
        .filter(
            Workspace.owner_user_id == owner_user_id,
            Workspace.tenant_id == tenant_id,
            Workspace.is_default.is_(True),
            Workspace.status == WorkspaceStatus.ACTIVE.value,
        )
        .scalar()
    )
    if workspace_id is not None:
        return _lock_active_workspace(
            db,
            workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ).id

    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:material, 0))"),
            {"material": f"workspace-default:{owner_user_id}:{tenant_id}"},
        )
        workspace_id = (
            db.query(Workspace.id)
            .filter(
                Workspace.owner_user_id == owner_user_id,
                Workspace.tenant_id == tenant_id,
                Workspace.is_default.is_(True),
                Workspace.status == WorkspaceStatus.ACTIVE.value,
            )
            .scalar()
        )
        if workspace_id is not None:
            return _lock_active_workspace(
                db,
                workspace_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
            ).id

    values = {
        "id": str(uuid.uuid4()),
        "owner_user_id": owner_user_id,
        "tenant_id": tenant_id,
        "name": "Default Workspace",
        "source_cloud": snapshot.get("source_provider", "aws"),
        "target_cloud": snapshot.get("target_provider", "azure"),
        "is_default": True,
    }
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        insert = postgresql_insert(Workspace).values(**values)
        insert = insert.on_conflict_do_nothing()
        db.execute(insert)
        workspace = (
            db.query(Workspace)
            .filter(
                Workspace.owner_user_id == owner_user_id,
                Workspace.tenant_id == tenant_id,
                Workspace.is_default.is_(True),
                Workspace.status == WorkspaceStatus.ACTIVE.value,
            )
            .first()
        )
        if workspace is None:
            raise IntegrityError("default workspace upsert did not elect a row", None, None)
        return workspace.id

    workspace = Workspace(**values)
    db.add(workspace)
    db.flush()
    return workspace.id


def _stage_analysis_version(
    db: Session,
    *,
    analysis: Analysis,
    owner_user_id: str,
    snapshot: Dict[str, Any],
    label: Optional[str],
    restored_from: Optional[int],
) -> AnalysisVersion:
    redacted = _redact_snapshot(snapshot)
    snapshot_json = _serialize_snapshot(redacted)
    mappings = redacted.get("mappings", [])
    confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
    services_detected = redacted.get("services_detected", len(mappings))
    confidence_avg = round(sum(confidences) / len(confidences), 4) if confidences else None
    max_version = (
        db.query(func.max(AnalysisVersion.version_number))
        .filter(AnalysisVersion.analysis_id == analysis.id)
        .scalar()
        or 0
    )
    version_number = max(int(analysis.current_version or 0), int(max_version)) + 1
    version = AnalysisVersion(
        analysis_id=analysis.id,
        version_number=version_number,
        label=label or f"v{version_number}",
        snapshot=snapshot_json,
        content_hash=_short_hash(snapshot_json),
        created_by=owner_user_id,
        restored_from=restored_from,
    )
    db.add(version)
    analysis.current_version = version_number
    analysis.services_detected = services_detected
    if confidence_avg is not None:
        analysis.confidence_avg = confidence_avg
    return version


def _matching_current_version(
    db: Session,
    *,
    analysis: Analysis,
    snapshot: Dict[str, Any],
) -> Optional[AnalysisVersion]:
    if analysis.current_version <= 0:
        return None
    snapshot_json = _serialize_snapshot(snapshot)
    candidate = (
        db.query(AnalysisVersion)
        .filter(
            AnalysisVersion.analysis_id == analysis.id,
            AnalysisVersion.version_number == analysis.current_version,
            AnalysisVersion.content_hash == _short_hash(snapshot_json),
        )
        .first()
    )
    if candidate is None or candidate.snapshot != snapshot_json:
        return None
    return candidate


def _write_session_cache(
    session_store: Any,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    snapshot: Dict[str, Any],
    version_number: int,
    owner_api_key_id: Optional[str] = None,
    allow_existing: bool = True,
    allow_legacy_tenant_rehome: bool = False,
    legacy_owner_user_ids: Optional[List[str]] = None,
    allow_unowned_upload_claim: bool = False,
    authoritative_hydration: bool = False,
) -> None:
    cached_snapshot = {
        **_redact_snapshot(snapshot),
        "diagram_id": diagram_id,
        "_tenant_id": tenant_id,
        "_analysis_version": version_number,
    }
    if owner_api_key_id:
        cached_snapshot["_owner_api_key_id"] = owner_api_key_id
    else:
        cached_snapshot["_owner_user_id"] = owner_user_id

    if allow_existing:
        existing = (
            session_store.peek(diagram_id)
            if hasattr(session_store, "peek")
            else session_store.get(diagram_id)
        )
        if isinstance(existing, dict):
            existing_owner_matches = (
                existing.get("_owner_api_key_id") == owner_api_key_id
                if owner_api_key_id
                else existing.get("_owner_user_id") == owner_user_id
            )
            existing_tenant_matches = existing.get("_tenant_id") in {
                tenant_id,
                "default_tenant",
            }
            try:
                existing_version = int(existing.get("_analysis_version"))
            except (TypeError, ValueError):
                existing_version = None
            must_replace = existing_version is None or (
                authoritative_hydration and existing_version > version_number
            )
            if existing_owner_matches and existing_tenant_matches and must_replace:
                if not session_store.delete(diagram_id):
                    raise AnalysisCacheWriteError("Stale cache deletion could not be confirmed")
    if not allow_existing:
        updated, _current = session_store.update_if(
            diagram_id,
            lambda current: current is None,
            lambda _current: cached_snapshot,
        )
        if not updated:
            raise AnalysisCacheWriteError("Refusing to hydrate over an existing cache entry")
        return

    def _same_owner_and_not_newer(current: Any) -> bool:
        if current is None:
            return True
        if not isinstance(current, dict):
            return False
        current_version = current.get("_analysis_version")
        unowned_upload_claim = bool(
            allow_unowned_upload_claim
            and current.get("diagram_id") == diagram_id
            and current.get("status") == "uploaded"
            and current.get("_owner_user_id") is None
            and current.get("_owner_api_key_id") is None
            and current_version is None
        )
        if unowned_upload_claim:
            return True
        owner_matches = (
            current.get("_owner_api_key_id") == owner_api_key_id
            and current.get("_owner_user_id") is None
            if owner_api_key_id
            else current.get("_owner_user_id") == owner_user_id
            and current.get("_owner_api_key_id") is None
        )
        legacy_owner_matches = bool(
            not owner_api_key_id
            and allow_legacy_tenant_rehome
            and current.get("_owner_user_id") in set(legacy_owner_user_ids or [])
            and current.get("_owner_api_key_id") is None
        )
        if legacy_owner_matches:
            owner_matches = True
        canonical_legacy_tenant = bool(
            allow_legacy_tenant_rehome
            and not owner_api_key_id
            and current.get("_owner_user_id") == owner_user_id
            and current.get("_owner_api_key_id") is None
            and current.get("_tenant_id") == "default_tenant"
        )
        if canonical_legacy_tenant:
            owner_matches = True
        tenant_matches = current.get("_tenant_id") == tenant_id or (
            owner_api_key_id is not None
            and current.get("_owner_api_key_id") == owner_api_key_id
            and current.get("_tenant_id") is None
        ) or (
            allow_legacy_tenant_rehome
            and (
                current.get("_owner_user_id") == owner_user_id
                or legacy_owner_matches
            )
            and current.get("_tenant_id") == "default_tenant"
        )
        return (
            owner_matches
            and tenant_matches
            and (
                allow_legacy_tenant_rehome
                or current_version is None
                or int(current_version) <= version_number
            )
        )

    updated, _current = session_store.update_if(
        diagram_id,
        _same_owner_and_not_newer,
        lambda _current: cached_snapshot,
    )
    if not updated:
        raise AnalysisCacheWriteError("Shared analysis cache rejected the ownership-safe update")


def persist_analysis_state(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: Optional[str],
    diagram_id: str,
    snapshot: Dict[str, Any],
    workspace_id: Optional[str] = None,
    session_store: Any = None,
    label: Optional[str] = None,
    restored_from: Optional[int] = None,
    expected_version: Optional[int] = None,
    operation: Optional[str] = None,
    request_hash: Optional[str] = None,
    require_snapshot_version: bool = True,
    artifact_type: Optional[str] = None,
    artifact_format: Optional[str] = None,
    artifact_content: Optional[str] = None,
    cache_owner_api_key_id: Optional[str] = None,
    cache_required: bool = False,
    allow_legacy_cache_rehome: bool = False,
    cache_legacy_owner_user_ids: Optional[List[str]] = None,
    allow_unowned_upload_claim: bool = False,
    precommit_hook: Optional[Any] = None,
) -> AnalysisWriteResult:
    """Commit authenticated analysis state, then refresh its transient cache.

    The database transaction is the success boundary. A cache failure never
    rolls back or replaces canonical PostgreSQL state. Callers that cannot
    continue without a fresh cache can set ``cache_required=True`` and receive
    ``AnalysisCacheWriteError`` after the durable commit succeeds.
    """
    _require_durable_identity(owner_user_id, tenant_id)
    assert tenant_id is not None

    last_integrity_error: Optional[IntegrityError] = None
    artifact: Optional[Artifact] = None
    for attempt in range(5):
        try:
            locked_workspaces: list[Workspace] = []
            analysis_identity = (
                db.query(Analysis.id, Analysis.workspace_id)
                .filter(
                    Analysis.diagram_id == diagram_id,
                    Analysis.owner_user_id == owner_user_id,
                    Analysis.tenant_id == tenant_id,
                )
                .one_or_none()
            )
            if analysis_identity is not None:
                if (
                    workspace_id is not None
                    and analysis_identity.workspace_id != workspace_id
                ):
                    _lock_workspace_mutations(
                        db,
                        [analysis_identity.workspace_id, workspace_id],
                    )
                analysis, source_workspace = _lock_active_analysis(
                    db,
                    analysis_identity.id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                )
                locked_workspaces.append(source_workspace)
            else:
                analysis = None

            if analysis is None:
                tombstone = _get_lifecycle(
                    db,
                    diagram_id=diagram_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    for_update=True,
                )
                if tombstone is not None and tombstone.state != "active":
                    raise ValueError("Diagram has been purged")
                if tombstone is not None and tombstone.workspace_id:
                    resolved_workspace = _lock_active_workspace(
                        db,
                        tombstone.workspace_id,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                    )
                    resolved_workspace_id = resolved_workspace.id
                else:
                    resolved_workspace_id = _resolve_workspace_id(
                        db,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                        snapshot=snapshot,
                        workspace_id=workspace_id,
                    )
                    resolved_workspace = _lock_active_workspace(
                        db,
                        resolved_workspace_id,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                    )
                locked_workspaces.append(resolved_workspace)
                mappings = snapshot.get("mappings", [])
                confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
                analysis = Analysis(
                    workspace_id=resolved_workspace_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    diagram_id=diagram_id,
                    source_cloud=snapshot.get("source_provider", "aws"),
                    target_cloud=snapshot.get("target_provider", "azure"),
                    status="completed",
                    services_detected=snapshot.get("services_detected", len(mappings)),
                    confidence_avg=(round(sum(confidences) / len(confidences), 4) if confidences else None),
                    current_version=0,
                )
                db.add(analysis)
                db.flush()
                if tombstone is None:
                    _ensure_active_lifecycle(
                        db,
                        diagram_id=diagram_id,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                        workspace_id=resolved_workspace_id,
                    )
                else:
                    tombstone.workspace_id = resolved_workspace_id
            else:
                _ensure_active_lifecycle(
                    db,
                    diagram_id=diagram_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    workspace_id=analysis.workspace_id,
                )
                if workspace_id is not None and analysis.workspace_id != workspace_id:
                    requested_workspace = _lock_active_workspace(
                        db,
                        workspace_id,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                    )
                    locked_workspaces.append(requested_workspace)
                    analysis.workspace_id = requested_workspace.id
                    lifecycle = _get_lifecycle(
                        db,
                        diagram_id=diagram_id,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                        for_update=True,
                    )
                    assert lifecycle is not None
                    lifecycle.workspace_id = requested_workspace.id

            current_version = int(analysis.current_version or 0)
            if operation and request_hash:
                receipt = (
                    db.query(AnalysisMutationReceipt)
                    .filter(
                        AnalysisMutationReceipt.owner_user_id == owner_user_id,
                        AnalysisMutationReceipt.tenant_id == tenant_id,
                        AnalysisMutationReceipt.diagram_id == diagram_id,
                        AnalysisMutationReceipt.operation == operation,
                        AnalysisMutationReceipt.request_hash == request_hash,
                    )
                    .first()
                )
                if receipt is None and current_version > 0:
                    # A durable commit may have succeeded before its transient
                    # cache projection failed. On retry, expected_version (and
                    # therefore request_hash) advances to that committed
                    # version. Replay only when the requested snapshot is
                    # already the current canonical version; an intervening
                    # mutation cannot match and must create a new transition.
                    matching_version = _matching_current_version(
                        db,
                        analysis=analysis,
                        snapshot=snapshot,
                    )
                    if matching_version is not None:
                        receipt = (
                            db.query(AnalysisMutationReceipt)
                            .filter(
                                AnalysisMutationReceipt.owner_user_id
                                == owner_user_id,
                                AnalysisMutationReceipt.tenant_id == tenant_id,
                                AnalysisMutationReceipt.diagram_id == diagram_id,
                                AnalysisMutationReceipt.operation == operation,
                                AnalysisMutationReceipt.version_id
                                == matching_version.id,
                            )
                            .first()
                        )
                if receipt is not None:
                    version = db.query(AnalysisVersion).filter(
                        AnalysisVersion.id == receipt.version_id,
                        AnalysisVersion.analysis_id == analysis.id,
                    ).one()
                    artifact = None
                    if artifact_type and artifact_content is not None:
                        artifact = (
                            db.query(Artifact)
                            .filter(
                                Artifact.version_id == version.id,
                                Artifact.artifact_type == artifact_type,
                                Artifact.content_hash
                                == _full_hash(artifact_content.encode("utf-8")),
                            )
                            .first()
                        )
                    for locked_workspace in locked_workspaces:
                        _assert_active_workspace(locked_workspace)
                    db.commit()
                    version_created = False
                    idempotent_replay = True
                    break

            if current_version > 0 and expected_version is None and operation is not None:
                raise AnalysisVersionConflictError("Existing analyses require expected_version")
            if expected_version is not None and current_version != expected_version:
                raise AnalysisVersionConflictError(
                    f"Expected version {expected_version}, current version is {analysis.current_version}"
                )

            snapshot_version = snapshot.get("_analysis_version")
            if (
                current_version > 0
                and restored_from is None
                and operation is not None
                and require_snapshot_version
            ):
                try:
                    snapshot_version_number = int(snapshot_version)
                except (TypeError, ValueError) as exc:
                    raise AnalysisVersionConflictError(
                        "Mutation snapshot lacks an immutable durable version"
                    ) from exc
                if snapshot_version_number != current_version:
                    raise AnalysisVersionConflictError(
                        "Mutation snapshot is stale relative to PostgreSQL"
                    )

            version = None
            if label is None and restored_from is None:
                version = _matching_current_version(db, analysis=analysis, snapshot=snapshot)
            version_created = version is None
            if version is None:
                version = _stage_analysis_version(
                    db,
                    analysis=analysis,
                    owner_user_id=owner_user_id,
                    snapshot=snapshot,
                    label=label,
                    restored_from=restored_from,
                )
            if artifact_type and artifact_content is not None:
                db.flush()
                artifact = create_artifact(
                    db,
                    analysis_id=analysis.id,
                    version_id=version.id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    artifact_type=artifact_type,
                    format=artifact_format,
                    content=artifact_content,
                    commit=False,
                )
            if operation and request_hash:
                db.flush()
                db.add(AnalysisMutationReceipt(
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    diagram_id=diagram_id,
                    operation=operation,
                    request_hash=request_hash,
                    analysis_id=analysis.id,
                    version_id=version.id,
                    version_number=version.version_number,
                ))
            if precommit_hook is not None:
                precommit_hook(db)
            for locked_workspace in locked_workspaces:
                _assert_active_workspace(locked_workspace)
            db.commit()
            idempotent_replay = False
            break
        except AnalysisVersionConflictError:
            db.rollback()
            raise
        except ValueError:
            db.rollback()
            raise
        except IntegrityError as exc:
            db.rollback()
            last_integrity_error = exc
            if db.get_bind().dialect.name == "postgresql":
                time.sleep(0.01 * (attempt + 1))
            continue
        except Exception as exc:
            db.rollback()
            logger.error(
                "canonical_analysis_persistence_failed diagram_id=%s error_type=%s",
                safe(diagram_id),
                type(exc).__name__,
            )
            raise DurableAnalysisPersistenceError("Failed to persist canonical analysis state") from exc
    else:
        raise DurableAnalysisPersistenceError("Failed to persist canonical analysis state after retries") from last_integrity_error

    if version_created:
        try:
            _trim_old_versions(db, analysis.id)
        except Exception as exc:
            db.rollback()
            logger.warning(
                "analysis_version_retention_failed analysis_id=%s error_type=%s",
                safe(analysis.id),
                type(exc).__name__,
            )

    cache_updated = False
    if session_store is not None:
        try:
            cache_snapshot = _json.loads(version.snapshot) if idempotent_replay else snapshot
            _write_session_cache(
                session_store,
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                snapshot=cache_snapshot,
                version_number=version.version_number,
                owner_api_key_id=cache_owner_api_key_id,
                allow_legacy_tenant_rehome=allow_legacy_cache_rehome,
                legacy_owner_user_ids=cache_legacy_owner_user_ids,
                allow_unowned_upload_claim=allow_unowned_upload_claim,
            )
            cache_updated = True
        except AnalysisCacheWriteError:
            if cache_required:
                raise
            logger.warning("analysis_cache_refresh_failed diagram_id=%s", safe(diagram_id))
        except Exception as exc:
            if cache_required:
                raise AnalysisCacheWriteError("Shared analysis cache update failed") from exc
            logger.warning(
                "analysis_cache_refresh_failed diagram_id=%s error_type=%s",
                safe(diagram_id),
                type(exc).__name__,
            )

    return AnalysisWriteResult(
        analysis=analysis,
        version=version,
        cache_updated=cache_updated,
        artifact=artifact,
        idempotent_replay=idempotent_replay,
    )


def persist_analysis_mutation(db: Session, **kwargs: Any) -> AnalysisWriteResult:
    """Authenticated mutation boundary with mandatory CAS and idempotency."""
    analysis = _get_analysis_by_diagram(
        db,
        diagram_id=kwargs["diagram_id"],
        owner_user_id=kwargs["owner_user_id"],
        tenant_id=kwargs["tenant_id"],
    )
    if analysis is not None and int(analysis.current_version or 0) > 0:
        if kwargs.get("expected_version") is None:
            raise AnalysisVersionConflictError("Existing analyses require expected_version")
        if not kwargs.get("operation") or not kwargs.get("request_hash"):
            raise ValueError("Authenticated mutations require durable idempotency metadata")
    return persist_analysis_state(db, **kwargs)


def issue_restore_grant(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: str,
    diagram_id: str,
    ttl_seconds: int,
    payload_hash: Optional[str] = None,
) -> tuple[str, int, int]:
    """Persist and return a one-time opaque restore nonce."""
    cleanup_restore_grants(db, limit=200)
    analysis_identity = (
        db.query(Analysis.id)
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    analysis = None
    workspace = None
    if analysis_identity is not None:
        analysis, workspace = _lock_active_analysis(
            db,
            analysis_identity.id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
    lifecycle = _get_lifecycle(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    if lifecycle is None:
        if analysis is None:
            raise ValueError("Diagram not found")
        lifecycle = _ensure_active_lifecycle(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            workspace_id=analysis.workspace_id,
        )
    elif workspace is None and lifecycle.workspace_id is not None:
        workspace = _lock_active_workspace(
            db,
            lifecycle.workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
    if lifecycle.state != "active":
        raise ValueError("Diagram not found")
    expected_version = int(analysis.current_version or 0) if analysis is not None else 0
    nonce = secrets.token_urlsafe(32)
    nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    expires_at = datetime.fromtimestamp(time.time() + ttl_seconds, tz=timezone.utc)
    db.add(
        RestoreGrant(
            nonce_digest=nonce_digest,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            generation=int(lifecycle.generation or 1),
            expected_version=expected_version,
            payload_hash=payload_hash,
            expires_at=expires_at,
            cleanup_at=expires_at,
        )
    )
    if workspace is not None:
        _assert_active_workspace(workspace)
    db.commit()
    return nonce, int(lifecycle.generation or 1), expected_version


def cleanup_restore_grants(db: Session, *, limit: int = 200) -> int:
    """Delete a bounded oldest page of expired, consumed, or revoked grants."""
    now = datetime.now(timezone.utc)
    query = (
        db.query(RestoreGrant.id)
        .filter(RestoreGrant.cleanup_at <= now)
        .order_by(RestoreGrant.cleanup_at.asc(), RestoreGrant.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    stale_ids = [grant_id for (grant_id,) in query.all()]
    if not stale_ids:
        return 0
    deleted = db.query(RestoreGrant).filter(RestoreGrant.id.in_(stale_ids)).delete(
        synchronize_session=False
    )
    db.flush()
    return int(deleted or 0)


def consume_restore_grant(
    db: Session,
    *,
    nonce: str,
    owner_user_id: str,
    tenant_id: str,
    diagram_id: str,
    generation: int,
    expected_version: int,
    payload_hash: str,
    commit: bool = True,
) -> bool:
    """Atomically consume a matching, live restore grant."""
    nonce_digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    query = db.query(RestoreGrant).filter(RestoreGrant.nonce_digest == nonce_digest)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    grant = query.first()
    workspace = None
    analysis_identity = (
        db.query(Analysis.id)
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    try:
        if analysis_identity is not None:
            _analysis, workspace = _lock_active_analysis(
                db,
                analysis_identity.id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
            )
    except CanonicalWriteDeniedError:
        db.rollback()
        return False
    lifecycle = _get_lifecycle(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    if (
        workspace is None
        and lifecycle is not None
        and lifecycle.workspace_id is not None
    ):
        try:
            workspace = _lock_active_workspace(
                db,
                lifecycle.workspace_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
            )
        except CanonicalWriteDeniedError:
            db.rollback()
            return False
    now = datetime.now(timezone.utc)
    expires_at = grant.expires_at if grant is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    valid = bool(
        grant is not None
        and lifecycle is not None
        and lifecycle.state == "active"
        and grant.consumed_at is None
        and grant.revoked_at is None
        and expires_at is not None
        and expires_at >= now
        and grant.owner_user_id == owner_user_id
        and grant.tenant_id == tenant_id
        and grant.diagram_id == diagram_id
        and grant.generation == generation == lifecycle.generation
        and grant.expected_version == expected_version
        and (grant.payload_hash is None or grant.payload_hash == payload_hash)
    )
    if not valid:
        db.rollback()
        return False
    grant.payload_hash = payload_hash
    grant.consumed_at = now
    grant.cleanup_at = now
    if workspace is not None:
        _assert_active_workspace(workspace)
    if commit:
        db.commit()
    else:
        db.flush()
    return True


def rehome_legacy_analysis_scope(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    source_tenant_id: str,
    target_tenant_id: str,
    target_owner_user_id: Optional[str] = None,
) -> str:
    """Move one exact-owner legacy analysis graph to a verified tenant scope.

    The provider is never inferred here. ``target_tenant_id`` and an optional
    ``target_owner_user_id`` must already have been derived from the currently
    verified principal. Conflicts are audited and denied without changing
    either namespace.
    """
    if not target_tenant_id or source_tenant_id == target_tenant_id:
        return "not_found"
    target_owner_user_id = target_owner_user_id or owner_user_id

    legacy_ids = (
        db.query(Analysis.id)
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == source_tenant_id,
        )
        .all()
    )
    legacy_rows = []
    for (legacy_id,) in legacy_ids:
        try:
            legacy_analysis, _workspace = _lock_active_analysis(
                db,
                legacy_id,
                owner_user_id=owner_user_id,
                tenant_id=source_tenant_id,
            )
        except CanonicalWriteDeniedError:
            db.rollback()
            return "not_found"
        legacy_rows.append(legacy_analysis)
    if len(legacy_rows) != 1:
        if legacy_rows:
            db.add(TenantRehomeAudit(
                owner_user_id=owner_user_id,
                source_tenant_id=source_tenant_id,
                target_tenant_id=target_tenant_id,
                status="conflict_denied",
                details=_json.dumps(
                    {"diagram_id": diagram_id, "reason": "ambiguous_legacy_owner_rows"},
                    sort_keys=True,
                ),
            ))
            db.commit()
            return "conflict"
        return "not_found"

    analysis = legacy_rows[0]
    workspace = _lock_active_workspace(
        db,
        analysis.workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=source_tenant_id,
    )

    workspace_analysis_query = db.query(Analysis).filter(
        Analysis.workspace_id == workspace.id,
        Analysis.owner_user_id == owner_user_id,
        Analysis.tenant_id == source_tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        workspace_analysis_query = workspace_analysis_query.with_for_update()
    workspace_analyses = workspace_analysis_query.all()
    total_workspace_analyses = db.query(Analysis.id).filter(
        Analysis.workspace_id == workspace.id,
    ).count()
    if total_workspace_analyses != len(workspace_analyses):
        db.add(TenantRehomeAudit(
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="conflict_denied",
            details=_json.dumps(
                {"diagram_id": diagram_id, "reason": "mixed_scope_workspace"},
                sort_keys=True,
            ),
        ))
        db.commit()
        return "conflict"
    analysis_ids = [item.id for item in workspace_analyses]
    graph_scope_counts = {
        "source_assets": (
            db.query(SourceAsset.id).filter(SourceAsset.workspace_id == workspace.id).count(),
            db.query(SourceAsset.id).filter(
                SourceAsset.workspace_id == workspace.id,
                SourceAsset.owner_user_id == owner_user_id,
                SourceAsset.tenant_id == source_tenant_id,
            ).count(),
        ),
        "artifacts": (
            db.query(Artifact.id).filter(Artifact.analysis_id.in_(analysis_ids)).count(),
            db.query(Artifact.id).filter(
                Artifact.analysis_id.in_(analysis_ids),
                Artifact.owner_user_id == owner_user_id,
                Artifact.tenant_id == source_tenant_id,
            ).count(),
        ),
        "decisions": (
            db.query(Decision.id).filter(Decision.analysis_id.in_(analysis_ids)).count(),
            db.query(Decision.id).filter(
                Decision.analysis_id.in_(analysis_ids),
                Decision.owner_user_id == owner_user_id,
                Decision.tenant_id == source_tenant_id,
            ).count(),
        ),
    }
    if any(total != scoped for total, scoped in graph_scope_counts.values()):
        db.add(TenantRehomeAudit(
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="conflict_denied",
            details=_json.dumps(
                {
                    "diagram_id": diagram_id,
                    "reason": "mixed_scope_workspace_graph",
                    "row_counts": {
                        name: {"total": total, "source_scope": scoped}
                        for name, (total, scoped) in graph_scope_counts.items()
                    },
                },
                sort_keys=True,
            ),
        ))
        db.commit()
        return "conflict"
    diagram_ids = [item.diagram_id for item in workspace_analyses if item.diagram_id]
    target_conflict = (
        db.query(Analysis.id)
        .filter(
            Analysis.owner_user_id == target_owner_user_id,
            Analysis.tenant_id == target_tenant_id,
            Analysis.diagram_id.in_(diagram_ids),
        )
        .first()
        if diagram_ids
        else None
    )
    if target_conflict is not None:
        db.add(TenantRehomeAudit(
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="conflict_denied",
            details=_json.dumps(
                {"diagram_id": diagram_id, "reason": "target_scope_exists"},
                sort_keys=True,
            ),
        ))
        db.commit()
        return "conflict"

    workspace_conflict = (
        db.query(Workspace.id)
        .filter(
            Workspace.owner_user_id == target_owner_user_id,
            Workspace.tenant_id == target_tenant_id,
            Workspace.is_default.is_(True),
            Workspace.id != workspace.id,
        )
        .first()
    )
    if workspace_conflict is not None:
        if workspace.is_default:
            workspace.is_default = False
        if workspace.name == "Default Workspace":
            workspace.name = "Migrated Legacy Workspace"

    workspace.owner_user_id = target_owner_user_id
    workspace.tenant_id = target_tenant_id
    db.query(SourceAsset).filter(
        SourceAsset.workspace_id == workspace.id,
        SourceAsset.owner_user_id == owner_user_id,
        SourceAsset.tenant_id == source_tenant_id,
    ).update(
        {
            SourceAsset.owner_user_id: target_owner_user_id,
            SourceAsset.tenant_id: target_tenant_id,
        },
        synchronize_session=False,
    )
    for workspace_analysis in workspace_analyses:
        workspace_analysis.owner_user_id = target_owner_user_id
        workspace_analysis.tenant_id = target_tenant_id
    db.query(Artifact).filter(
        Artifact.analysis_id.in_(analysis_ids),
        Artifact.owner_user_id == owner_user_id,
        Artifact.tenant_id == source_tenant_id,
    ).update(
        {
            Artifact.owner_user_id: target_owner_user_id,
            Artifact.tenant_id: target_tenant_id,
        },
        synchronize_session=False,
    )
    db.query(Decision).filter(
        Decision.analysis_id.in_(analysis_ids),
        Decision.owner_user_id == owner_user_id,
        Decision.tenant_id == source_tenant_id,
    ).update(
        {
            Decision.owner_user_id: target_owner_user_id,
            Decision.tenant_id: target_tenant_id,
        },
        synchronize_session=False,
    )
    db.add(
        TenantRehomeAudit(
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="access_rehome_completed",
            details=_json.dumps(
                {
                    "analysis_ids": analysis_ids,
                    "diagram_id": diagram_id,
                    "target_owner_user_id": target_owner_user_id,
                    "workspace_id": workspace.id,
                },
                sort_keys=True,
            ),
        )
    )
    try:
        _assert_active_workspace(workspace)
        db.commit()
    except IntegrityError:
        db.rollback()
        db.add(
            TenantRehomeAudit(
                owner_user_id=owner_user_id,
                source_tenant_id=source_tenant_id,
                target_tenant_id=target_tenant_id,
                status="conflict_denied",
                details=_json.dumps(
                    {
                        "diagram_id": diagram_id,
                        "reason": "concurrent_integrity_conflict",
                    },
                    sort_keys=True,
                ),
            )
        )
        db.commit()
        return "conflict"
    return "rehomed"


def rehome_legacy_owner_scope(
    db: Session,
    *,
    owner_user_ids: List[str],
    source_tenant_id: str,
    target_tenant_id: str,
    target_owner_user_id: str,
) -> Dict[str, int]:
    """Bulk-migrate clean exact-owner workspaces and quarantine only conflicts.

    This is invoked before authenticated workspace/list access, so discovery
    does not depend on the caller already knowing a legacy diagram ID.
    """
    summary = {"rehomed": 0, "quarantined": 0, "already_processed": 0}
    for source_owner_user_id in dict.fromkeys(owner_user_ids):
        workspace_query = db.query(Workspace).filter(
            Workspace.owner_user_id == source_owner_user_id,
            Workspace.tenant_id == source_tenant_id,
            Workspace.status == WorkspaceStatus.ACTIVE.value,
        )
        if db.get_bind().dialect.name == "postgresql":
            workspace_query = workspace_query.with_for_update()
        for workspace in workspace_query.all():
            existing_alias = db.query(TenantRehomeAlias).filter(
                TenantRehomeAlias.source_owner_user_id == source_owner_user_id,
                TenantRehomeAlias.source_tenant_id == source_tenant_id,
                TenantRehomeAlias.entity_type == "workspace",
                TenantRehomeAlias.source_entity_id == workspace.id,
            ).first()
            if existing_alias is not None:
                summary["already_processed"] += 1
                continue
            analyses = db.query(Analysis).filter(
                Analysis.workspace_id == workspace.id,
                Analysis.owner_user_id == source_owner_user_id,
                Analysis.tenant_id == source_tenant_id,
            ).all()
            analysis_ids = [analysis.id for analysis in analyses]
            diagram_ids = [analysis.diagram_id for analysis in analyses if analysis.diagram_id]
            mixed_scope = (
                db.query(Analysis.id).filter(Analysis.workspace_id == workspace.id).count() != len(analyses)
                or db.query(SourceAsset.id).filter(SourceAsset.workspace_id == workspace.id).count()
                != db.query(SourceAsset.id).filter(
                    SourceAsset.workspace_id == workspace.id,
                    SourceAsset.owner_user_id == source_owner_user_id,
                    SourceAsset.tenant_id == source_tenant_id,
                ).count()
                or db.query(DiagramLifecycle.id).filter(
                    DiagramLifecycle.workspace_id == workspace.id
                ).count()
                != db.query(DiagramLifecycle.id).filter(
                    DiagramLifecycle.workspace_id == workspace.id,
                    DiagramLifecycle.owner_user_id == source_owner_user_id,
                    DiagramLifecycle.tenant_id == source_tenant_id,
                ).count()
                or db.query(Artifact.id).filter(Artifact.analysis_id.in_(analysis_ids)).count()
                != db.query(Artifact.id).filter(
                    Artifact.analysis_id.in_(analysis_ids),
                    Artifact.owner_user_id == source_owner_user_id,
                    Artifact.tenant_id == source_tenant_id,
                ).count()
                or db.query(Decision.id).filter(Decision.analysis_id.in_(analysis_ids)).count()
                != db.query(Decision.id).filter(
                    Decision.analysis_id.in_(analysis_ids),
                    Decision.owner_user_id == source_owner_user_id,
                    Decision.tenant_id == source_tenant_id,
                ).count()
            )
            conflict = bool(
                diagram_ids
                and db.query(Analysis.id).filter(
                    Analysis.owner_user_id == target_owner_user_id,
                    Analysis.tenant_id == target_tenant_id,
                    Analysis.diagram_id.in_(diagram_ids),
                ).first()
            )
            if mixed_scope or conflict:
                reason = "mixed_scope_workspace_graph" if mixed_scope else "target_diagram_conflict"
                db.add(TenantRehomeAlias(
                    source_owner_user_id=source_owner_user_id,
                    source_tenant_id=source_tenant_id,
                    target_owner_user_id=target_owner_user_id,
                    target_tenant_id=target_tenant_id,
                    entity_type="workspace",
                    source_entity_id=workspace.id,
                    status="quarantined",
                    reason=reason,
                ))
                for analysis in analyses:
                    db.add(TenantRehomeAlias(
                        source_owner_user_id=source_owner_user_id,
                        source_tenant_id=source_tenant_id,
                        target_owner_user_id=target_owner_user_id,
                        target_tenant_id=target_tenant_id,
                        entity_type="analysis",
                        source_entity_id=analysis.id,
                        status="quarantined",
                        reason=reason,
                    ))
                db.add(TenantRehomeAudit(
                    owner_user_id=source_owner_user_id,
                    source_tenant_id=source_tenant_id,
                    target_tenant_id=target_tenant_id,
                    status="conflict_denied",
                    details=_json.dumps(
                        {
                            "workspace_id": workspace.id,
                            "diagram_ids": sorted(diagram_ids),
                            "reason": reason,
                        },
                        sort_keys=True,
                    ),
                ))
                summary["quarantined"] += 1
                continue

            target_default = db.query(Workspace.id).filter(
                Workspace.owner_user_id == target_owner_user_id,
                Workspace.tenant_id == target_tenant_id,
                Workspace.is_default.is_(True),
                Workspace.id != workspace.id,
            ).first()
            if target_default is not None and workspace.is_default:
                workspace.is_default = False
            workspace.owner_user_id = target_owner_user_id
            workspace.tenant_id = target_tenant_id
            db.query(SourceAsset).filter(
                SourceAsset.workspace_id == workspace.id,
                SourceAsset.owner_user_id == source_owner_user_id,
                SourceAsset.tenant_id == source_tenant_id,
            ).update(
                {
                    SourceAsset.owner_user_id: target_owner_user_id,
                    SourceAsset.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(Analysis).filter(Analysis.id.in_(analysis_ids)).update(
                {
                    Analysis.owner_user_id: target_owner_user_id,
                    Analysis.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(DiagramLifecycle).filter(
                DiagramLifecycle.workspace_id == workspace.id,
                DiagramLifecycle.owner_user_id == source_owner_user_id,
                DiagramLifecycle.tenant_id == source_tenant_id,
            ).update(
                {
                    DiagramLifecycle.owner_user_id: target_owner_user_id,
                    DiagramLifecycle.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(ProjectMember).filter(
                ProjectMember.project_id == workspace.id,
                ProjectMember.project_owner_user_id == source_owner_user_id,
                ProjectMember.tenant_id == source_tenant_id,
            ).update(
                {
                    ProjectMember.project_owner_user_id: target_owner_user_id,
                    ProjectMember.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(AnalysisMutationReceipt).filter(
                AnalysisMutationReceipt.analysis_id.in_(analysis_ids),
                AnalysisMutationReceipt.owner_user_id == source_owner_user_id,
                AnalysisMutationReceipt.tenant_id == source_tenant_id,
            ).update(
                {
                    AnalysisMutationReceipt.owner_user_id: target_owner_user_id,
                    AnalysisMutationReceipt.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(AnalysisRestoreReceipt).filter(
                AnalysisRestoreReceipt.analysis_id.in_(analysis_ids),
                AnalysisRestoreReceipt.owner_user_id == source_owner_user_id,
                AnalysisRestoreReceipt.tenant_id == source_tenant_id,
            ).update(
                {
                    AnalysisRestoreReceipt.owner_user_id: target_owner_user_id,
                    AnalysisRestoreReceipt.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(MigrationReplay).filter(
                MigrationReplay.analysis_id.in_(analysis_ids),
                MigrationReplay.owner_user_id == source_owner_user_id,
                MigrationReplay.tenant_id == source_tenant_id,
            ).update(
                {
                    MigrationReplay.owner_user_id: target_owner_user_id,
                    MigrationReplay.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(RestoreGrant).filter(
                RestoreGrant.diagram_id.in_(diagram_ids),
                RestoreGrant.owner_user_id == source_owner_user_id,
                RestoreGrant.tenant_id == source_tenant_id,
            ).update(
                {
                    RestoreGrant.owner_user_id: target_owner_user_id,
                    RestoreGrant.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(PurgeOperation).filter(
                PurgeOperation.workspace_id == workspace.id,
                PurgeOperation.owner_user_id == source_owner_user_id,
                PurgeOperation.tenant_id == source_tenant_id,
            ).update(
                {
                    PurgeOperation.owner_user_id: target_owner_user_id,
                    PurgeOperation.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(Artifact).filter(Artifact.analysis_id.in_(analysis_ids)).update(
                {
                    Artifact.owner_user_id: target_owner_user_id,
                    Artifact.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.query(Decision).filter(Decision.analysis_id.in_(analysis_ids)).update(
                {
                    Decision.owner_user_id: target_owner_user_id,
                    Decision.tenant_id: target_tenant_id,
                },
                synchronize_session=False,
            )
            db.add(TenantRehomeAlias(
                source_owner_user_id=source_owner_user_id,
                source_tenant_id=source_tenant_id,
                target_owner_user_id=target_owner_user_id,
                target_tenant_id=target_tenant_id,
                entity_type="workspace",
                source_entity_id=workspace.id,
                target_entity_id=workspace.id,
                status="rehomed",
            ))
            for analysis in analyses:
                db.add(TenantRehomeAlias(
                    source_owner_user_id=source_owner_user_id,
                    source_tenant_id=source_tenant_id,
                    target_owner_user_id=target_owner_user_id,
                    target_tenant_id=target_tenant_id,
                    entity_type="analysis",
                    source_entity_id=analysis.id,
                    target_entity_id=analysis.id,
                    status="rehomed",
                ))
            db.add(TenantRehomeAudit(
                owner_user_id=source_owner_user_id,
                source_tenant_id=source_tenant_id,
                target_tenant_id=target_tenant_id,
                status="access_rehome_completed",
                details=_json.dumps(
                    {
                        "workspace_id": workspace.id,
                        "analysis_ids": analysis_ids,
                        "target_owner_user_id": target_owner_user_id,
                    },
                    sort_keys=True,
                ),
            ))
            summary["rehomed"] += 1
            _assert_active_workspace(workspace)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise
    return summary


def owner_migration_conflict_status(
    db: Session,
    *,
    target_owner_user_id: str,
    target_tenant_id: str,
) -> Dict[str, Any]:
    """Return a count-only migration indicator without foreign graph details."""
    count = db.query(TenantRehomeAlias.id).filter(
        TenantRehomeAlias.target_owner_user_id == target_owner_user_id,
        TenantRehomeAlias.target_tenant_id == target_tenant_id,
        TenantRehomeAlias.entity_type == "workspace",
        TenantRehomeAlias.status == "quarantined",
    ).count()
    return {
        "has_conflicts": count > 0,
        "conflict_count": count,
        "status": "action_required" if count else "ready",
    }


def list_quarantined_legacy_graphs(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List operator reconciliation records with no child payload snapshots."""
    query = db.query(TenantRehomeAlias).filter(
        TenantRehomeAlias.entity_type == "workspace",
        TenantRehomeAlias.status == "quarantined",
    )
    total = query.count()
    rows = query.order_by(
        TenantRehomeAlias.created_at.asc(),
        TenantRehomeAlias.id.asc(),
    ).offset(offset).limit(limit).all()
    return {
        "quarantines": [
            {
                "alias_id": row.id,
                "source_owner_user_id": row.source_owner_user_id,
                "source_tenant_id": row.source_tenant_id,
                "target_owner_user_id": row.target_owner_user_id,
                "target_tenant_id": row.target_tenant_id,
                "workspace_id": row.source_entity_id,
                "reason": row.reason,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def resolve_quarantined_legacy_graph(
    db: Session,
    *,
    alias_id: str,
) -> Dict[str, Any]:
    """Move one conflict-free quarantined graph to its recorded target scope."""
    alias_query = db.query(TenantRehomeAlias).filter(
        TenantRehomeAlias.id == alias_id,
        TenantRehomeAlias.entity_type == "workspace",
    )
    if db.get_bind().dialect.name == "postgresql":
        alias_query = alias_query.with_for_update()
    alias = alias_query.one_or_none()
    if alias is None:
        raise ValueError("Quarantine not found")
    if alias.status == "resolved":
        return {"alias_id": alias.id, "status": "resolved", "idempotent": True}
    if alias.status != "quarantined" or not alias.target_owner_user_id or not alias.target_tenant_id:
        raise ValueError("Quarantine target is unavailable")
    workspace_query = db.query(Workspace).filter(
        Workspace.id == alias.source_entity_id,
        Workspace.owner_user_id == alias.source_owner_user_id,
        Workspace.tenant_id == alias.source_tenant_id,
        Workspace.status == WorkspaceStatus.ACTIVE.value,
    )
    if db.get_bind().dialect.name == "postgresql":
        workspace_query = workspace_query.with_for_update()
    workspace = workspace_query.one_or_none()
    if workspace is None:
        raise ValueError("Quarantined workspace is unavailable")
    analyses = db.query(Analysis).filter(
        Analysis.workspace_id == workspace.id,
        Analysis.owner_user_id == alias.source_owner_user_id,
        Analysis.tenant_id == alias.source_tenant_id,
    ).all()
    analysis_ids = [analysis.id for analysis in analyses]
    diagram_ids = [analysis.diagram_id for analysis in analyses if analysis.diagram_id]
    mixed_scope = (
        db.query(Analysis.id).filter(Analysis.workspace_id == workspace.id).count()
        != len(analyses)
        or db.query(SourceAsset.id).filter(SourceAsset.workspace_id == workspace.id).count()
        != db.query(SourceAsset.id).filter(
            SourceAsset.workspace_id == workspace.id,
            SourceAsset.owner_user_id == alias.source_owner_user_id,
            SourceAsset.tenant_id == alias.source_tenant_id,
        ).count()
        or db.query(DiagramLifecycle.id).filter(
            DiagramLifecycle.workspace_id == workspace.id
        ).count()
        != db.query(DiagramLifecycle.id).filter(
            DiagramLifecycle.workspace_id == workspace.id,
            DiagramLifecycle.owner_user_id == alias.source_owner_user_id,
            DiagramLifecycle.tenant_id == alias.source_tenant_id,
        ).count()
        or db.query(Artifact.id).filter(Artifact.analysis_id.in_(analysis_ids)).count()
        != db.query(Artifact.id).filter(
            Artifact.analysis_id.in_(analysis_ids),
            Artifact.owner_user_id == alias.source_owner_user_id,
            Artifact.tenant_id == alias.source_tenant_id,
        ).count()
        or db.query(Decision.id).filter(Decision.analysis_id.in_(analysis_ids)).count()
        != db.query(Decision.id).filter(
            Decision.analysis_id.in_(analysis_ids),
            Decision.owner_user_id == alias.source_owner_user_id,
            Decision.tenant_id == alias.source_tenant_id,
        ).count()
    )
    if mixed_scope:
        raise ValueError("Quarantine mixed-scope conflict is still present")
    if diagram_ids and db.query(Analysis.id).filter(
        Analysis.owner_user_id == alias.target_owner_user_id,
        Analysis.tenant_id == alias.target_tenant_id,
        Analysis.diagram_id.in_(diagram_ids),
    ).first():
        raise ValueError("Quarantine conflict is still present")
    if diagram_ids and db.query(SourceAsset.id).filter(
        SourceAsset.owner_user_id == alias.target_owner_user_id,
        SourceAsset.tenant_id == alias.target_tenant_id,
        SourceAsset.diagram_id.in_(diagram_ids),
    ).first():
        raise ValueError("Quarantine conflict is still present")
    target_lifecycles = db.query(DiagramLifecycle).filter(
        DiagramLifecycle.owner_user_id == alias.target_owner_user_id,
        DiagramLifecycle.tenant_id == alias.target_tenant_id,
        DiagramLifecycle.diagram_id.in_(diagram_ids),
    ).all()
    if any(lifecycle.state != "active" for lifecycle in target_lifecycles):
        raise ValueError("Quarantine conflict is still present")
    for target_lifecycle in target_lifecycles:
        db.delete(target_lifecycle)
    db.flush()
    target_default_exists = workspace.is_default and db.query(Workspace.id).filter(
        Workspace.owner_user_id == alias.target_owner_user_id,
        Workspace.tenant_id == alias.target_tenant_id,
        Workspace.is_default.is_(True),
        Workspace.id != workspace.id,
    ).first() is not None
    if target_default_exists:
        workspace.is_default = False
    workspace.owner_user_id = alias.target_owner_user_id
    workspace.tenant_id = alias.target_tenant_id
    db.query(SourceAsset).filter(
        SourceAsset.workspace_id == workspace.id,
        SourceAsset.owner_user_id == alias.source_owner_user_id,
        SourceAsset.tenant_id == alias.source_tenant_id,
    ).update(
        {
            SourceAsset.owner_user_id: alias.target_owner_user_id,
            SourceAsset.tenant_id: alias.target_tenant_id,
        },
        synchronize_session=False,
    )
    db.query(Analysis).filter(Analysis.id.in_(analysis_ids)).update(
        {
            Analysis.owner_user_id: alias.target_owner_user_id,
            Analysis.tenant_id: alias.target_tenant_id,
        },
        synchronize_session=False,
    )
    db.query(DiagramLifecycle).filter(
        DiagramLifecycle.workspace_id == workspace.id,
        DiagramLifecycle.owner_user_id == alias.source_owner_user_id,
        DiagramLifecycle.tenant_id == alias.source_tenant_id,
    ).update(
        {
            DiagramLifecycle.owner_user_id: alias.target_owner_user_id,
            DiagramLifecycle.tenant_id: alias.target_tenant_id,
        },
        synchronize_session=False,
    )
    for model in (Artifact, Decision):
        db.query(model).filter(
            model.analysis_id.in_(analysis_ids),
            model.owner_user_id == alias.source_owner_user_id,
            model.tenant_id == alias.source_tenant_id,
        ).update(
            {
                model.owner_user_id: alias.target_owner_user_id,
                model.tenant_id: alias.target_tenant_id,
            },
            synchronize_session=False,
        )
    child_aliases = db.query(TenantRehomeAlias).filter(
        TenantRehomeAlias.source_owner_user_id == alias.source_owner_user_id,
        TenantRehomeAlias.source_tenant_id == alias.source_tenant_id,
        TenantRehomeAlias.source_entity_id.in_([workspace.id, *analysis_ids]),
        TenantRehomeAlias.status == "quarantined",
    ).all()
    for child_alias in child_aliases:
        child_alias.status = "resolved"
        child_alias.target_owner_user_id = alias.target_owner_user_id
        child_alias.target_tenant_id = alias.target_tenant_id
        child_alias.target_entity_id = child_alias.source_entity_id
        child_alias.reason = "operator_reconciled"
    db.add(
        TenantRehomeAudit(
            owner_user_id=alias.source_owner_user_id,
            source_tenant_id=alias.source_tenant_id,
            target_tenant_id=alias.target_tenant_id,
            status="quarantine_resolved",
            details=_json.dumps(
                {
                    "alias_id": alias.id,
                    "workspace_id": workspace.id,
                    "analysis_ids": sorted(analysis_ids),
                },
                sort_keys=True,
            ),
        )
    )
    _assert_active_workspace(workspace)
    db.commit()
    return {"alias_id": alias.id, "status": "resolved", "idempotent": False}


def get_current_analysis_version(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> tuple[Analysis, AnalysisVersion]:
    """Return the locked current immutable version for a canonical diagram."""
    analysis_identity = (
        db.query(Analysis.id)
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    if analysis_identity is None:
        raise ValueError("Canonical analysis version is required")
    analysis, _workspace = _lock_active_analysis(
        db,
        analysis_identity.id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if int(analysis.current_version or 0) <= 0:
        raise ValueError("Canonical analysis version is required")
    version = db.query(AnalysisVersion).filter(
        AnalysisVersion.analysis_id == analysis.id,
        AnalysisVersion.version_number == analysis.current_version,
    ).one_or_none()
    if version is None:
        raise ValueError("Canonical analysis version is required")
    return analysis, version


def create_export_artifact(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    artifact_type: str,
    format: str,
    content: bytes,
    storage_url: Optional[str] = None,
    inline_content: Optional[str] = None,
    expected_version_id: Optional[str] = None,
) -> Artifact:
    """Idempotently bind exact generated bytes to the locked current version."""
    analysis, version = get_current_analysis_version(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    workspace = _lock_active_workspace(
        db,
        analysis.workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if expected_version_id is not None:
        version = db.query(AnalysisVersion).filter(
            AnalysisVersion.id == expected_version_id,
            AnalysisVersion.analysis_id == analysis.id,
        ).one_or_none()
        if version is None:
            raise ValueError("Canonical analysis version is required")
    content_hash = _full_hash(content)
    existing = db.query(Artifact).filter(
        Artifact.analysis_id == analysis.id,
        Artifact.version_id == version.id,
        Artifact.owner_user_id == owner_user_id,
        Artifact.tenant_id == tenant_id,
        Artifact.artifact_type == artifact_type,
        Artifact.content_hash == content_hash,
    ).one_or_none()
    if existing is not None:
        _assert_active_workspace(workspace)
        db.commit()
        return existing
    if inline_content is None and storage_url is None:
        inline_content = content.decode("utf-8")
    artifact = Artifact(
        analysis_id=analysis.id,
        version_id=version.id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        artifact_type=artifact_type,
        format=format,
        content=inline_content,
        storage_url=storage_url,
        content_hash=content_hash,
        size_bytes=len(content),
    )
    db.add(artifact)
    try:
        _assert_active_workspace(workspace)
        db.commit()
    except IntegrityError:
        db.rollback()
        analysis, _version = get_current_analysis_version(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        existing = (
            db.query(Artifact)
            .filter(
                Artifact.analysis_id == analysis.id,
                Artifact.version_id == version.id,
                Artifact.artifact_type == artifact_type,
                Artifact.content_hash == content_hash,
            )
            .one()
        )
        db.commit()
        return existing
    db.refresh(artifact)
    return artifact


def find_export_artifact(
    db: Session,
    *,
    analysis_id: str,
    version_id: str,
    owner_user_id: str,
    tenant_id: str,
    artifact_type: str,
    content_hash: str,
) -> Optional[Artifact]:
    """Return an exact scoped immutable export without mutating state."""
    return db.query(Artifact).filter(
        Artifact.analysis_id == analysis_id,
        Artifact.version_id == version_id,
        Artifact.owner_user_id == owner_user_id,
        Artifact.tenant_id == tenant_id,
        Artifact.artifact_type == artifact_type,
        Artifact.content_hash == content_hash,
    ).one_or_none()


def create_migration_replay(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    title: str,
) -> MigrationReplay:
    analysis, version = get_current_analysis_version(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    replay = MigrationReplay(
        analysis_id=analysis.id,
        version_id=version.id,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        title=title,
    )
    db.add(replay)
    workspace = _lock_active_workspace(
        db,
        analysis.workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    _assert_active_workspace(workspace)
    db.commit()
    db.refresh(replay)
    return replay


def get_migration_replay(
    db: Session,
    *,
    replay_id: str,
    owner_user_id: str,
    tenant_id: str,
    for_update: bool = False,
) -> Optional[MigrationReplay]:
    query = db.query(MigrationReplay).filter(
        MigrationReplay.id == replay_id,
        MigrationReplay.owner_user_id == owner_user_id,
        MigrationReplay.tenant_id == tenant_id,
    )
    if for_update and db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    return query.one_or_none()


def add_migration_replay_event(
    db: Session,
    *,
    replay_id: str,
    owner_user_id: str,
    tenant_id: str,
    event_type: str,
    data: Dict[str, Any],
) -> MigrationReplayEvent:
    replay = get_migration_replay(
        db,
        replay_id=replay_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    if replay is None:
        raise ValueError("Replay not found")
    _analysis, workspace = _lock_active_analysis(
        db,
        replay.analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    sequence = int(
        db.query(func.max(MigrationReplayEvent.sequence)).filter(
            MigrationReplayEvent.replay_id == replay_id
        ).scalar()
        or -1
    ) + 1
    event = MigrationReplayEvent(
        replay_id=replay_id,
        sequence=sequence,
        event_type=event_type,
        data=_json.dumps(data, sort_keys=True, default=str),
    )
    db.add(event)
    _assert_active_workspace(workspace)
    db.commit()
    db.refresh(event)
    return event


def serialize_migration_replay(db: Session, replay: MigrationReplay) -> Dict[str, Any]:
    events = db.query(MigrationReplayEvent).filter(
        MigrationReplayEvent.replay_id == replay.id
    ).order_by(MigrationReplayEvent.sequence.asc()).all()
    return {
        "replay_id": replay.id,
        "analysis_id": replay.diagram_id,
        "analysis_record_id": replay.analysis_id,
        "version_id": replay.version_id,
        "title": replay.title,
        "owner_user_id": replay.owner_user_id,
        "tenant_id": replay.tenant_id,
        "created_at": replay.created_at.timestamp() if replay.created_at else 0,
        "updated_at": replay.updated_at.timestamp() if replay.updated_at else 0,
        "events": [
            {
                "event_id": event.id,
                "event_type": event.event_type,
                "data": _json.loads(event.data or "{}"),
                "timestamp": event.created_at.timestamp() if event.created_at else 0,
                "sequence": event.sequence,
            }
            for event in events
        ],
    }


def list_migration_replays(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: str,
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    query = db.query(MigrationReplay).filter(
        MigrationReplay.owner_user_id == owner_user_id,
        MigrationReplay.tenant_id == tenant_id,
    )
    total = query.count()
    rows = query.order_by(MigrationReplay.created_at.desc(), MigrationReplay.id.desc()).offset(offset).limit(limit).all()
    event_counts = dict(
        db.query(MigrationReplayEvent.replay_id, func.count(MigrationReplayEvent.id))
        .filter(MigrationReplayEvent.replay_id.in_([row.id for row in rows]))
        .group_by(MigrationReplayEvent.replay_id)
        .all()
    ) if rows else {}
    return {
        "replays": [
            {
                "replay_id": row.id,
                "analysis_id": row.diagram_id,
                "version_id": row.version_id,
                "title": row.title,
                "event_count": int(event_counts.get(row.id, 0)),
                "created_at": row.created_at.timestamp() if row.created_at else 0,
            }
            for row in rows
        ],
        "total": total,
    }


def purge_analysis_state(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    cleanup_empty_implicit_workspace: bool = True,
) -> Dict[str, Any]:
    """Delete one tenant-scoped durable analysis graph before purge receipt."""
    analysis_query = db.query(Analysis).filter(
        Analysis.diagram_id == diagram_id,
        Analysis.owner_user_id == owner_user_id,
        Analysis.tenant_id == tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        analysis_query = analysis_query.with_for_update()
    analysis = analysis_query.first()
    counts = {
        "analyses": 0,
        "versions": 0,
        "artifacts": 0,
        "decisions": 0,
        "source_assets": 0,
        "implicit_workspaces": 0,
    }
    workspace_id = analysis.workspace_id if analysis is not None else None
    artifact_source_ids = (
        [
            source_asset_id
            for (source_asset_id,) in (
                db.query(Artifact.source_asset_id)
                .filter(
                    Artifact.analysis_id == analysis.id,
                    Artifact.source_asset_id.is_not(None),
                )
                .all()
            )
        ]
        if analysis is not None
        else []
    )
    source_identity_ids = [
        source_asset_id
        for source_asset_id in [
            analysis.source_asset_id if analysis is not None else None,
            *artifact_source_ids,
        ]
        if source_asset_id is not None
    ]
    source_identity_filter = SourceAsset.diagram_id == diagram_id
    if source_identity_ids:
        source_identity_filter = or_(
            SourceAsset.id.in_(source_identity_ids),
            source_identity_filter,
        )
    source_candidates_query = db.query(SourceAsset).filter(
        SourceAsset.owner_user_id == owner_user_id,
        SourceAsset.tenant_id == tenant_id,
        source_identity_filter,
    )
    if db.get_bind().dialect.name == "postgresql":
        source_candidates_query = source_candidates_query.with_for_update()
    source_candidates = source_candidates_query.all()
    candidate_workspace_ids = {
        candidate_workspace_id
        for candidate_workspace_id in [
            workspace_id,
            *(source.workspace_id for source in source_candidates),
        ]
        if candidate_workspace_id is not None
    }
    if analysis is not None:
        replay_ids = [
            replay_id
            for (replay_id,) in db.query(MigrationReplay.id).filter(
                MigrationReplay.analysis_id == analysis.id
            ).all()
        ]
        if replay_ids:
            replay_events_deleted = db.query(MigrationReplayEvent).filter(
                MigrationReplayEvent.replay_id.in_(replay_ids)
            ).delete(synchronize_session=False)
            if replay_events_deleted:
                counts["replay_events"] = replay_events_deleted
        replays_deleted = db.query(MigrationReplay).filter(
            MigrationReplay.analysis_id == analysis.id
        ).delete(synchronize_session=False)
        if replays_deleted:
            counts["replays"] = replays_deleted
        counts["artifacts"] = db.query(Artifact).filter(
            Artifact.analysis_id == analysis.id
        ).delete(synchronize_session=False)
        counts["decisions"] = db.query(Decision).filter(
            Decision.analysis_id == analysis.id
        ).delete(synchronize_session=False)
        counts["versions"] = db.query(AnalysisVersion).filter(
            AnalysisVersion.analysis_id == analysis.id
        ).delete(synchronize_session=False)
        db.delete(analysis)
        db.flush()
        counts["analyses"] = 1
    candidate_ids = [source.id for source in source_candidates]
    referenced_source_ids = {
        source_asset_id
        for (source_asset_id,) in (
            db.query(Analysis.source_asset_id)
            .filter(Analysis.source_asset_id.in_(candidate_ids))
            .all()
            if candidate_ids
            else []
        )
        if source_asset_id is not None
    }
    referenced_source_ids.update(
        source_asset_id
        for (source_asset_id,) in (
            db.query(Artifact.source_asset_id)
            .filter(Artifact.source_asset_id.in_(candidate_ids))
            .all()
            if candidate_ids
            else []
        )
        if source_asset_id is not None
    )
    for source in source_candidates:
        if source.id not in referenced_source_ids:
            db.delete(source)
            counts["source_assets"] += 1
        elif source.diagram_id == diagram_id:
            # Preserve shared provenance without retaining the purged identity.
            source.diagram_id = None
    db.flush()

    if cleanup_empty_implicit_workspace:
        for candidate_workspace_id in candidate_workspace_ids:
            workspace = (
                db.query(Workspace)
                .filter(
                    Workspace.id == candidate_workspace_id,
                    Workspace.owner_user_id == owner_user_id,
                    Workspace.tenant_id == tenant_id,
                    Workspace.is_default.is_(True),
                )
                .first()
            )
            remaining = db.query(Analysis.id).filter(
                Analysis.workspace_id == candidate_workspace_id
            ).first()
            sources = db.query(SourceAsset.id).filter(
                SourceAsset.workspace_id == candidate_workspace_id
            ).first()
            if workspace is not None and remaining is None and sources is None:
                db.delete(workspace)
                counts["implicit_workspaces"] += 1
    db.commit()
    return counts


def link_analysis_to_workspace(
    db: Session,
    *,
    diagram_id: str,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> tuple[Analysis, str]:
    """Atomically move a durable uploaded/analyzed identity and lifecycle.

    PostgreSQL metadata is authoritative even when ``current_version == 0``;
    no browser/session payload is read or persisted by this operation.
    """
    analysis_identity = (
        db.query(Analysis.id, Analysis.workspace_id)
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        )
        .one_or_none()
    )
    if analysis_identity is None:
        raise CanonicalWriteDeniedError("Canonical state not found")
    _lock_workspace_mutations(
        db,
        [analysis_identity.workspace_id, workspace_id],
    )
    analysis, source_workspace = _lock_active_analysis(
        db,
        analysis_identity.id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    workspace = _lock_active_workspace(
        db,
        workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    lifecycle = _get_lifecycle(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    if lifecycle is not None and lifecycle.state != "active":
        raise ValueError("Diagram has been purged")
    previous_workspace_id = analysis.workspace_id
    if workspace.is_default and db.query(Workspace.id).filter(
        Workspace.owner_user_id == owner_user_id,
        Workspace.tenant_id == tenant_id,
        Workspace.is_default.is_(True),
        Workspace.id != workspace.id,
    ).first():
        workspace.is_default = False
    analysis.workspace_id = workspace.id
    source_candidates = db.query(SourceAsset).filter(
        SourceAsset.owner_user_id == owner_user_id,
        SourceAsset.tenant_id == tenant_id,
        or_(
            SourceAsset.id == analysis.source_asset_id,
            SourceAsset.diagram_id == diagram_id,
        ),
    ).all()
    for source in source_candidates:
        other_analysis = db.query(Analysis.id).filter(
            Analysis.source_asset_id == source.id,
            Analysis.id != analysis.id,
        ).first()
        other_artifact = db.query(Artifact.id).filter(
            Artifact.source_asset_id == source.id,
            Artifact.analysis_id != analysis.id,
        ).first()
        if other_analysis is None and other_artifact is None:
            source.workspace_id = workspace.id
    if lifecycle is None:
        lifecycle = DiagramLifecycle(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            workspace_id=workspace.id,
            generation=1,
            state="active",
        )
        db.add(lifecycle)
    else:
        lifecycle.workspace_id = workspace.id
    _assert_active_workspace(source_workspace)
    _assert_active_workspace(workspace)
    db.commit()
    db.refresh(analysis)
    return analysis, previous_workspace_id


def _purge_manifest(operation: PurgeOperation) -> Dict[str, Any]:
    try:
        manifest = _json.loads(operation.manifest or "{}")
    except (TypeError, ValueError):
        manifest = {}
    return manifest if isinstance(manifest, dict) else {}


def _artifact_blob_uris_for_diagram(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> List[str]:
    analysis_ids = [
        value
        for (value,) in db.query(Analysis.id).filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        ).all()
    ]
    if not analysis_ids:
        return []
    return sorted({
        str(value)
        for (value,) in db.query(Artifact.storage_url).filter(
            Artifact.analysis_id.in_(analysis_ids),
            Artifact.owner_user_id == owner_user_id,
            Artifact.tenant_id == tenant_id,
            Artifact.storage_url.is_not(None),
        ).all()
        if value
    })


def _diagram_workspace_id(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> Optional[str]:
    candidates = [
        db.query(Analysis.workspace_id).filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        ).scalar(),
        db.query(SourceAsset.workspace_id).filter(
            SourceAsset.diagram_id == diagram_id,
            SourceAsset.owner_user_id == owner_user_id,
            SourceAsset.tenant_id == tenant_id,
        ).scalar(),
        db.query(DiagramLifecycle.workspace_id).filter(
            DiagramLifecycle.diagram_id == diagram_id,
            DiagramLifecycle.owner_user_id == owner_user_id,
            DiagramLifecycle.tenant_id == tenant_id,
        ).scalar(),
    ]
    return next((str(value) for value in candidates if value is not None), None)


def _workspace_diagram_ids(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> List[str]:
    diagram_ids: set[str] = set()
    for model in (Analysis, SourceAsset, DiagramLifecycle):
        diagram_ids.update(
            str(value)
            for (value,) in db.query(model.diagram_id).filter(
                model.workspace_id == workspace_id,
                model.owner_user_id == owner_user_id,
                model.tenant_id == tenant_id,
                model.diagram_id.is_not(None),
            ).all()
        )
    diagram_ids.update(
        str(value)
        for (value,) in db.query(PurgeOperation.scope_id).filter(
            PurgeOperation.workspace_id == workspace_id,
            PurgeOperation.scope_type == "diagram",
            PurgeOperation.owner_user_id == owner_user_id,
            PurgeOperation.tenant_id == tenant_id,
        ).all()
    )
    return sorted(diagram_ids)


def load_purge_manifest(
    db: Session,
    *,
    operation_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """Return one operation manifest only within its durable security scope."""
    operation = db.query(PurgeOperation).filter(
        PurgeOperation.id == operation_id,
        PurgeOperation.owner_user_id == owner_user_id,
        PurgeOperation.tenant_id == tenant_id,
    ).one()
    return _purge_manifest(operation)


def merge_purge_manifest(
    db: Session,
    *,
    operation_id: str,
    owner_user_id: str,
    tenant_id: str,
    values: Dict[str, Any],
) -> Dict[str, Any]:
    """Add immutable discovery IDs to a scoped manifest without erasing retries."""
    query = db.query(PurgeOperation).filter(
        PurgeOperation.id == operation_id,
        PurgeOperation.owner_user_id == owner_user_id,
        PurgeOperation.tenant_id == tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    operation = query.one()
    manifest = _purge_manifest(operation)
    for key, value in values.items():
        if isinstance(value, list):
            current = manifest.get(key, [])
            if not isinstance(current, list):
                current = []
            manifest[key] = sorted({str(item) for item in [*current, *value]})
        elif key not in manifest or manifest[key] in (None, "", {}):
            manifest[key] = value
    operation.manifest = _json.dumps(manifest, sort_keys=True)
    db.commit()
    return manifest


def _purge_operation_query(
    db: Session,
    *,
    scope_type: str,
    scope_id: str,
    owner_user_id: str,
    tenant_id: str,
):
    return db.query(PurgeOperation).filter(
        PurgeOperation.scope_type == scope_type,
        PurgeOperation.scope_id == scope_id,
        PurgeOperation.owner_user_id == owner_user_id,
        PurgeOperation.tenant_id == tenant_id,
    )


def begin_diagram_purge(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> Optional[PurgeOperation]:
    """Persist a generation tombstone and retry receipt before cleanup."""
    operation_query = _purge_operation_query(
        db,
        scope_type="diagram",
        scope_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        operation_query = operation_query.with_for_update()
    operation = operation_query.first()
    lifecycle = _get_lifecycle(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    analysis = db.query(Analysis).filter(
        Analysis.diagram_id == diagram_id,
        Analysis.owner_user_id == owner_user_id,
        Analysis.tenant_id == tenant_id,
    ).first()
    source = db.query(SourceAsset).filter(
        SourceAsset.diagram_id == diagram_id,
        SourceAsset.owner_user_id == owner_user_id,
        SourceAsset.tenant_id == tenant_id,
    ).first()
    if operation is None and lifecycle is None and analysis is None and source is None:
        return None
    if lifecycle is None:
        lifecycle = DiagramLifecycle(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            workspace_id=(
                analysis.workspace_id
                if analysis
                else source.workspace_id
                if source
                else operation.workspace_id
                if operation
                else None
            ),
            generation=1,
            state="purging",
        )
        db.add(lifecycle)
        db.flush()
    elif lifecycle.state == "active":
        lifecycle.generation = int(lifecycle.generation or 0) + 1
        lifecycle.state = "purging"
    if operation is None:
        operation = PurgeOperation(
            scope_type="diagram",
            scope_id=diagram_id,
            workspace_id=(
                analysis.workspace_id
                if analysis is not None
                else source.workspace_id
                if source is not None
                else lifecycle.workspace_id
            ),
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            generation=lifecycle.generation,
        )
        db.add(operation)
    elif operation.status == "completed" and lifecycle.state == "purged":
        return operation
    operation.status = "in_progress"
    operation.attempts = int(operation.attempts or 0) + 1
    operation.last_error_stage = None
    if not _purge_manifest(operation):
        operation.manifest = _json.dumps(
            {
                "schema_version": 1,
                "scope_type": "diagram",
                "scope_id": diagram_id,
                "workspace_id": operation.workspace_id,
                "diagram_ids": [diagram_id],
                "blob_uris": _artifact_blob_uris_for_diagram(
                    db,
                    diagram_id=diagram_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                ),
                "job_ids": [],
                "job_event_ids": [],
            },
            sort_keys=True,
        )
    now = datetime.now(timezone.utc)
    db.query(RestoreGrant).filter(
        RestoreGrant.owner_user_id == owner_user_id,
        RestoreGrant.tenant_id == tenant_id,
        RestoreGrant.diagram_id == diagram_id,
        RestoreGrant.revoked_at.is_(None),
    ).update(
        {RestoreGrant.revoked_at: now, RestoreGrant.cleanup_at: now},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(operation)
    return operation


def begin_workspace_purge(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> tuple[PurgeOperation, List[str]]:
    """Tombstone a workspace and every child diagram before cleanup."""
    query = _purge_operation_query(
        db,
        scope_type="workspace",
        scope_id=workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    operation = query.first()
    workspace_query = db.query(Workspace).filter(
        Workspace.id == workspace_id,
        Workspace.owner_user_id == owner_user_id,
        Workspace.tenant_id == tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        workspace_query = workspace_query.with_for_update()
    workspace = workspace_query.first()
    if workspace is None:
        if operation is None:
            raise ValueError("Workspace not found")
        manifest = _purge_manifest(operation)
        stages = _json.loads(operation.stages or "{}")
        diagram_ids = set(manifest.get("diagram_ids", stages.get("_diagram_ids", [])))
        diagram_ids.update(
            value for (value,) in db.query(DiagramLifecycle.diagram_id).filter(
                DiagramLifecycle.workspace_id == workspace_id,
                DiagramLifecycle.owner_user_id == owner_user_id,
                DiagramLifecycle.tenant_id == tenant_id,
            ).all()
        )
        return operation, sorted(diagram_ids)
    diagram_ids = _workspace_diagram_ids(
        db,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if operation is None:
        operation = PurgeOperation(
            scope_type="workspace",
            scope_id=workspace_id,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        db.add(operation)
    elif operation.status == "completed":
        stages = _json.loads(operation.stages or "{}")
        return operation, list(stages.get("_diagram_ids", []))
    workspace.status = "deleting"
    operation.status = "in_progress"
    operation.attempts = int(operation.attempts or 0) + 1
    operation.last_error_stage = None
    existing_stages = _json.loads(operation.stages or "{}")
    existing_stages["_diagram_ids"] = diagram_ids
    operation.stages = _json.dumps(existing_stages, sort_keys=True)
    if not _purge_manifest(operation):
        operation.manifest = _json.dumps(
            {
                "schema_version": 1,
                "scope_type": "workspace",
                "scope_id": workspace_id,
                "workspace_id": workspace_id,
                "diagram_ids": diagram_ids,
                "blob_uris": sorted({
                    uri
                    for diagram_id in diagram_ids
                    for uri in _artifact_blob_uris_for_diagram(
                        db,
                        diagram_id=diagram_id,
                        owner_user_id=owner_user_id,
                        tenant_id=tenant_id,
                    )
                }),
                "job_ids": [],
                "job_event_ids": [],
            },
            sort_keys=True,
        )
    for diagram_id in diagram_ids:
        lifecycle = _get_lifecycle(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            for_update=True,
        )
        if lifecycle is None:
            lifecycle = DiagramLifecycle(
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                generation=1,
                state="purging",
            )
            db.add(lifecycle)
        elif lifecycle.state == "active":
            lifecycle.generation = int(lifecycle.generation or 0) + 1
            lifecycle.state = "purging"
    now = datetime.now(timezone.utc)
    db.query(RestoreGrant).filter(
        RestoreGrant.owner_user_id == owner_user_id,
        RestoreGrant.tenant_id == tenant_id,
        RestoreGrant.diagram_id.in_(diagram_ids),
        RestoreGrant.revoked_at.is_(None),
    ).update(
        {RestoreGrant.revoked_at: now, RestoreGrant.cleanup_at: now},
        synchronize_session=False,
    )
    db.commit()
    db.refresh(operation)
    return operation, diagram_ids


def record_purge_stage(
    db: Session,
    operation_id: str,
    *,
    stage: str,
    result: Any,
    failed: bool = False,
) -> PurgeOperation:
    operation = db.query(PurgeOperation).filter(PurgeOperation.id == operation_id).one()
    stages = _json.loads(operation.stages or "{}")
    stages[stage] = result
    operation.stages = _json.dumps(stages, sort_keys=True, default=str)
    if failed:
        operation.status = "failed"
    elif operation.status != "completed":
        operation.status = "in_progress"
    operation.last_error_stage = stage if failed else None
    db.commit()
    db.refresh(operation)
    return operation


def complete_diagram_purge(
    db: Session,
    operation_id: str,
    *,
    preserve_workspace_id: bool = False,
) -> PurgeOperation:
    operation = db.query(PurgeOperation).filter(PurgeOperation.id == operation_id).one()
    lifecycle = _get_lifecycle(
        db,
        diagram_id=operation.scope_id,
        owner_user_id=operation.owner_user_id,
        tenant_id=operation.tenant_id,
        for_update=True,
    )
    if lifecycle is not None:
        lifecycle.state = "purged"
        lifecycle.purged_at = datetime.now(timezone.utc)
        if not preserve_workspace_id:
            lifecycle.workspace_id = None
    operation.status = "completed"
    operation.last_error_stage = None
    operation.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(operation)
    return operation


def complete_workspace_purge(db: Session, operation_id: str) -> PurgeOperation:
    operation = db.query(PurgeOperation).filter(PurgeOperation.id == operation_id).one()
    stages = _json.loads(operation.stages or "{}")
    diagram_ids = list(stages.get("_diagram_ids", []))
    workspace = db.query(Workspace).filter(
        Workspace.id == operation.scope_id,
        Workspace.owner_user_id == operation.owner_user_id,
        Workspace.tenant_id == operation.tenant_id,
    ).first()
    if workspace is not None:
        db.delete(workspace)
    lifecycles = (
        db.query(DiagramLifecycle)
        .filter(
            DiagramLifecycle.owner_user_id == operation.owner_user_id,
            DiagramLifecycle.tenant_id == operation.tenant_id,
            or_(
                DiagramLifecycle.workspace_id == operation.scope_id,
                DiagramLifecycle.diagram_id.in_(diagram_ids),
            ),
        )
        .all()
    )
    for lifecycle in lifecycles:
        lifecycle.state = "purged"
        lifecycle.purged_at = datetime.now(timezone.utc)
        lifecycle.workspace_id = None
    operation.status = "completed"
    operation.last_error_stage = None
    operation.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(operation)
    return operation


def load_analysis_state(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: Optional[str],
    session_store: Any = None,
    cache_owner_api_key_id: Optional[str] = None,
    allow_legacy_cache_rehome: bool = False,
    cache_legacy_owner_user_ids: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Load the latest tenant-scoped durable snapshot and optionally hydrate cache."""
    _require_durable_identity(owner_user_id, tenant_id)
    assert tenant_id is not None
    analysis = _get_analysis_by_diagram(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if analysis is None or analysis.current_version <= 0:
        return None
    version = get_analysis_version(
        db,
        analysis_id=analysis.id,
        version_number=analysis.current_version,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if version is None:
        return None
    snapshot = _json.loads(version.snapshot)
    hydrated = {
        **snapshot,
        "diagram_id": diagram_id,
        "_tenant_id": tenant_id,
        "_analysis_version": version.version_number,
    }
    if cache_owner_api_key_id:
        hydrated["_owner_api_key_id"] = cache_owner_api_key_id
    else:
        hydrated["_owner_user_id"] = owner_user_id
    if session_store is not None:
        try:
            _write_session_cache(
                session_store,
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                snapshot=hydrated,
                version_number=version.version_number,
                owner_api_key_id=cache_owner_api_key_id,
                allow_existing=True,
                allow_legacy_tenant_rehome=allow_legacy_cache_rehome,
                legacy_owner_user_ids=cache_legacy_owner_user_ids,
                authoritative_hydration=True,
            )
        except Exception as exc:
            logger.warning(
                "analysis_cache_hydration_failed diagram_id=%s error_type=%s",
                safe(diagram_id),
                type(exc).__name__,
            )
    return hydrated


def get_analysis_by_diagram(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> Optional[Analysis]:
    """Return the durable analysis identity behind compatibility diagram APIs."""
    return _get_analysis_by_diagram(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )


def diagram_is_tombstoned(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> bool:
    """Return whether durable lifecycle state denies reads and mutations."""
    lifecycle = _get_lifecycle(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    return lifecycle is not None and lifecycle.state != "active"


def compare_analysis_versions(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    tenant_id: str,
    version_a: int,
    version_b: int,
) -> Dict[str, Any]:
    """Return the legacy diff shape from two durable immutable snapshots."""
    from versioning import _detect_changes

    first = get_analysis_version(
        db,
        analysis_id=analysis_id,
        version_number=version_a,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    second = get_analysis_version(
        db,
        analysis_id=analysis_id,
        version_number=version_b,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if first is None or second is None:
        return {"error": "One or both versions not found"}
    snapshot_a = _json.loads(first.snapshot)
    snapshot_b = _json.loads(second.snapshot)
    changes = _detect_changes(snapshot_a, snapshot_b)
    mappings_a = {m["source_service"]: m for m in snapshot_a.get("mappings", [])}
    mappings_b = {m["source_service"]: m for m in snapshot_b.get("mappings", [])}
    service_diff = []
    for service in sorted(set(mappings_a) | set(mappings_b)):
        in_a = service in mappings_a
        in_b = service in mappings_b
        status = (
            "unchanged" if in_a and in_b and mappings_a[service] == mappings_b[service]
            else "modified" if in_a and in_b
            else "removed" if in_a
            else "added"
        )
        service_diff.append(
            {
                "service": service,
                "status": status,
                "version_a": mappings_a.get(service),
                "version_b": mappings_b.get(service),
            }
        )
    analysis = get_analysis_record(
        db,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    assert analysis is not None
    return {
        "diagram_id": analysis.diagram_id,
        "version_a": version_a,
        "version_b": version_b,
        "changes": [change.to_dict() for change in changes],
        "service_diff": service_diff,
        "summary": {
            key: sum(1 for item in service_diff if item["status"] == key)
            for key in ("added", "removed", "modified", "unchanged")
        },
    }

def maybe_link_session(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: Optional[str] = None,
    diagram_id: str,
    session: Dict[str, Any],
    workspace_id: Optional[str] = None,
) -> Optional[AnalysisVersion]:
    """Compatibility wrapper for the canonical durable write boundary.

    If *workspace_id* is given the analysis is linked to that workspace.
    If no matching Analysis exists for *diagram_id*, a default workspace and
    analysis are created automatically so the session is never lost.

    Tenantless calls are retained only for non-authenticated/sample
    compatibility. Legacy callers still receive ``None`` instead of an exception. Active
    authenticated analysis paths call ``persist_analysis_state`` directly and
    fail closed when canonical persistence is unavailable.
    """
    if tenant_id is None:
        try:
            analysis = (
                db.query(Analysis)
                .filter(
                    Analysis.diagram_id == diagram_id,
                    Analysis.owner_user_id == owner_user_id,
                    Analysis.tenant_id.is_(None),
                )
                .first()
            )
            if analysis is None:
                if workspace_id is None:
                    workspace = (
                        db.query(Workspace)
                        .filter(
                            Workspace.owner_user_id == owner_user_id,
                            Workspace.tenant_id.is_(None),
                            Workspace.is_default.is_(True),
                            Workspace.status == "active",
                        )
                        .first()
                    )
                    if workspace is None:
                        workspace = create_workspace(
                            db,
                            owner_user_id=owner_user_id,
                            name="Default Workspace",
                            source_cloud=session.get("source_provider", "aws"),
                            target_cloud=session.get("target_provider", "azure"),
                            is_default=True,
                        )
                    workspace_id = workspace.id
                analysis = create_analysis(
                    db,
                    workspace_id=workspace_id,
                    owner_user_id=owner_user_id,
                    diagram_id=diagram_id,
                    source_cloud=session.get("source_provider", "aws"),
                    target_cloud=session.get("target_provider", "azure"),
                )
            return save_analysis_version(
                db,
                analysis_id=analysis.id,
                owner_user_id=owner_user_id,
                snapshot=session,
            )
        except Exception as exc:
            logger.warning("maybe_link_session_failed diagram_id=%s error=%s", safe(diagram_id), safe(str(exc)))
            return None

    try:
        analysis = _get_analysis_by_diagram(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        expected_version = int(analysis.current_version or 0) if analysis is not None else None
        if expected_version and session.get("_analysis_version") is not None and int(session["_analysis_version"]) != expected_version:
            logger.warning("maybe_link_session_rejected_stale_snapshot diagram_id=%s", safe(diagram_id))
            return None
        request_hash = hashlib.sha256(
            _json.dumps(
                {
                    "workspace_id": workspace_id,
                    "expected_version": expected_version,
                    "snapshot": session,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        result = persist_analysis_mutation(
            db,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            snapshot=session,
            workspace_id=workspace_id,
            expected_version=expected_version,
            operation="workspace-link",
            request_hash=request_hash,
            require_snapshot_version=False,
        )
        return result.version
    except Exception as exc:
        logger.warning("maybe_link_session_failed diagram_id=%s error=%s", safe(diagram_id), safe(str(exc)))
        return None
