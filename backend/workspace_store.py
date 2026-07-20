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
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from log_sanitizer import safe
from models.workspace import (
    Analysis,
    AnalysisVersion,
    Artifact,
    Decision,
    SourceAsset,
    TenantRehomeAudit,
    Workspace,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

MAX_VERSIONS_PER_ANALYSIS = 50
MAX_WORKSPACES_PER_USER = 500


class DurableAnalysisPersistenceError(RuntimeError):
    """Raised when canonical analysis state cannot be committed."""


class AnalysisCacheWriteError(RuntimeError):
    """Raised when a required cache refresh fails after a durable commit."""


class AnalysisVersionConflictError(RuntimeError):
    """Raised when an optimistic mutation targets an obsolete durable version."""


@dataclass(frozen=True)
class AnalysisWriteResult:
    """Result of one canonical analysis persistence operation."""

    analysis: Analysis
    version: AnalysisVersion
    cache_updated: bool
    artifact: Optional[Artifact] = None


def _short_hash(data: str) -> str:
    """Return a 16-char hex digest of *data* for content-addressed dedup."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _full_hash(data: bytes) -> str:
    """Return full 64-char SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def _tenant_matches(column, tenant_id: Optional[str]):
    return column.is_(None) if tenant_id is None else column == tenant_id


def _redact_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Remove internal ownership/session fields before durable storage or API return."""
    redacted = dict(snapshot or {})
    for key in list(redacted):
        if key.startswith("_owner_") or key in {"_tenant_id", "export_capability", "exportCapability"}:
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


def _require_durable_identity(owner_user_id: str, tenant_id: Optional[str]) -> None:
    """Reject implicit or incomplete identity on authenticated durable writes."""
    if not owner_user_id or not tenant_id:
        raise ValueError("Authenticated durable analysis records require owner_user_id and tenant_id")


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
    q = db.query(Workspace).filter(Workspace.owner_user_id == owner_user_id)
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
    ws = get_workspace(db, workspace_id, owner_user_id=owner_user_id, tenant_id=tenant_id)
    if ws is None:
        return None
    allowed = {"name", "description", "status", "source_cloud", "target_cloud"}
    for k, v in fields.items():
        if k in allowed:
            setattr(ws, k, v)
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
    workspace = get_workspace(db, workspace_id, owner_user_id=owner_user_id, tenant_id=tenant_id)
    if workspace is None:
        raise ValueError(f"Workspace {workspace_id!r} not found or access denied")

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
    workspace = get_workspace(db, workspace_id, owner_user_id=owner_user_id, tenant_id=tenant_id)
    if workspace is None:
        raise ValueError(f"Workspace {workspace_id!r} not found or access denied")

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
    """Return an analysis record owned by *owner_user_id*."""
    q = db.query(Analysis).filter(
        Analysis.id == analysis_id,
        Analysis.owner_user_id == owner_user_id,
    )
    q = q.filter(_tenant_matches(Analysis.tenant_id, tenant_id))
    return q.first()


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
        query = db.query(Analysis)
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update()
        analysis = (
            query
            .filter(
                Analysis.id == analysis_id,
                Analysis.owner_user_id == owner_user_id,
                _tenant_matches(Analysis.tenant_id, tenant_id),
            )
            .first()
        )
        if analysis is None:
            raise ValueError(f"Analysis {analysis_id!r} not found or access denied")

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
    """Delete oldest unreferenced versions beyond MAX_VERSIONS_PER_ANALYSIS."""
    versions = (
        db.query(AnalysisVersion)
        .filter(AnalysisVersion.analysis_id == analysis_id)
        .order_by(AnalysisVersion.version_number.asc())
        .all()
    )
    excess = len(versions) - MAX_VERSIONS_PER_ANALYSIS
    if excess > 0:
        for v in versions[:excess]:
            referenced = (
                db.query(Artifact.id)
                .filter(Artifact.version_id == v.id)
                .first()
                or db.query(Decision.id).filter(Decision.version_id == v.id).first()
            )
            if referenced:
                continue
            db.delete(v)
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
) -> Optional[AnalysisVersion]:
    """Restore a previous version by creating a new version from it.

    ``session_store`` remains accepted for API compatibility. Cache refresh is
    delegated to the same durable-first write boundary used by active analysis
    completion paths.

    Returns the new version record, or None when the source version is not found.
    """
    source = get_analysis_version(
        db,
        analysis_id=analysis_id,
        version_number=version_number,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if source is None:
        return None

    snapshot = _json.loads(source.snapshot)
    analysis = get_analysis_record(
        db,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    assert analysis is not None
    if analysis.diagram_id and tenant_id is not None:
        result = persist_analysis_state(
            db,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=analysis.diagram_id,
            snapshot=snapshot,
            workspace_id=analysis.workspace_id,
            session_store=session_store,
            cache_owner_api_key_id=cache_owner_api_key_id,
            label=f"restored-from-v{version_number}",
            restored_from=version_number,
        )
        return result.version

    new_version = save_analysis_version(
        db,
        analysis_id=analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        snapshot=snapshot,
        label=f"restored-from-v{version_number}",
        restored_from=version_number,
    )
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
    analysis = get_analysis_record(
        db,
        analysis_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if analysis is None:
        raise ValueError(f"Analysis {analysis_id!r} not found or access denied")
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
    version_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Decision:
    """Record a risk or architectural decision."""
    decision = Decision(
        analysis_id=analysis_id,
        version_id=version_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        decision_type=decision_type,
        title=title,
        description=description,
        severity=severity,
        extra_data=_json.dumps(metadata or {}),
    )
    db.add(decision)
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
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        )
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _resolve_workspace_id(
    db: Session,
    *,
    owner_user_id: str,
    tenant_id: str,
    snapshot: Dict[str, Any],
    workspace_id: Optional[str],
) -> str:
    if workspace_id is not None:
        workspace = get_workspace(
            db,
            workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        if workspace is None:
            raise ValueError(f"Workspace {workspace_id!r} not found or access denied")
        return workspace.id

    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.owner_user_id == owner_user_id,
            Workspace.tenant_id == tenant_id,
            Workspace.is_default.is_(True),
            Workspace.status == "active",
        )
        .first()
    )
    if workspace is not None:
        return workspace.id

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
                Workspace.status == "active",
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
    allow_unowned_upload_claim: bool = False,
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
        tenant_matches = current.get("_tenant_id") == tenant_id or (
            owner_api_key_id is not None
            and current.get("_owner_api_key_id") == owner_api_key_id
            and current.get("_tenant_id") is None
        ) or (
            allow_legacy_tenant_rehome
            and current.get("_owner_user_id") == owner_user_id
            and current.get("_tenant_id") == "default_tenant"
        )
        return (
            owner_matches
            and tenant_matches
            and (current_version is None or int(current_version) <= version_number)
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
    artifact_type: Optional[str] = None,
    artifact_format: Optional[str] = None,
    artifact_content: Optional[str] = None,
    cache_owner_api_key_id: Optional[str] = None,
    cache_required: bool = False,
    allow_legacy_cache_rehome: bool = False,
    allow_unowned_upload_claim: bool = False,
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
            analysis = _get_analysis_by_diagram(
                db,
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                for_update=True,
            )
            if analysis is None:
                resolved_workspace_id = _resolve_workspace_id(
                    db,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    snapshot=snapshot,
                    workspace_id=workspace_id,
                )
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
            elif workspace_id is not None and analysis.workspace_id != workspace_id:
                raise ValueError(f"Analysis for diagram {diagram_id!r} belongs to another workspace")

            if expected_version is not None and int(analysis.current_version or 0) != expected_version:
                raise AnalysisVersionConflictError(
                    f"Expected version {expected_version}, current version is {analysis.current_version}"
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
            db.commit()
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
            _write_session_cache(
                session_store,
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                snapshot=snapshot,
                version_number=version.version_number,
                owner_api_key_id=cache_owner_api_key_id,
                allow_legacy_tenant_rehome=allow_legacy_cache_rehome,
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
    )


def persist_analysis_mutation(db: Session, **kwargs: Any) -> AnalysisWriteResult:
    """Named repository/UoW entry point for every authenticated mutation."""
    return persist_analysis_state(db, **kwargs)


def rehome_legacy_analysis_scope(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    source_tenant_id: str,
    target_tenant_id: str,
) -> str:
    """Move one exact-owner legacy analysis graph to a verified tenant scope.

    The provider is never inferred here. ``target_tenant_id`` must already have
    been derived from the currently verified principal. Conflicts are audited
    and denied without changing either namespace.
    """
    if not target_tenant_id or source_tenant_id == target_tenant_id:
        return "not_found"

    query = db.query(Analysis).filter(
        Analysis.diagram_id == diagram_id,
        Analysis.owner_user_id == owner_user_id,
        Analysis.tenant_id == source_tenant_id,
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    legacy_rows = query.all()
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
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == analysis.workspace_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.tenant_id == source_tenant_id,
        )
        .first()
    )
    if workspace is None:
        return "not_found"

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
    diagram_ids = [item.diagram_id for item in workspace_analyses if item.diagram_id]
    target_conflict = (
        db.query(Analysis.id)
        .filter(
            Analysis.owner_user_id == owner_user_id,
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
            Workspace.owner_user_id == owner_user_id,
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

    workspace.tenant_id = target_tenant_id
    db.query(SourceAsset).filter(
        SourceAsset.workspace_id == workspace.id,
        SourceAsset.owner_user_id == owner_user_id,
        SourceAsset.tenant_id == source_tenant_id,
    ).update({SourceAsset.tenant_id: target_tenant_id}, synchronize_session=False)
    for workspace_analysis in workspace_analyses:
        workspace_analysis.tenant_id = target_tenant_id
    db.query(Artifact).filter(
        Artifact.analysis_id.in_(analysis_ids),
        Artifact.owner_user_id == owner_user_id,
        Artifact.tenant_id == source_tenant_id,
    ).update({Artifact.tenant_id: target_tenant_id}, synchronize_session=False)
    db.query(Decision).filter(
        Decision.analysis_id.in_(analysis_ids),
        Decision.owner_user_id == owner_user_id,
        Decision.tenant_id == source_tenant_id,
    ).update({Decision.tenant_id: target_tenant_id}, synchronize_session=False)
    db.add(TenantRehomeAudit(
        owner_user_id=owner_user_id,
        source_tenant_id=source_tenant_id,
        target_tenant_id=target_tenant_id,
        status="access_rehome_completed",
        details=_json.dumps(
            {
                "analysis_ids": analysis_ids,
                "diagram_id": diagram_id,
                "workspace_id": workspace.id,
            },
            sort_keys=True,
        ),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.add(TenantRehomeAudit(
            owner_user_id=owner_user_id,
            source_tenant_id=source_tenant_id,
            target_tenant_id=target_tenant_id,
            status="conflict_denied",
            details=_json.dumps(
                {"diagram_id": diagram_id, "reason": "concurrent_integrity_conflict"},
                sort_keys=True,
            ),
        ))
        db.commit()
        return "conflict"
    return "rehomed"


def purge_analysis_state(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    cleanup_empty_implicit_workspace: bool = True,
) -> Dict[str, Any]:
    """Delete one tenant-scoped durable analysis graph before purge receipt."""
    analysis = _get_analysis_by_diagram(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        for_update=True,
    )
    counts = {
        "analyses": 0,
        "versions": 0,
        "artifacts": 0,
        "decisions": 0,
        "implicit_workspaces": 0,
    }
    if analysis is None:
        return counts

    workspace_id = analysis.workspace_id
    counts["artifacts"] = db.query(Artifact).filter(Artifact.analysis_id == analysis.id).delete(
        synchronize_session=False
    )
    counts["decisions"] = db.query(Decision).filter(Decision.analysis_id == analysis.id).delete(
        synchronize_session=False
    )
    counts["versions"] = db.query(AnalysisVersion).filter(
        AnalysisVersion.analysis_id == analysis.id
    ).delete(synchronize_session=False)
    db.delete(analysis)
    db.flush()
    counts["analyses"] = 1

    if cleanup_empty_implicit_workspace:
        workspace = (
            db.query(Workspace)
            .filter(
                Workspace.id == workspace_id,
                Workspace.owner_user_id == owner_user_id,
                Workspace.tenant_id == tenant_id,
                Workspace.is_default.is_(True),
            )
            .first()
        )
        remaining = db.query(Analysis.id).filter(Analysis.workspace_id == workspace_id).first()
        sources = db.query(SourceAsset.id).filter(SourceAsset.workspace_id == workspace_id).first()
        if workspace is not None and remaining is None and sources is None:
            db.delete(workspace)
            counts["implicit_workspaces"] = 1
    db.commit()
    return counts


def load_analysis_state(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: Optional[str],
    session_store: Any = None,
    cache_owner_api_key_id: Optional[str] = None,
    allow_legacy_cache_rehome: bool = False,
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
                allow_existing=allow_legacy_cache_rehome,
                allow_legacy_tenant_rehome=allow_legacy_cache_rehome,
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
        result = persist_analysis_state(
            db,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            snapshot=session,
            workspace_id=workspace_id,
        )
        return result.version
    except Exception as exc:
        logger.warning("maybe_link_session_failed diagram_id=%s error=%s", safe(diagram_id), safe(str(exc)))
        return None
