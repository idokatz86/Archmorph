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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from log_sanitizer import safe
from models.workspace import (
    Analysis,
    AnalysisVersion,
    Artifact,
    Decision,
    SourceAsset,
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


@dataclass(frozen=True)
class AnalysisWriteResult:
    """Result of one canonical analysis persistence operation."""

    analysis: Analysis
    version: AnalysisVersion
    cache_updated: bool


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
) -> Workspace:
    """Create and persist a new Workspace."""
    ws = Workspace(
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        name=name,
        description=description,
        source_cloud=source_cloud,
        target_cloud=target_cloud,
    )
    db.add(ws)
    db.commit()
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
    snapshot_json = _json.dumps(snapshot, default=str)
    content_hash = _short_hash(snapshot_json)
    mappings = snapshot.get("mappings", [])
    confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
    services_detected = snapshot.get("services_detected", len(mappings))
    confidence_avg = round(sum(confidences) / len(confidences), 4) if confidences else None

    last_integrity_error: Optional[IntegrityError] = None
    for _attempt in range(3):
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
            raise ValueError(f"Analysis {analysis_id!r} not found or access denied")

        new_version_number = analysis.current_version + 1
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
) -> Artifact:
    """Record a generated artifact."""
    content_hash: Optional[str] = None
    size_bytes: Optional[int] = None
    if content:
        content_hash = _full_hash(content.encode("utf-8"))
        size_bytes = len(content.encode("utf-8"))

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
    db.commit()
    db.refresh(artifact)
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
            Workspace.name == "Default Workspace",
            Workspace.status == "active",
        )
        .first()
    )
    if workspace is not None:
        return workspace.id

    workspace = Workspace(
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        name="Default Workspace",
        source_cloud=snapshot.get("source_provider", "aws"),
        target_cloud=snapshot.get("target_provider", "azure"),
    )
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
    snapshot_json = _json.dumps(redacted, default=str)
    mappings = redacted.get("mappings", [])
    confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
    services_detected = redacted.get("services_detected", len(mappings))
    confidence_avg = round(sum(confidences) / len(confidences), 4) if confidences else None
    version_number = analysis.current_version + 1
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
    snapshot_json = _json.dumps(_redact_snapshot(snapshot), default=str)
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
    allow_existing: bool = True,
) -> None:
    cached_snapshot = {
        **_redact_snapshot(snapshot),
        "diagram_id": diagram_id,
        "_owner_user_id": owner_user_id,
        "_tenant_id": tenant_id,
    }
    if not allow_existing:
        updated, _current = session_store.update_if(
            diagram_id,
            lambda current: current is None,
            lambda _current: cached_snapshot,
        )
        if not updated:
            raise AnalysisCacheWriteError("Refusing to hydrate over an existing cache entry")
        return

    def _same_owner(current: Any) -> bool:
        return current is None or (
            isinstance(current, dict)
            and current.get("_owner_user_id") in (None, owner_user_id)
            and current.get("_tenant_id") in (None, tenant_id)
        )

    updated, _current = session_store.update_if(
        diagram_id,
        _same_owner,
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
    cache_required: bool = False,
) -> AnalysisWriteResult:
    """Commit authenticated analysis state, then refresh its transient cache.

    The database transaction is the success boundary. A cache failure never
    rolls back or replaces canonical PostgreSQL state. Callers that cannot
    continue without a fresh cache can set ``cache_required=True`` and receive
    ``AnalysisCacheWriteError`` after the durable commit succeeds.
    """
    _require_durable_identity(owner_user_id, tenant_id)
    assert tenant_id is not None

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
        db.commit()
    except ValueError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise DurableAnalysisPersistenceError("Failed to persist canonical analysis state") from exc

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

    return AnalysisWriteResult(analysis=analysis, version=version, cache_updated=cache_updated)


def load_analysis_state(
    db: Session,
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: Optional[str],
    session_store: Any = None,
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
        "_owner_user_id": owner_user_id,
        "_tenant_id": tenant_id,
    }
    if session_store is not None:
        try:
            _write_session_cache(
                session_store,
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                snapshot=hydrated,
                allow_existing=False,
            )
        except Exception as exc:
            logger.warning(
                "analysis_cache_hydration_failed diagram_id=%s error_type=%s",
                safe(diagram_id),
                type(exc).__name__,
            )
    return hydrated

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
                            Workspace.name == "Default Workspace",
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
