"""
Shared test fixtures for Archmorph backend tests.

Provides:
  - test_client: FastAPI TestClient (session-scoped)
  - mock_openai_response: reusable OpenAI mock
  - sample_diagram_data: standard analysis result for tests
  - auto-use timing fixture for slow-test detection
"""

import copy
import os
import sys
import time
from urllib.parse import urlparse
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Disable rate limiting for all tests
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "false")
os.environ.setdefault("ENVIRONMENT", "test")

from main import app  # noqa: E402
from routers import shared as shared_router  # noqa: E402


# ─────────────────────────────────────────────────────────────
# Session-scoped fixtures (expensive setup, created once)
# ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_client():
    """Session-scoped FastAPI TestClient — avoids repeated app startup."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ─────────────────────────────────────────────────────────────
# Sample data fixtures
# ─────────────────────────────────────────────────────────────

SAMPLE_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ", "serverless"],
    "services_detected": 3,
    "zones": [
        {
            "id": 1,
            "name": "Compute",
            "number": 1,
            "services": [
                {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
            ],
        },
        {
            "id": 2,
            "name": "Storage",
            "number": 2,
            "services": [
                {"aws": "S3", "azure": "Azure Blob Storage", "confidence": 0.95},
            ],
        },
    ],
    "mappings": [
        {
            "source_service": "Lambda",
            "source_provider": "aws",
            "azure_service": "Azure Functions",
            "confidence": 0.95,
            "notes": "Zone 1 – Compute",
        },
        {
            "source_service": "S3",
            "source_provider": "aws",
            "azure_service": "Azure Blob Storage",
            "confidence": 0.95,
            "notes": "Zone 2 – Storage",
        },
        {
            "source_service": "DynamoDB",
            "source_provider": "aws",
            "azure_service": "Azure Cosmos DB",
            "confidence": 0.85,
            "notes": "Zone 2 – Storage",
        },
    ],
    "warnings": [],
    "confidence_summary": {"high": 2, "medium": 1, "low": 0, "average": 0.92},
}


@pytest.fixture()
def sample_diagram_data():
    """Return a deep copy of a standard mock analysis result."""
    return copy.deepcopy(SAMPLE_ANALYSIS)


@pytest.fixture()
def mock_openai_response():
    """Return a factory that builds a mock OpenAI chat-completion response."""

    def _build(content: str = '{"result": "ok"}'):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = content
        return mock_resp

    return _build


TEST_API_KEY = "test-suite-api-key"


def _diagram_id_from_url(url: object) -> str | None:
    path = urlparse(str(url)).path
    prefixes = ("/api/diagrams/", "/api/v1/diagrams/")
    prefix = next((value for value in prefixes if path.startswith(value)), None)
    if prefix is None:
        return None
    suffix = path[len(prefix):]
    diagram_id = suffix.split("/", 1)[0]
    return diagram_id or None


def _has_owner_metadata(session: dict) -> bool:
    return bool(
        session.get("_owner_user_id")
        or session.get("_tenant_id")
        or session.get("_owner_api_key_id")
    )


def _auth_headers_for_session_owner(session: dict) -> dict[str, str] | None:
    owner_user_id = session.get("_owner_user_id")
    tenant_id = session.get("_tenant_id")
    if not owner_user_id or not tenant_id:
        return None

    from auth import AuthProvider, User, UserTier, generate_session_token

    user = User(
        id=owner_user_id,
        email=f"{owner_user_id}@example.test",
        name=owner_user_id,
        provider=AuthProvider.GITHUB,
        tier=UserTier.TEAM,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


@pytest.fixture(autouse=True)
def _default_diagram_route_api_key(request, monkeypatch):
    """Authenticate legacy diagram-route TestClient calls with a stable API principal."""

    if request.node.nodeid.endswith("test_owned_async_generation_requires_authenticated_user"):
        return

    original_request = TestClient.request

    def request_with_test_api_key(self, method, url, *args, **kwargs):
        diagram_id = _diagram_id_from_url(url)
        if diagram_id is not None:
            headers = dict(kwargs.pop("headers", None) or {})
            has_auth = any(key.lower() in {"authorization", "x-api-key"} for key in headers)
            if not has_auth:
                session = shared_router.SESSION_STORE.get(diagram_id)
                if isinstance(session, dict):
                    owner_headers = _auth_headers_for_session_owner(session)
                    if owner_headers:
                        headers.update(owner_headers)
                    else:
                        headers["X-API-Key"] = TEST_API_KEY
                        if not _has_owner_metadata(session):
                            session["_owner_api_key_id"] = shared_router.get_api_key_service_principal(
                                {"x-api-key": TEST_API_KEY}
                            )
                else:
                    headers["X-API-Key"] = TEST_API_KEY
            kwargs["headers"] = headers
        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "request", request_with_test_api_key)


# ─────────────────────────────────────────────────────────────
# Auto-use: Prevent live OpenAI calls via classify_image
# ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_classify_image():
    """Mock classify_image globally so tests do not hit the live OpenAI API."""
    from unittest.mock import patch
    
    mock_classification = {
        "is_architecture_diagram": True,
        "confidence": 0.95,
        "image_type": "architecture_diagram",
        "reason": "Mocked by auto fixture"
    }
    
    with patch("routers.diagrams.classify_image", return_value=mock_classification) as m:
        yield m

# ─────────────────────────────────────────────────────────────
# Auto-use: test timing (prints warnings for slow tests)
# ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _test_timer(request):
    """Record wall-clock time for every test; warn if > 2 s."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    if elapsed > 2.0:
        # Attach as a custom property so pytest-html / reporters can pick it up
        if hasattr(request.node, "user_properties"):
            request.node.user_properties.append(("duration_warning", f"{elapsed:.2f}s"))

@pytest.fixture(autouse=True)
def _global_openai_mock(request, monkeypatch):
    """
    Globally prevent live OpenAI calls by mocking cached_chat_completion.
    Test execution speed will dramatically improve and flakiness will drop.
    """
    if "test_gpt_cache.py" in request.node.nodeid:
        return
        
    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = '{"result": "mocked", "services": [], "hld": {"title": "Test HLD", "services": [], "executive_summary": "Test", "architecture_overview": {}}, "action": "none", "timeline": []}'
    
    # Needs a mock token count
    mock_resp.usage = MagicMock()
    mock_resp.usage.total_tokens = 42

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp

    # Make get_openai_client() return our mock by setting the singleton
    monkeypatch.setattr("openai_client._client", mock_client)
    
    # Also patch cached_chat_completion because people do `from openai_client import cached_chat_completion`
    monkeypatch.setattr("openai_client.cached_chat_completion", MagicMock(return_value=mock_resp))


# ─────────────────────────────────────────────────────────────
# Multi-tenant test fixtures (F-QA-5 / #841)
#
# Provides two independent tenant/user identities so tests can
# assert that cross-tenant access is denied without mutating
# production state.
# ─────────────────────────────────────────────────────────────

@pytest.fixture()
def tenant_a():
    """Return a stable dict representing Tenant A's identity context."""
    return {
        "org_id": "org-tenant-a",
        "tenant_id": "tenant-a",
        "org_name": "Tenant Alpha",
        "api_key": "test-key-tenant-a",
        "user_id": "user-a-001",
        "role": "owner",
    }


@pytest.fixture()
def tenant_b():
    """Return a stable dict representing Tenant B's identity context."""
    return {
        "org_id": "org-tenant-b",
        "tenant_id": "tenant-b",
        "org_name": "Tenant Beta",
        "api_key": "test-key-tenant-b",
        "user_id": "user-b-001",
        "role": "member",
    }


@pytest.fixture()
def user_a(tenant_a):
    """Alias for Tenant A's primary user — same as tenant_a fixture."""
    return tenant_a


@pytest.fixture()
def user_b(tenant_b):
    """Alias for Tenant B's primary user — same as tenant_b fixture."""
    return tenant_b


def _session_auth_headers(*, user_id: str, tenant_id: str) -> dict[str, str]:
    from auth import AuthProvider, User, UserTier, generate_session_token

    user = User(
        id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
        provider=AuthProvider.GITHUB,
        tier=UserTier.FREE,
        tenant_id=tenant_id,
    )
    return {"Authorization": f"Bearer {generate_session_token(user)}"}


@pytest.fixture()
def tenant_a_auth_headers(tenant_a):
    return _session_auth_headers(user_id=tenant_a["user_id"], tenant_id=tenant_a["tenant_id"])


@pytest.fixture()
def tenant_b_auth_headers(tenant_b):
    return _session_auth_headers(user_id=tenant_b["user_id"], tenant_id=tenant_b["tenant_id"])


def assert_cross_tenant_denied(response, *, allowed_codes=(403, 404)):
    """Assert that a cross-tenant access attempt was correctly denied.

    Accepts 403 Forbidden and 404 Not Found (to prevent information
    disclosure about the existence of a resource owned by another tenant).

    Usage::

        resp = client.get(f"/api/diagrams/{tenant_a_diagram_id}",
                  headers=tenant_b_auth_headers)
        assert_cross_tenant_denied(resp)
    """
    assert response.status_code in allowed_codes, (
        f"Expected cross-tenant request to be denied with {allowed_codes}, "
        f"got {response.status_code}: {response.text[:200]}"
    )
