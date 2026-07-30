"""Restart-safe fixed-point deletion for diagrams and workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import analysis_history
import openai_client
import usage_metrics
from artifact_blob_store import artifact_blob_absent, delete_artifact_blob
import database
from iac_chat import clear_iac_chat, has_iac_chat
from job_queue import job_manager
from models.workspace import (
    Analysis,
    DiagramLifecycle,
    PurgeOperation,
    RestoreGrant,
    SourceAsset,
    Workspace,
)
from routers import collaboration_routes, replay_routes, tf_backend
from routers.shared import (
    EXPORT_CAPABILITY_STORE,
    IMAGE_STORE,
    PROJECT_STORE,
    SESSION_STORE,
    SHARE_STORE,
)
import shareable_reports
from services import credential_manager
import versioning
import vision_analyzer
from workspace_store import (
    begin_diagram_purge,
    begin_workspace_purge,
    complete_diagram_purge,
    complete_workspace_purge,
    load_purge_manifest,
    merge_purge_manifest,
    purge_analysis_state,
    record_purge_stage,
)


def _session():
    return database.SessionLocal()


@dataclass(frozen=True)
class PurgeResult:
    operation_id: str
    status: str
    project_id: str | None
    deleted: dict[str, Any]


class PurgeIncompleteError(RuntimeError):
    def __init__(self, operation_id: str, stage: str):
        super().__init__(f"Purge operation is incomplete at {stage}")
        self.operation_id = operation_id
        self.stage = stage


def _store_records_for_diagram(store, diagram_id: str) -> list[str]:
    return [
        key
        for key in store.keys("*")
        if isinstance((value := store.peek(key)), dict)
        and value.get("diagram_id") == diagram_id
    ]


def _purge_store_records(store, diagram_id: str) -> int:
    keys = _store_records_for_diagram(store, diagram_id)
    for key in keys:
        if not store.delete(key):
            raise RuntimeError("Store deletion could not be confirmed")
    return len(keys)


def _delete_key(store, key: str) -> bool:
    present = store.peek(key) is not None
    if not store.delete(key):
        raise RuntimeError("Store deletion could not be confirmed")
    return present


def _run_stage(operation_id: str, stage: str, callback: Callable[[], Any]) -> Any:
    try:
        result = callback()
    except Exception as exc:
        db = _session()
        try:
            record_purge_stage(
                db,
                operation_id,
                stage=stage,
                result={"confirmed_absent": False, "error_type": type(exc).__name__},
                failed=True,
            )
        finally:
            db.close()
        raise PurgeIncompleteError(operation_id, stage) from exc
    db = _session()
    try:
        record_purge_stage(
            db,
            operation_id,
            stage=stage,
            result={"confirmed_absent": True, "result": result},
        )
    finally:
        db.close()
    return result


def _durable_diagram_absent(diagram_id: str, owner_user_id: str, tenant_id: str) -> bool:
    db = _session()
    try:
        if db.query(Analysis.id).filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        ).first():
            return False
        sources = db.query(SourceAsset).filter(
            SourceAsset.diagram_id == diagram_id,
            SourceAsset.owner_user_id == owner_user_id,
            SourceAsset.tenant_id == tenant_id,
        ).all()
        for source in sources:
            analysis_reference = db.query(Analysis.id).filter(
                Analysis.source_asset_id == source.id
            ).first()
            from models.workspace import Artifact

            artifact_reference = db.query(Artifact.id).filter(
                Artifact.source_asset_id == source.id
            ).first()
            if analysis_reference is None and artifact_reference is None:
                return False
        return True
    finally:
        db.close()


def _operation_manifest(operation_id: str, owner_user_id: str, tenant_id: str) -> dict[str, Any]:
    db = _session()
    try:
        return load_purge_manifest(
            db,
            operation_id=operation_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
    finally:
        db.close()


def _capture_job_manifest(
    operation_id: str,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    discovered = job_manager.manifest_diagram(
        diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    db = _session()
    try:
        return merge_purge_manifest(
            db,
            operation_id=operation_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            values={
                "job_ids": discovered["job_ids"],
                "job_event_ids": discovered["event_ids"],
            },
        )
    finally:
        db.close()


def _job_manifest(manifest: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "job_ids": [str(value) for value in manifest.get("job_ids", [])],
        "event_ids": [str(value) for value in manifest.get("job_event_ids", [])],
    }


def _delete_manifested_blobs(
    manifest: dict[str, Any],
    owner_user_id: str,
    tenant_id: str,
) -> dict[str, int]:
    deleted = 0
    already_absent = 0
    for uri in manifest.get("blob_uris", []):
        if delete_artifact_blob(
            str(uri),
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ):
            deleted += 1
        else:
            already_absent += 1
    return {"deleted": deleted, "already_absent": already_absent}


def _manifested_blobs_absent(
    manifest: dict[str, Any],
    owner_user_id: str,
    tenant_id: str,
) -> bool:
    return all(
        artifact_blob_absent(
            str(uri),
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        for uri in manifest.get("blob_uris", [])
    )


def _project_diagram_absent(workspace_id: str | None, diagram_id: str) -> bool:
    if not workspace_id:
        return True
    project = PROJECT_STORE.peek(workspace_id)
    if not isinstance(project, dict):
        return True
    diagram_ids = project.get("diagram_ids", [])
    diagrams = project.get("diagrams", [])
    return bool(
        diagram_id not in diagram_ids
        and not any(
            isinstance(item, dict) and item.get("diagram_id") == diagram_id
            for item in diagrams
        )
    )


def _purge_project_diagram(workspace_id: str | None, diagram_id: str) -> int:
    if not workspace_id:
        return 0
    project = PROJECT_STORE.peek(workspace_id)
    if not isinstance(project, dict):
        return 0
    updated = dict(project)
    updated["diagram_ids"] = [value for value in project.get("diagram_ids", []) if value != diagram_id]
    updated["diagrams"] = [
        value
        for value in project.get("diagrams", [])
        if not isinstance(value, dict) or value.get("diagram_id") != diagram_id
    ]
    if updated == project:
        return 0
    PROJECT_STORE.set(workspace_id, updated)
    if not _project_diagram_absent(workspace_id, diagram_id):
        raise RuntimeError("Project diagram removal could not be confirmed")
    return 1


def diagram_fixed_point_checks(
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    *,
    operation_id: str | None = None,
) -> dict[str, bool]:
    """Return confirmed-absence checks for every diagram state domain."""
    db = _session()
    try:
        live_grant = db.query(RestoreGrant.id).filter(
            RestoreGrant.owner_user_id == owner_user_id,
            RestoreGrant.tenant_id == tenant_id,
            RestoreGrant.diagram_id == diagram_id,
            RestoreGrant.consumed_at.is_(None),
            RestoreGrant.revoked_at.is_(None),
        ).first()
    finally:
        db.close()
    manifest = (
        _operation_manifest(operation_id, owner_user_id, tenant_id)
        if operation_id is not None
        else {}
    )
    workspace_id = manifest.get("workspace_id")
    return {
        "session": SESSION_STORE.peek(diagram_id) is None,
        "image": IMAGE_STORE.peek(diagram_id) is None,
        "vision_cache": vision_analyzer.diagram_cache_absent(diagram_id),
        "gpt_response_cache": openai_client.diagram_response_cache_absent(diagram_id),
        "export_capabilities": not _store_records_for_diagram(
            EXPORT_CAPABILITY_STORE, diagram_id
        ),
        "share_store": not _store_records_for_diagram(SHARE_STORE, diagram_id),
        "share_links": shareable_reports.diagram_shares_absent(diagram_id),
        "jobs": job_manager.diagram_absent(
            diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            manifest=_job_manifest(manifest),
        ),
        "iac_chat": not has_iac_chat(diagram_id),
        "collaboration": collaboration_routes.diagram_collaboration_absent(diagram_id),
        "replays": replay_routes.diagram_replays_absent(diagram_id),
        "history": analysis_history.diagram_absent(diagram_id, owner_user_id),
        "version_history": versioning.diagram_versions_absent(diagram_id),
        "usage_telemetry": usage_metrics.usage_telemetry_absent(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ),
        "restore_grants": live_grant is None,
        "project_membership": _project_diagram_absent(workspace_id, diagram_id),
        "blob_objects": _manifested_blobs_absent(manifest, owner_user_id, tenant_id),
        "durable_graph": _durable_diagram_absent(diagram_id, owner_user_id, tenant_id),
    }


def diagram_fixed_point(
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    *,
    operation_id: str | None = None,
) -> bool:
    return all(
        diagram_fixed_point_checks(
            diagram_id,
            owner_user_id,
            tenant_id,
            operation_id=operation_id,
        ).values()
    )


def _purge_durable_diagram(
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    *,
    cleanup_empty_implicit_workspace: bool,
) -> dict[str, Any]:
    db = _session()
    try:
        return purge_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            cleanup_empty_implicit_workspace=cleanup_empty_implicit_workspace,
        )
    finally:
        db.close()


def purge_diagram(
    *,
    diagram_id: str,
    owner_user_id: str,
    tenant_id: str,
    preserve_workspace_id: bool = False,
) -> PurgeResult:
    """Converge one diagram to confirmed absence before returning success."""
    db = _session()
    try:
        analysis = db.query(Analysis).filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner_user_id,
            Analysis.tenant_id == tenant_id,
        ).first()
        lifecycle = db.query(DiagramLifecycle).filter(
            DiagramLifecycle.diagram_id == diagram_id,
            DiagramLifecycle.owner_user_id == owner_user_id,
            DiagramLifecycle.tenant_id == tenant_id,
        ).first()
        project_id = analysis.workspace_id if analysis else lifecycle.workspace_id if lifecycle else None
        operation = begin_diagram_purge(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        if operation is None:
            raise ValueError("Diagram not found")
        operation_id = operation.id
        operation_status = operation.status
    finally:
        db.close()

    if operation_status == "completed":
        try:
            if diagram_fixed_point(
                diagram_id,
                owner_user_id,
                tenant_id,
                operation_id=operation_id,
            ):
                return PurgeResult(operation_id, "completed", project_id, {})
        except Exception:
            # Re-enter the idempotent stages; storage/read failures must never
            # turn a historical receipt into an unverified success response.
            pass

    deleted: dict[str, Any] = {}
    deleted["session"] = _run_stage(operation_id, "session", lambda: _delete_key(SESSION_STORE, diagram_id))
    deleted["image"] = _run_stage(operation_id, "image", lambda: _delete_key(IMAGE_STORE, diagram_id))
    deleted["vision_cache"] = _run_stage(
        operation_id,
        "vision_cache",
        lambda: vision_analyzer.purge_diagram_cache(diagram_id),
    )
    deleted["gpt_response_cache"] = _run_stage(
        operation_id,
        "gpt_response_cache",
        lambda: openai_client.purge_diagram_response_cache(diagram_id),
    )
    deleted["export_capabilities"] = _run_stage(
        operation_id,
        "export_capabilities",
        lambda: _purge_store_records(EXPORT_CAPABILITY_STORE, diagram_id),
    )
    deleted["share_store"] = _run_stage(
        operation_id,
        "share_store",
        lambda: _purge_store_records(SHARE_STORE, diagram_id),
    )
    deleted["share_links"] = _run_stage(
        operation_id,
        "share_links",
        lambda: shareable_reports.purge_diagram_shares(diagram_id),
    )
    manifest = _capture_job_manifest(operation_id, diagram_id, owner_user_id, tenant_id)
    job_counts = _run_stage(
        operation_id,
        "jobs",
        lambda: job_manager.purge_diagram(
            diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            manifest=_job_manifest(manifest),
        ),
    )
    deleted["jobs"] = len(manifest.get("job_ids", []))
    deleted["job_events"] = job_counts["event_rings"]
    deleted["iac_chat"] = _run_stage(operation_id, "iac_chat", lambda: clear_iac_chat(diagram_id))
    deleted["collaboration"] = _run_stage(
        operation_id,
        "collaboration",
        lambda: collaboration_routes.purge_diagram_collaboration(diagram_id),
    )
    deleted["replays"] = _run_stage(
        operation_id,
        "replays",
        lambda: replay_routes.purge_diagram_replays(diagram_id),
    )
    deleted["history"] = _run_stage(
        operation_id,
        "history",
        lambda: analysis_history.purge_diagram(diagram_id, owner_user_id),
    )
    deleted["version_history"] = _run_stage(
        operation_id,
        "version_history",
        lambda: versioning.purge_diagram_versions(diagram_id),
    )
    deleted["usage_telemetry"] = _run_stage(
        operation_id,
        "usage_telemetry",
        lambda: usage_metrics.purge_usage_telemetry(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ),
    )
    deleted["project_membership"] = _run_stage(
        operation_id,
        "project_membership",
        lambda: _purge_project_diagram(manifest.get("workspace_id"), diagram_id),
    )
    deleted["blob_objects"] = _run_stage(
        operation_id,
        "blob_objects",
        lambda: _delete_manifested_blobs(manifest, owner_user_id, tenant_id),
    )
    deleted["durable"] = _run_stage(
        operation_id,
        "durable_graph",
        lambda: _purge_durable_diagram(
            diagram_id,
            owner_user_id,
            tenant_id,
            cleanup_empty_implicit_workspace=not preserve_workspace_id,
        ),
    )

    try:
        checks = diagram_fixed_point_checks(
            diagram_id,
            owner_user_id,
            tenant_id,
            operation_id=operation_id,
        )
    except Exception as exc:
        db = _session()
        try:
            record_purge_stage(
                db,
                operation_id,
                stage="fixed_point",
                result={"confirmed_absent": False, "error_type": type(exc).__name__},
                failed=True,
            )
        finally:
            db.close()
        raise PurgeIncompleteError(operation_id, "fixed_point") from exc
    if not all(checks.values()):
        db = _session()
        try:
            record_purge_stage(
                db,
                operation_id,
                stage="fixed_point",
                result={"confirmed_absent": False, "checks": checks},
                failed=True,
            )
        finally:
            db.close()
        failed_checks = ",".join(key for key, confirmed in checks.items() if not confirmed)
        raise PurgeIncompleteError(operation_id, f"fixed_point:{failed_checks}")

    db = _session()
    try:
        complete_diagram_purge(
            db,
            operation_id,
            preserve_workspace_id=preserve_workspace_id,
        )
    finally:
        db.close()
    return PurgeResult(operation_id, "completed", project_id, deleted)


def _workspace_fixed_point(
    workspace_id: str,
    owner_user_id: str,
    tenant_id: str,
    diagram_ids: list[str],
) -> bool:
    db = _session()
    try:
        workspace_absent = db.query(Workspace.id).filter(
            Workspace.id == workspace_id,
            Workspace.owner_user_id == owner_user_id,
            Workspace.tenant_id == tenant_id,
        ).first() is None
        state_absent = tf_backend.project_state_absent(db, workspace_id, owner_user_id, tenant_id)
        child_operation_ids = dict(
            db.query(PurgeOperation.scope_id, PurgeOperation.id).filter(
                PurgeOperation.scope_type == "diagram",
                PurgeOperation.scope_id.in_(diagram_ids),
                PurgeOperation.owner_user_id == owner_user_id,
                PurgeOperation.tenant_id == tenant_id,
            ).all()
        )
    finally:
        db.close()
    return bool(
        workspace_absent
        and state_absent
        and PROJECT_STORE.peek(workspace_id) is None
        and credential_manager.scope_credentials_absent(owner_user_id, tenant_id)
        and usage_metrics.usage_telemetry_absent(
            project_id=workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        and all(
            diagram_fixed_point(
                diagram_id,
                owner_user_id,
                tenant_id,
                operation_id=child_operation_ids.get(diagram_id),
            )
            for diagram_id in diagram_ids
        )
    )


def _purge_workspace_sql_state(workspace_id: str, owner_user_id: str, tenant_id: str) -> int:
    db = _session()
    try:
        return tf_backend.purge_project_state(db, workspace_id, owner_user_id, tenant_id)
    finally:
        db.close()


def _complete_workspace(operation_id: str) -> bool:
    db = _session()
    try:
        complete_workspace_purge(db, operation_id)
        return True
    finally:
        db.close()


def purge_workspace(*, workspace_id: str, owner_user_id: str, tenant_id: str) -> PurgeResult:
    """Converge all workspace child state and SQL graph to deletion."""
    db = _session()
    try:
        operation, diagram_ids = begin_workspace_purge(
            db,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        operation_id = operation.id
        operation_status = operation.status
    finally:
        db.close()

    if operation_status == "completed":
        try:
            if _workspace_fixed_point(
                workspace_id,
                owner_user_id,
                tenant_id,
                diagram_ids,
            ):
                return PurgeResult(operation_id, "completed", workspace_id, {})
        except Exception:
            pass

    deleted_diagrams: dict[str, Any] = {}
    for diagram_id in diagram_ids:
        try:
            deleted_diagrams[diagram_id] = purge_diagram(
                diagram_id=diagram_id,
                owner_user_id=owner_user_id,
                tenant_id=tenant_id,
                preserve_workspace_id=True,
            ).deleted
        except (PurgeIncompleteError, ValueError) as exc:
            db = _session()
            try:
                record_purge_stage(
                    db,
                    operation_id,
                    stage=f"diagram:{diagram_id}",
                    result={"confirmed_absent": False, "error_type": type(exc).__name__},
                    failed=True,
                )
            finally:
                db.close()
            raise PurgeIncompleteError(operation_id, f"diagram:{diagram_id}") from exc

    _run_stage(
        operation_id,
        "project_cache",
        lambda: _delete_key(PROJECT_STORE, workspace_id),
    )
    _run_stage(
        operation_id,
        "terraform_state",
        lambda: _purge_workspace_sql_state(workspace_id, owner_user_id, tenant_id),
    )
    _run_stage(
        operation_id,
        "credentials",
        lambda: credential_manager.purge_scope_credentials(owner_user_id, tenant_id),
    )
    _run_stage(
        operation_id,
        "usage_telemetry",
        lambda: usage_metrics.purge_usage_telemetry(
            project_id=workspace_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ),
    )
    _run_stage(operation_id, "workspace_graph", lambda: _complete_workspace(operation_id))
    try:
        fixed_point = _workspace_fixed_point(
            workspace_id,
            owner_user_id,
            tenant_id,
            diagram_ids,
        )
    except Exception as exc:
        db = _session()
        try:
            record_purge_stage(
                db,
                operation_id,
                stage="fixed_point",
                result={"confirmed_absent": False, "error_type": type(exc).__name__},
                failed=True,
            )
        finally:
            db.close()
        raise PurgeIncompleteError(operation_id, "fixed_point") from exc
    if not fixed_point:
        db = _session()
        try:
            record_purge_stage(
                db,
                operation_id,
                stage="fixed_point",
                result={"confirmed_absent": False},
                failed=True,
            )
        finally:
            db.close()
        raise PurgeIncompleteError(operation_id, "fixed_point")
    return PurgeResult(
        operation_id,
        "completed",
        workspace_id,
        {"workspace": True, "diagrams": deleted_diagrams},
    )
