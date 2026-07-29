"""Adversarial regressions for the final independent canonical-state audit."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request
from fastapi.routing import APIRoute
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

import openai_client
from cost_metering import BudgetCreateRequest, BudgetPeriod, CostMeter, CostScope
from job_queue import JobManager
from logging_config import ArchmorphJsonFormatter
from main import app
from routers import shared
from routers.api_keys_routes import _hash_index, _keys, create_api_key
from routers.shared import route_effect_scope
from route_effects import (
    classify_endpoint_effects,
    runtime_route_effect_scope,
    runtime_route_effects,
)
from session_store import InMemoryStore
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from database import Base
from analysis_payload_bounds import AnalysisPayloadTooLarge, validate_restore_payload_shape
from models.workspace import RestoreGrant, Workspace
from workspace_store import (
    consume_restore_grant,
    issue_restore_grant,
    persist_analysis_state,
    snapshot_payload_hash,
    create_workspace,
    update_workspace,
)
from auth import AuthProvider, User, generate_session_token
from export_capabilities import _principal_marker
from job_queue import Job
from models.deployment_state import DeploymentState
from project_store import PROJECT_READ_ROLES
from routers.jobs import _ensure_job_access
from routers.tf_backend import authorized_deployment_state


@pytest.fixture(autouse=True)
def _isolated_security_state(monkeypatch):
    _keys.clear()
    _hash_index.clear()
    CostMeter.reset()
    openai_client.reset_cache()
    monkeypatch.setattr(shared, "API_KEY", "static-administrator-placeholder")
    monkeypatch.setattr(shared, "API_KEY_ROTATED", "")
    monkeypatch.setattr(shared, "API_KEY_PRINCIPAL_ID", "static-service-principal")
    monkeypatch.setattr(shared.limiter, "_limiter", FixedWindowRateLimiter(MemoryStorage()))
    yield
    _keys.clear()
    _hash_index.clear()
    CostMeter.reset()
    openai_client.reset_cache()


def _headers(raw_key: str) -> dict[str, str]:
    return {"X-API-Key": raw_key}


def _scope(record) -> CostScope:
    return CostScope(
        owner_user_id=f"api-key:{record.principal_id}",
        tenant_id=f"service:{record.principal_id}",
        actor_kind="managed",
        key_id=record.id,
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _response(label: str):
    response = MagicMock()
    response.choices = [MagicMock(finish_reason="stop")]
    response.choices[0].message.content = label
    response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)
    return response


def test_cost_records_budgets_alerts_and_csv_are_isolated_by_managed_principal():
    first, _first_raw = create_api_key("first", ["read", "write"])
    second, _second_raw = create_api_key("second", ["read", "write"])
    first_scope = _scope(first)
    second_scope = _scope(second)
    meter = CostMeter.instance()

    meter.record(
        model="gpt-4.1",
        prompt_tokens=100,
        completion_tokens=50,
        agent_id="shared-agent-name",
        scope=first_scope,
    )
    meter.record(
        model="gpt-4o",
        prompt_tokens=200,
        completion_tokens=100,
        agent_id="shared-agent-name",
        scope=second_scope,
    )
    first_budget = meter.create_budget(
        BudgetCreateRequest(
            agent_id="shared-agent-name",
            amount_usd=1.0,
            period=BudgetPeriod.MONTHLY,
        ),
        scope=first_scope,
    )

    assert meter.get_overview(scope=first_scope).total_records == 1
    assert meter.get_overview(scope=second_scope).total_records == 1
    assert [item.model for item in meter.get_model_breakdown(scope=first_scope)] == ["gpt-4.1"]
    assert [item.model for item in meter.get_model_breakdown(scope=second_scope)] == ["gpt-4o"]
    assert [item.id for item in meter.list_budgets(scope=first_scope)] == [first_budget.id]
    assert meter.list_budgets(scope=second_scope) == []
    assert "gpt-4.1" in meter.export_csv(scope=first_scope)
    assert "gpt-4o" not in meter.export_csv(scope=first_scope)
    assert "gpt-4o" in meter.export_csv(scope=second_scope)


def test_legacy_unscoped_cost_rows_are_hidden_except_explicit_global_admin():
    meter = CostMeter.instance()
    meter.record(model="legacy-model", prompt_tokens=1, completion_tokens=1)
    record, _raw = create_api_key("admin", ["admin"])
    caller_scope = _scope(record)
    global_scope = CostScope(**{**caller_scope.__dict__, "global_admin": True})

    assert meter.get_overview(scope=caller_scope).total_records == 0
    assert meter.get_overview(scope=global_scope).total_records >= 1
    assert any(
        item.model == "legacy-model"
        for item in meter.get_model_breakdown(scope=global_scope)
    )


def test_bypass_cache_neither_reads_nor_stores_and_scopes_do_not_cross():
    first = _response("first")
    second = _response("second")
    third = _response("third")
    client = MagicMock()
    client.chat.completions.create.side_effect = [first, second, third]
    messages = [{"role": "user", "content": "customer-derived"}]

    real_cached_completion = openai_client.cached_chat_completion
    with patch("openai_client.get_openai_client", return_value=client):
        assert real_cached_completion(
            messages,
            cache_owner_user_id="owner-a",
            cache_tenant_id="tenant-a",
            cache_diagram_id="diagram-a",
        ) is first
        assert real_cached_completion(
            messages,
            cache_owner_user_id="owner-b",
            cache_tenant_id="tenant-b",
            cache_diagram_id="diagram-b",
        ) is second
        assert real_cached_completion(
            messages,
            cache_owner_user_id="owner-a",
            cache_tenant_id="tenant-a",
            cache_diagram_id="diagram-a",
            bypass_cache=True,
        ) is third
        assert real_cached_completion(
            messages,
            cache_owner_user_id="owner-a",
            cache_tenant_id="tenant-a",
            cache_diagram_id="diagram-a",
        ) is first

    assert client.chat.completions.create.call_count == 3
    assert openai_client.purge_diagram_response_cache("diagram-a") == 1
    assert openai_client.diagram_response_cache_absent("diagram-a")
    assert not openai_client.diagram_response_cache_absent("diagram-b")


def test_orphan_event_ring_is_discovered_without_envelope_and_foreign_ring_untouched():
    manager = JobManager(max_jobs=20, ttl_seconds=60)
    manager._jobs_store = InMemoryStore(maxsize=20, ttl=60)
    manager._events_store = InMemoryStore(maxsize=20, ttl=60)
    manager._events_store.set(
        "orphan-owned",
        {
            "scope_schema_version": 1,
            "job_id": "orphan-owned",
            "diagram_id": "diagram-owned",
            "owner_user_id": "owner-a",
            "tenant_id": "tenant-a",
            "owner_api_key_id": None,
            "next_seq": 1,
            "dropped_events": 0,
            "events": [{"id": 0, "event": "progress", "data": {}, "ts": "now"}],
        },
    )
    manager._events_store.set(
        "orphan-foreign",
        {
            "scope_schema_version": 1,
            "job_id": "orphan-foreign",
            "diagram_id": "diagram-owned",
            "owner_user_id": "owner-b",
            "tenant_id": "tenant-b",
            "owner_api_key_id": None,
            "next_seq": 1,
            "dropped_events": 0,
            "events": [{"id": 0, "event": "progress", "data": {}, "ts": "now"}],
        },
    )

    manifest = manager.manifest_diagram(
        "diagram-owned",
        owner_user_id="owner-a",
        tenant_id="tenant-a",
    )
    assert manifest == {"job_ids": [], "event_ids": ["orphan-owned"]}
    assert manager.purge_diagram(
        "diagram-owned",
        owner_user_id="owner-a",
        tenant_id="tenant-a",
        manifest=manifest,
    ) == {"envelopes": 0, "event_rings": 1}
    assert manager._events_store.peek("orphan-owned") is None
    assert manager._events_store.peek("orphan-foreign") is not None


def test_legacy_orphan_ring_is_quarantined_not_claimed():
    manager = JobManager(max_jobs=20, ttl_seconds=60)
    manager._jobs_store = InMemoryStore(maxsize=20, ttl=60)
    manager._events_store = InMemoryStore(maxsize=20, ttl=60)
    manager._events_store.set("legacy-orphan", {"next_seq": 0, "events": []})

    manifest = manager.manifest_diagram(
        "diagram-a",
        owner_user_id="owner-a",
        tenant_id="tenant-a",
    )
    assert manifest == {"job_ids": [], "event_ids": []}
    quarantined = manager._events_store.peek("legacy-orphan")
    assert quarantined["quarantined"] is True
    assert quarantined["diagram_id"] is None


def test_runtime_effect_classification_covers_every_base_and_v1_get_both_directions():
    audited = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/"):
            continue
        for method in sorted(set(route.methods or ()) & {"GET", "HEAD"}):
            audited += 1
            detected = classify_endpoint_effects(route.endpoint)
            declared = runtime_route_effects(route)
            scope = runtime_route_effect_scope(route, method)
            assert detected == declared, (
                f"{method} {route.path} effect mismatch: "
                f"detected={sorted(detected)} declared={sorted(declared)}"
            )
            assert scope == ("write" if detected else None)
            assert route_effect_scope(
                method,
                route.path,
                route=route,
            ) == scope

    assert audited > 250


def test_identified_gets_are_runtime_classified_side_effect_free():
    corrected_paths = {
        "/api/replays",
        "/api/diagrams/{diagram_id}/cost-breakdown",
        "/api/diagrams/{diagram_id}/cost-estimate",
        "/api/projects/{project_id}/analysis",
    }
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and "GET" in (route.methods or set())
    }
    for path in corrected_paths:
        route = routes[path]
        assert classify_endpoint_effects(route.endpoint) == frozenset()
        assert runtime_route_effects(route) == frozenset()
        assert runtime_route_effect_scope(route, "GET") is None
        v1_path = "/api/v1/" + path[len("/api/"):]
        if v1_path in routes:
            assert classify_endpoint_effects(routes[v1_path].endpoint) == frozenset()
            assert runtime_route_effects(routes[v1_path]) == frozenset()


def test_effectful_get_scope_is_documented_in_base_and_v1_openapi_contract():
    expected = {
        "/api/diagrams/{diagram_id}/cost-assumptions": {"artifact", "sql"},
        "/api/diagrams/{diagram_id}/cost-estimate/export": {
            "artifact",
            "capability",
        },
        "/api/diagrams/{diagram_id}/migration-timeline/export": {
            "artifact",
            "capability",
            "telemetry",
        },
        "/api/diagrams/{diagram_id}/report": {
            "artifact",
            "capability",
            "telemetry",
        },
        "/api/replay/{replay_id}/export": {"artifact"},
    }
    schema = app.openapi()
    for base_path, effects in expected.items():
        for path in (
            base_path,
            "/api/v1/" + base_path[len("/api/") :],
        ):
            operation = schema["paths"][path]["get"]
            assert operation["x-archmorph-effect-scope"] == "write"
            assert set(operation["x-archmorph-effects"]) == effects


def test_read_key_cannot_call_effectful_get_but_write_key_reaches_handler(test_client):
    _reader, read_key = create_api_key("reader", ["read"])
    _writer, write_key = create_api_key("writer", ["write"])

    denied = test_client.get(
        "/api/diagrams/not-owned/cost-assumptions",
        headers=_headers(read_key),
    )
    allowed_scope = test_client.get(
        "/api/diagrams/not-owned/cost-assumptions",
        headers=_headers(write_key),
    )
    denied_v1 = test_client.get(
        "/api/v1/diagrams/not-owned/cost-assumptions",
        headers=_headers(read_key),
    )
    assert denied.status_code == denied_v1.status_code == 403
    assert allowed_scope.status_code == 404


def test_read_key_reaches_corrected_side_effect_free_gets(test_client, monkeypatch):
    from routers import projects as project_routes
    from routers import replay_routes

    _reader, read_key = create_api_key("reader", ["read"])
    headers = _headers(read_key)
    monkeypatch.setattr(
        replay_routes,
        "list_migration_replays",
        lambda *_args, **_kwargs: {"replays": [], "total": 0},
    )
    monkeypatch.setattr(
        project_routes,
        "_combined_analysis_for_project",
        lambda *_args, **_kwargs: {
            "project_id": "side-effect-free",
            "source_diagram_ids": [],
            "services_detected": 0,
        },
    )
    replay_routes._replay_store.clear()

    with patch("routers.insights.record_event", create=True) as telemetry:
        responses = [
            test_client.get("/api/replays", headers=headers),
            test_client.get(
                "/api/diagrams/not-owned/cost-breakdown",
                headers=headers,
            ),
            test_client.get(
                "/api/diagrams/not-owned/cost-estimate",
                headers=headers,
            ),
            test_client.get(
                "/api/projects/not-owned/analysis",
                headers=headers,
            ),
        ]

    assert responses[0].status_code == 200, responses[0].text
    assert [response.status_code for response in responses[1:]] == [404, 404, 200]
    assert replay_routes._replay_store.keys("*") == []
    telemetry.assert_not_called()


def test_read_only_cost_estimation_does_not_mutate_process_or_file_cache(
    tmp_path,
    monkeypatch,
):
    from services import azure_pricing

    cache_file = tmp_path / "pricing-cache.json"
    monkeypatch.setattr(azure_pricing, "CACHE_FILE", cache_file)
    monkeypatch.setattr(azure_pricing, "_price_cache", {})
    monkeypatch.setattr(azure_pricing, "_cache_loaded", False)
    monkeypatch.setattr(azure_pricing, "_get_blob_client", lambda: None)
    monkeypatch.setattr(azure_pricing, "_fetch_price_from_api", lambda *_args, **_kwargs: None)

    result = azure_pricing.estimate_services_cost(
        [
            {
                "source_service": "Lambda",
                "source_provider": "aws",
                "azure_service": "Azure Functions",
            }
        ],
        persist_cache=False,
    )

    assert result["service_count"] == 1
    assert azure_pricing._price_cache == {}
    assert azure_pricing._cache_loaded is False
    assert not cache_file.exists()


def test_rate_limit_readiness_requires_explicit_shared_storage_for_redis_host(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("REDIS_HOST", "managed-redis.invalid")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RATE_LIMIT_STORAGE", raising=False)
    monkeypatch.setenv("CONTAINER_APP_MIN_REPLICAS", "2")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    readiness = shared.rate_limit_readiness()
    assert readiness["entra_host_requires_adapter"] is True
    assert readiness["ready"] is False

    monkeypatch.setenv("RATE_LIMIT_STORAGE", "rediss://shared-limiter.invalid:6380/1")
    readiness = shared.rate_limit_readiness()
    assert readiness["shared"] is True
    assert readiness["ready"] is True


def test_json_formatter_redacts_canary_secrets_and_exception_text():
    formatter = ArchmorphJsonFormatter()
    record = logging.LogRecord(
        "canary",
        logging.ERROR,
        __file__,
        1,
        "provider failed authorization=Bearer canary-secret-token api_key=arch_canarysecretvalue",
        (),
        None,
    )
    payload: dict = {}
    formatter.add_fields(payload, record, {})
    serialized = json.dumps(payload)
    assert "canary-secret-token" not in serialized
    assert "arch_canarysecretvalue" not in serialized
    assert "[REDACTED]" in serialized


def test_request_middleware_audit_uses_secret_free_api_key_attribution(test_client, monkeypatch):
    record, raw = create_api_key("audit", ["read"])
    captured = {}

    def capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("audit_logging.audit_logger.log_api_access", capture)
    response = test_client.get("/api/versions", headers=_headers(raw))
    assert response.status_code == 200
    assert captured["user_id"] == record.id
    assert captured["details"]["actor_kind"] == "api_key"
    assert raw not in json.dumps(captured)


def test_restore_grant_rollback_does_not_burn_and_retry_converges(db):
    seeded = persist_analysis_state(
        db,
        owner_user_id="restore-owner",
        tenant_id="restore-tenant",
        diagram_id="restore-diagram",
        snapshot={"mappings": []},
    )
    payload_hash = snapshot_payload_hash(json.loads(seeded.version.snapshot))
    nonce, generation, expected_version = issue_restore_grant(
        db,
        owner_user_id="restore-owner",
        tenant_id="restore-tenant",
        diagram_id="restore-diagram",
        ttl_seconds=60,
        payload_hash=payload_hash,
    )
    kwargs = {
        "nonce": nonce,
        "owner_user_id": "restore-owner",
        "tenant_id": "restore-tenant",
        "diagram_id": "restore-diagram",
        "generation": generation,
        "expected_version": expected_version,
        "payload_hash": payload_hash,
    }
    assert consume_restore_grant(db, **kwargs, commit=False) is True
    db.rollback()
    digest = __import__("hashlib").sha256(nonce.encode()).hexdigest()
    assert db.query(RestoreGrant).filter_by(nonce_digest=digest).one().consumed_at is None
    assert consume_restore_grant(db, **kwargs) is True
    assert consume_restore_grant(db, **kwargs) is False


def test_restore_payload_bounds_reject_deep_large_and_oversized_strings():
    nested = value = {}
    for _ in range(25):
        child = {}
        value["child"] = child
        value = child
    with pytest.raises(AnalysisPayloadTooLarge, match="body.depth"):
        validate_restore_payload_shape(nested)
    with pytest.raises(AnalysisPayloadTooLarge, match="body.array_items"):
        validate_restore_payload_shape({"items": list(range(201))})
    with pytest.raises(AnalysisPayloadTooLarge, match="body.string"):
        validate_restore_payload_shape({"hld": "x" * (2 * 1024 * 1024 + 1)})


def test_restore_content_length_is_rejected_before_model_parsing(test_client):
    response = test_client.post(
        "/api/diagrams/preparse-limit/restore-session",
        headers={"Content-Length": str(13 * 1024 * 1024)},
        content=b"{}",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_archived_workspace_rejects_new_canonical_analysis(db):
    workspace = create_workspace(
        db,
        owner_user_id="archive-owner",
        tenant_id="archive-tenant",
        name="Archived",
    )
    update_workspace(
        db,
        workspace.id,
        owner_user_id="archive-owner",
        tenant_id="archive-tenant",
        status="archived",
    )
    with pytest.raises(ValueError, match="Canonical state not found"):
        persist_analysis_state(
            db,
            owner_user_id="archive-owner",
            tenant_id="archive-tenant",
            diagram_id="archived-diagram",
            workspace_id=workspace.id,
            snapshot={"mappings": []},
        )


def test_b2c_canonical_subject_owns_jobs_capabilities_and_legacy_terraform(db):
    user = User(
        id="legacy-b2c-user-id",
        provider=AuthProvider.AZURE_AD_B2C,
        provider_subject="canonical-b2c-subject",
        tenant_id="b2c-tenant",
    )
    token = generate_session_token(user)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
    })
    principal = shared.get_request_durable_principal(request)
    assert principal["owner_user_id"] == "canonical-b2c-subject"
    assert principal["legacy_owner_user_ids"] == ["legacy-b2c-user-id"]
    assert _principal_marker(request) == (
        "user:b2c-tenant:canonical-b2c-subject"
    )

    canonical_job = Job(
        "analyze",
        owner_user_id="canonical-b2c-subject",
        tenant_id="b2c-tenant",
    )
    legacy_job = Job(
        "analyze",
        owner_user_id="legacy-b2c-user-id",
        tenant_id="b2c-tenant",
    )
    _ensure_job_access(
        canonical_job,
        user,
        None,
        durable_principal=principal,
    )
    _ensure_job_access(
        legacy_job,
        user,
        None,
        durable_principal=principal,
    )

    project = Workspace(
        id="b2c-project",
        owner_user_id="canonical-b2c-subject",
        tenant_id="b2c-tenant",
        name="B2C canonical project",
        status="active",
        is_default=False,
    )
    db.add(project)
    db.flush()
    db.add(
        DeploymentState(
            project_id="b2c-project",
            environment="prod",
            owner_user_id="legacy-b2c-user-id",
            tenant_id="b2c-tenant",
            state_json={"version": 1},
        )
    )
    db.commit()
    with authorized_deployment_state(
        db,
        project_id=project.id,
        environment="prod",
        caller_user_id="canonical-b2c-subject",
        tenant_id="b2c-tenant",
        allowed_roles=PROJECT_READ_ROLES,
    ) as (state, _canonical_project, _environment):
        assert state.owner_user_id == "canonical-b2c-subject"
