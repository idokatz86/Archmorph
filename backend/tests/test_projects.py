import copy
import io
from unittest.mock import patch

import pytest

from database import SessionLocal
from models.tenant import Organization, TeamMember
from models.workspace import Analysis, ProjectMember, Workspace
from project_store import PROJECT_CACHE_VERSION, _cache_project, create_project
from session_store import InMemoryStore
from routers.shared import IMAGE_STORE, PROJECT_STORE, SESSION_STORE


MOCK_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "services_detected": 2,
    "zones": [
        {
            "id": 1,
            "name": "Compute",
            "services": [
                {
                    "aws": "Amazon EC2",
                    "azure": "Azure Virtual Machines",
                    "confidence": 0.95,
                }
            ],
        },
    ],
    "mappings": [
        {
            "source_service": "Amazon EC2",
            "source_provider": "aws",
            "azure_service": "Azure Virtual Machines",
            "confidence": 0.95,
        },
        {
            "source_service": "Amazon S3",
            "source_provider": "aws",
            "azure_service": "Azure Blob Storage",
            "confidence": 0.91,
        },
    ],
    "service_connections": [
        {"from": "Amazon EC2", "to": "Amazon S3", "protocol": "HTTPS"}
    ],
    "warnings": [],
    "confidence_summary": {"high": 2, "medium": 0, "low": 0, "average": 0.93},
}


@pytest.fixture(autouse=True)
def clean_project_state():
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    PROJECT_STORE.clear()
    db = SessionLocal()
    try:
        db.query(ProjectMember).delete()
        db.query(TeamMember).filter(
            TeamMember.user_id.in_(["user-foreign", "user-a-collaborator"])
        ).delete(synchronize_session=False)
        db.query(Organization).filter(
            Organization.org_id.in_(["tenant-a", "tenant-b"])
        ).delete(synchronize_session=False)
        db.query(Analysis).delete()
        db.query(Workspace).filter(Workspace.is_default.is_(False)).delete()
        db.commit()
    finally:
        db.close()
    yield
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    PROJECT_STORE.clear()


def _upload(test_client, headers, *, filename="arch.png", project_id=None):
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    path = f"/api/projects/{project_id}/diagrams" if project_id else "/api/projects/diagrams"
    response = test_client.post(
        path,
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "image/png")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _analyze(test_client, diagram_id, headers, analysis=None):
    with patch(
        "routers.diagrams.analyze_image",
        return_value=copy.deepcopy(analysis or MOCK_ANALYSIS),
    ):
        response = test_client.post(
            f"/api/diagrams/{diagram_id}/analyze",
            headers=headers,
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_allocates_high_entropy_server_project_id(test_client, tenant_a_auth_headers):
    first = _upload(test_client, tenant_a_auth_headers)
    second = _upload(test_client, tenant_a_auth_headers)

    assert first["project_id"].startswith("proj-")
    assert len(first["project_id"]) >= 29
    assert first["project_id"] != second["project_id"]
    assert first["project_id"] != "demo-project"


def test_authorized_project_id_reacquires_existing_project(test_client, tenant_a_auth_headers):
    first = _upload(test_client, tenant_a_auth_headers, filename="first.png")
    second = _upload(
        test_client,
        tenant_a_auth_headers,
        filename="second.png",
        project_id=first["project_id"],
    )

    assert second["project_id"] == first["project_id"]
    response = test_client.get(
        f"/api/projects/{first['project_id']}",
        headers=tenant_a_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["diagram_ids"] == sorted(
        [first["diagram_id"], second["diagram_id"]]
    )


def test_legacy_upload_path_is_compatibility_only_in_openapi(test_client):
    schema = test_client.get("/openapi.json").json()

    assert "/api/projects/diagrams" in schema["paths"]
    assert "/api/projects/{project_id}/diagrams" not in schema["paths"]


def test_foreign_caller_selected_project_id_allocates_isolated_project(
    test_client,
    tenant_a_auth_headers,
    tenant_b_auth_headers,
):
    owner_upload = _upload(test_client, tenant_a_auth_headers)
    foreign_upload = _upload(
        test_client,
        tenant_b_auth_headers,
        project_id=owner_upload["project_id"],
    )

    assert foreign_upload["project_id"] != owner_upload["project_id"]
    denied = test_client.get(
        f"/api/projects/{owner_upload['project_id']}",
        headers=tenant_b_auth_headers,
    )
    assert denied.status_code == 404


def test_project_analysis_survives_redis_loss(test_client, tenant_a_auth_headers):
    uploaded = _upload(test_client, tenant_a_auth_headers)
    _analyze(test_client, uploaded["diagram_id"], tenant_a_auth_headers)
    SESSION_STORE.clear()
    PROJECT_STORE.clear()

    response = test_client.get(
        f"/api/projects/{uploaded['project_id']}/analysis",
        headers=tenant_a_auth_headers,
    )

    assert response.status_code == 200, response.text
    combined = response.json()
    assert combined["project_id"] == uploaded["project_id"]
    assert combined["source_diagram_ids"] == [uploaded["diagram_id"]]
    assert combined["services_detected"] == 2


def test_stale_project_cache_projection_cannot_replace_newer_version():
    cache = InMemoryStore(maxsize=10, ttl=3600)
    cache.set(
        "proj-cache-cas",
        {
            "project_id": "proj-cache-cas",
            "project_version": 9,
            "_cache_contract_version": PROJECT_CACHE_VERSION,
            "_owner_user_id": "cache-owner",
            "_tenant_id": "cache-tenant",
        },
    )

    updated = _cache_project(
        cache,
        {"project_id": "proj-cache-cas", "project_version": 8},
        owner_user_id="cache-owner",
        tenant_id="cache-tenant",
    )

    assert updated is False
    assert cache.peek("proj-cache-cas")["project_version"] == 9


@pytest.mark.parametrize("suffix,method", [
    ("", "get"),
    ("/analysis", "get"),
    ("/generate?format=terraform", "post"),
    ("/members", "get"),
])
def test_two_owner_two_tenant_project_idor_is_indistinguishable_from_missing(
    test_client,
    tenant_a_auth_headers,
    tenant_b_auth_headers,
    suffix,
    method,
):
    uploaded = _upload(test_client, tenant_a_auth_headers)
    _analyze(test_client, uploaded["diagram_id"], tenant_a_auth_headers)
    foreign = getattr(test_client, method)(
        f"/api/projects/{uploaded['project_id']}{suffix}",
        headers=tenant_b_auth_headers,
    )
    missing = getattr(test_client, method)(
        f"/api/projects/proj-missing-project-identity{suffix}",
        headers=tenant_b_auth_headers,
    )

    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json()["error"]["message"] == missing.json()["error"]["message"]


def test_project_generate_uses_durable_combined_analysis(test_client, tenant_a_auth_headers):
    uploaded = _upload(test_client, tenant_a_auth_headers)
    _analyze(test_client, uploaded["diagram_id"], tenant_a_auth_headers)
    SESSION_STORE.clear()
    with patch(
        "routers.projects.generate_iac_code",
        return_value='resource "azurerm_resource_group" "rg" {}',
    ) as generate:
        response = test_client.post(
            f"/api/projects/{uploaded['project_id']}/generate?format=terraform",
            headers=tenant_a_auth_headers,
        )

    assert response.status_code == 200, response.text
    assert generate.call_args.kwargs["analysis"]["combined"] is True


def test_project_id_collision_retries(monkeypatch):
    db = SessionLocal()
    try:
        existing = create_project(
            db,
            owner_user_id="collision-owner-a",
            tenant_id="collision-tenant-a",
        )
        existing_id = existing.id
        db.expunge(existing)
        generated = iter([existing_id, "proj-collision-retry-safe-id"])
        monkeypatch.setattr("project_store.generate_project_id", lambda: next(generated))

        created = create_project(
            db,
            owner_user_id="collision-owner-b",
            tenant_id="collision-tenant-b",
        )

        assert created.id == "proj-collision-retry-safe-id"
    finally:
        db.close()


def test_foreign_member_rejected_and_same_tenant_member_persists(
    test_client,
    tenant_a_auth_headers,
):
    uploaded = _upload(test_client, tenant_a_auth_headers)
    project_id = uploaded["project_id"]
    db = SessionLocal()
    try:
        db.add_all([
            Organization(
                org_id="tenant-a",
                name="Tenant A",
                slug="project-test-tenant-a",
            ),
            Organization(
                org_id="tenant-b",
                name="Tenant B",
                slug="project-test-tenant-b",
            ),
            TeamMember(
                org_id="tenant-a",
                user_id="user-a-collaborator",
                email="collaborator-a@example.test",
                is_active=True,
            ),
            TeamMember(
                org_id="tenant-b",
                user_id="user-foreign",
                email="foreign@example.test",
                is_active=True,
            ),
        ])
        db.commit()
    finally:
        db.close()
    foreign = test_client.put(
        f"/api/projects/{project_id}/members/user-foreign",
        headers=tenant_a_auth_headers,
        json={"user_id": "user-foreign", "role": "viewer"},
    )
    assert foreign.status_code == 400

    accepted = test_client.put(
        f"/api/projects/{project_id}/members/user-a-collaborator",
        headers=tenant_a_auth_headers,
        json={
            "user_id": "user-a-collaborator",
            "role": "editor",
        },
    )
    assert accepted.status_code == 200, accepted.text

    PROJECT_STORE.clear()
    members = test_client.get(
        f"/api/projects/{project_id}/members",
        headers=tenant_a_auth_headers,
    )
    assert members.status_code == 200
    assert len(members.json()["members"]) == 1
    assert members.json()["members"][0]["user_id"] == "user-a-collaborator"
    assert members.json()["members"][0]["role"] == "editor"
