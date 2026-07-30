import copy
import os
import sys

import pytest
from fastapi.routing import APIRoute

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import AuthProvider, User, UserTier, generate_session_token  # noqa: E402
from export_capabilities import (  # noqa: E402
    issue_restore_capability,
    verify_export_capability,
    verify_restore_capability,
)
from main import SESSION_STORE, app  # noqa: E402
from routers.replay_routes import _replay_store, require_replay_access, require_replay_body_access  # noqa: E402
from routers.share_routes import require_share_access  # noqa: E402
from routers.shared import (  # noqa: E402
    get_api_key_service_principal,
    get_request_durable_principal,
    require_api_read_or_user_session,
    require_api_write_or_user_session,
    require_diagram_access,
    verify_api_key,
    verify_api_key_or_user_session,
)
from shareable_reports import _shares  # noqa: E402
from tests.conftest import SAMPLE_ANALYSIS, assert_cross_tenant_denied  # noqa: E402


def _auth_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    user = User(
        id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


def _owned_session(*, owner_user_id: str | None = None, tenant_id: str | None = None, owner_api_key: str | None = None):
    session = copy.deepcopy(SAMPLE_ANALYSIS)
    if owner_user_id:
        session["_owner_user_id"] = owner_user_id
    if tenant_id:
        session["_tenant_id"] = tenant_id
    if owner_api_key:
        session["_owner_api_key_id"] = owner_api_key
    return session


def _durable_restore_capability(
    request,
    diagram_id: str,
    *,
    owner_user_id: str,
    tenant_id: str,
):
    from database import SessionLocal, init_db
    from models.workspace import Analysis, DiagramLifecycle
    from project_store import create_project, get_project_id_for_diagram, register_diagram

    init_db()
    db = SessionLocal()
    try:
        lifecycle = db.query(DiagramLifecycle).filter_by(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ).first()
        project_id = get_project_id_for_diagram(
            db,
            diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
        if project_id is None:
            if lifecycle is not None and lifecycle.workspace_id:
                project_id = lifecycle.workspace_id
            else:
                project = create_project(
                    db,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                )
                project_id = project.id
        if db.query(Analysis.id).filter_by(
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        ).first() is None:
            if lifecycle is not None:
                db.add(Analysis(
                    workspace_id=project_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    diagram_id=diagram_id,
                    status="uploaded",
                    current_version=0,
                ))
                lifecycle.workspace_id = project_id
                db.commit()
            else:
                register_diagram(
                    db,
                    project_id=project_id,
                    diagram_id=diagram_id,
                    owner_user_id=owner_user_id,
                    tenant_id=tenant_id,
                    filename="restore-fixture.png",
                )
        return issue_restore_capability(
            request,
            diagram_id,
            db=db,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )
    finally:
        db.close()


def test_durable_user_principal_preserves_stable_owner_id_and_opaque_tenant_scope():
    from auth import provider_subject_tenant_scope
    from starlette.requests import Request

    user = User(
        id="github_42",
        provider=AuthProvider.GITHUB,
        provider_subject="42",
        tenant_id=provider_subject_tenant_scope(AuthProvider.GITHUB, "42"),
    )
    token = generate_session_token(user)
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )

    principal = get_request_durable_principal(request)

    assert principal["owner_user_id"] == "github_42"
    assert principal["tenant_id"] == provider_subject_tenant_scope(AuthProvider.GITHUB, "42")


def test_direct_b2c_durable_principal_uses_verified_provider_subject():
    from auth import provider_subject_tenant_scope
    from starlette.requests import Request

    user = User(
        id="azure_ad_b2c_subject-42",
        provider=AuthProvider.AZURE_AD_B2C,
        provider_subject="subject-42",
        tenant_id=provider_subject_tenant_scope(AuthProvider.AZURE_AD_B2C, "subject-42"),
    )
    token = generate_session_token(user)
    request = Request({
        "type": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    })

    principal = get_request_durable_principal(request)

    assert principal["owner_user_id"] == "subject-42"
    assert principal["tenant_id"] == provider_subject_tenant_scope(
        AuthProvider.AZURE_AD_B2C,
        "subject-42",
    )
    assert principal["legacy_owner_user_ids"] == ["azure_ad_b2c_subject-42"]


def test_durable_api_principal_reuses_verified_credential_context(monkeypatch):
    from starlette.requests import Request
    from routers.shared import CredentialContext, CredentialKind

    request = Request({"type": "http", "headers": []})
    request.state.credential_context = CredentialContext(
        kind=CredentialKind.STATIC,
        principal_id="api-key:static-service",
        key_id="static",
        scopes=frozenset({"read", "write"}),
        rate_limit=None,
        tenant_id="service:static-service",
        owner_user_id="api-key:static-service",
    )
    monkeypatch.setattr(
        "auth.get_user_from_request_headers",
        lambda _headers: (_ for _ in ()).throw(
            AssertionError("verified API context must not reparse authentication")
        ),
    )

    principal = get_request_durable_principal(request)

    assert principal["owner_user_id"] == "api-key:static-service"
    assert principal["tenant_id"] == "service:static-service"
    assert principal["owner_api_key_id"] == "api-key:static-service"


def test_development_credential_context_has_no_durable_principal(monkeypatch):
    from starlette.requests import Request
    from routers.shared import CredentialContext, CredentialKind

    request = Request({"type": "http", "headers": []})
    request.state.credential_context = CredentialContext(
        kind=CredentialKind.DEVELOPMENT,
        principal_id="development",
        key_id=None,
        scopes=frozenset({"read", "write"}),
        rate_limit=None,
        tenant_id=None,
        owner_user_id=None,
    )
    monkeypatch.setattr(
        "auth.get_user_from_request_headers",
        lambda _headers: (_ for _ in ()).throw(
            AssertionError("development context must not reparse authentication")
        ),
    )

    assert get_request_durable_principal(request) is None


@pytest.fixture(autouse=True)
def clean_state():
    SESSION_STORE.clear()
    _shares.clear()
    _replay_store.clear()
    yield
    SESSION_STORE.clear()
    _shares.clear()
    _replay_store.clear()


def test_cost_estimate_denies_cross_tenant_access(test_client, tenant_a_auth_headers, tenant_b_auth_headers):
    diagram_id = "tenant-locked-cost-diagram"
    SESSION_STORE[diagram_id] = _owned_session(owner_user_id="user-a-001", tenant_id="tenant-a")

    owner = test_client.get(f"/api/diagrams/{diagram_id}/cost-estimate", headers=tenant_a_auth_headers)
    intruder = test_client.get(f"/api/diagrams/{diagram_id}/cost-estimate", headers=tenant_b_auth_headers)

    assert owner.status_code == 200, owner.text
    assert_cross_tenant_denied(intruder)


def test_iac_chat_history_denies_cross_api_principal_access(test_client):
    diagram_id = "api-principal-owned-diagram"
    owner_headers = {"X-API-Key": "principal-a"}
    intruder_headers = {"X-API-Key": "principal-b"}
    SESSION_STORE[diagram_id] = _owned_session(
        owner_api_key=get_api_key_service_principal({"x-api-key": owner_headers["X-API-Key"]})
    )

    owner = test_client.get(f"/api/diagrams/{diagram_id}/iac-chat/history", headers=owner_headers)
    intruder = test_client.get(f"/api/diagrams/{diagram_id}/iac-chat/history", headers=intruder_headers)

    assert owner.status_code == 200, owner.text
    assert intruder.status_code == 404


def test_public_sample_exception_remains_accessible_without_authentication(test_client):
    response = test_client.get("/api/diagrams/sample-aws-iaas-abcdef/cost-estimate")
    assert response.status_code == 200, response.text


def test_public_template_exception_remains_accessible_without_authentication(test_client):
    analyze = test_client.post("/api/templates/aws-iaas-web/analyze")
    assert analyze.status_code == 200, analyze.text

    diagram_id = analyze.json()["diagram_id"]
    response = test_client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
    assert response.status_code == 200, response.text


def test_shared_report_get_is_public_but_stats_and_delete_require_owner(
    test_client,
    tenant_a_auth_headers,
    tenant_b_auth_headers,
):
    diagram_id = "shared-report-owner-diagram"
    SESSION_STORE[diagram_id] = _owned_session(owner_user_id="user-a-001", tenant_id="tenant-a")

    created = test_client.post(f"/api/diagrams/{diagram_id}/share", headers=tenant_a_auth_headers)
    assert created.status_code == 200, created.text
    share_id = created.json()["share_id"]

    public_get = test_client.get(f"/api/shared/{share_id}")
    stats_owner = test_client.get(f"/api/shared/{share_id}/stats", headers=tenant_a_auth_headers)
    stats_intruder = test_client.get(f"/api/shared/{share_id}/stats", headers=tenant_b_auth_headers)
    delete_intruder = test_client.delete(f"/api/shared/{share_id}", headers=tenant_b_auth_headers)

    assert public_get.status_code == 200, public_get.text
    assert stats_owner.status_code == 200, stats_owner.text
    assert_cross_tenant_denied(stats_intruder)
    assert_cross_tenant_denied(delete_intruder)


def test_replay_get_denies_cross_tenant_access(test_client, tenant_a_auth_headers, tenant_b_auth_headers):
    diagram_id = "replay-owner-diagram"
    from database import SessionLocal
    from workspace_store import persist_analysis_state

    db = SessionLocal()
    try:
        persist_analysis_state(
            db,
            owner_user_id="user-a-001",
            tenant_id="tenant-a",
            diagram_id=diagram_id,
            snapshot=_owned_session(owner_user_id="user-a-001", tenant_id="tenant-a"),
            session_store=SESSION_STORE,
            cache_required=True,
        )
    finally:
        db.close()

    created = test_client.post(
        "/api/replay/record",
        json={"analysis_id": diagram_id, "title": "Owner replay"},
        headers=tenant_a_auth_headers,
    )
    assert created.status_code == 200, created.text
    replay_id = created.json()["replay_id"]

    owner = test_client.get(f"/api/replay/{replay_id}", headers=tenant_a_auth_headers)
    intruder = test_client.get(f"/api/replay/{replay_id}", headers=tenant_b_auth_headers)

    assert owner.status_code == 200, owner.text
    assert_cross_tenant_denied(intruder)


def test_diagram_artifact_routes_require_api_key_or_user_session_dependency_and_export_capability():
    exempt_paths = {
        "/api/diagrams/{diagram_id}/restore-session",
        "/api/diagrams/{diagram_id}/analyze",
        "/api/diagrams/{diagram_id}/analyze-async",
    }
    capability_paths = {
        "/api/diagrams/{diagram_id}/export-diagram",
        "/api/diagrams/{diagram_id}/export-architecture-package",
        "/api/diagrams/{diagram_id}/export-hld",
        "/api/diagrams/{diagram_id}/export-package",
        "/api/diagrams/{diagram_id}/report",
        "/api/diagrams/{diagram_id}/cost-estimate/export",
        "/api/diagrams/{diagram_id}/migration-timeline/export",
    }

    missing: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if (
            not route.path.startswith("/api/diagrams/{diagram_id}/")
            or route.path in exempt_paths
        ):
            continue
        dependency_callables = {dep.call for dep in route.dependant.dependencies}
        methods = sorted(set(route.methods or ()) - {"HEAD", "OPTIONS"})
        if not dependency_callables.intersection(
            {
                verify_api_key,
                verify_api_key_or_user_session,
                require_api_read_or_user_session,
                require_api_write_or_user_session,
            }
        ):
            missing.append(
                f"{methods} {route.path} missing API-key-or-user-session auth dependency"
            )
        if require_diagram_access not in dependency_callables:
            missing.append(f"{methods} {route.path} missing require_diagram_access")
        if (
            route.path in capability_paths
            and verify_export_capability not in dependency_callables
        ):
            missing.append(f"{methods} {route.path} missing verify_export_capability")

    assert not missing, "\n".join(missing)


def test_share_and_replay_manifests_keep_public_and_private_exceptions_explicit():
    indexed = {
        (
            route.path,
            tuple(sorted(set(route.methods or ()) - {"HEAD", "OPTIONS"})),
        ): route
        for route in app.routes
        if isinstance(route, APIRoute)
    }

    shared_get = indexed[("/api/shared/{share_id}", ("GET",))]
    shared_stats = indexed[("/api/shared/{share_id}/stats", ("GET",))]
    shared_delete = indexed[("/api/shared/{share_id}", ("DELETE",))]
    replay_get = indexed[("/api/replay/{replay_id}", ("GET",))]
    replay_export = indexed[("/api/replay/{replay_id}/export", ("GET",))]
    replay_add_event = indexed[("/api/replay/events", ("POST",))]

    shared_get_deps = {dep.call for dep in shared_get.dependant.dependencies}
    assert verify_api_key not in shared_get_deps
    assert require_share_access not in shared_get_deps

    for route in (shared_stats, shared_delete):
        deps = {dep.call for dep in route.dependant.dependencies}
        expected_scope = (
            require_api_read_or_user_session
            if route is shared_stats
            else require_api_write_or_user_session
        )
        assert expected_scope in deps
        assert require_share_access in deps

    for route in (replay_get, replay_export):
        deps = {dep.call for dep in route.dependant.dependencies}
        assert verify_api_key in deps
        assert require_replay_access in deps

    replay_add_event_deps = {dep.call for dep in replay_add_event.dependant.dependencies}
    assert verify_api_key in replay_add_event_deps
    assert require_replay_body_access in replay_add_event_deps


def test_restore_session_keeps_owner_only_mutation_guard(test_client):
    diagram_id = "restore-session-locked"
    SESSION_STORE[diagram_id] = _owned_session(owner_user_id="owner-1", tenant_id="tenant-a")

    other_headers = _auth_headers("owner-2", "tenant-a")
    response = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers=other_headers,
        json={"analysis": copy.deepcopy(SAMPLE_ANALYSIS)},
    )

    assert_cross_tenant_denied(response)


def test_restore_missing_and_foreign_namespace_return_same_404(
    test_client,
    tenant_a_auth_headers,
    tenant_b_auth_headers,
):
    diagram_id = "restore-oracle-locked"
    SESSION_STORE[diagram_id] = _owned_session(owner_user_id="user-a-001", tenant_id="tenant-a")
    payload = {"analysis": copy.deepcopy(SAMPLE_ANALYSIS)}

    foreign = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers=tenant_b_auth_headers,
        json=payload,
    )
    missing = test_client.post(
        "/api/diagrams/restore-oracle-missing/restore-session",
        headers=tenant_b_auth_headers,
        json=payload,
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_restore_capability_survives_cache_loss_and_is_principal_bound(
    test_client,
    tenant_a_auth_headers,
    tenant_b_auth_headers,
):
    from starlette.requests import Request

    diagram_id = "restore-capability-cache-loss"
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", tenant_a_auth_headers["Authorization"].encode())],
        }
    )
    capability = _durable_restore_capability(
        request,
        diagram_id,
        owner_user_id="user-a-001",
        tenant_id="tenant-a",
    )
    SESSION_STORE.delete(diagram_id)
    payload = {
        "analysis": copy.deepcopy(SAMPLE_ANALYSIS),
        "restore_capability": capability,
    }

    denied = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers=tenant_b_auth_headers,
        json=payload,
    )
    allowed = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers=tenant_a_auth_headers,
        json=payload,
    )

    assert denied.status_code == 404
    assert allowed.status_code == 200, allowed.text
    next_capability = allowed.json()["restore_capability"]
    assert next_capability
    assert verify_restore_capability(request, diagram_id, next_capability) is True


def test_restore_capability_records_api_key_actor_marker(monkeypatch):
    import jwt
    from auth import JWT_ALGORITHM, JWT_SECRET
    from routers import shared
    from starlette.requests import Request

    monkeypatch.setattr(shared, "API_KEY", "restore-api-key")
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-api-key", b"restore-api-key")],
        }
    )

    principal = get_api_key_service_principal({"x-api-key": "restore-api-key"})
    capability = _durable_restore_capability(
        request,
        "restore-api-marker",
        owner_user_id=principal,
        tenant_id=f"service:{principal.split(':', 1)[-1]}",
    )
    payload = jwt.decode(capability, JWT_SECRET, algorithms=[JWT_ALGORITHM])

    assert payload["actor_kind"] == "api_key"
    assert payload["scope"] == "session:restore"
    assert payload["principal_digest"]


def test_api_key_restore_capability_claims_and_restores_namespace(test_client, monkeypatch):
    from routers import shared
    from starlette.requests import Request

    api_key = "restore-api-key-route"
    diagram_id = "restore-api-key-namespace"
    monkeypatch.setattr(shared, "API_KEY", api_key)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-api-key", api_key.encode())],
        }
    )
    principal = get_api_key_service_principal({"x-api-key": api_key})
    capability = _durable_restore_capability(
        request,
        diagram_id,
        owner_user_id=principal,
        tenant_id=f"service:{principal.split(':', 1)[-1]}",
    )

    response = test_client.post(
        f"/api/diagrams/{diagram_id}/restore-session",
        headers={"X-API-Key": api_key},
        json={
            "analysis": copy.deepcopy(SAMPLE_ANALYSIS),
            "restore_capability": capability,
        },
    )

    assert response.status_code == 200, response.text
    assert SESSION_STORE.peek(diagram_id)["_owner_api_key_id"] == principal
