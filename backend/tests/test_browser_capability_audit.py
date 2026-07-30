"""Adversarial closure tests for mixed browser auth and scoped capabilities."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import logging
import time

import pytest

from auth import AuthProvider, User, generate_session_token
from export_capabilities import (
    _digest,
    attach_export_capability_for_persisted_job,
    issue_export_capability_for_identity,
)
from job_queue import Job, JobManager
from models.workspace import ProjectMember
from routers import shared
from routers.api_keys_routes import _hash_index, _keys, create_api_key, rotate_api_key
from routers.collaboration_routes import (
    _change_store,
    _participant_capability_record,
    _session_store,
)
from routers.shared import EXPORT_CAPABILITY_STORE, IMAGE_STORE, SESSION_STORE
from shareable_reports import _shares, create_share, get_share_stats
from workspace_store import create_workspace, persist_analysis_state


OWNER = "browser-capability-owner"
TENANT = "browser-capability-tenant"
FOREIGN = "browser-capability-foreign"

BASE_ANALYSIS = {
    "title": "Browser Capability Audit",
    "source_provider": "aws",
    "target_provider": "azure",
    "zones": [],
    "mappings": [
        {
            "source_service": "Lambda",
            "azure_service": "Azure Functions",
            "category": "compute",
            "confidence": 0.95,
        }
    ],
    "warnings": [],
}


def _auth_headers(
    user_id: str,
    tenant_id: str = TENANT,
    *,
    provider: AuthProvider = AuthProvider.GITHUB,
    provider_subject: str | None = None,
) -> dict[str, str]:
    user = User(
        id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
        provider=provider,
        provider_subject=provider_subject,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


def _seed_analysis(
    diagram_id: str,
    *,
    owner: str = OWNER,
    tenant: str = TENANT,
    two_versions: bool = False,
    explicit_project: bool = False,
    cache_owner_api_key_id: str | None = None,
) -> tuple[str, str]:
    from database import SessionLocal

    db = SessionLocal()
    try:
        workspace_id = None
        if explicit_project:
            workspace_id = create_workspace(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                name=f"Project {diagram_id}",
            ).id
        first = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            workspace_id=workspace_id,
            snapshot={**copy.deepcopy(BASE_ANALYSIS), "diagram_id": diagram_id},
            session_store=SESSION_STORE,
            cache_owner_api_key_id=cache_owner_api_key_id,
            cache_required=True,
        )
        if two_versions:
            persist_analysis_state(
                db,
                owner_user_id=owner,
                tenant_id=tenant,
                diagram_id=diagram_id,
                workspace_id=first.analysis.workspace_id,
                snapshot={
                    **copy.deepcopy(BASE_ANALYSIS),
                    "diagram_id": diagram_id,
                    "title": "Browser Capability Audit v2",
                    "_analysis_version": 1,
                },
                session_store=SESSION_STORE,
                cache_owner_api_key_id=cache_owner_api_key_id,
                cache_required=True,
                expected_version=1,
                operation=f"prepare-{diagram_id}",
                request_hash=hashlib.sha256(diagram_id.encode()).hexdigest(),
            )
        return first.analysis.id, first.analysis.workspace_id
    finally:
        db.close()


def _capability_record(token: str) -> dict:
    record = EXPORT_CAPABILITY_STORE.peek(_digest(token))
    assert isinstance(record, dict)
    return record


@pytest.fixture(autouse=True)
def _isolated_capability_state(monkeypatch):
    from job_queue import job_manager

    monkeypatch.setenv("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "true")
    monkeypatch.setattr(shared, "API_KEY", "configured-static-browser-key")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "")
    monkeypatch.setattr(
        shared, "API_KEY_PRINCIPAL_ID", "configured-static-browser-principal"
    )
    EXPORT_CAPABILITY_STORE.clear()
    _session_store.clear()
    _change_store.clear()
    _shares.clear()
    _keys.clear()
    _hash_index.clear()
    job_manager._jobs.clear()
    job_manager._jobs_store.clear()
    job_manager._events_store.clear()
    job_manager._active_counts_store.clear()
    job_manager._idempotency_store.clear()
    yield
    EXPORT_CAPABILITY_STORE.clear()
    _session_store.clear()
    _change_store.clear()
    _shares.clear()
    _keys.clear()
    _hash_index.clear()
    job_manager._jobs.clear()
    job_manager._jobs_store.clear()
    job_manager._events_store.clear()
    job_manager._active_counts_store.clear()
    job_manager._idempotency_store.clear()


def test_bearer_only_restore_share_and_v1_aliases_ignore_configured_static_key(
    test_client,
    monkeypatch,
):
    diagram_id = "mixed-auth-browser-routes"
    _seed_analysis(diagram_id, two_versions=True)
    bearer = _auth_headers(OWNER)
    coexistence = {**bearer, "X-API-Key": "invalid-and-must-not-shadow-bearer"}
    restore_headers = {
        **coexistence,
        "If-Match": 'W/"2"',
        "Idempotency-Key": "browser-restore-idempotency",
    }

    restored = test_client.post(
        f"/api/diagrams/{diagram_id}/versions/1/restore",
        headers=restore_headers,
    )
    replay_alias = test_client.post(
        f"/api/v1/diagrams/{diagram_id}/versions/1/restore",
        headers=restore_headers,
    )
    assert restored.status_code == replay_alias.status_code == 200
    assert restored.json()["new_version"]["version_number"] == 3
    assert replay_alias.json() == restored.json()

    monkeypatch.setattr(
        "routers.hld_routes.diagrams_compat.generate_hld",
        lambda **_kwargs: {"title": "Bearer HLD", "sections": []},
    )
    monkeypatch.setattr(
        "routers.hld_routes.diagrams_compat.generate_hld_markdown",
        lambda _hld: "# Bearer HLD",
    )
    hld = test_client.post(
        f"/api/v1/diagrams/{diagram_id}/generate-hld",
        headers=coexistence,
    )
    assert hld.status_code == 200, hld.text

    created = test_client.post(
        f"/api/v1/diagrams/{diagram_id}/share",
        headers=coexistence,
    )
    assert created.status_code == 200, created.text
    share_id = created.json()["share_id"]
    stats = test_client.get(f"/api/shared/{share_id}/stats", headers=bearer)
    foreign = test_client.get(
        f"/api/shared/{share_id}/stats",
        headers=_auth_headers(FOREIGN),
    )
    revoked = test_client.delete(
        f"/api/v1/shared/{share_id}",
        headers=bearer,
    )
    after_revoke = test_client.get(f"/api/shared/{share_id}/stats", headers=bearer)
    assert stats.status_code == 200
    assert foreign.status_code == 404
    assert revoked.status_code == 200
    assert after_revoke.status_code == 404


def test_participant_capability_only_flow_is_bound_non_oracular_and_not_ambient(
    test_client,
    caplog,
):
    diagram_id = "participant-capability-scope"
    _seed_analysis(diagram_id, explicit_project=True)
    owner_headers = _auth_headers(OWNER)
    created_response = test_client.post(
        "/api/collab/sessions",
        headers=owner_headers,
        json={"analysis_id": diagram_id, "owner": OWNER},
    )
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()

    with caplog.at_level(logging.INFO):
        capability_only = test_client.get(
            f"/api/v1/collab/sessions/{created['session_id']}",
            headers={"X-Participant-Capability": created["participant_token"]},
        )
    assert capability_only.status_code == 200, capability_only.text
    assert created["participant_token"] not in caplog.text

    member_headers = _auth_headers("browser-capability-member")
    joined = test_client.post(
        f"/api/v1/collab/sessions/{created['session_id']}/join",
        headers=member_headers,
        json={
            "share_code": created["share_code"],
            "user_id": "browser-capability-member",
            "role": "security",
        },
    )
    assert joined.status_code == 200, joined.text
    member_token = joined.json()["participant_token"]
    submitted = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        json={
            "user_id": "browser-capability-member",
            "participant_token": member_token,
            "change_type": "approval",
            "payload": {"approved": True},
        },
    )
    submitted_header = test_client.post(
        f"/api/v1/collab/sessions/{created['session_id']}/changes",
        headers={"X-Participant-Capability": member_token},
        json={
            "user_id": "browser-capability-member",
            "change_type": "comment",
            "payload": {"text": "header transport"},
        },
    )
    ambiguous = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        headers={"X-Participant-Capability": member_token},
        json={
            "user_id": "browser-capability-member",
            "participant_token": "different-explicit-capability",
            "change_type": "comment",
            "payload": {},
        },
    )
    history = test_client.get(
        f"/api/v1/collab/sessions/{created['session_id']}/changes",
        headers={"X-Participant-Capability": member_token},
    )
    assert (
        submitted.status_code
        == submitted_header.status_code
        == history.status_code
        == 200
    )
    assert ambiguous.status_code == 404
    assert history.json()["total"] == 2

    stored = _session_store.peek(created["session_id"])
    participant = next(
        item
        for item in stored["participants"]
        if item["user_id"] == "browser-capability-member"
    )
    original_binding = copy.deepcopy(participant["participant_capability"])

    malformed = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        headers={"X-Participant-Capability": "malformed-capability"},
    )
    participant["participant_capability"] = {
        **original_binding,
        "expires_at": time.time() - 1,
    }
    _session_store.set(created["session_id"], stored)
    expired = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        headers={"X-Participant-Capability": member_token},
    )
    participant["participant_capability"] = {
        **original_binding,
        "revoked_at": time.time(),
    }
    _session_store.set(created["session_id"], stored)
    revoked = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        headers={"X-Participant-Capability": member_token},
    )
    second = test_client.post(
        "/api/collab/sessions",
        headers=owner_headers,
        json={"analysis_id": diagram_id, "owner": OWNER},
    ).json()
    foreign_session = test_client.get(
        f"/api/collab/sessions/{second['session_id']}",
        headers={"X-Participant-Capability": member_token},
    )
    denials = [malformed, expired, revoked, foreign_session]
    assert {response.status_code for response in denials} == {404}
    assert {response.json()["error"]["message"] for response in denials} == {
        "Collaboration session not found"
    }

    query_read = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        params={"participant_capability": member_token},
    )
    query_write = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        params={"participant_token": member_token},
        json={
            "user_id": "browser-capability-member",
            "participant_token": member_token,
            "change_type": "comment",
            "payload": {},
        },
    )
    unrelated_workspace = test_client.get(
        "/api/workspaces",
        headers={"X-Participant-Capability": member_token},
    )
    assert query_read.status_code == query_write.status_code == 400
    assert unrelated_workspace.status_code == 401


def test_canonical_b2c_alias_migrates_collaboration_share_and_restore_owner(
    test_client,
):
    legacy_id = "azure_ad_b2c_legacy-browser-owner"
    canonical_subject = "canonical-browser-subject"
    tenant_id = "b2c-browser-tenant"
    diagram_id = "b2c-browser-diagram"
    _seed_analysis(
        diagram_id,
        owner=canonical_subject,
        tenant=tenant_id,
        two_versions=True,
        explicit_project=True,
    )
    headers = _auth_headers(
        legacy_id,
        tenant_id,
        provider=AuthProvider.AZURE_AD_B2C,
        provider_subject=canonical_subject,
    )

    restored = test_client.post(
        f"/api/v1/diagrams/{diagram_id}/versions/1/restore",
        headers={
            **headers,
            "If-Match": '"2"',
            "Idempotency-Key": "b2c-browser-restore",
        },
    )
    assert restored.status_code == 200, restored.text

    created = test_client.post(
        "/api/collab/sessions",
        headers=headers,
        json={"analysis_id": diagram_id, "owner": legacy_id},
    )
    assert created.status_code == 200, created.text
    assert created.json()["owner"] == canonical_subject
    session_id = created.json()["session_id"]
    stored = _session_store.peek(session_id)
    stored["owner"] = legacy_id
    stored["participants"][0]["user_id"] = legacy_id
    stored["participants"][0]["participant_capability"] = (
        _participant_capability_record(
            stored,
            stored["participants"][0],
            intent="collaboration:participant",
        )
    )
    _session_store.set(session_id, stored)
    migrated = test_client.get(f"/api/collab/sessions/{session_id}", headers=headers)
    assert migrated.status_code == 200, migrated.text
    migrated_record = _session_store.peek(session_id)
    assert migrated_record["owner"] == canonical_subject
    assert migrated_record["participants"][0]["user_id"] == canonical_subject

    share = create_share(
        {"diagram_id": diagram_id, **BASE_ANALYSIS},
        creator_id=legacy_id,
        creator_tenant_id=tenant_id,
    )
    stats = test_client.get(
        f"/api/v1/shared/{share['share_id']}/stats",
        headers=headers,
    )
    assert stats.status_code == 200, stats.text
    migrated_share = get_share_stats(share["share_id"])
    assert migrated_share["creator_id"] == canonical_subject
    assert migrated_share["creator_tenant_id"] == tenant_id


def test_project_editor_collaboration_capability_tracks_durable_membership(test_client):
    diagram_id = "editor-collaboration-membership"
    _analysis_id, project_id = _seed_analysis(diagram_id, explicit_project=True)
    from database import SessionLocal

    db = SessionLocal()
    try:
        db.add(
            ProjectMember(
                project_id=project_id,
                project_owner_user_id=OWNER,
                tenant_id=TENANT,
                member_user_id=FOREIGN,
                role="editor",
            )
        )
        db.commit()
    finally:
        db.close()

    created = test_client.post(
        "/api/collab/sessions",
        headers=_auth_headers(FOREIGN),
        json={"analysis_id": diagram_id, "owner": FOREIGN},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    stored = _session_store.peek(payload["session_id"])
    assert stored["owner"] == FOREIGN
    assert stored["project_owner_user_id"] == OWNER

    allowed = test_client.get(
        f"/api/collab/sessions/{payload['session_id']}",
        headers={"X-Participant-Capability": payload["participant_token"]},
    )
    assert allowed.status_code == 200

    db = SessionLocal()
    try:
        db.query(ProjectMember).filter_by(
            project_id=project_id,
            member_user_id=FOREIGN,
        ).delete()
        db.commit()
    finally:
        db.close()
    revoked = test_client.get(
        f"/api/collab/sessions/{payload['session_id']}",
        headers={"X-Participant-Capability": payload["participant_token"]},
    )
    assert revoked.status_code == 404


def test_managed_key_read_write_scope_is_explicit_on_browser_routes(test_client):
    reader_record, reader_key = create_api_key("browser-reader", ["read"])
    reader_owner = f"api-key:{reader_record.principal_id}"
    reader_tenant = f"service:{reader_record.principal_id}"
    reader_diagram = "managed-reader-browser-diagram"
    _seed_analysis(
        reader_diagram,
        owner=reader_owner,
        tenant=reader_tenant,
        two_versions=True,
        cache_owner_api_key_id=reader_owner,
    )
    reader_headers = {"X-API-Key": reader_key}
    versions = test_client.get(
        f"/api/v1/diagrams/{reader_diagram}/versions",
        headers=reader_headers,
    )
    denied_restore = test_client.post(
        f"/api/diagrams/{reader_diagram}/versions/1/restore",
        headers={
            **reader_headers,
            "If-Match": '"2"',
            "Idempotency-Key": "managed-reader-restore",
        },
    )
    share = create_share(
        {"diagram_id": reader_diagram, **BASE_ANALYSIS},
        creator_api_principal_id=reader_owner,
    )
    stats = test_client.get(
        f"/api/shared/{share['share_id']}/stats",
        headers=reader_headers,
    )
    denied_revoke = test_client.delete(
        f"/api/v1/shared/{share['share_id']}",
        headers=reader_headers,
    )
    assert versions.status_code == stats.status_code == 200
    assert denied_restore.status_code == denied_revoke.status_code == 403

    writer_record, writer_key = create_api_key("browser-writer", ["write"])
    writer_owner = f"api-key:{writer_record.principal_id}"
    writer_tenant = f"service:{writer_record.principal_id}"
    writer_diagram = "managed-writer-browser-diagram"
    _seed_analysis(
        writer_diagram,
        owner=writer_owner,
        tenant=writer_tenant,
        cache_owner_api_key_id=writer_owner,
    )
    writer_headers = {"X-API-Key": writer_key}
    denied_read = test_client.get(
        f"/api/diagrams/{writer_diagram}/versions",
        headers=writer_headers,
    )
    allowed_share = test_client.post(
        f"/api/v1/diagrams/{writer_diagram}/share",
        headers=writer_headers,
    )
    assert denied_read.status_code == 403
    assert allowed_share.status_code == 200, allowed_share.text


def test_managed_api_key_rotation_preserves_bound_export_principal_and_v1_chain(
    test_client,
):
    record, old_key = create_api_key("bound-export-client", ["read", "write"])
    owner = f"api-key:{record.principal_id}"
    tenant = f"service:{record.principal_id}"
    diagram_id = "managed-rotation-export-diagram"
    _seed_analysis(
        diagram_id,
        owner=owner,
        tenant=tenant,
        cache_owner_api_key_id=owner,
    )
    token = issue_export_capability_for_identity(
        diagram_id,
        caller_owner_user_id=owner,
        tenant_id=tenant,
        owner_api_key_id=owner,
    )
    rotated = rotate_api_key(record.id)
    assert rotated is not None
    rotated_record, new_key = rotated
    assert rotated_record.principal_id == record.principal_id

    old_denied = test_client.post(
        f"/api/v1/diagrams/{diagram_id}/export-architecture-package?format=html",
        headers={"X-API-Key": old_key, "X-Export-Capability": token},
    )
    allowed = test_client.post(
        f"/api/v1/diagrams/{diagram_id}/export-architecture-package?format=html",
        headers={"X-API-Key": new_key, "X-Export-Capability": token},
    )
    replay = test_client.post(
        f"/api/diagrams/{diagram_id}/export-architecture-package?format=html",
        headers={"X-API-Key": new_key, "X-Export-Capability": token},
    )
    assert old_denied.status_code == 401
    assert allowed.status_code == 200, allowed.text
    assert replay.status_code == 401
    successor = allowed.json()["export_capability"]
    successor_record = _capability_record(successor)
    assert successor_record["principal_marker"] == f"api:{tenant}:{owner}"
    assert successor_record["owner_user_id"] == owner
    assert successor_record["tenant_id"] == tenant


def test_export_successor_chain_binds_scope_denies_same_project_foreign_and_rejects_urls(
    test_client,
    monkeypatch,
    caplog,
):
    diagram_id = "bound-export-successor-chain"
    analysis_id, project_id = _seed_analysis(
        diagram_id,
        explicit_project=True,
    )
    from database import SessionLocal

    db = SessionLocal()
    try:
        db.add(
            ProjectMember(
                project_id=project_id,
                project_owner_user_id=OWNER,
                tenant_id=TENANT,
                member_user_id=FOREIGN,
                role="editor",
            )
        )
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        "export_artifacts._upload_blob",
        lambda **kwargs: f"testblob://{kwargs['content_hash']}",
    )
    owner_headers = {
        **_auth_headers(OWNER),
        "X-API-Key": "invalid-key-must-not-shadow-bearer",
    }
    foreign_headers = _auth_headers(FOREIGN)
    token = issue_export_capability_for_identity(
        diagram_id,
        caller_owner_user_id=OWNER,
        tenant_id=TENANT,
    )

    foreign = test_client.post(
        f"/api/diagrams/{diagram_id}/export-architecture-package?format=html",
        headers={**foreign_headers, "X-Export-Capability": token},
    )
    assert foreign.status_code == 401
    assert (
        foreign.json()["error"]["message"] == "Invalid or unavailable export capability"
    )

    generated = test_client.post(
        f"/api/diagrams/{diagram_id}/migration-timeline",
        headers=owner_headers,
    )
    assert generated.status_code == 200, generated.text

    cost = test_client.get(
        f"/api/v1/diagrams/{diagram_id}/cost-estimate/export",
        headers={**owner_headers, "X-Export-Capability": token},
    )
    assert cost.status_code == 200, cost.text
    cost_next = cost.headers["x-export-capability-next"]
    cost_record = _capability_record(cost_next)
    assert cost_record["principal_marker"] == f"user:{TENANT}:{OWNER}"
    assert cost_record["owner_user_id"] == OWNER
    assert cost_record["tenant_id"] == TENANT
    assert cost_record["analysis_id"] == analysis_id
    assert cost_record["project_id"] == project_id
    assert cost_record["intent"] == "cost_estimate"
    assert cost_record["format"] == "csv"
    assert cost_record["issued_intent"] == "cost_estimate"
    assert cost_record["issued_format"] == "csv"
    assert token not in json.dumps(cost_record)
    assert owner_headers["Authorization"].split(" ", 1)[1] not in json.dumps(
        cost_record
    )

    replay = test_client.get(
        f"/api/diagrams/{diagram_id}/cost-estimate/export",
        headers={**owner_headers, "X-Export-Capability": token},
    )
    timeline = test_client.get(
        f"/api/diagrams/{diagram_id}/migration-timeline/export?format=json",
        headers={**owner_headers, "X-Export-Capability": cost_next},
    )
    assert replay.status_code == 401
    assert timeline.status_code == 200, timeline.text
    timeline_next = timeline.headers["x-export-capability-next"]
    timeline_record = _capability_record(timeline_next)
    assert timeline_record["intent"] == "migration_timeline"
    assert timeline_record["format"] == "json"
    assert timeline_record["issued_intent"] == "migration_timeline"
    assert timeline_record["issued_format"] == "json"

    report = test_client.get(
        f"/api/v1/diagrams/{diagram_id}/report?format=pdf",
        headers={**owner_headers, "X-Export-Capability": timeline_next},
    )
    assert report.status_code == 200, report.text
    report_next = report.headers["x-export-capability-next"]
    report_record = _capability_record(report_next)
    assert report_record["intent"] == "analysis_report"
    assert report_record["format"] == "pdf"
    assert report_record["issued_intent"] == "analysis_report"
    assert report_record["issued_format"] == "pdf"

    EXPORT_CAPABILITY_STORE.set(
        _digest(report_next),
        {**report_record, "intent": "tampered-intent"},
    )
    malformed_scope = test_client.get(
        f"/api/diagrams/{diagram_id}/report",
        headers={**owner_headers, "X-Export-Capability": report_next},
    )
    assert malformed_scope.status_code == 401
    assert (
        malformed_scope.json()["error"]["message"]
        == "Invalid or unavailable export capability"
    )

    with caplog.at_level(logging.INFO):
        query_rejected = test_client.get(
            f"/api/diagrams/{diagram_id}/report",
            params={"export_token": report_next},
            headers=owner_headers,
        )
    assert query_rejected.status_code == 400
    assert report_next not in caplog.text


@pytest.mark.asyncio
async def test_async_completion_issues_from_persisted_envelope_after_local_cache_loss(
    monkeypatch,
):
    diagram_id = "async-persisted-capability"
    analysis_id, project_id = _seed_analysis(diagram_id, explicit_project=True)
    image = b"persisted-async-image"
    IMAGE_STORE[diagram_id] = (image, "image/png")

    manager = JobManager(max_jobs=50, worker_id="persisted-capability-worker")
    import routers.diagrams as diagrams_router

    original_manager = diagrams_router.job_manager
    diagrams_router.job_manager = manager
    monkeypatch.setattr(
        diagrams_router,
        "classify_image",
        lambda *_args, **_kwargs: {
            "is_architecture_diagram": True,
            "confidence": 0.99,
            "image_type": "architecture_diagram",
        },
    )
    monkeypatch.setattr(
        diagrams_router,
        "analyze_image",
        lambda *_args, **_kwargs: copy.deepcopy(BASE_ANALYSIS),
    )
    try:
        job = manager.submit(
            "analyze",
            diagram_id=diagram_id,
            owner_user_id=OWNER,
            tenant_id=TENANT,
            execution_payload={
                "diagram_id": diagram_id,
                "image_sha256": hashlib.sha256(image).hexdigest(),
                "content_type": "image/png",
                "model": "test-model",
                "vision_prompt_hash": "test-prompt-hash",
            },
        )
        lease = manager.claim(job.job_id)
        assert lease
        manager._jobs[job.job_id] = Job(
            "analyze",
            diagram_id=diagram_id,
            owner_user_id=FOREIGN,
            tenant_id=TENANT,
            job_id=job.job_id,
        )
        manager._jobs.clear()
        with manager.lease_context(lease):
            await diagrams_router._run_analysis_job(job.job_id, job.execution_payload)

        completed = manager.get_persisted(job.job_id)
        assert completed is not None
        assert completed.status.value == "completed"
        successor = completed.result["export_capability"]
        record = _capability_record(successor)
        assert record["principal_marker"] == f"user:{TENANT}:{OWNER}"
        assert record["owner_user_id"] == OWNER
        assert record["tenant_id"] == TENANT
        assert record["analysis_id"] == analysis_id
        assert record["project_id"] == project_id
        assert record["issued_intent"] == "artifact:export"
        assert record["issued_format"] == "*"
    finally:
        diagrams_router.job_manager = original_manager
        IMAGE_STORE.delete(diagram_id)
        SESSION_STORE.delete(diagram_id)


@pytest.mark.asyncio
async def test_async_api_key_envelope_issues_secret_free_canonical_binding():
    key_record, raw_key = create_api_key("async-export-client", ["read", "write"])
    owner = f"api-key:{key_record.principal_id}"
    tenant = f"service:{key_record.principal_id}"
    diagram_id = "async-api-key-capability"
    analysis_id, project_id = _seed_analysis(
        diagram_id,
        owner=owner,
        tenant=tenant,
        explicit_project=True,
        cache_owner_api_key_id=owner,
    )
    manager = JobManager(max_jobs=20, worker_id="async-api-key-worker")
    job = manager.submit(
        "generate_hld",
        diagram_id=diagram_id,
        tenant_id=tenant,
        owner_api_key_id=owner,
        execution_payload={"diagram_id": diagram_id},
    )

    result = await attach_export_capability_for_persisted_job(
        {"status": "completed"},
        manager,
        job.job_id,
        diagram_id,
    )

    record = _capability_record(result["export_capability"])
    assert record["principal_marker"] == f"api:{tenant}:{owner}"
    assert record["owner_user_id"] == owner
    assert record["tenant_id"] == tenant
    assert record["analysis_id"] == analysis_id
    assert record["project_id"] == project_id
    assert raw_key not in json.dumps(record)


@pytest.mark.asyncio
async def test_persisted_job_capability_fails_closed_without_shared_envelope():
    diagram_id = "missing-job-envelope-capability"
    _seed_analysis(diagram_id, explicit_project=True)
    manager = JobManager(max_jobs=20, worker_id="missing-envelope-worker")
    local_only = Job(
        "analyze",
        diagram_id=diagram_id,
        owner_user_id=OWNER,
        tenant_id=TENANT,
    )
    manager._jobs[local_only.job_id] = local_only

    with pytest.raises(Exception) as exc_info:
        await attach_export_capability_for_persisted_job(
            {},
            manager,
            local_only.job_id,
            diagram_id,
        )

    assert getattr(exc_info.value, "status_code", None) == 503


@pytest.mark.asyncio
async def test_transient_completion_never_issues_unbound_successor_capability():
    manager = JobManager(max_jobs=20, worker_id="transient-successor-worker")
    job = manager.submit(
        "generate_iac",
        diagram_id="transient-public-compatibility",
        owner_user_id=OWNER,
        tenant_id=TENANT,
        execution_payload={"diagram_id": "transient-public-compatibility"},
    )

    result = await attach_export_capability_for_persisted_job(
        {"status": "completed"},
        manager,
        job.job_id,
        "transient-public-compatibility",
        allow_missing_durable_scope=True,
    )

    assert result == {"status": "completed"}
    assert EXPORT_CAPABILITY_STORE.keys("*") == []


def test_all_async_completion_chains_use_persisted_job_capability_issuer():
    from routers.diagrams import _run_analysis_job
    from routers.hld_routes import _run_hld_job
    from routers.iac_routes import _run_iac_job

    for worker in (_run_analysis_job, _run_hld_job, _run_iac_job):
        source = inspect.getsource(worker)
        assert "attach_export_capability_for_persisted_job" in source
        assert "attach_export_capability(result" not in source


def test_participant_capability_is_an_explicit_base_and_v1_openapi_security_option(
    test_client,
):
    schema = test_client.get("/openapi.json").json()
    operations = (
        ("/api/collab/sessions/{session_id}", "get"),
        ("/api/collab/sessions/{session_id}/changes", "get"),
        ("/api/collab/sessions/{session_id}/changes", "post"),
        ("/api/v1/collab/sessions/{session_id}", "get"),
        ("/api/v1/collab/sessions/{session_id}/changes", "get"),
        ("/api/v1/collab/sessions/{session_id}/changes", "post"),
    )
    for path, method in operations:
        security_names = {
            name
            for requirement in schema["paths"][path][method]["security"]
            for name in requirement
        }
        assert {
            "ParticipantCapability",
            "APIKeyHeader",
            "HTTPBearer",
        }.issubset(security_names)
