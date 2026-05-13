"""Tests for the IaC architecture-blocker gate (Issue #610)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from main import app  # noqa: E402
from routers.shared import SESSION_STORE  # noqa: E402
from routers.iac_routes import _check_architecture_blockers  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def _put_session_with_blocker(diagram_id: str) -> None:
    SESSION_STORE.set(
        diagram_id,
        {
            "diagram_id": diagram_id,
            "identified_services": [
                {"name": "Azure Front Door"},
                {"name": "Azure Storage (SFTP)"},
            ],
            "service_connections": [
                {"from": "Azure Front Door", "to": "Azure Storage (SFTP)", "type": "SFTP"}
            ],
            "architecture_issues": [
                {
                    "rule_id": "front-door-sftp-storage-blocker",
                    "severity": "blocker",
                    "category": "protocol",
                    "title": "Front Door cannot front SFTP storage",
                    "message": "Front Door is HTTP/HTTPS-only.",
                    "remediation": "Use Public IP or VNet-integrated path.",
                    "docs_url": "https://learn.microsoft.com/azure/frontdoor/",
                    "affected_services": ["Azure Front Door", "Azure Storage (SFTP)"],
                    "source": "curated",
                }
            ],
            "architecture_issues_summary": {
                "blocker": 1,
                "warning": 0,
                "info": 0,
                "total": 1,
            },
        },
    )


def _put_session_without_blockers(diagram_id: str) -> None:
    SESSION_STORE.set(
        diagram_id,
        {
            "diagram_id": diagram_id,
            "identified_services": [{"name": "Azure App Service"}],
            "service_connections": [],
            "architecture_issues": [
                {
                    "rule_id": "info-rule",
                    "severity": "info",
                    "category": "tier-feature",
                    "title": "Just FYI",
                    "message": "An info note.",
                    "remediation": "n/a",
                    "docs_url": "https://learn.microsoft.com/",
                    "affected_services": [],
                    "source": "curated",
                }
            ],
            "architecture_issues_summary": {
                "blocker": 0,
                "warning": 0,
                "info": 1,
                "total": 1,
            },
        },
    )


def _put_session_with_warning_only(diagram_id: str) -> None:
    SESSION_STORE.set(
        diagram_id,
        {
            "diagram_id": diagram_id,
            "identified_services": [{"name": "Azure App Service"}],
            "service_connections": [],
            "architecture_issues": [
                {
                    "rule_id": "warn-rule",
                    "severity": "warning",
                    "category": "network-topology",
                    "title": "warn",
                    "message": "warning msg",
                    "remediation": "n/a",
                    "docs_url": "https://learn.microsoft.com/",
                    "affected_services": [],
                    "source": "curated",
                }
            ],
        },
    )


@pytest.fixture(autouse=True)
def _cleanup_session():
    seeded: list[str] = []
    yield seeded
    for did in seeded:
        try:
            SESSION_STORE.delete(did)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sync endpoint
# ---------------------------------------------------------------------------


class TestIaCGateSync:
    def test_blocker_refuses_generation(self, client, _cleanup_session):
        diagram_id = "test-blocker-refuses"
        _put_session_with_blocker(diagram_id)
        _cleanup_session.append(diagram_id)

        resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform")
        assert resp.status_code == 409, resp.text
        # Just make sure the rule id appears in the response body somewhere.
        assert "front-door-sftp-storage-blocker" in resp.text

    def test_force_true_bypasses_gate(self, client, _cleanup_session):
        diagram_id = "test-force-bypasses"
        _put_session_with_blocker(diagram_id)
        _cleanup_session.append(diagram_id)

        with patch("routers.iac_routes.generate_iac_code", return_value="# stubbed\n"):
            resp = client.post(
                f"/api/diagrams/{diagram_id}/generate?format=terraform&force=true"
            )
        assert resp.status_code == 200, resp.text
        assert "stubbed" in resp.json().get("code", "")

    def test_no_blockers_passes_through(self, client, _cleanup_session):
        diagram_id = "test-no-blockers"
        _put_session_without_blockers(diagram_id)
        _cleanup_session.append(diagram_id)

        with patch("routers.iac_routes.generate_iac_code", return_value="# ok\n"):
            resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform")
        assert resp.status_code == 200, resp.text

    def test_warning_severity_does_not_gate(self, client, _cleanup_session):
        diagram_id = "test-warning-only"
        _put_session_with_warning_only(diagram_id)
        _cleanup_session.append(diagram_id)

        with patch("routers.iac_routes.generate_iac_code", return_value="# ok\n"):
            resp = client.post(f"/api/diagrams/{diagram_id}/generate?format=terraform")
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Async endpoint
# ---------------------------------------------------------------------------


class TestIaCGateAsync:
    def test_async_blocker_refuses_generation(self, client, _cleanup_session):
        diagram_id = "test-async-blocker"
        _put_session_with_blocker(diagram_id)
        _cleanup_session.append(diagram_id)

        resp = client.post(
            f"/api/diagrams/{diagram_id}/generate-async?format=terraform"
        )
        assert resp.status_code == 409, resp.text

    def test_async_force_true_bypasses_gate(self, client, _cleanup_session):
        diagram_id = "test-async-force"
        _put_session_with_blocker(diagram_id)
        _cleanup_session.append(diagram_id)

        resp = client.post(
            f"/api/diagrams/{diagram_id}/generate-async?format=terraform&force=true"
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body.get("status") == "queued"
        assert body.get("job_id")


def test_force_override_log_sanitizes_diagram_and_rule_ids(caplog):
    session = {
        "architecture_issues": [
            {"severity": "blocker", "rule_id": "rule-1\nINJECT"},
            {"severity": "blocker", "rule_id": "rule-2\rINJECT"},
        ]
    }

    with caplog.at_level("WARNING", logger="routers.iac_routes"):
        _check_architecture_blockers("diag\r\nid", session, force=True)

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "\n" not in message
    assert "\r" not in message
    assert "diagid" in message
    assert "rule-1INJECT,rule-2INJECT" in message
