"""Regression tests for sensitive hardening controls."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent


def test_auth_fails_closed_when_environment_production_without_jwt_secret():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["ENVIRONMENT"] = "production"
    env.pop("ENV", None)
    env.pop("JWT_SECRET", None)

    result = subprocess.run(
        [sys.executable, "-c", "import auth"],
        cwd=BACKEND_DIR,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "JWT_SECRET environment variable must be set" in result.stderr


def test_front_door_waf_rate_limit_matches_all_without_negation():
    terraform = (REPO_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")
    marker = 'name     = "RateLimitPerIP"'
    start = terraform.index(marker)
    end = terraform.index('# Block known bad user agents', start)
    block = terraform[start:end]

    assert 'operator       = "IPMatch"' in block or 'operator           = "IPMatch"' in block
    assert 'match_values   = ["0.0.0.0/0", "::/0"]' in block or 'match_values       = ["0.0.0.0/0", "::/0"]' in block
    assert "negation_condition" not in block


def test_sensitive_artifact_and_session_routes_require_api_key_dependency():
    from main import app
    from routers.shared import verify_api_key

    protected_routes = {
        ("/api/diagrams/{diagram_id}/versions", "GET"),
        ("/api/diagrams/{diagram_id}/versions", "POST"),
        ("/api/diagrams/{diagram_id}/versions/save", "POST"),
        ("/api/diagrams/{diagram_id}/versions/{version}", "GET"),
        ("/api/diagrams/{diagram_id}/versions/{version}/branch", "POST"),
        ("/api/diagrams/{diagram_id}/versions/{version_number}", "GET"),
        ("/api/diagrams/{diagram_id}/versions/{version_number}/restore", "POST"),
        ("/api/diagrams/{diagram_id}/versions/compare", "GET"),
        ("/api/diagrams/{diagram_id}/diff", "GET"),
        ("/api/diagrams/{diagram_id}/share", "POST"),
        ("/api/shared/{share_id}/stats", "GET"),
        ("/api/shared/{share_id}", "DELETE"),
        ("/api/chat/history/{session_id}", "GET"),
        ("/api/chat/{session_id}", "DELETE"),
        ("/api/diagrams/{diagram_id}/iac-chat/history", "GET"),
        ("/api/diagrams/{diagram_id}/iac-chat", "DELETE"),
        ("/api/diagrams/{diagram_id}/cost-estimate", "GET"),
        ("/api/diagrams/{diagram_id}/cost-breakdown", "GET"),
        ("/api/diagrams/{diagram_id}/cost-optimization", "GET"),
    }

    matched = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        route_keys = {(path, method) for method in methods if (path, method) in protected_routes}
        if not route_keys:
            continue
        dependency_callables = {dep.call for dep in route.dependant.dependencies}
        assert verify_api_key in dependency_callables, f"{path} {methods} must require API key"
        matched.update(route_keys)

    assert matched == protected_routes


def test_admin_execution_routes_require_admin_bearer_dependency():
    from main import app
    from routers.shared import verify_admin_key

    admin_routes = {
        ("/api/deploy/execute/{project_id}", "POST"),
        ("/api/admin/suggestions/queue", "GET"),
        ("/api/admin/suggestions/{suggestion_id}/review", "POST"),
        ("/api/admin/suggestions/generate", "POST"),
        ("/api/admin/suggestions/generate/batch", "POST"),
        ("/api/admin/suggestions/pending", "GET"),
        ("/api/admin/suggestions/history", "GET"),
        ("/api/admin/suggestions/stats", "GET"),
    }

    matched = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        route_keys = {(path, method) for method in methods if (path, method) in admin_routes}
        if not route_keys:
            continue
        dependency_callables = {dep.call for dep in route.dependant.dependencies}
        assert verify_admin_key in dependency_callables, f"{path} {methods} must require admin bearer"
        matched.update(route_keys)

    assert matched == admin_routes


def test_creator_owned_share_stats_requires_matching_user_identity(monkeypatch):
    from main import app
    import routers.share_routes as share_routes
    import routers.shared as shared_router

    monkeypatch.setattr(shared_router, "API_KEY", "test-api-key")
    monkeypatch.setattr(
        share_routes.shareable_reports,
        "get_share_stats",
        lambda share_id: {"share_id": share_id, "creator_id": "owner-1", "view_count": 0},
    )
    monkeypatch.setattr(share_routes, "get_user_from_request_headers", lambda headers: None)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/shared/share-1/stats", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 403


def test_creator_owned_share_stats_allows_matching_user_identity(monkeypatch):
    from main import app
    import routers.share_routes as share_routes
    import routers.shared as shared_router

    monkeypatch.setattr(shared_router, "API_KEY", "test-api-key")
    monkeypatch.setattr(
        share_routes.shareable_reports,
        "get_share_stats",
        lambda share_id: {"share_id": share_id, "creator_id": "owner-1", "view_count": 0},
    )
    monkeypatch.setattr(
        share_routes,
        "get_user_from_request_headers",
        lambda headers: SimpleNamespace(id="owner-1"),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/shared/share-1/stats", headers={"X-API-Key": "test-api-key"})

    assert response.status_code == 200
    assert response.json()["creator_id"] == "owner-1"


def test_authenticated_sync_analysis_persists_owner_metadata_before_session_write():
    from auth import AuthProvider, User, UserTier, generate_session_token
    from main import IMAGE_STORE, SESSION_STORE, app

    diagram_id = "owner-metadata-diagram"
    IMAGE_STORE.clear()
    SESSION_STORE.clear()
    IMAGE_STORE[diagram_id] = (b"fake-image-bytes", "image/png")

    user = User(
        id="owner-123",
        email="owner@example.test",
        name="Owner",
        provider=AuthProvider.GITHUB,
        tier=UserTier.FREE,
        tenant_id="tenant-owner",
    )
    headers = {"Authorization": f"Bearer {generate_session_token(user)}"}
    analysis = {
        "diagram_type": "Test",
        "source_provider": "aws",
        "target_provider": "azure",
        "architecture_patterns": [],
        "services_detected": 1,
        "zones": [],
        "mappings": [
            {
                "source_service": "RDS",
                "source_provider": "aws",
                "azure_service": "Azure SQL",
                "confidence": 0.9,
            }
        ],
        "warnings": [],
        "confidence_summary": {"high": 1, "medium": 0, "low": 0, "average": 0.9},
    }
    classification = {
        "is_architecture_diagram": True,
        "confidence": 0.95,
        "image_type": "architecture_diagram",
        "reason": "test",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        with patch("routers.diagrams.classify_image", return_value=classification), patch(
            "routers.diagrams.analyze_image", return_value=analysis
        ):
            response = client.post(f"/api/diagrams/{diagram_id}/analyze", headers=headers)

    assert response.status_code == 200, response.text
    stored = SESSION_STORE[diagram_id]
    assert stored["_owner_user_id"] == "owner-123"
    assert stored["_tenant_id"] == "tenant-owner"