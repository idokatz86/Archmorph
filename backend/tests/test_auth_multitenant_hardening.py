import base64

from auth import AuthProvider, User, UserTier, generate_session_token
from job_queue import job_manager
from routers.shared import MAX_UPLOAD_SIZE


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


def test_jobs_and_fail_closed_dependency_require_auth(test_client):
    secured_job = job_manager.submit(
        "test-secure",
        diagram_id="d-secure",
        owner_user_id="jobs-owner",
        tenant_id="tenant-jobs",
    )
    assert test_client.get(f"/api/jobs/{secured_job.job_id}").status_code == 401
    assert test_client.get("/api/models").status_code == 401
