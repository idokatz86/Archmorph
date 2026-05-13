import pytest

from auth import AuthProvider, User, UserTier, generate_session_token
from routers.collaboration_routes import _change_store, _session_store


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


@pytest.fixture(autouse=True)
def _clear_collaboration_stores():
    _session_store.clear()
    _change_store.clear()
    yield
    _session_store.clear()
    _change_store.clear()


def _create_session(test_client, headers: dict[str, str], *, owner: str, analysis_id: str = "analysis-1") -> dict:
    response = test_client.post(
        "/api/collab/sessions",
        headers=headers,
        json={"analysis_id": analysis_id, "owner": owner},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_cross_tenant_denied(response) -> None:
    assert response.status_code in (403, 404), response.text


def test_create_session_rejects_forged_owner_and_binds_authenticated_owner(
    test_client,
    tenant_a,
    tenant_a_auth_headers,
):
    forged = test_client.post(
        "/api/collab/sessions",
        headers=tenant_a_auth_headers,
        json={"analysis_id": "analysis-1", "owner": "forged-owner"},
    )
    assert forged.status_code == 403

    created = _create_session(
        test_client,
        tenant_a_auth_headers,
        owner=tenant_a["user_id"],
    )

    stored = _session_store[created["session_id"]]
    assert created["owner"] == tenant_a["user_id"]
    assert created["participant_token"]
    assert stored["owner"] == tenant_a["user_id"]
    assert stored["tenant_id"] == tenant_a["tenant_id"]
    assert stored["participants"][0]["user_id"] == tenant_a["user_id"]
    assert stored["participants"][0]["participant_token"] == created["participant_token"]


def test_join_requires_authenticated_matching_participant_and_tenant(
    test_client,
    tenant_a,
    tenant_a_auth_headers,
    tenant_b,
    tenant_b_auth_headers,
):
    created = _create_session(
        test_client,
        tenant_a_auth_headers,
        owner=tenant_a["user_id"],
    )
    same_tenant_headers = _auth_headers("user-a-002", tenant_a["tenant_id"])

    anonymous = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/join",
        json={"share_code": created["share_code"], "user_id": "user-a-002", "role": "manager"},
    )
    assert anonymous.status_code == 401

    forged = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/join",
        headers=same_tenant_headers,
        json={"share_code": created["share_code"], "user_id": "forged-user", "role": "manager"},
    )
    assert forged.status_code == 403

    cross_tenant = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/join",
        headers=tenant_b_auth_headers,
        json={"share_code": created["share_code"], "user_id": tenant_b["user_id"], "role": "manager"},
    )
    _assert_cross_tenant_denied(cross_tenant)

    valid = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/join",
        headers=same_tenant_headers,
        json={"share_code": created["share_code"], "user_id": "user-a-002", "role": "manager"},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["participant_token"]


def test_session_reads_require_membership_or_participant_proof(
    test_client,
    tenant_a,
    tenant_a_auth_headers,
    tenant_b_auth_headers,
):
    created = _create_session(
        test_client,
        tenant_a_auth_headers,
        owner=tenant_a["user_id"],
    )
    outsider_headers = _auth_headers("user-a-003", tenant_a["tenant_id"])
    second_session = _create_session(
        test_client,
        tenant_a_auth_headers,
        owner=tenant_a["user_id"],
        analysis_id="analysis-2",
    )

    anonymous = test_client.get(f"/api/collab/sessions/{created['session_id']}")
    assert anonymous.status_code == 401

    outsider = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        headers=outsider_headers,
    )
    assert outsider.status_code == 403

    cross_tenant = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        headers=tenant_b_auth_headers,
    )
    _assert_cross_tenant_denied(cross_tenant)

    wrong_token = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        params={"participant_token": second_session["participant_token"]},
    )
    assert wrong_token.status_code == 404

    valid = test_client.get(
        f"/api/collab/sessions/{created['session_id']}",
        params={"participant_token": created["participant_token"]},
    )
    assert valid.status_code == 200, valid.text
    participants = valid.json()["participants"]
    assert participants[0]["user_id"] == tenant_a["user_id"]
    assert "participant_token" not in participants[0]


def test_change_and_history_routes_reject_forgery_and_allow_valid_participant_flows(
    test_client,
    tenant_a,
    tenant_a_auth_headers,
    tenant_b,
    tenant_b_auth_headers,
):
    created = _create_session(
        test_client,
        tenant_a_auth_headers,
        owner=tenant_a["user_id"],
    )
    member_user_id = "user-a-002"
    member_headers = _auth_headers(member_user_id, tenant_a["tenant_id"])
    outsider_headers = _auth_headers("user-a-003", tenant_a["tenant_id"])

    joined = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/join",
        headers=member_headers,
        json={"share_code": created["share_code"], "user_id": member_user_id, "role": "security"},
    )
    assert joined.status_code == 200, joined.text
    member_token = joined.json()["participant_token"]

    forged = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        headers=member_headers,
        json={"user_id": tenant_a["user_id"], "change_type": "comment", "payload": {"text": "hi"}},
    )
    assert forged.status_code == 403

    outsider = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        headers=outsider_headers,
        json={"user_id": "user-a-003", "change_type": "comment", "payload": {"text": "hi"}},
    )
    assert outsider.status_code == 403

    cross_tenant = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        headers=tenant_b_auth_headers,
        json={"user_id": tenant_b["user_id"], "change_type": "comment", "payload": {"text": "hi"}},
    )
    _assert_cross_tenant_denied(cross_tenant)

    anonymous_no_proof = test_client.get(f"/api/collab/sessions/{created['session_id']}/changes")
    assert anonymous_no_proof.status_code == 401

    anonymous_forged = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        json={
            "user_id": tenant_a["user_id"],
            "participant_token": member_token,
            "change_type": "comment",
            "payload": {"text": "forged"},
        },
    )
    assert anonymous_forged.status_code == 403

    valid_authenticated = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        headers=member_headers,
        json={"user_id": member_user_id, "change_type": "comment", "payload": {"text": "hi"}},
    )
    assert valid_authenticated.status_code == 200, valid_authenticated.text

    valid_anonymous = test_client.post(
        f"/api/collab/sessions/{created['session_id']}/changes",
        json={
            "user_id": member_user_id,
            "participant_token": member_token,
            "change_type": "approval",
            "payload": {"approved": True},
        },
    )
    assert valid_anonymous.status_code == 200, valid_anonymous.text

    history = test_client.get(
        f"/api/collab/sessions/{created['session_id']}/changes",
        params={"participant_token": member_token},
    )
    assert history.status_code == 200, history.text
    payload = history.json()
    assert payload["total"] == 2
    assert [change["user_id"] for change in payload["changes"]] == [member_user_id, member_user_id]
