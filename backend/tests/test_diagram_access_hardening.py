import copy
import os
import sys

import pytest
from fastapi.routing import APIRoute

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import AuthProvider, User, UserTier, generate_session_token  # noqa: E402
from export_capabilities import verify_export_capability  # noqa: E402
from main import SESSION_STORE, app  # noqa: E402
from routers.replay_routes import _replay_store, require_replay_access, require_replay_body_access  # noqa: E402
from routers.share_routes import require_share_access  # noqa: E402
from routers.shared import get_api_key_service_principal, require_diagram_access, verify_api_key  # noqa: E402
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
    SESSION_STORE[diagram_id] = _owned_session(owner_user_id="user-a-001", tenant_id="tenant-a")

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


def test_diagram_artifact_routes_require_api_key_access_dependency_and_export_capability():
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
    }

    missing: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/diagrams/{diagram_id}/") or route.path in exempt_paths:
            continue
        dependency_callables = {dep.call for dep in route.dependant.dependencies}
        methods = sorted(set(route.methods or ()) - {"HEAD", "OPTIONS"})
        if verify_api_key not in dependency_callables:
            missing.append(f"{methods} {route.path} missing verify_api_key")
        if require_diagram_access not in dependency_callables:
            missing.append(f"{methods} {route.path} missing require_diagram_access")
        if route.path in capability_paths and verify_export_capability not in dependency_callables:
            missing.append(f"{methods} {route.path} missing verify_export_capability")

    assert not missing, "\n".join(missing)


def test_share_and_replay_manifests_keep_public_and_private_exceptions_explicit():
    indexed = {
        (route.path, tuple(sorted(set(route.methods or ()) - {"HEAD", "OPTIONS"}))): route
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
        assert verify_api_key in deps
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
