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
    transient    — Redis/session cache and coordination only
    workspace    — canonical PostgreSQL records; survives cache loss/expiry
  audit        — written to audit_log (separate table, longer retention)
"""

import json as _json
import uuid as _uuid
from enum import Enum

from sqlalchemy import (
    and_,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.sql import func

from database import Base


def _new_uuid() -> str:
    return str(_uuid.uuid4())


class WorkspaceStatus(str, Enum):
    """Supported durable workspace lifecycle states."""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETING = "deleting"


# ─────────────────────────────────────────────────────────────
# Workspace
# ─────────────────────────────────────────────────────────────

class Workspace(Base):
    """Top-level durable container for a user's architecture work."""

    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    source_cloud = Column(String(20), nullable=False, server_default="aws")
    target_cloud = Column(String(20), nullable=False, server_default="azure")
    status = Column(String(20), nullable=False, server_default=WorkspaceStatus.ACTIVE.value)
    is_public = Column(Boolean, nullable=False, server_default=false())
    is_default = Column(Boolean, nullable=False, server_default=false())
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'deleting')",
            name="ck_workspaces_status",
        ),
        Index("ix_workspaces_owner_tenant", "owner_user_id", "tenant_id"),
        Index(
            "ux_workspaces_default_owner_tenant",
            "owner_user_id",
            "tenant_id",
            unique=True,
            postgresql_where=and_(is_default.is_(True), tenant_id.is_not(None)),
            sqlite_where=and_(is_default.is_(True), tenant_id.is_not(None)),
        ),
        Index(
            "ux_workspaces_default_owner_no_tenant",
            "owner_user_id",
            unique=True,
            postgresql_where=and_(is_default.is_(True), tenant_id.is_(None)),
            sqlite_where=and_(is_default.is_(True), tenant_id.is_(None)),
        ),
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
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─────────────────────────────────────────────────────────────
# Project membership
# ─────────────────────────────────────────────────────────────

class ProjectMember(Base):
    """Durable member authorization scoped to one owner/tenant project."""

    __tablename__ = "project_members"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    project_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False, index=True)
    member_user_id = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False, server_default="viewer")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "ux_project_members_project_member",
            "project_id",
            "member_user_id",
            unique=True,
        ),
        Index(
            "ix_project_members_scope",
            "project_owner_user_id",
            "tenant_id",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "user_id": self.member_user_id,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class APIKeyCredential(Base):
    """Durable hashed API-key credential mapped to a stable client principal."""

    __tablename__ = "api_key_credentials"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    principal_id = Column(String(100), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True)
    key_prefix = Column(String(12), nullable=False)
    scopes = Column(Text, nullable=False)
    rate_limit = Column(Integer, nullable=False, server_default="100")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked = Column(Boolean, nullable=False, server_default=false())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_api_key_credentials_active", "principal_id", "revoked"),
    )


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
    tenant_id = Column(String(100), nullable=True, index=True)
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
    tenant_id = Column(String(100), nullable=True, index=True)
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
        Index(
            "ux_analyses_owner_tenant_diagram",
            "owner_user_id",
            "tenant_id",
            "diagram_id",
            unique=True,
            postgresql_where=and_(tenant_id.is_not(None), diagram_id.is_not(None)),
            sqlite_where=and_(tenant_id.is_not(None), diagram_id.is_not(None)),
        ),
        Index(
            "ux_analyses_owner_no_tenant_diagram",
            "owner_user_id",
            "diagram_id",
            unique=True,
            postgresql_where=and_(tenant_id.is_(None), diagram_id.is_not(None)),
            sqlite_where=and_(tenant_id.is_(None), diagram_id.is_not(None)),
        ),
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
        UniqueConstraint(
            "analysis_id",
            "id",
            name="uq_analysis_versions_analysis_id_id",
        ),
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


class AnalysisMutationReceipt(Base):
    """Durable idempotency receipt for one scoped analysis mutation."""

    __tablename__ = "analysis_mutation_receipts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    diagram_id = Column(String(50), nullable=False)
    operation = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    analysis_id = Column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_id = Column(
        String(36),
        ForeignKey("analysis_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ux_analysis_mutation_receipts_scope",
            "owner_user_id",
            "tenant_id",
            "diagram_id",
            "operation",
            "request_hash",
            unique=True,
        ),
        Index("ix_analysis_mutation_receipts_analysis", "analysis_id"),
    )


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
    tenant_id = Column(String(100), nullable=True, index=True)
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
        Index(
            "ux_artifacts_version_type_hash",
            "version_id",
            "artifact_type",
            "content_hash",
            unique=True,
            postgresql_where=and_(version_id.is_not(None), content_hash.is_not(None)),
            sqlite_where=and_(version_id.is_not(None), content_hash.is_not(None)),
        ),
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
        nullable=True,
        index=True,
    )
    owner_user_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=True, index=True)
    decision_type = Column(String(50), nullable=False)  # risk | decision | note
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String(20), nullable=True)        # low | medium | high | critical
    status = Column(String(20), nullable=False, server_default="open")  # open | resolved | accepted
    extra_data = Column(Text, nullable=True)              # JSON-serialized extras
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id", "version_id"],
            ["analysis_versions.analysis_id", "analysis_versions.id"],
            name="fk_decisions_analysis_version",
            ondelete="RESTRICT",
        ),
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


class TenantRehomeAudit(Base):
    """Operator audit for guarded legacy tenant migration and quarantine."""

    __tablename__ = "tenant_rehome_audit"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    owner_user_id = Column(String(100), nullable=False, index=True)
    source_tenant_id = Column(String(100), nullable=False)
    target_tenant_id = Column(String(100), nullable=True)
    status = Column(String(40), nullable=False, index=True)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TenantRehomeAlias(Base):
    """Durable source-to-target mapping for each migrated or quarantined graph."""

    __tablename__ = "tenant_rehome_aliases"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    source_owner_user_id = Column(String(100), nullable=False)
    source_tenant_id = Column(String(100), nullable=False)
    target_owner_user_id = Column(String(100), nullable=True)
    target_tenant_id = Column(String(100), nullable=True)
    entity_type = Column(String(20), nullable=False)
    source_entity_id = Column(String(100), nullable=False)
    target_entity_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False)
    reason = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('workspace', 'analysis')",
            name="ck_tenant_rehome_aliases_entity_type",
        ),
        CheckConstraint(
            "status IN ('rehomed', 'quarantined', 'resolved')",
            name="ck_tenant_rehome_aliases_status",
        ),
        Index(
            "ux_tenant_rehome_aliases_source",
            "source_owner_user_id",
            "source_tenant_id",
            "entity_type",
            "source_entity_id",
            unique=True,
        ),
        Index(
            "ix_tenant_rehome_aliases_target",
            "target_owner_user_id",
            "target_tenant_id",
        ),
    )


class MigrationReplay(Base):
    """Canonical replay header bound to one immutable analysis version."""

    __tablename__ = "migration_replays"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    analysis_id = Column(
        String(36),
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(String(36), nullable=False)
    diagram_id = Column(String(50), nullable=False, index=True)
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    title = Column(String(256), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["analysis_id", "version_id"],
            ["analysis_versions.analysis_id", "analysis_versions.id"],
            name="fk_migration_replays_analysis_version",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_migration_replays_scope_created",
            "owner_user_id",
            "tenant_id",
            "created_at",
        ),
    )


class MigrationReplayEvent(Base):
    """Append-only event in a canonical migration replay."""

    __tablename__ = "migration_replay_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    replay_id = Column(
        String(36),
        ForeignKey("migration_replays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False)
    event_type = Column(String(40), nullable=False)
    data = Column(Text, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ux_migration_replay_events_sequence",
            "replay_id",
            "sequence",
            unique=True,
        ),
    )


class DiagramLifecycle(Base):
    """Durable generation, deletion tombstone, and current workspace binding."""

    __tablename__ = "diagram_lifecycle"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    diagram_id = Column(String(50), nullable=False)
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation = Column(Integer, nullable=False, server_default="1")
    state = Column(String(20), nullable=False, server_default="active")
    purged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'purging', 'purged')",
            name="ck_diagram_lifecycle_state",
        ),
        Index(
            "ux_diagram_lifecycle_scope",
            "owner_user_id",
            "tenant_id",
            "diagram_id",
            unique=True,
        ),
        Index("ix_diagram_lifecycle_diagram", "diagram_id"),
    )


class RestoreGrant(Base):
    """Server-held one-time restore capability bound to immutable claims."""

    __tablename__ = "restore_grants"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    nonce_digest = Column(String(64), nullable=False, unique=True)
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    diagram_id = Column(String(50), nullable=False)
    generation = Column(Integer, nullable=False)
    expected_version = Column(Integer, nullable=False, server_default="0")
    payload_hash = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ix_restore_grants_scope",
            "owner_user_id",
            "tenant_id",
            "diagram_id",
            "generation",
        ),
    )


class PurgeOperation(Base):
    """Restart-safe deletion operation and completion receipt."""

    __tablename__ = "purge_operations"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    scope_type = Column(String(20), nullable=False)
    scope_id = Column(String(50), nullable=False)
    workspace_id = Column(String(36), nullable=True, index=True)
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, server_default="pending")
    generation = Column(Integer, nullable=True)
    manifest = Column(Text, nullable=False, server_default="{}")
    stages = Column(Text, nullable=False, server_default="{}")
    last_error_stage = Column(String(100), nullable=True)
    attempts = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('diagram', 'workspace')",
            name="ck_purge_operations_scope",
        ),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'failed', 'completed')",
            name="ck_purge_operations_status",
        ),
        Index(
            "ux_purge_operations_scope",
            "owner_user_id",
            "tenant_id",
            "scope_type",
            "scope_id",
            unique=True,
        ),
        Index("ix_purge_operations_status", "status"),
    )
