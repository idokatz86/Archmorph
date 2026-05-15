"""
Tests for IaC optimistic concurrency / ETag protection (#858 / F-BUG-8).

Verifies that concurrent edits to the same diagram's IaC code are detected
server-side and return HTTP 409 instead of silently overwriting.
"""

import copy
import os
import sys
import time
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from fastapi.testclient import TestClient
from main import app, SESSION_STORE


SAMPLE_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ"],
    "services_detected": 2,
    "zones": [],
    "mappings": [
        {"source_service": "Lambda", "azure_service": "Azure Functions", "confidence": 0.95},
        {"source_service": "DynamoDB", "azure_service": "Azure Cosmos DB", "confidence": 0.85},
    ],
    "warnings": [],
    "confidence_summary": {"high": 1, "medium": 1, "low": 0, "average": 0.90},
}

MOCK_TERRAFORM_CODE = """
resource "azurerm_resource_group" "rg" {
  name     = "rg-test"
  location = "West Europe"
}
"""
STALE_TERRAFORM_CODE = 'resource "azurerm_resource_group" "stale" {}'


def _auth_headers(user_id: str = "iac-async-user", tenant_id: str = "tenant-iac-async") -> dict:
    from auth import AuthProvider, User, UserTier, generate_session_token

    user = User(
        id=user_id,
        email=f"{user_id}@example.com",
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant_id,
    )
    token = generate_session_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_session():
    SESSION_STORE.clear()
    yield
    SESSION_STORE.clear()


@pytest.fixture()
def diagram_with_analysis(client):
    """Seed a diagram session with a pre-populated analysis."""
    diagram_id = "test-concurrency-diag-001"
    SESSION_STORE[diagram_id] = copy.deepcopy(SAMPLE_ANALYSIS)
    return diagram_id


@pytest.fixture()
def owned_diagram_with_analysis(client):
    """Seed an authenticated diagram session for async job access checks."""
    diagram_id = "test-concurrency-diag-owned-001"
    session = copy.deepcopy(SAMPLE_ANALYSIS)
    session["_owner_user_id"] = "iac-async-user"
    session["_tenant_id"] = "tenant-iac-async"
    SESSION_STORE[diagram_id] = session
    return diagram_id


class TestIacEtagGeneration:
    """ETag is generated and returned after IaC generation."""

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_generate_iac_returns_etag_header(self, mock_gen, client, diagram_with_analysis):
        resp = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        assert resp.status_code == 200
        assert "etag" in resp.headers, "ETag header must be present after IaC generation"
        assert resp.headers["etag"], "ETag must not be empty"
        assert resp.json()["etag"] == resp.headers["etag"]

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_generate_iac_etag_is_deterministic_for_same_code(self, mock_gen, client, diagram_with_analysis):
        """Same code must always produce the same ETag."""
        resp1 = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        resp2 = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        assert resp1.headers["etag"] == resp2.headers["etag"]

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_generate_iac_stores_code_and_etag_in_session(self, mock_gen, client, diagram_with_analysis):
        """The session must carry the ETag after generation."""
        from routers.iac_routes import _IAC_ETAG_KEY
        client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        session = SESSION_STORE[diagram_with_analysis]
        assert _IAC_ETAG_KEY in session, "Session must store the IaC ETag"


class TestIacOptimisticConcurrency:
    """Concurrent edit detection via If-Match."""

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_matching_if_match_succeeds(self, mock_gen, client, diagram_with_analysis):
        """If-Match matching the stored ETag must succeed (200)."""
        # First generation — no If-Match required
        r1 = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        etag = r1.headers["etag"]

        # Second generation — correct If-Match → should succeed
        r2 = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
            headers={"If-Match": etag},
        )
        assert r2.status_code == 200

    def test_stale_if_match_returns_409(self, client, diagram_with_analysis):
        """If-Match with a stale ETag must return 409 (conflict).

        We directly inject a known ETag into the session to simulate a prior
        generation by Client A, then submit a request with a different (stale)
        ETag from Client B.  No real IaC generation is needed.
        """
        from routers.iac_routes import _IAC_ETAG_KEY, _compute_iac_etag

        # Simulate: Client A already generated code and stored its ETag
        current_etag = _compute_iac_etag("resource 'azurerm_rg' 'rg' { name = 'current' }")
        session = SESSION_STORE[diagram_with_analysis]
        session[_IAC_ETAG_KEY] = current_etag
        SESSION_STORE[diagram_with_analysis] = session

        # Client B holds a stale ETag from a previously-seen version
        stale_etag = _compute_iac_etag("resource 'azurerm_rg' 'rg' { name = 'stale' }")
        assert stale_etag != current_etag  # sanity

        r = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
            headers={"If-Match": stale_etag},
        )
        assert r.status_code == 409
        body = r.json()
        assert "iac_version_conflict" in str(body) or "conflict" in str(body).lower()

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_missing_if_match_with_no_prior_etag_succeeds(self, mock_gen, client, diagram_with_analysis):
        """First-time generation (no stored ETag) without If-Match must succeed."""
        r = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        assert r.status_code == 200

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_missing_if_match_with_prior_etag_succeeds(self, mock_gen, client, diagram_with_analysis):
        """Omitting If-Match even when a prior ETag exists must succeed (free regeneration)."""
        # First generation — establishes an ETag
        client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        # Regeneration without If-Match → still succeeds
        r2 = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
        )
        assert r2.status_code == 200

    def test_async_generate_with_stale_if_match_returns_409(self, client, owned_diagram_with_analysis):
        """Async generation must honor the same stale If-Match guard as sync generation."""
        from routers.iac_routes import _IAC_ETAG_KEY, _compute_iac_etag

        current_etag = _compute_iac_etag("current async canonical code")
        stale_etag = _compute_iac_etag("stale async canonical code")
        session = SESSION_STORE[owned_diagram_with_analysis]
        session[_IAC_ETAG_KEY] = current_etag
        SESSION_STORE[owned_diagram_with_analysis] = session

        response = client.post(
            f"/api/diagrams/{owned_diagram_with_analysis}/generate-async",
            params={"format": "terraform"},
            headers={**_auth_headers(), "If-Match": stale_etag},
        )

        assert response.status_code == 409
        assert current_etag in str(response.json())

    def test_409_body_includes_current_etag(self, client, diagram_with_analysis):
        """409 response body must include the current ETag for client recovery."""
        from routers.iac_routes import _IAC_ETAG_KEY, _compute_iac_etag

        # Plant a known ETag
        current_etag = _compute_iac_etag("resource 'azurerm_rg' 'rg' { name = 'latest' }")
        session = SESSION_STORE[diagram_with_analysis]
        session[_IAC_ETAG_KEY] = current_etag
        SESSION_STORE[diagram_with_analysis] = session

        r = client.post(
            f"/api/diagrams/{diagram_with_analysis}/generate",
            params={"format": "terraform"},
            headers={"If-Match": "stale-etag-not-matching"},
        )
        assert r.status_code == 409
        body = r.json()
        assert current_etag in str(body)

    def test_iac_chat_updates_stored_etag(self, client, diagram_with_analysis):
        """Successful chat mutations must refresh the canonical ETag."""
        from routers.iac_routes import _IAC_ETAG_KEY, _compute_iac_etag, _iac_code_hash

        initial_code = 'resource "azurerm_resource_group" "old" {}'
        updated_code = 'resource "azurerm_resource_group" "new" {}'
        session = SESSION_STORE[diagram_with_analysis]
        session["iac_code"] = initial_code
        session["iac_code_hash"] = _iac_code_hash(initial_code)
        session[_IAC_ETAG_KEY] = _compute_iac_etag(initial_code)
        SESSION_STORE[diagram_with_analysis] = session

        with patch("routers.iac_routes.process_iac_chat", return_value={"code": updated_code}):
            resp = client.post(
                f"/api/diagrams/{diagram_with_analysis}/iac-chat",
                json={
                    "message": "rename resource",
                    "code": initial_code,
                    "format": "terraform",
                    "code_hash": _iac_code_hash(initial_code),
                },
            )

        assert resp.status_code == 200
        assert resp.json()["etag"] == _compute_iac_etag(updated_code)
        assert SESSION_STORE[diagram_with_analysis][_IAC_ETAG_KEY] == _compute_iac_etag(updated_code)


class TestAsyncIacCanonicalState:
    """Async generation must persist canonical state for chat + concurrency checks."""

    @staticmethod
    def _wait_for_completion(client, job_id: str, headers: dict) -> dict:
        for _ in range(40):
            status_resp = client.get(f"/api/jobs/{job_id}", headers=headers)
            assert status_resp.status_code == 200
            job_status = status_resp.json()
            if job_status["status"] == "completed":
                return job_status
            time.sleep(0.05)
        pytest.fail(f"Async IaC job {job_id} did not complete in time")

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_async_generate_persists_canonical_code_hash_and_etag(
        self,
        mock_gen,
        client,
        owned_diagram_with_analysis,
    ):
        from routers.iac_routes import _IAC_ETAG_KEY, _compute_iac_etag, _iac_code_hash

        headers = _auth_headers()
        queued = client.post(
            f"/api/diagrams/{owned_diagram_with_analysis}/generate-async",
            params={"format": "terraform"},
            headers=headers,
        )
        assert queued.status_code == 202
        job_id = queued.json()["job_id"]

        job_status = self._wait_for_completion(client, job_id, headers)

        result = job_status["result"]
        expected_hash = _iac_code_hash(MOCK_TERRAFORM_CODE)
        expected_etag = _compute_iac_etag(MOCK_TERRAFORM_CODE)

        assert result["code"] == MOCK_TERRAFORM_CODE
        assert result["code_hash"] == expected_hash
        assert result["etag"] == expected_etag

        session = SESSION_STORE[owned_diagram_with_analysis]
        assert session["iac_code"] == MOCK_TERRAFORM_CODE
        assert session["iac_code_hash"] == expected_hash
        assert session["iac_format"] == "terraform"
        assert session[_IAC_ETAG_KEY] == expected_etag

    @patch("routers.iac_routes.generate_iac_code", return_value=MOCK_TERRAFORM_CODE)
    def test_async_result_drives_chat_hash_checks_and_if_match_conflicts(
        self,
        mock_gen,
        client,
        owned_diagram_with_analysis,
    ):
        from routers.iac_routes import _compute_iac_etag, _iac_code_hash

        headers = _auth_headers()
        queued = client.post(
            f"/api/diagrams/{owned_diagram_with_analysis}/generate-async",
            params={"format": "terraform"},
            headers=headers,
        )
        assert queued.status_code == 202
        job_id = queued.json()["job_id"]

        self._wait_for_completion(client, job_id, headers)

        stale_hash = _iac_code_hash(STALE_TERRAFORM_CODE)
        chat_resp = client.post(
            f"/api/diagrams/{owned_diagram_with_analysis}/iac-chat",
            headers=headers,
            json={
                "message": "add tags",
                "code": "client copy",
                "format": "terraform",
                "code_hash": stale_hash,
            },
        )
        assert chat_resp.status_code == 409

        stale_etag = _compute_iac_etag(STALE_TERRAFORM_CODE)
        generate_resp = client.post(
            f"/api/diagrams/{owned_diagram_with_analysis}/generate",
            params={"format": "terraform"},
            headers={**headers, "If-Match": stale_etag},
        )
        assert generate_resp.status_code == 409

    def test_async_completion_does_not_overwrite_newer_canonical_state(
        self,
        client,
        owned_diagram_with_analysis,
    ):
        from routers.iac_routes import _IAC_ETAG_KEY, _compute_iac_etag, _iac_code_hash

        headers = _auth_headers()
        newer_code = 'resource "azurerm_resource_group" "newer" {}'

        def generate_after_concurrent_update(*args, **kwargs):
            session = SESSION_STORE[owned_diagram_with_analysis]
            session["iac_code"] = newer_code
            session["iac_code_hash"] = _iac_code_hash(newer_code)
            session[_IAC_ETAG_KEY] = _compute_iac_etag(newer_code)
            SESSION_STORE[owned_diagram_with_analysis] = session
            return MOCK_TERRAFORM_CODE

        with patch("routers.iac_routes.generate_iac_code", side_effect=generate_after_concurrent_update):
            queued = client.post(
                f"/api/diagrams/{owned_diagram_with_analysis}/generate-async",
                params={"format": "terraform"},
                headers=headers,
            )
        assert queued.status_code == 202
        job_status = self._wait_for_completion(client, queued.json()["job_id"], headers)

        result = job_status["result"]
        assert result["code"] == MOCK_TERRAFORM_CODE
        assert result["canonical_state_persisted"] is False
        assert result["canonical_state_conflict"] is True
        assert result["current_etag"] == _compute_iac_etag(newer_code)

        session = SESSION_STORE[owned_diagram_with_analysis]
        assert session["iac_code"] == newer_code
        assert session["iac_code_hash"] == _iac_code_hash(newer_code)
        assert session[_IAC_ETAG_KEY] == _compute_iac_etag(newer_code)

    def test_async_completion_does_not_recreate_purged_session(
        self,
        client,
        owned_diagram_with_analysis,
    ):
        from routers.iac_routes import _iac_code_hash

        headers = _auth_headers()

        def generate_after_purge(*args, **kwargs):
            SESSION_STORE.delete(owned_diagram_with_analysis)
            return MOCK_TERRAFORM_CODE

        with patch("routers.iac_routes.generate_iac_code", side_effect=generate_after_purge):
            queued = client.post(
                f"/api/diagrams/{owned_diagram_with_analysis}/generate-async",
                params={"format": "terraform"},
                headers=headers,
            )
        assert queued.status_code == 202
        job_status = self._wait_for_completion(client, queued.json()["job_id"], headers)

        result = job_status["result"]
        assert result["code"] == MOCK_TERRAFORM_CODE
        assert result["code_hash"] == _iac_code_hash(MOCK_TERRAFORM_CODE)
        assert result["canonical_state_persisted"] is False
        assert result["canonical_state_conflict"] is True
        assert result["current_etag"] is None
        assert SESSION_STORE.get(owned_diagram_with_analysis) is None
