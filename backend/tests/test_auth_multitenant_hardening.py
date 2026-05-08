import base64
from urllib.parse import urlencode

from auth import AuthProvider, User, UserTier, generate_session_token
from job_queue import job_manager
from routers.shared import MAX_UPLOAD_SIZE
from routers.shared import SESSION_STORE


def _auth_headers(user_id: str, tenant_id: str) -> dict:
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant_id,
    )
    token = generate_session_token(user)
    return {"Authorization": f"Bearer {token}"}


def _session_token(user_id: str, tenant_id: str) -> str:
    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant_id,
    )
    return generate_session_token(user)


def test_restore_session_rejects_oversized_analysis(test_client):
    headers = _auth_headers("restore-user", "tenant-restore")
    payload = {
        "analysis": {
            "services_detected": 1,
            "mappings": [{"source_service": "s", "azure_service": "a"} for _ in range(201)],
        }
    }
    resp = test_client.post("/api/v1/diagrams/restore-oversized/restore-session", json=payload, headers=headers)
    assert resp.status_code == 413


def test_restore_session_rejects_oversized_image_base64(test_client):
    headers = _auth_headers("restore-user-img", "tenant-restore")
    oversized_bytes = b"x" * (MAX_UPLOAD_SIZE + 1)
    payload = {
        "analysis": {"services_detected": 1, "mappings": []},
        "image_base64": base64.b64encode(oversized_bytes).decode("ascii"),
    }
    resp = test_client.post("/api/v1/diagrams/restore-large-image/restore-session", json=payload, headers=headers)
    assert resp.status_code == 413


def test_tf_state_requires_authentication(test_client):
    assert test_client.get("/api/terraform/state/p1/dev").status_code == 401
    assert test_client.post("/api/terraform/state/p1/dev", json={}).status_code == 401
    assert test_client.request("LOCK", "/api/terraform/state/p1/dev", content="{}").status_code == 401
    assert test_client.request("UNLOCK", "/api/terraform/state/p1/dev", content="{}").status_code == 401
    assert test_client.post("/api/terraform/state/p1/dev/rollback").status_code == 401


def test_tf_state_owner_tenant_enforced_and_unlock_supported(test_client):
    owner_headers = _auth_headers("tf-owner", "tenant-tf-a")
    other_headers = _auth_headers("tf-other", "tenant-tf-b")
    state_url = "/api/terraform/state/proj-sec/dev"

    assert test_client.post(state_url, headers=owner_headers, json={"version": 4}).status_code == 200
    assert test_client.request("LOCK", state_url, headers=owner_headers, content='{"ID":"lock-1"}').status_code == 200
    assert test_client.request("UNLOCK", state_url, headers=owner_headers, content='{"ID":"lock-1"}').status_code == 200

    assert test_client.get(state_url, headers=other_headers).status_code == 403
    assert test_client.post(state_url, headers=other_headers, json={"version": 5}).status_code == 403
    assert test_client.request("LOCK", state_url, headers=other_headers, content='{"ID":"lock-2"}').status_code == 403
    assert test_client.request("UNLOCK", state_url, headers=other_headers, content='{"ID":"lock-2"}').status_code == 403
    assert test_client.post(f"{state_url}/rollback", headers=other_headers).status_code == 403


def test_tf_state_lock_keys_do_not_collide_on_underscores(test_client):
    headers = _auth_headers("tf-key-owner", "tenant-tf-key")
    first_url = "/api/terraform/state/a_b/c"
    second_url = "/api/terraform/state/a/b_c"

    assert test_client.request("LOCK", first_url, headers=headers, content='{"ID":"lock-first"}').status_code == 200
    assert test_client.request("LOCK", second_url, headers=headers, content='{"ID":"lock-second"}').status_code == 200

    assert test_client.post(first_url, headers=headers, json={"version": 1}, params={"ID": "lock-first"}).status_code == 200
    assert test_client.post(second_url, headers=headers, json={"version": 2}, params={"ID": "lock-second"}).status_code == 200


def test_jobs_and_fail_closed_dependency_require_auth(test_client):
    secured_job = job_manager.submit(
        "test-secure",
        diagram_id="d-secure",
        owner_user_id="jobs-owner",
        tenant_id="tenant-jobs",
    )
    assert test_client.get(f"/api/jobs/{secured_job.job_id}").status_code == 401
    assert test_client.get("/api/models").status_code == 401


def test_owned_async_generation_requires_authenticated_user(test_client):
    SESSION_STORE["owned-async-diagram"] = {
        "_owner_user_id": "async-owner",
        "_tenant_id": "tenant-async",
        "analysis": {"services_detected": 0, "mappings": []},
    }

    try:
        iac_resp = test_client.post("/api/diagrams/owned-async-diagram/generate-async")
        hld_resp = test_client.post("/api/diagrams/owned-async-diagram/generate-hld-async")
    finally:
        SESSION_STORE.delete("owned-async-diagram")

    assert iac_resp.status_code == 401
    assert hld_resp.status_code == 401


def test_job_mismatch_returns_404_and_stream_accepts_query_token(test_client):
    from routers.jobs import _stream_user_from_request
    from starlette.requests import Request

    secured_job = job_manager.submit(
        "test-secure-stream",
        diagram_id="d-secure-stream",
        owner_user_id="jobs-stream-owner",
        tenant_id="tenant-stream",
    )
    owner_token = _session_token("jobs-stream-owner", "tenant-stream")
    other_headers = _auth_headers("jobs-stream-other", "tenant-stream")

    assert test_client.get(f"/api/jobs/{secured_job.job_id}", headers=other_headers).status_code == 404
    request = Request({
        "type": "http",
        "method": "GET",
        "path": f"/api/jobs/{secured_job.job_id}/stream",
        "headers": [],
        "query_string": urlencode({"token": owner_token}).encode("ascii"),
    })
    assert _stream_user_from_request(request).id == "jobs-stream-owner"
