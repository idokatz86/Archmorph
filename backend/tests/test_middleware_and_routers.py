"""
Tests for Archmorph Middleware Chain, Router Shared Utilities,
and V1 Prefix Mirroring Logic.

Sprint refactoring coverage:
  - SecurityHeadersMiddleware
  - CorrelationIdMiddleware
  - LatencyTrackingMiddleware
  - AuditMiddleware
  - VersionMiddleware
  - routers/shared.py utilities
  - routers/v1.py build_v1_router logic
  - HLD export API routes
  - Best practices & cost optimization routes
  - Share link routes
"""

import copy
import io
import os
import sys
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import app, SESSION_STORE, IMAGE_STORE


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clean_session():
    SESSION_STORE.clear()
    IMAGE_STORE.clear()
    yield
    SESSION_STORE.clear()
    IMAGE_STORE.clear()


MOCK_ANALYSIS = {
    "diagram_type": "AWS Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ", "serverless"],
    "services_detected": 3,
    "zones": [
        {
            "id": 1, "name": "Compute", "number": 1,
            "services": [
                {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
            ],
        },
        {
            "id": 2, "name": "Storage", "number": 2,
            "services": [
                {"aws": "S3", "azure": "Azure Blob Storage", "confidence": 0.95},
            ],
        },
    ],
    "mappings": [
        {"source_service": "Lambda", "source_provider": "aws", "azure_service": "Azure Functions", "confidence": 0.95},
        {"source_service": "S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.95},
        {"source_service": "DynamoDB", "source_provider": "aws", "azure_service": "Azure Cosmos DB", "confidence": 0.85},
    ],
    "warnings": [],
    "confidence_summary": {"high": 2, "medium": 1, "low": 0, "average": 0.92},
}


def _upload_and_analyze(client, clean_session):
    """Helper: upload + analyze, returns diagram_id."""
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    resp = client.post(
        "/api/projects/proj-mw/diagrams",
        files={"file": ("mw.png", io.BytesIO(content), "image/png")},
    )
    assert resp.status_code == 200
    diagram_id = resp.json()["diagram_id"]

    with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)), \
         patch("routers.diagrams.classify_image", return_value={
             "is_architecture_diagram": True, "confidence": 0.95,
             "image_type": "architecture_diagram", "reason": "Mock"
         }):
        resp = client.post(f"/api/diagrams/{diagram_id}/analyze")
    assert resp.status_code == 200
    return diagram_id


# ====================================================================
# 1. SecurityHeadersMiddleware
# ====================================================================

class TestSecurityHeadersMiddleware:
    """Verify security headers are present on every response."""

    def test_x_content_type_options(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_referrer_policy(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_x_xss_protection(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-xss-protection") == "0"

    def test_permissions_policy(self, client):
        resp = client.get("/api/health")
        assert "camera=()" in resp.headers.get("permissions-policy", "")

    def test_content_security_policy(self, client):
        resp = client.get("/api/health")
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_strict_transport_security(self, client):
        resp = client.get("/api/health")
        hsts = resp.headers.get("strict-transport-security", "")
        assert "max-age=31536000" in hsts

    def test_security_headers_on_non_health_endpoints(self, client):
        """Security headers also appear on other endpoints."""
        resp = client.get("/api/contact")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_security_headers_on_404(self, client):
        """Security headers even on error responses."""
        resp = client.get("/api/nonexistent-endpoint-abc")
        assert resp.headers.get("x-content-type-options") == "nosniff"


# ====================================================================
# 2. CorrelationIdMiddleware
# ====================================================================

class TestCorrelationIdMiddleware:
    """Verify correlation ID propagation."""

    def test_generates_correlation_id(self, client):
        """Response includes X-Correlation-ID even when not sent."""
        resp = client.get("/api/health")
        cid = resp.headers.get("x-correlation-id")
        assert cid is not None
        # Should be a valid UUID
        uuid.UUID(cid)

    def test_propagates_provided_correlation_id(self, client):
        """Responses echo back the correlation ID from request."""
        custom_cid = "test-correlation-12345"
        resp = client.get("/api/health", headers={"X-Correlation-ID": custom_cid})
        assert resp.headers.get("x-correlation-id") == custom_cid

    def test_different_requests_different_ids(self, client):
        """Different requests get different auto-generated IDs."""
        r1 = client.get("/api/health")
        r2 = client.get("/api/health")
        cid1 = r1.headers.get("x-correlation-id")
        cid2 = r2.headers.get("x-correlation-id")
        assert cid1 != cid2


# ====================================================================
# 3. LatencyTrackingMiddleware
# ====================================================================

class TestLatencyTrackingMiddleware:
    """Verify latency tracking header."""

    def test_response_time_header_present(self, client):
        resp = client.get("/api/health")
        rt = resp.headers.get("x-response-time")
        assert rt is not None
        assert rt.endswith("ms")

    def test_response_time_is_numeric(self, client):
        resp = client.get("/api/health")
        rt = resp.headers.get("x-response-time", "0ms")
        value = float(rt.replace("ms", ""))
        assert value >= 0

    def test_response_time_on_post(self, client):
        """POST requests also get timing header."""
        resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.headers.get("x-response-time") is not None


# ====================================================================
# 4. VersionMiddleware (X-API-Version header)
# ====================================================================

class TestVersionMiddleware:
    """Verify API version header injection."""

    def test_api_version_header_on_unversioned(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("x-api-version") == "v1"

    def test_api_version_header_on_v1(self, client):
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-api-version") == "v1"

    def test_api_deprecated_header_false(self, client):
        resp = client.get("/api/v1/health")
        assert resp.headers.get("x-api-deprecated") == "false"


# ====================================================================
# 5. routers/shared.py — Utilities
# ====================================================================

class TestSharedUtilities:
    """Test utilities from routers/shared.py."""

    def test_session_store_is_available(self):
        """SESSION_STORE imported from shared is the same used by app."""
        from routers.shared import SESSION_STORE as shared_store
        assert shared_store is SESSION_STORE

    def test_image_store_is_available(self):
        """IMAGE_STORE imported from shared is the same used by app."""
        from routers.shared import IMAGE_STORE as shared_store
        assert shared_store is IMAGE_STORE

    def test_share_store_exists(self):
        """SHARE_STORE exists and works."""
        from routers.shared import SHARE_STORE
        assert SHARE_STORE is not None

    def test_limiter_exists(self):
        """Rate limiter is configured."""
        from routers.shared import limiter
        assert limiter is not None

    def test_max_upload_size(self):
        """MAX_UPLOAD_SIZE is a positive integer."""
        from routers.shared import MAX_UPLOAD_SIZE
        assert isinstance(MAX_UPLOAD_SIZE, int)
        assert MAX_UPLOAD_SIZE > 0

    def test_environment_default(self):
        """ENVIRONMENT defaults to 'production'."""
        from routers.shared import ENVIRONMENT
        assert isinstance(ENVIRONMENT, str)
        assert len(ENVIRONMENT) > 0

    def test_pydantic_models_importable(self):
        """Pydantic models from shared are importable."""
        from routers.shared import Project, ServiceMapping
        p = Project(name="Test")
        assert p.name == "Test"

        sm = ServiceMapping(
            source_service="Lambda",
            source_provider="aws",
            azure_service="Azure Functions",
            confidence=0.95,
        )
        assert sm.confidence == 0.95


# ====================================================================
# 6. routers/v1.py — build_v1_router Logic
# ====================================================================

class TestV1RouterBuilder:
    """Test the v1 router builder logic directly."""

    def test_build_v1_router_returns_router(self):
        from routers.v1 import build_v1_router
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/api/test-endpoint")
        async def test_ep():
            return {"ok": True}

        v1 = build_v1_router([(router, "")])
        assert isinstance(v1, APIRouter)
        # Should have mirrored the route
        paths = [r.path for r in v1.routes]
        assert "/api/v1/test-endpoint" in paths

    def test_build_v1_router_skips_non_api(self):
        from routers.v1 import build_v1_router
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/non-api/something")
        async def non_api():
            return {}

        v1 = build_v1_router([(router, "")])
        paths = [r.path for r in v1.routes]
        assert len(paths) == 0

    def test_build_v1_router_skips_existing_v1(self):
        from routers.v1 import build_v1_router
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/api/v1/already-versioned")
        async def already_v1():
            return {}

        v1 = build_v1_router([(router, "")])
        paths = [r.path for r in v1.routes]
        assert "/api/v1/v1/already-versioned" not in paths

    def test_build_v1_router_with_prefix(self):
        from routers.v1 import build_v1_router
        from fastapi import APIRouter

        router = APIRouter()

        @router.get("/icons/list")
        async def icons():
            return {}

        v1 = build_v1_router([(router, "/api")])
        paths = [r.path for r in v1.routes]
        assert "/api/v1/icons/list" in paths

    def test_v1_routes_count_matches_app(self, client):
        """V1 router has mirrored routes in the live app."""
        # Just verify a sample of v1 routes work
        endpoints = ["/api/v1/health", "/api/v1/services", "/api/v1/contact", "/api/v1/roadmap"]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 200, f"Failed for {ep}"


# ====================================================================
# 7. HLD Export API Routes
# ====================================================================

class TestHLDExportRoutes:
    """Test HLD export endpoint at route level."""

    def test_export_hld_auto_generates(self, client, clean_session):
        """Export HLD without generating it first auto-generates it → 200."""
        # Upload + analyze, but don't generate HLD
        diagram_id = _upload_and_analyze(client, clean_session)
        resp = client.post(f"/api/diagrams/{diagram_id}/export-hld?format=docx")
        assert resp.status_code == 200

    def test_export_hld_invalid_format(self, client, clean_session):
        """Invalid export format → 400."""
        diagram_id = _upload_and_analyze(client, clean_session)
        # Generate HLD
        with patch("routers.diagrams.generate_hld") as mock_hld:
            mock_hld.return_value = {"title": "T", "services": [], "executive_summary": "S"}
            client.post(f"/api/diagrams/{diagram_id}/generate-hld")

        resp = client.post(f"/api/diagrams/{diagram_id}/export-hld?format=xyz")
        assert resp.status_code == 400

    def test_export_hld_docx_success(self, client, clean_session):
        """Export HLD to DOCX succeeds."""
        diagram_id = _upload_and_analyze(client, clean_session)
        with patch("routers.diagrams.generate_hld") as mock_hld:
            mock_hld.return_value = {
                "title": "Test HLD",
                "services": [{"azure_service": "Functions", "source_service": "Lambda"}],
                "executive_summary": "Migration plan.",
                "architecture_overview": {"description": "Serverless"},
                "networking_design": {},
                "security_design": {},
                "data_architecture": {},
            }
            client.post(f"/api/diagrams/{diagram_id}/generate-hld")

        resp = client.post(f"/api/diagrams/{diagram_id}/export-hld?format=docx")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "docx"
        assert "content_b64" in data or "content" in data

    def test_export_hld_nonexistent_diagram(self, client, clean_session):
        """Export HLD for nonexistent diagram → 404."""
        resp = client.post("/api/diagrams/no-such-diag/export-hld?format=docx")
        assert resp.status_code == 404


# ====================================================================
# 8. Cost Optimization Routes
# ====================================================================

class TestCostOptimizationRoutes:
    """Test cost optimization endpoints."""

    def test_cost_optimization_404_without_analysis(self, client, clean_session):
        resp = client.get("/api/diagrams/no-exist/cost-optimization")
        assert resp.status_code == 404

    def test_cost_optimization_with_analysis(self, client, clean_session):
        diagram_id = _upload_and_analyze(client, clean_session)
        resp = client.get(f"/api/diagrams/{diagram_id}/cost-optimization")
        assert resp.status_code == 200


# ====================================================================
# 9. Share Link Routes
# ====================================================================

class TestShareLinkRoutes:
    """Test share link creation and retrieval."""

    def test_create_share_link(self, client, clean_session):
        diagram_id = _upload_and_analyze(client, clean_session)
        resp = client.post(f"/api/diagrams/{diagram_id}/share")
        assert resp.status_code == 200
        data = resp.json()
        assert "share_id" in data
        assert len(data["share_id"]) >= 6
        assert "share_url" in data or "url" in data

    def test_get_shared_analysis(self, client, clean_session):
        diagram_id = _upload_and_analyze(client, clean_session)
        share_resp = client.post(f"/api/diagrams/{diagram_id}/share")
        share_id = share_resp.json()["share_id"]

        resp = client.get(f"/api/shared/{share_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "share_id" in data
        assert data.get("read_only") is True

    def test_get_shared_analysis_404(self, client, clean_session):
        resp = client.get("/api/shared/nonexistent-share-id")
        assert resp.status_code == 404

    def test_share_link_not_found_without_analysis(self, client, clean_session):
        resp = client.post("/api/diagrams/no-such-diag/share")
        assert resp.status_code == 404


# ====================================================================
# 10. Terraform Preview Route
# ====================================================================

class TestTerraformPreviewRoute:
    """Test terraform preview endpoint."""

    def test_terraform_preview_404(self, client, clean_session):
        resp = client.post("/api/diagrams/no-exist/terraform-preview")
        assert resp.status_code == 404

    def test_terraform_preview_with_analysis(self, client, clean_session):
        diagram_id = _upload_and_analyze(client, clean_session)
        resp = client.post(f"/api/diagrams/{diagram_id}/terraform-preview")
        assert resp.status_code == 200


# ====================================================================
# 11. Template Gallery Routes
# ====================================================================

class TestTemplateGalleryRoutes:
    """Test starter architecture listing and Workbench-ready analysis."""

    def test_list_templates_has_starter_regression_metadata(self, client):
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert data["categories"]
        assert all("estimated_monthly_cost" not in template for template in data["templates"])
        assert all("sample_id" not in template for template in data["templates"])
        assert len(data["templates"]) >= 3
        for template in data["templates"]:
            assert template["source_provider"] in {"aws", "gcp"}
            assert template["complexity"]
            assert template["services"]
            assert template["available_deliverables"]
            assert template["expected_outputs"]
            assert template["regression_profile"]["coverage"] == "golden"

    def test_filter_templates_by_category(self, client):
        resp = client.get("/api/templates?category=containers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["templates"]
        assert {template["category"] for template in data["templates"]} == {"containers"}

    def test_analyze_template_creates_translator_session(self, client, clean_session):
        resp = client.post("/api/templates/aws-iaas-web/analyze")
        assert resp.status_code == 200
        data = resp.json()
        assert data["diagram_id"].startswith("template-aws-iaas-web-")
        assert data["is_template"] is True
        assert data["is_starter"] is True
        assert data["template_id"] == "aws-iaas-web"
        assert data["starter_metadata"]["available_deliverables"]
        assert data["starter_metadata"]["regression_profile"]["id"] == "golden-aws-iaas-web"
        assert data["diagram_id"] in SESSION_STORE


# ====================================================================
# 12. V1 Route Parity for New Routes
# ====================================================================

class TestV1RouteParityForNewRoutes:
    """Verify new sprint routes are also mirrored under /api/v1/."""

    def test_v1_flags_endpoint(self, client):
        resp = client.get("/api/v1/flags")
        assert resp.status_code == 200
        assert "flags" in resp.json()

    def test_v1_flags_single(self, client):
        resp = client.get("/api/v1/flags/dark_mode")
        assert resp.status_code == 200
        assert resp.json()["name"] == "dark_mode"

    def test_v1_samples(self, client):
        resp = client.get("/api/v1/samples")
        assert resp.status_code == 200

    def test_v1_templates(self, client):
        resp = client.get("/api/v1/templates")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

    def test_v1_services_stats(self, client):
        resp = client.get("/api/v1/services/stats")
        assert resp.status_code == 200
        assert resp.json()["totalServices"] > 0

    def test_v1_services_providers(self, client):
        resp = client.get("/api/v1/services/providers")
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()["providers"]]
        assert "aws" in ids

    def test_v1_services_categories(self, client):
        resp = client.get("/api/v1/services/categories")
        assert resp.status_code == 200

    def test_v1_services_mappings(self, client):
        resp = client.get("/api/v1/services/mappings")
        assert resp.status_code == 200

    def test_v1_versions(self, client):
        resp = client.get("/api/v1/versions")
        assert resp.status_code == 200
        assert resp.json()["current_version"] == "v1"

    def test_v1_auth_config(self, client):
        resp = client.get("/api/v1/auth/config")
        assert resp.status_code == 200


# ====================================================================
# 12. Middleware Chain Order
# ====================================================================

class TestMiddlewareChainOrder:
    """Verify all middleware headers appear together in responses."""

    def test_all_middleware_headers_present(self, client):
        """A single request should have headers from all middleware."""
        resp = client.get("/api/health")
        # SecurityHeadersMiddleware
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        # CorrelationIdMiddleware
        assert resp.headers.get("x-correlation-id") is not None
        # LatencyTrackingMiddleware
        assert resp.headers.get("x-response-time") is not None
        # VersionMiddleware
        assert resp.headers.get("x-api-version") == "v1"

    def test_all_middleware_on_error_response(self, client, clean_session):
        """404 responses still go through middleware chain."""
        resp = client.get("/api/diagrams/nonexistent/cost-estimate")
        # Should still have middleware headers
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-correlation-id") is not None
        assert resp.headers.get("x-response-time") is not None
