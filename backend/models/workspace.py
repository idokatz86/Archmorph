"""
Durable workspace, analysis-version, and artifact database models (Issue #1129).

Introduces the persistence substrate required for saved workspaces and product
retention:

  Workspace       — top-level container owned by a user/tenant
  SourceAsset     — uploaded diagram/file linked to a workspace
  Analysis        — one analytical run within a workspace
  AnalysisVersion — immutable snapshot of an analysis (append-only)
  Artifact        — generated output (IaC, HLD, cost report, …) linked to a version
  Decision        — risk/decision record captured during an analysis run

Retention boundaries
--------------------
  transient    — Redis/session store only (current live sessions)
  workspace    — saved to this module's tables; survives session expiry
  audit        — written to audit_log (separate table, longer retention)
"""

import json as _json
import uuid as _uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from database import Base


def _new_uuid() -> str:
    return str(_uuid.uuid4())


# ─────────────────────────────────────────────────────────────
# Workspace
# ─────────────────────────────────────────────────────────────

class Workspace(Base):
    """Top-level durable container for a user's architecture work."""

    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    source_cloud = Column(String(20), nullable=False, server_default="aws")
    target_cloud = Column(String(20), nullable=False, server_default="azure")
    status = Column(String(20), nullable=False, server_default="active")  # active | archived
    is_public = Column(Boolean, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_workspaces_owner_tenant", "owner_user_id", "tenant_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "description": self.description,
            "source_cloud": self.source_cloud,
            "target_cloud": self.target_cloud,
            "status": self.status,
            "is_public": self.is_public,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─────────────────────────────────────────────────────────────
# SourceAsset
# ─────────────────────────────────────────────────────────────

class SourceAsset(Base):
    """Uploaded diagram/file attached to a workspace.

    Content bytes are **never** stored here; only metadata is persisted so
    that artifact records can reference provenance without retaining raw data.
    """

    __tablename__ = "source_assets"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    filename = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 hex
    diagram_id = Column(String(50), nullable=True, index=True)    # session store key
    source_cloud = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_source_assets_workspace_hash", "workspace_id", "content_hash"),
        Index("ix_source_assets_owner_tenant", "owner_user_id", "tenant_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_size_bytes": self.file_size_bytes,
            "content_hash": self.content_hash,
            "diagram_id": self.diagram_id,
            "source_cloud": self.source_cloud,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─────────────────────────────────────────────────────────────
# Analysis
# ─────────────────────────────────────────────────────────────

class Analysis(Base):
    """A single analytical run within a workspace.

    Links a workspace to one source asset and carries top-level metadata.
    The actual results are stored in ``AnalysisVersion`` snapshots.
    """

    __tablename__ = "analyses"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_asset_id = Column(
        String(36),
        ForeignKey("source_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    diagram_id = Column(String(50), nullable=True, index=True)    # session store key
    title = Column(String(300), nullable=True)
    source_cloud = Column(String(20), nullable=False, server_default="aws")
    target_cloud = Column(String(20), nullable=False, server_default="azure")
    status = Column(String(20), nullable=False, server_default="completed")
    services_detected = Column(Integer, server_default="0")
    confidence_avg = Column(Float, nullable=True)
    current_version = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_analyses_workspace_owner", "workspace_id", "owner_user_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "source_asset_id": self.source_asset_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "diagram_id": self.diagram_id,
            "title": self.title,
            "source_cloud": self.source_cloud,
            "target_cloud": self.target_cloud,
            "status": self.status,
            "services_detected": self.services_detected,
            "confidence_avg": self.confidence_avg,
            "current_version": self.current_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─────────────────────────────────────────────────────────────
# AnalysisVersion
# ─────────────────────────────────────────────────────────────

class AnalysisVersion(Base):
    """Immutable snapshot of an analysis at a point in time (append-only).

    Versions are never mutated after creation — restoring a version creates a
    new version record.  ``snapshot`` stores the full JSON session dict.
    """

    __tablename__ = "analysis_versions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    analysis_id = Column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number = Column(Integer, nullable=False)
    label = Column(String(100), nullable=True)
    snapshot = Column(Text, nullable=False)          # JSON-serialized session dict
    content_hash = Column(String(16), nullable=True, index=True)
    created_by = Column(String(100), nullable=True)
    restored_from = Column(Integer, nullable=True)   # version_number this was restored from
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_analysis_versions_analysis_num", "analysis_id", "version_number", unique=True),
    )

    def to_dict(self, *, include_snapshot: bool = False) -> dict:
        result: dict = {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "version_number": self.version_number,
            "label": self.label,
            "content_hash": self.content_hash,
            "created_by": self.created_by,
            "restored_from": self.restored_from,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_snapshot:
            result["snapshot"] = _json.loads(self.snapshot) if self.snapshot else {}
        return result


# ─────────────────────────────────────────────────────────────
# Artifact
# ─────────────────────────────────────────────────────────────

class Artifact(Base):
    """A generated output artifact linked to an analysis version.

    Artifact types include: terraform, bicep, hld, cost_report, architecture_package.
    Content bytes are stored as text (for text artifacts) or omitted when
    stored externally (``storage_url`` is set instead).
    """

    __tablename__ = "artifacts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    analysis_id = Column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        String(36),
        ForeignKey("analysis_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_asset_id = Column(
        String(36),
        ForeignKey("source_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    artifact_type = Column(String(50), nullable=False, index=True)  # terraform|bicep|hld|cost_report|…
    format = Column(String(20), nullable=True)                       # terraform|bicep|json|markdown
    content = Column(Text, nullable=True)                            # inline text content
    storage_url = Column(Text, nullable=True)                        # external blob URL
    content_hash = Column(String(64), nullable=True, index=True)     # SHA-256 hex
    size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_artifacts_analysis_type", "analysis_id", "artifact_type"),
        Index("ix_artifacts_owner_tenant", "owner_user_id", "tenant_id"),
    )

    def to_dict(self, *, include_content: bool = False) -> dict:
        result: dict = {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "version_id": self.version_id,
            "source_asset_id": self.source_asset_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "artifact_type": self.artifact_type,
            "format": self.format,
            "has_external_storage": bool(self.storage_url),
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_content:
            result["content"] = self.content
            result["storage_url"] = self.storage_url
        return result


# ─────────────────────────────────────────────────────────────
# Decision
# ─────────────────────────────────────────────────────────────

class Decision(Base):
    """A risk or architectural decision captured during an analysis run."""

    __tablename__ = "decisions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    analysis_id = Column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        String(36),
        ForeignKey("analysis_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(36), nullable=True, index=True)
    decision_type = Column(String(50), nullable=False)  # risk | decision | note
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(20), nullable=True)        # low | medium | high | critical
    status = Column(String(20), nullable=False, server_default="open")  # open | resolved | accepted
    extra_data = Column(Text, nullable=True)              # JSON-serialized extras
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_decisions_analysis_type", "analysis_id", "decision_type"),
        Index("ix_decisions_owner_tenant", "owner_user_id", "tenant_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "analysis_id": self.analysis_id,
            "version_id": self.version_id,
            "owner_user_id": self.owner_user_id,
            "tenant_id": self.tenant_id,
            "decision_type": self.decision_type,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "metadata": _json.loads(self.extra_data) if self.extra_data else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
