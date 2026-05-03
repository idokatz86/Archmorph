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
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Disable rate limiting for all tests
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHMORPH_EXPORT_CAPABILITY_REQUIRED", "false")

from main import app  # noqa: E402


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
