"""Cache-loss integration coverage for every canonical mutation path (#1237)."""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from unittest.mock import patch

import pytest
import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from auth import (
    AuthProvider,
    JWT_ALGORITHM,
    JWT_SECRET,
    User,
    UserTier,
    generate_session_token,
)
from database import Base
from error_envelope import ArchmorphException
from main import SESSION_STORE
from models.workspace import Analysis, AnalysisVersion, Artifact, Decision, Workspace
from tests.conftest import SAMPLE_ANALYSIS
from workspace_store import load_analysis_state, persist_analysis_state


@pytest.fixture()
def durable_runtime(tmp_path, monkeypatch):
    import database

    engine = create_engine(
        f"sqlite:///{tmp_path / 'canonical-routes.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield factory
    SESSION_STORE.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _identity():
    suffix = uuid.uuid4().hex
    user_id = f"canonical-route-{suffix}"
    tenant_id = f"tenant-{suffix}"
    token = generate_session_token(
        User(
            id=user_id,
            provider=AuthProvider.GITHUB,
            tier=UserTier.TEAM,
            tenant_id=tenant_id,
        )
    )
    return user_id, tenant_id, {"Authorization": f"Bearer {token}"}


def _seed(factory, *, diagram_id, owner_user_id, tenant_id, extra=None):
    snapshot = copy.deepcopy(SAMPLE_ANALYSIS)
    snapshot["diagram_id"] = diagram_id
    if extra:
        snapshot.update(extra)
    db = factory()
    try:
        result = persist_analysis_state(
            db,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            snapshot=snapshot,
            session_store=SESSION_STORE,
            cache_required=True,
        )
        return result.analysis.id
    finally:
        db.close()


def _hydrate_after_cache_loss(factory, *, diagram_id, owner_user_id, tenant_id):
    SESSION_STORE.delete(diagram_id)
    db = factory()
    try:
        return load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
    finally:
        db.close()


def _artifacts(factory, analysis_id, artifact_type):
    db = factory()
    try:
        return (
            db.query(Artifact)
            .filter(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == artifact_type,
            )
            .all()
        )
    finally:
        db.close()


def test_analysis_add_and_apply_each_survive_cache_loss(test_client, durable_runtime):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-analysis-mutations-{uuid.uuid4().hex}"
    _seed(durable_runtime, diagram_id=diagram_id, owner_user_id=owner, tenant_id=tenant)

    def add_service(*, analysis, user_text):
        updated = copy.deepcopy(analysis)
        updated["services_added"] = ["Azure Cache for Redis"]
        updated["services_detected"] += 1
        return updated

    with patch("routers.analysis.add_services_from_text", side_effect=add_service):
        added = test_client.post(
            f"/api/diagrams/{diagram_id}/add-services",
            headers=headers,
            json={"text": "Add Redis"},
        )
    assert added.status_code == 200, added.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["services_added"] == ["Azure Cache for Redis"]

    def apply_answers(analysis, answers):
        updated = copy.deepcopy(analysis)
        updated["guided_answers"] = answers
        return updated

    with patch("routers.analysis.apply_answers", side_effect=apply_answers):
        applied = test_client.post(
            f"/api/diagrams/{diagram_id}/apply-answers",
            headers=headers,
            json={"availability": "zone-redundant"},
        )
    assert applied.status_code == 200, applied.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["guided_answers"] == {"availability": "zone-redundant"}


def test_review_disposition_survives_cache_loss(test_client, durable_runtime):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-review-mutation-{uuid.uuid4().hex}"
    _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        extra={
            "mappings": [
                {
                    "source_service": "Unknown",
                    "azure_service": "Review target",
                    "confidence": 0.4,
                }
            ]
        },
    )
    queue = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)
    item_id = queue.json()["items"][0]["id"]

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/review-queue/{item_id}/disposition",
        headers=headers,
        json={"action": "mark_risk", "edited_text": "Explicitly accepted"},
    )

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["review_queue_dispositions"][item_id]["action"] == "mark_risk"
    assert any(item["id"] == item_id for item in hydrated["risk_annotations"])


def test_sync_hld_and_iac_artifacts_survive_cache_loss(test_client, durable_runtime):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-sync-artifacts-{uuid.uuid4().hex}"
    analysis_id = _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    hld = {"title": "Durable HLD", "executive_summary": "Persisted"}
    markdown = "# Durable HLD\n"
    with (
        patch("routers.hld_routes.diagrams_compat.generate_hld", return_value=hld),
        patch("routers.hld_routes.diagrams_compat.generate_hld_markdown", return_value=markdown),
    ):
        response = test_client.post(f"/api/diagrams/{diagram_id}/generate-hld", headers=headers)
    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["hld"] == hld
    hld_artifacts = _artifacts(durable_runtime, analysis_id, "hld")
    assert len(hld_artifacts) == 1
    assert hld_artifacts[0].content == markdown
    assert hld_artifacts[0].version_id

    code = 'resource "azurerm_resource_group" "main" {}'
    with patch("routers.iac_routes.generate_iac_code", return_value=code):
        response = test_client.post(
            f"/api/diagrams/{diagram_id}/generate?format=terraform",
            headers=headers,
        )
    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["iac_code"] == code
    iac_artifacts = _artifacts(durable_runtime, analysis_id, "terraform")
    assert len(iac_artifacts) == 1
    assert iac_artifacts[0].content == code
    assert iac_artifacts[0].version_id


def test_iac_chat_mutation_and_artifact_survive_cache_loss(test_client, durable_runtime):
    from routers.iac_routes import _compute_iac_etag, _iac_code_hash

    owner, tenant, headers = _identity()
    diagram_id = f"diag-iac-chat-{uuid.uuid4().hex}"
    old_code = 'resource "azurerm_resource_group" "old" {}'
    new_code = 'resource "azurerm_resource_group" "new" {}'
    analysis_id = _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        extra={
            "iac_code": old_code,
            "iac_code_hash": _iac_code_hash(old_code),
            "_iac_etag": _compute_iac_etag(old_code),
            "iac_format": "terraform",
        },
    )
    chat_history = [
        {"role": "user", "content": "rename"},
        {"role": "assistant", "content": "updated"},
    ]
    with (
        patch(
            "routers.iac_routes.process_iac_chat",
            return_value={"code": new_code, "reply": "updated"},
        ),
        patch("routers.iac_routes.get_iac_chat_history", return_value=chat_history),
    ):
        response = test_client.post(
            f"/api/diagrams/{diagram_id}/iac-chat",
            headers=headers,
            json={
                "message": "rename",
                "code": old_code,
                "format": "terraform",
                "code_hash": _iac_code_hash(old_code),
            },
        )

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["iac_code"] == new_code
    assert [message["role"] for message in hydrated["iac_chat_history"][-2:]] == [
        "user",
        "assistant",
    ]
    artifacts = _artifacts(durable_runtime, analysis_id, "terraform")
    assert len(artifacts) == 1
    assert artifacts[0].content == new_code


def test_api_key_iac_mutation_survives_cache_loss(test_client, durable_runtime, monkeypatch):
    from routers import shared
    from routers.shared import get_api_key_service_principal

    api_key = "canonical-route-api-key"
    monkeypatch.setattr(shared, "API_KEY", api_key)
    principal = get_api_key_service_principal({"x-api-key": api_key})
    tenant = f"service:{principal.split(':', 1)[-1]}"
    diagram_id = f"diag-api-key-{uuid.uuid4().hex}"
    _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=principal,
        tenant_id=tenant,
        extra={"_owner_api_key_id": principal},
    )
    session = SESSION_STORE.peek(diagram_id)
    session.pop("_owner_user_id", None)
    session["_owner_api_key_id"] = principal
    SESSION_STORE.set(diagram_id, session)
    code = 'resource "azurerm_resource_group" "api_key" {}'

    with patch("routers.iac_routes.generate_iac_code", return_value=code):
        response = test_client.post(
            f"/api/diagrams/{diagram_id}/generate?format=terraform",
            headers={"X-API-Key": api_key},
        )

    assert response.status_code == 200, response.text
    SESSION_STORE.delete(diagram_id)
    db = durable_runtime()
    try:
        hydrated = load_analysis_state(
            db,
            diagram_id=diagram_id,
            owner_user_id=principal,
            tenant_id=tenant,
            session_store=SESSION_STORE,
            cache_owner_api_key_id=principal,
        )
    finally:
        db.close()
    assert hydrated["iac_code"] == code
    assert SESSION_STORE.peek(diagram_id)["_owner_api_key_id"] == principal


def test_infrastructure_import_survives_cache_loss_with_linked_artifact(
    test_client,
    durable_runtime,
    monkeypatch,
):
    from routers import infra_import as infra_routes

    owner, tenant, headers = _identity()
    diagram_id = f"import-{uuid.uuid4().hex}"
    content = 'resource "aws_s3_bucket" "example" {}'
    imported = copy.deepcopy(SAMPLE_ANALYSIS)
    imported.update({
        "diagram_id": diagram_id,
        "source_provider": "aws",
        "service_connections": [],
        "confidence_summary": {"high": 0, "medium": 0, "low": 0, "average": 0},
        "architecture_patterns": [],
    })
    monkeypatch.setattr(infra_routes, "generate_session_id", lambda _prefix: diagram_id)
    monkeypatch.setattr(infra_routes, "parse_infrastructure", lambda *_args: imported)

    response = test_client.post(
        "/api/import/infrastructure",
        headers=headers,
        json={"content": content, "format": "terraform_hcl", "filename": "main.tf"},
    )

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["diagram_id"] == diagram_id
    db = durable_runtime()
    try:
        analysis_id = db.query(Analysis.id).filter(
            Analysis.diagram_id == diagram_id,
            Analysis.owner_user_id == owner,
            Analysis.tenant_id == tenant,
        ).scalar()
    finally:
        db.close()
    artifacts = _artifacts(durable_runtime, analysis_id, "infrastructure_import")
    assert len(artifacts) == 1
    persisted_import = json.loads(artifacts[0].content)
    assert persisted_import["diagram_id"] == diagram_id
    assert persisted_import["source_format"] == "terraform_hcl"
    assert content not in artifacts[0].content
    assert artifacts[0].version_id


def test_api_key_infrastructure_import_survives_cache_loss(
    test_client,
    durable_runtime,
    monkeypatch,
):
    from routers import infra_import as infra_routes
    from routers import shared
    from routers.shared import get_api_key_service_principal

    api_key = "canonical-import-api-key"
    monkeypatch.setattr(shared, "API_KEY", api_key)
    principal = get_api_key_service_principal({"x-api-key": api_key})
    tenant = f"service:{principal.split(':', 1)[-1]}"
    diagram_id = f"import-api-{uuid.uuid4().hex}"
    imported = copy.deepcopy(SAMPLE_ANALYSIS)
    imported.update({
        "diagram_id": diagram_id,
        "source_provider": "aws",
        "service_connections": [],
        "confidence_summary": {"high": 0, "medium": 0, "low": 0, "average": 0},
        "architecture_patterns": [],
    })
    monkeypatch.setattr(infra_routes, "generate_session_id", lambda _prefix: diagram_id)
    monkeypatch.setattr(infra_routes, "parse_infrastructure", lambda *_args: imported)

    response = test_client.post(
        "/api/import/infrastructure",
        headers={"X-API-Key": api_key},
        json={
            "content": 'resource "aws_s3_bucket" "example" {}',
            "format": "terraform_hcl",
            "filename": "main.tf",
        },
    )

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=principal,
        tenant_id=tenant,
    )
    assert hydrated["diagram_id"] == diagram_id


def test_cost_timeline_and_network_mutations_survive_cache_and_process_loss(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-insight-mutations-{uuid.uuid4().hex}"
    analysis_id = _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        extra={"analysis": copy.deepcopy(SAMPLE_ANALYSIS)},
    )

    configured = test_client.post(
        f"/api/diagrams/{diagram_id}/cost-estimate/configure",
        headers=headers,
        json={
            "overrides": [
                {
                    "service": "Azure Functions",
                    "instance_count": 2,
                    "sku": "Premium",
                    "reserved_term": "1yr",
                }
            ]
        },
    )
    assert configured.status_code == 200, configured.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["_cost_overrides"]["Azure Functions"]["instance_count"] == 2
    assert len(_artifacts(durable_runtime, analysis_id, "cost_configuration")) == 1

    timeline = test_client.post(
        f"/api/diagrams/{diagram_id}/migration-timeline",
        headers=headers,
    )
    assert timeline.status_code == 200, timeline.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["migration_timeline"]["total_phases"] == 7
    assert len(_artifacts(durable_runtime, analysis_id, "migration_timeline")) == 1

    network = test_client.post(
        f"/api/diagrams/{diagram_id}/network-topology",
        headers=headers,
        json={},
    )
    assert network.status_code == 200, network.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["network_topology"] == network.json()["network_topology"]
    assert len(_artifacts(durable_runtime, analysis_id, "network_topology")) == 1


def test_failed_cost_mutation_does_not_modify_cache_before_durable_commit(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-cost-rollback-{uuid.uuid4().hex}"
    _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        extra={
            "_cost_overrides": {
                "Azure Functions": {
                    "instance_count": 1,
                    "sku": "Consumption",
                    "reserved_term": None,
                }
            }
        },
    )

    with patch(
        "routers.insights.persist_diagram_mutation",
        side_effect=ArchmorphException(503, "durable write unavailable"),
    ):
        response = test_client.post(
            f"/api/diagrams/{diagram_id}/cost-estimate/configure",
            headers=headers,
            json={
                "overrides": [{
                    "service": "Azure Functions",
                    "instance_count": 9,
                    "sku": "Premium",
                    "reserved_term": "1yr",
                }]
            },
        )

    assert response.status_code == 503
    cached = SESSION_STORE.peek(diagram_id)
    assert cached["_cost_overrides"]["Azure Functions"]["instance_count"] == 1


def test_iac_chat_clear_survives_cache_and_process_loss(test_client, durable_runtime):
    from iac_chat import IAC_CHAT_SESSIONS

    owner, tenant, headers = _identity()
    diagram_id = f"diag-iac-chat-clear-{uuid.uuid4().hex}"
    _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        extra={"iac_chat_history": [{"role": "user", "content": "remove me"}]},
    )
    IAC_CHAT_SESSIONS[f"{diagram_id}:iac"] = [{"role": "user", "content": "remove me"}]

    response = test_client.delete(f"/api/diagrams/{diagram_id}/iac-chat", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["cleared"] is True
    IAC_CHAT_SESSIONS.clear()
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["iac_chat_history"] == []


def test_purge_deletes_durable_graph_and_empty_implicit_workspace_before_receipt(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-durable-purge-{uuid.uuid4().hex}"
    db = durable_runtime()
    try:
        result = persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id=tenant,
            diagram_id=diagram_id,
            snapshot={"mappings": [], "iac_chat_history": []},
            session_store=SESSION_STORE,
            artifact_type="purge_fixture",
            artifact_format="text",
            artifact_content="delete me",
            cache_required=True,
        )
        db.add(Decision(
            analysis_id=result.analysis.id,
            version_id=result.version.id,
            owner_user_id=owner,
            tenant_id=tenant,
            decision_type="risk",
            title="delete me",
        ))
        db.commit()
        analysis_id = result.analysis.id
        workspace_id = result.analysis.workspace_id
    finally:
        db.close()

    response = test_client.delete(f"/api/diagrams/{diagram_id}/purge", headers=headers)

    assert response.status_code == 200, response.text
    durable = response.json()["purged"]["durable"]
    assert durable == {
        "analyses": 1,
        "versions": 1,
        "artifacts": 1,
        "decisions": 1,
        "implicit_workspaces": 1,
    }
    db = durable_runtime()
    try:
        assert db.query(Analysis).filter_by(id=analysis_id).count() == 0
        assert db.query(AnalysisVersion).filter_by(analysis_id=analysis_id).count() == 0
        assert db.query(Artifact).filter_by(analysis_id=analysis_id).count() == 0
        assert db.query(Decision).filter_by(analysis_id=analysis_id).count() == 0
        assert db.query(Workspace).filter_by(id=workspace_id).count() == 0
    finally:
        db.close()
    SESSION_STORE.delete(diagram_id)
    missing = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)
    assert missing.status_code == 404


def test_artifact_route_checks_requested_analysis_for_same_principal(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    first_id = _seed(
        durable_runtime,
        diagram_id=f"diag-artifact-first-{uuid.uuid4().hex}",
        owner_user_id=owner,
        tenant_id=tenant,
    )
    second_id = _seed(
        durable_runtime,
        diagram_id=f"diag-artifact-second-{uuid.uuid4().hex}",
        owner_user_id=owner,
        tenant_id=tenant,
    )
    db = durable_runtime()
    try:
        artifact = Artifact(
            analysis_id=first_id,
            owner_user_id=owner,
            tenant_id=tenant,
            artifact_type="bicep",
            content="resource example = {}",
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        artifact_id = artifact.id
    finally:
        db.close()

    response = test_client.get(
        f"/api/analyses/{second_id}/artifacts/{artifact_id}?include_content=true",
        headers=headers,
    )

    assert response.status_code == 404


def test_legacy_default_tenant_cache_is_rehomed_on_owner_access(test_client, durable_runtime):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-legacy-cache-{uuid.uuid4().hex}"
    legacy = copy.deepcopy(SAMPLE_ANALYSIS)
    legacy["diagram_id"] = diagram_id
    legacy["_owner_user_id"] = owner
    legacy["_tenant_id"] = "default_tenant"
    SESSION_STORE.set(diagram_id, legacy)

    response = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)

    assert response.status_code == 200, response.text
    rehomed = SESSION_STORE.peek(diagram_id)
    assert rehomed["_tenant_id"] == tenant
    durable = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert durable["diagram_id"] == diagram_id


def test_legacy_default_tenant_cache_rehomes_from_migrated_durable_target(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-legacy-migrated-cache-{uuid.uuid4().hex}"
    _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
        extra={"durable_value": "canonical"},
    )
    stale_cache = copy.deepcopy(SAMPLE_ANALYSIS)
    stale_cache.update(
        {
            "diagram_id": diagram_id,
            "_owner_user_id": owner,
            "_tenant_id": "default_tenant",
            "durable_value": "stale",
        }
    )
    SESSION_STORE.set(diagram_id, stale_cache)

    response = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)

    assert response.status_code == 200, response.text
    rehomed = SESSION_STORE.peek(diagram_id)
    assert rehomed["_tenant_id"] == tenant
    assert rehomed["durable_value"] == "canonical"


def test_exact_owner_legacy_default_tenant_row_rehomes_on_access(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-legacy-cache-conflict-{uuid.uuid4().hex}"
    db = durable_runtime()
    try:
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            diagram_id=diagram_id,
            snapshot={"legacy": True, "mappings": []},
        )
    finally:
        db.close()
    stale_cache = copy.deepcopy(SAMPLE_ANALYSIS)
    stale_cache.update(
        {
            "diagram_id": diagram_id,
            "_owner_user_id": owner,
            "_tenant_id": "default_tenant",
        }
    )
    SESSION_STORE.set(diagram_id, stale_cache)

    response = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)

    assert response.status_code == 200, response.text
    assert SESSION_STORE.peek(diagram_id)["_tenant_id"] == tenant
    durable = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert durable["legacy"] is True


def test_exact_owner_legacy_default_row_rehomes_after_cache_loss(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-legacy-cache-loss-{uuid.uuid4().hex}"
    db = durable_runtime()
    try:
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            diagram_id=diagram_id,
            snapshot={"legacy_after_loss": True, "mappings": []},
        )
    finally:
        db.close()
    SESSION_STORE.delete(diagram_id)

    response = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["legacy_after_loss"] is True


def test_legacy_and_target_durable_conflict_is_uniform_404(
    test_client,
    durable_runtime,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-legacy-target-conflict-{uuid.uuid4().hex}"
    for scope, value in (("default_tenant", "legacy"), (tenant, "target")):
        db = durable_runtime()
        try:
            persist_analysis_state(
                db,
                owner_user_id=owner,
                tenant_id=scope,
                diagram_id=diagram_id,
                snapshot={"value": value, "mappings": []},
            )
        finally:
            db.close()
    stale_cache = copy.deepcopy(SAMPLE_ANALYSIS)
    stale_cache.update({
        "diagram_id": diagram_id,
        "_owner_user_id": owner,
        "_tenant_id": "default_tenant",
    })
    SESSION_STORE.set(diagram_id, stale_cache)

    conflict = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)
    missing = test_client.get(
        f"/api/diagrams/missing-{uuid.uuid4().hex}/review-queue",
        headers=headers,
    )

    assert conflict.status_code == missing.status_code == 404
    assert conflict.json()["error"]["message"] == missing.json()["error"]["message"]
    assert SESSION_STORE.peek(diagram_id)["_tenant_id"] == "default_tenant"


def test_direct_b2c_old_default_row_rehomes_to_verified_current_scope(
    test_client,
    durable_runtime,
):
    from auth import provider_subject_tenant_scope

    subject = f"b2c-subject-{uuid.uuid4().hex}"
    user_id = f"azure_ad_b2c_{subject}"
    owner = subject
    tenant = provider_subject_tenant_scope(AuthProvider.AZURE_AD_B2C, subject)
    headers = {
        "Authorization": f"Bearer {generate_session_token(User(
            id=user_id,
            provider=AuthProvider.AZURE_AD_B2C,
            provider_subject=subject,
            tier=UserTier.TEAM,
            tenant_id=tenant,
        ))}"
    }
    diagram_id = f"diag-b2c-legacy-{uuid.uuid4().hex}"
    db = durable_runtime()
    try:
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            diagram_id=diagram_id,
            snapshot={"provider": "b2c", "mappings": []},
        )
    finally:
        db.close()
    SESSION_STORE.set(diagram_id, {
        "diagram_id": diagram_id,
        "mappings": [],
        "_owner_user_id": owner,
        "_tenant_id": "default_tenant",
    })

    response = test_client.get(f"/api/diagrams/{diagram_id}/review-queue", headers=headers)

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["provider"] == "b2c"


def test_raw_b2c_old_token_rehomes_without_owner_prefix_guess(
    test_client,
    durable_runtime,
):
    from auth import provider_subject_tenant_scope
    from datetime import datetime, timedelta, timezone

    subject = f"raw-b2c-subject-{uuid.uuid4().hex}"
    owner = subject
    tenant = provider_subject_tenant_scope(AuthProvider.AZURE_AD_B2C, subject)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": subject,
            "provider": "azure_ad_b2c",
            "tier": "free",
            "tenant_id": "default_tenant",
            "iat": now,
            "exp": now + timedelta(hours=1),
            "type": "access",
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    diagram_id = f"diag-raw-b2c-legacy-{uuid.uuid4().hex}"
    db = durable_runtime()
    try:
        persist_analysis_state(
            db,
            owner_user_id=owner,
            tenant_id="default_tenant",
            diagram_id=diagram_id,
            snapshot={"provider": "raw-b2c", "mappings": []},
        )
    finally:
        db.close()
    SESSION_STORE.set(diagram_id, {
        "diagram_id": diagram_id,
        "mappings": [],
        "_owner_user_id": subject,
        "_tenant_id": "default_tenant",
    })

    response = test_client.get(
        f"/api/diagrams/{diagram_id}/review-queue",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated["provider"] == "raw-b2c"


def _wait_for_job(test_client, job_id, headers):
    for _ in range(400):
        response = test_client.get(f"/api/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.03)
    pytest.fail(f"job {job_id} did not finish")


@pytest.mark.parametrize(
    ("route", "job_type", "patch_target", "patch_value", "artifact_type", "snapshot_key"),
    [
        (
            "generate-async?format=terraform",
            "generate_iac",
            "routers.iac_routes.generate_iac_code",
            'resource "azurerm_resource_group" "async" {}',
            "terraform",
            "iac_code",
        ),
        (
            "generate-hld-async",
            "generate_hld",
            "routers.hld_routes.diagrams_compat.generate_hld",
            {"title": "Async durable HLD"},
            "hld",
            "hld",
        ),
    ],
)
def test_async_artifact_paths_survive_cache_loss(
    test_client,
    durable_runtime,
    route,
    job_type,
    patch_target,
    patch_value,
    artifact_type,
    snapshot_key,
):
    owner, tenant, headers = _identity()
    diagram_id = f"diag-{job_type}-{uuid.uuid4().hex}"
    analysis_id = _seed(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    patches = [patch(patch_target, return_value=patch_value)]
    if job_type == "generate_hld":
        patches.append(
            patch(
                "routers.hld_routes.diagrams_compat.generate_hld_markdown",
                return_value="# Async durable HLD\n",
            )
        )
    for active_patch in patches:
        active_patch.start()
    try:
        queued = test_client.post(f"/api/diagrams/{diagram_id}/{route}", headers=headers)
        assert queued.status_code == 202, queued.text
        from job_queue import durable_job_worker, job_manager

        job_id = queued.json()["job_id"]
        lease_token = job_manager.claim(job_id)
        if lease_token:
            asyncio.run(durable_job_worker._execute(job_id, lease_token))
        job = _wait_for_job(test_client, job_id, headers)
    finally:
        for active_patch in reversed(patches):
            active_patch.stop()

    assert job["status"] == "completed", job
    hydrated = _hydrate_after_cache_loss(
        durable_runtime,
        diagram_id=diagram_id,
        owner_user_id=owner,
        tenant_id=tenant,
    )
    assert hydrated[snapshot_key] == patch_value
    artifacts = _artifacts(durable_runtime, analysis_id, artifact_type)
    assert len(artifacts) == 1
    assert artifacts[0].version_id
