"""Adversarial canonical Terraform-state identity and authorization contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from auth import AuthProvider, User, UserTier, generate_session_token
from database import SessionLocal
from models.deployment_state import DeploymentState
from models.tenant import Organization, TeamMember
from models.workspace import ProjectMember, Workspace
from project_store import PROJECT_EDIT_ROLES
from routers.tf_backend import (
    LOCK_STORE,
    _state_scope_key,
    authorized_deployment_state,
    normalize_state_environment,
)


def _auth_headers(user_id: str, tenant_id: str) -> dict[str, str]:
    user = User(
        id=user_id,
        email=f"{user_id}@example.test",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


@pytest.fixture()
def canonical_tf_project():
    suffix = uuid.uuid4().hex[:16]
    project_id = f"proj-tf-{suffix}"
    tenant_id = f"tenant-tf-{suffix}"
    identities = {
        "project_id": project_id,
        "tenant_id": tenant_id,
        "owner": f"owner-{suffix}",
        "admin": f"admin-{suffix}",
        "editor": f"editor-{suffix}",
        "viewer": f"viewer-{suffix}",
        "foreign": f"foreign-{suffix}",
        "foreign_tenant": f"tenant-foreign-{suffix}",
    }
    db = SessionLocal()
    try:
        db.add(
            Organization(
                org_id=tenant_id,
                name="Canonical Terraform state tenant",
                slug=f"canonical-tf-{suffix}",
            )
        )
        db.flush()
        db.add(
            TeamMember(
                org_id=tenant_id,
                user_id=identities["admin"],
                email=f"{identities['admin']}@example.test",
                role="admin",
                is_active=True,
            )
        )
        db.add(
            Workspace(
                id=project_id,
                owner_user_id=identities["owner"],
                tenant_id=tenant_id,
                name="Canonical Terraform state project",
                status="active",
                is_default=False,
            )
        )
        db.flush()
        db.add_all(
            [
                ProjectMember(
                    project_id=project_id,
                    project_owner_user_id=identities["owner"],
                    tenant_id=tenant_id,
                    member_user_id=identities["editor"],
                    role="editor",
                ),
                ProjectMember(
                    project_id=project_id,
                    project_owner_user_id=identities["owner"],
                    tenant_id=tenant_id,
                    member_user_id=identities["viewer"],
                    role="viewer",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    LOCK_STORE.clear()
    yield identities

    LOCK_STORE.clear()
    db = SessionLocal()
    try:
        db.query(Workspace).filter(Workspace.id == project_id).delete()
        db.query(Organization).filter(Organization.org_id == tenant_id).delete()
        db.commit()
    finally:
        db.close()


def _error_signature(response) -> tuple[object, object, object]:
    error = response.json()["error"]
    return error["code"], error["message"], error["details"]


def test_normalized_environment_and_v1_alias_resolve_one_canonical_row(
    test_client,
    canonical_tf_project,
):
    project = canonical_tf_project
    owner_headers = _auth_headers(project["owner"], project["tenant_id"])
    admin_headers = _auth_headers(project["admin"], project["tenant_id"])
    editor_headers = _auth_headers(project["editor"], project["tenant_id"])
    v1_url = f"/api/v1/terraform/state/{project['project_id']}/Production"
    canonical_url = f"/api/terraform/state/{project['project_id']}/prod"

    assert normalize_state_environment(" PrOdUcTiOn ") == "prod"
    assert normalize_state_environment("STAGING") == "staging"
    assert (
        test_client.post(v1_url, headers=editor_headers, json={"serial": 1}).status_code
        == 200
    )
    assert (
        test_client.request(
            "LOCK",
            v1_url,
            headers=owner_headers,
            content='{"ID":"alias-lock"}',
        ).status_code
        == 200
    )
    assert (
        test_client.post(
            canonical_url,
            headers=editor_headers,
            params={"ID": "alias-lock"},
            json={"serial": 2},
        ).status_code
        == 200
    )
    assert (
        test_client.request(
            "UNLOCK",
            v1_url,
            headers=admin_headers,
            content='{"ID":"alias-lock"}',
        ).status_code
        == 200
    )
    assert (
        test_client.post(
            canonical_url, headers=owner_headers, json={"serial": 3}
        ).status_code
        == 200
    )
    rollback = test_client.post(f"{v1_url}/rollback", headers=owner_headers)
    assert rollback.status_code == 200
    assert rollback.json()["environment"] == "prod"
    response = test_client.get(canonical_url, headers=owner_headers)
    assert response.status_code == 200
    assert response.json() == {"serial": 2}

    db = SessionLocal()
    try:
        with authorized_deployment_state(
            db,
            project_id=project["project_id"],
            caller_user_id=project["editor"],
            tenant_id=project["tenant_id"],
            environment=" PrOdUcTiOn ",
            allowed_roles=PROJECT_EDIT_ROLES,
        ) as (state, canonical_project, environment):
            assert canonical_project.id == project["project_id"]
            assert environment == "prod"
        rows = (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project["project_id"],
            )
            .all()
        )
        assert [row.id for row in rows] == [state.id]
        assert state.environment == "prod"
        assert state.owner_user_id == project["owner"]
        assert state.tenant_id == project["tenant_id"]
    finally:
        db.close()


def test_owner_member_tenant_policy_denies_uniformly_without_state_or_lock_oracle(
    test_client,
    canonical_tf_project,
):
    project = canonical_tf_project
    state_url = f"/api/terraform/state/{project['project_id']}/dev"
    missing_url = f"/api/terraform/state/proj-missing-{uuid.uuid4().hex[:8]}/dev"
    owner_headers = _auth_headers(project["owner"], project["tenant_id"])
    editor_headers = _auth_headers(project["editor"], project["tenant_id"])
    viewer_headers = _auth_headers(project["viewer"], project["tenant_id"])
    foreign_headers = _auth_headers(project["foreign"], project["tenant_id"])
    wrong_tenant_headers = _auth_headers(project["owner"], project["foreign_tenant"])

    assert (
        test_client.post(
            state_url, headers=editor_headers, json={"serial": 1}
        ).status_code
        == 200
    )
    assert (
        test_client.request(
            "LOCK",
            state_url,
            headers=owner_headers,
            content='{"ID":"private-lock","Who":"canonical-owner"}',
        ).status_code
        == 200
    )
    assert test_client.get(state_url, headers=viewer_headers).status_code == 200

    denied = [
        test_client.get(state_url, headers=foreign_headers),
        test_client.get(state_url, headers=wrong_tenant_headers),
        test_client.get(missing_url, headers=foreign_headers),
        test_client.post(
            state_url,
            headers={**foreign_headers, "Content-Type": "application/json"},
            content="{not-json",
        ),
        test_client.request(
            "LOCK",
            state_url,
            headers=foreign_headers,
            content="{not-json",
        ),
        test_client.post(state_url, headers=viewer_headers, json={"serial": 2}),
        test_client.request(
            "LOCK",
            state_url,
            headers=viewer_headers,
            content='{"ID":"viewer-lock"}',
        ),
    ]
    assert {response.status_code for response in denied} == {404}
    assert len({_error_signature(response) for response in denied}) == 1
    assert all("private-lock" not in response.text for response in denied)
    assert all("canonical-owner" not in response.text for response in denied)

    db = SessionLocal()
    try:
        rows = (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project["project_id"],
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].owner_user_id == project["owner"]
        assert rows[0].tenant_id == project["tenant_id"]
        assert rows[0].lock_id == "private-lock"
    finally:
        db.close()


def test_forced_two_principal_barrier_first_creation_produces_exactly_one_row(
    canonical_tf_project,
):
    project = canonical_tf_project
    barrier = threading.Barrier(2)

    def create_as(caller_user_id: str) -> int:
        db = SessionLocal()
        try:
            barrier.wait(timeout=5)
            with authorized_deployment_state(
                db,
                project_id=project["project_id"],
                caller_user_id=caller_user_id,
                tenant_id=project["tenant_id"],
                environment=" PRODUCTION ",
                allowed_roles=PROJECT_EDIT_ROLES,
            ) as (state, _canonical_project, environment):
                assert environment == "prod"
                return state.id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        state_ids = list(executor.map(create_as, [project["owner"], project["editor"]]))

    assert len(set(state_ids)) == 1
    db = SessionLocal()
    try:
        rows = (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project["project_id"],
                DeploymentState.environment == "prod",
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].owner_user_id == project["owner"]
        assert rows[0].tenant_id == project["tenant_id"]
    finally:
        db.close()


def test_database_lock_survives_cache_loss_and_new_session_restart(
    test_client,
    canonical_tf_project,
):
    project = canonical_tf_project
    state_url = f"/api/terraform/state/{project['project_id']}/staging"
    owner_headers = _auth_headers(project["owner"], project["tenant_id"])
    editor_headers = _auth_headers(project["editor"], project["tenant_id"])

    assert (
        test_client.post(
            state_url, headers=owner_headers, json={"serial": 1}
        ).status_code
        == 200
    )
    assert (
        test_client.request(
            "LOCK",
            state_url,
            headers=owner_headers,
            content='{"ID":"durable-lock","Who":"owner"}',
        ).status_code
        == 200
    )
    LOCK_STORE.clear()

    conflict = test_client.post(
        state_url,
        headers=editor_headers,
        params={"ID": "different-lock"},
        json={"serial": 2},
    )
    assert conflict.status_code == 423
    assert conflict.json()["error"]["details"]["lock_info"]["ID"] == "durable-lock"

    db = SessionLocal()
    try:
        restarted_state = (
            db.query(DeploymentState)
            .filter_by(
                project_id=project["project_id"],
                environment="staging",
            )
            .one()
        )
        assert restarted_state.lock_id == "durable-lock"
        assert restarted_state.state_json == {"serial": 1}
    finally:
        db.close()

    assert test_client.get(state_url, headers=editor_headers).status_code == 200
    projected_lock = LOCK_STORE.get(_state_scope_key(project["project_id"], "staging"))
    assert projected_lock["ID"] == "durable-lock"
    assert (
        test_client.post(
            state_url,
            headers=editor_headers,
            params={"ID": "durable-lock"},
            json={"serial": 2},
        ).status_code
        == 200
    )
    assert (
        test_client.request(
            "UNLOCK",
            state_url,
            headers=editor_headers,
            content='{"ID":"durable-lock"}',
        ).status_code
        == 200
    )
    assert (
        test_client.post(
            state_url, headers=owner_headers, json={"serial": 3}
        ).status_code
        == 200
    )
    rollback = test_client.post(f"{state_url}/rollback", headers=owner_headers)
    assert rollback.status_code == 200
    assert rollback.json()["environment"] == "staging"
    assert test_client.get(state_url, headers=owner_headers).json() == {"serial": 2}

    db = SessionLocal()
    try:
        restarted_state = (
            db.query(DeploymentState)
            .filter_by(
                project_id=project["project_id"],
                environment="staging",
            )
            .one()
        )
        assert restarted_state.state_json == {"serial": 2}
        assert restarted_state.previous_state_json == {"serial": 3}
        assert restarted_state.lock_id is None
    finally:
        db.close()


def test_global_unique_scope_and_project_delete_cascades_state(
    test_client,
    canonical_tf_project,
):
    project = canonical_tf_project
    state_url = f"/api/terraform/state/{project['project_id']}/dev"
    owner_headers = _auth_headers(project["owner"], project["tenant_id"])
    assert test_client.get(state_url, headers=owner_headers).status_code == 200

    db = SessionLocal()
    try:
        db.add(
            DeploymentState(
                project_id=project["project_id"],
                environment="dev",
                owner_user_id="unrelated-principal",
                tenant_id="unrelated-tenant",
                state_json={},
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.query(Workspace).filter(Workspace.id == project["project_id"]).delete()
        db.commit()
        assert (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project["project_id"],
            )
            .count()
            == 0
        )
    finally:
        db.close()


def test_environment_validation_occurs_only_after_project_authorization(
    test_client,
    canonical_tf_project,
):
    project = canonical_tf_project
    invalid_url = f"/api/terraform/state/{project['project_id']}/qa"
    owner_headers = _auth_headers(project["owner"], project["tenant_id"])
    foreign_headers = _auth_headers(project["foreign"], project["tenant_id"])

    authorized = test_client.get(invalid_url, headers=owner_headers)
    foreign = test_client.get(invalid_url, headers=foreign_headers)
    assert authorized.status_code == 422
    assert foreign.status_code == 404
    assert "qa" not in authorized.text
    assert "qa" not in foreign.text

    db = SessionLocal()
    try:
        assert (
            db.query(DeploymentState)
            .filter(
                DeploymentState.project_id == project["project_id"],
            )
            .count()
            == 0
        )
    finally:
        db.close()
