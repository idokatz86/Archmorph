"""
Archmorph Workspace Store — durable CRUD layer for workspaces, analyses,
analysis versions, artifacts, and decisions (Issue #1129).

Design principles
-----------------
* **Dual-write**: changes are written to the SQLAlchemy-backed database for
  durability and optionally to the session store for hot reads.
* **Session compatibility**: existing live-session flow is unaffected.  The
  ``maybe_link_session`` helper is a lightweight hook that workspace-aware
  callers can use after a session is saved.
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
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

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


def _short_hash(data: str) -> str:
    """Return a 16-char hex digest of *data* for content-addressed dedup."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _full_hash(data: bytes) -> str:
    """Return full 64-char SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


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
    if tenant_id:
        q = q.filter(Workspace.tenant_id == tenant_id)
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
    if tenant_id:
        q = q.filter(Workspace.tenant_id == tenant_id)
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
    **fields: Any,
) -> Optional[Workspace]:
    """Update allowed fields on a workspace. Returns None when not found/forbidden."""
    ws = get_workspace(db, workspace_id, owner_user_id=owner_user_id)
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
) -> bool:
    """Delete a workspace and its cascaded records. Returns True when deleted."""
    ws = get_workspace(db, workspace_id, owner_user_id=owner_user_id)
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
    filename: str,
    content_type: Optional[str] = None,
    file_size_bytes: Optional[int] = None,
    content_hash: Optional[str] = None,
    diagram_id: Optional[str] = None,
    source_cloud: Optional[str] = None,
) -> SourceAsset:
    """Record metadata for an uploaded source asset."""
    asset = SourceAsset(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
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
) -> Optional[SourceAsset]:
    """Return a source asset owned by *owner_user_id*."""
    return (
        db.query(SourceAsset)
        .filter(
            SourceAsset.id == asset_id,
            SourceAsset.owner_user_id == owner_user_id,
        )
        .first()
    )


def list_source_assets(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List source assets in a workspace."""
    q = db.query(SourceAsset).filter(
        SourceAsset.workspace_id == workspace_id,
        SourceAsset.owner_user_id == owner_user_id,
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
        analysis.id,
        workspace_id,
        diagram_id,
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
    if tenant_id:
        q = q.filter(Analysis.tenant_id == tenant_id)
    return q.first()


def list_analyses_in_workspace(
    db: Session,
    *,
    workspace_id: str,
    owner_user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List all analyses in a workspace."""
    q = db.query(Analysis).filter(
        Analysis.workspace_id == workspace_id,
        Analysis.owner_user_id == owner_user_id,
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
    snapshot: Dict[str, Any],
    label: Optional[str] = None,
    restored_from: Optional[int] = None,
) -> AnalysisVersion:
    """Append a new immutable version snapshot for *analysis_id*.

    Also updates ``Analysis.current_version`` and trims old versions when the
    per-analysis cap is exceeded.
    """
    analysis = (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.owner_user_id == owner_user_id)
        .first()
    )
    if analysis is None:
        raise ValueError(f"Analysis {analysis_id!r} not found or access denied")

    snapshot_json = _json.dumps(snapshot, default=str)
    content_hash = _short_hash(snapshot_json)
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

    # Update parent analysis
    analysis.current_version = new_version_number
    # Also update summary stats from snapshot
    mappings = snapshot.get("mappings", [])
    analysis.services_detected = snapshot.get("services_detected", len(mappings))
    confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
    if confidences:
        analysis.confidence_avg = round(sum(confidences) / len(confidences), 4)

    db.commit()
    db.refresh(version)

    # Trim oldest versions when cap exceeded
    _trim_old_versions(db, analysis_id)

    logger.debug(
        "analysis_version_saved analysis_id=%s version=%d hash=%s",
        analysis_id,
        new_version_number,
        content_hash,
    )
    return version


def _trim_old_versions(db: Session, analysis_id: str) -> None:
    """Delete oldest versions beyond MAX_VERSIONS_PER_ANALYSIS."""
    versions = (
        db.query(AnalysisVersion)
        .filter(AnalysisVersion.analysis_id == analysis_id)
        .order_by(AnalysisVersion.version_number.asc())
        .all()
    )
    excess = len(versions) - MAX_VERSIONS_PER_ANALYSIS
    if excess > 0:
        for v in versions[:excess]:
            db.delete(v)
        db.commit()


def list_analysis_versions(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
) -> List[Dict[str, Any]]:
    """List version metadata (no snapshot) for an analysis."""
    # Ownership check
    analysis = (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.owner_user_id == owner_user_id)
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
) -> Optional[AnalysisVersion]:
    """Return a version including snapshot; returns None when not found/forbidden."""
    analysis = (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.owner_user_id == owner_user_id)
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
    session_store: Any = None,
) -> Optional[AnalysisVersion]:
    """Restore a previous version by creating a new version from it.

    If *session_store* is provided the live session dict is also updated so
    the current session immediately reflects the restored state.

    Returns the new version record, or None when the source version is not found.
    """
    source = get_analysis_version(
        db,
        analysis_id=analysis_id,
        version_number=version_number,
        owner_user_id=owner_user_id,
    )
    if source is None:
        return None

    snapshot = _json.loads(source.snapshot)
    new_version = save_analysis_version(
        db,
        analysis_id=analysis_id,
        owner_user_id=owner_user_id,
        snapshot=snapshot,
        label=f"restored-from-v{version_number}",
        restored_from=version_number,
    )

    # Dual-write: update live session if store is provided and analysis has a diagram_id
    if session_store is not None:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis and analysis.diagram_id:
            try:
                session_store.set(analysis.diagram_id, snapshot)
                logger.info(
                    "session_restored_from_version diagram_id=%s version=%d",
                    analysis.diagram_id,
                    version_number,
                )
            except Exception as exc:  # nosec B110 — session store is best-effort
                logger.warning("session_store_restore_failed: %s", exc)

    return new_version


# ─────────────────────────────────────────────────────────────
# Artifact CRUD
# ─────────────────────────────────────────────────────────────

def create_artifact(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
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
) -> Optional[Artifact]:
    """Return an artifact owned by *owner_user_id*."""
    return (
        db.query(Artifact)
        .filter(
            Artifact.id == artifact_id,
            Artifact.owner_user_id == owner_user_id,
        )
        .first()
    )


def list_artifacts(
    db: Session,
    *,
    analysis_id: str,
    owner_user_id: str,
    artifact_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List artifacts for an analysis."""
    # Ownership check
    analysis = (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.owner_user_id == owner_user_id)
        .first()
    )
    if analysis is None:
        return {"artifacts": [], "total": 0, "limit": limit, "offset": offset}

    q = db.query(Artifact).filter(Artifact.analysis_id == analysis_id)
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
    decision_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List decisions for an analysis."""
    analysis = (
        db.query(Analysis)
        .filter(Analysis.id == analysis_id, Analysis.owner_user_id == owner_user_id)
        .first()
    )
    if analysis is None:
        return []
    q = db.query(Decision).filter(Decision.analysis_id == analysis_id)
    if decision_type:
        q = q.filter(Decision.decision_type == decision_type)
    return [d.to_dict() for d in q.order_by(Decision.created_at.desc()).all()]


# ─────────────────────────────────────────────────────────────
# Session ↔ Workspace bridge
# ─────────────────────────────────────────────────────────────

def maybe_link_session(
    db: Session,
    *,
    owner_user_id: str,
    diagram_id: str,
    session: Dict[str, Any],
    workspace_id: Optional[str] = None,
) -> Optional[AnalysisVersion]:
    """Hook: persist a session snapshot as a new analysis version.

    If *workspace_id* is given the analysis is linked to that workspace.
    If no matching Analysis exists for *diagram_id*, a default workspace and
    analysis are created automatically so the session is never lost.

    This is called from the existing session-save code paths and does not
    block or raise — all errors are logged and swallowed.
    """
    try:
        return _do_link_session(
            db,
            owner_user_id=owner_user_id,
            diagram_id=diagram_id,
            session=session,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        logger.warning("maybe_link_session_failed diagram_id=%s error=%s", diagram_id, exc)
        return None


def _do_link_session(
    db: Session,
    *,
    owner_user_id: str,
    diagram_id: str,
    session: Dict[str, Any],
    workspace_id: Optional[str],
) -> Optional[AnalysisVersion]:
    # Find or auto-create analysis for this diagram_id
    analysis = (
        db.query(Analysis)
        .filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
        )
        .first()
    )

    if analysis is None:
        # Auto-create default workspace when not supplied
        if workspace_id is None:
            existing_ws = (
                db.query(Workspace)
                .filter(
                    Workspace.owner_user_id == owner_user_id,
                    Workspace.name == "Default Workspace",
                    Workspace.status == "active",
                )
                .first()
            )
            if existing_ws:
                workspace_id = existing_ws.id
            else:
                new_ws = create_workspace(
                    db,
                    owner_user_id=owner_user_id,
                    name="Default Workspace",
                    source_cloud=session.get("source_provider", "aws"),
                    target_cloud=session.get("target_provider", "azure"),
                )
                workspace_id = new_ws.id

        mappings = session.get("mappings", [])
        service_count = session.get("services_detected", len(mappings))
        confidences = [m.get("confidence") for m in mappings if m.get("confidence") is not None]
        confidence_avg = round(sum(confidences) / len(confidences), 4) if confidences else None

        analysis = create_analysis(
            db,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            diagram_id=diagram_id,
            source_cloud=session.get("source_provider", "aws"),
            target_cloud=session.get("target_provider", "azure"),
            status="completed",
            services_detected=service_count,
            confidence_avg=confidence_avg,
        )

    return save_analysis_version(
        db,
        analysis_id=analysis.id,
        owner_user_id=owner_user_id,
        snapshot=session,
    )
