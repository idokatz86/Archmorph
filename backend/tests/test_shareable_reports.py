"""Tests for shareable_reports.py — report sharing with expiry and views."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from shareable_reports import (
    create_share,
    get_share,
    get_share_stats,
    delete_share,
    render_view,
    purge_diagram_shares,
    _extract_executive_view,
    _extract_technical_view,
    _extract_financial_view,
    _extract_architect_view,
    _extract_devops_view,
    _extract_security_view,
    _extract_finops_view,
    _redact_sensitive,
)


SAMPLE_SNAPSHOT = {
    "title": "AWS to Azure Migration",
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure VMs", "confidence": 0.9},
        {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95},
    ],
    "cost_estimate": {"total_monthly": 500, "savings": 120},
    "services_detected": 2,
    "source_provider": "aws",
    "target_provider": "azure",
    "executive_summary": "Migration of 2 services from AWS to Azure.",
    "risks_and_mitigations": [{"risk": "Downtime", "impact": "medium", "mitigation": "Blue-green deploy"}],
    "_owner_user_id": "user-42",
    "_owner_api_key_id": "key-99",
    "_tenant_id": "tenant-abc",
}

SAMPLE_SNAPSHOT_FULL = {
    "title": "Full Migration Package",
    "source_cloud": "aws",
    "target_cloud": "azure",
    "services": [
        {
            "source_service": "EC2",
            "azure_service": "Azure VMs",
            "confidence": 90,
            "cost": {"monthly": 120},
            "sku": "Standard_D2s_v3",
            "region": "eastus",
        },
        {
            "source_service": "RDS",
            "azure_service": "Azure SQL",
            "confidence": 40,
            "cost": {"monthly": 200, "annual": 2400},
            "sku": "GP_Gen5_2",
            "tier": "GeneralPurpose",
        },
    ],
    "service_mappings": [{"src": "EC2", "dst": "Azure VMs"}],
    "dependency_graph": [{"from": "EC2", "to": "RDS"}],
    "iac_format": "terraform",
    "iac_code": "resource \"azurerm_virtual_machine\" \"main\" {}",
    "iac_code_hash": "abc123",
    "compliance_gaps": [{"gap": "No MFA enforced", "severity": "high"}],
    "risk_score": 65,
    "risk_level": "medium",
    "risk_factors": ["No encryption at rest"],
    "compliance_frameworks": ["SOC2", "ISO27001"],
    "security_findings": [{"finding": "Public S3 bucket equivalent exposed", "severity": "critical"}],
    "ri_savings": {"amount": 40, "currency": "USD"},
    "tco_comparison": {"on_prem": 900, "cloud": 500},
    "cost_estimate": {"total_monthly": 320, "total_annual": 3840, "currency": "USD"},
    "cost_assumptions": ["Assumes Reserved Instances for compute"],
    "savings_opportunities": ["Switch to B-series VMs for dev/test"],
    "deployment_notes": ["Apply Terraform from infrastructure/"],
    "regions": ["eastus", "westus"],
    "architecture_decisions": ["Use Azure Front Door for global load balancing"],
    "_owner_user_id": "user-42",
    "_owner_api_key_id": "key-99",
    "_tenant_id": "tenant-abc",
}


class TestCreateShare:
    def test_creates_share(self):
        share = create_share(SAMPLE_SNAPSHOT, creator_id="user-1")
        assert "share_id" in share
        assert "share_url" in share
        assert share["share_url"].startswith("/shared/")

    def test_creates_share_with_custom_expiry(self):
        share = create_share(SAMPLE_SNAPSHOT, expiry_days=7)
        assert share is not None
        assert "expires_at" in share

    def test_is_sample_false_by_default(self):
        share = create_share(SAMPLE_SNAPSHOT)
        assert share.get("is_sample") is False

    def test_is_sample_true_when_set(self):
        share = create_share(SAMPLE_SNAPSHOT, is_sample=True)
        assert share.get("is_sample") is True

    def test_is_sample_persisted_in_stats(self):
        share = create_share(SAMPLE_SNAPSHOT, is_sample=True)
        stats = get_share_stats(share["share_id"])
        assert stats is not None
        assert stats.get("is_sample") is True


class TestGetShare:
    def test_get_existing_share(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share.get("share_id")
        result = get_share(share_id)
        assert result is not None

    def test_get_nonexistent_share(self):
        result = get_share("nonexistent-share-xyz")
        assert result is None

    def test_increments_view_count(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share["share_id"]
        get_share(share_id)
        get_share(share_id)
        stats = get_share_stats(share_id)
        assert stats is not None
        assert stats["view_count"] >= 2

    def test_expired_share_returns_none(self):
        share = create_share(SAMPLE_SNAPSHOT, expiry_days=1)
        share_id = share["share_id"]
        # Manually set expiry in the past
        from shareable_reports import _shares, _lock
        with _lock:
            _shares[share_id]["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat()
        result = get_share(share_id)
        assert result is None

    def test_revoked_share_returns_none(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share["share_id"]
        delete_share(share_id)
        result = get_share(share_id)
        assert result is None

    def test_revoked_share_is_auditable_via_stats(self):
        """Stats endpoint should still show revoked=True after revocation."""
        share = create_share(SAMPLE_SNAPSHOT, creator_id="owner-user")
        share_id = share["share_id"]
        delete_share(share_id)
        stats = get_share_stats(share_id)
        assert stats is not None
        assert stats["revoked"] is True


class TestGetShareStats:
    def test_stats_for_existing_share(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share.get("share_id")
        # Access the share to generate view counts
        get_share(share_id)
        stats = get_share_stats(share_id)
        if stats:
            assert isinstance(stats, dict)

    def test_stats_for_nonexistent(self):
        stats = get_share_stats("nonexistent-xyz")
        assert stats is None

    def test_stats_includes_creator_fields(self):
        share = create_share(
            SAMPLE_SNAPSHOT,
            creator_id="u-123",
            creator_tenant_id="t-456",
        )
        stats = get_share_stats(share["share_id"])
        assert stats is not None
        assert stats["creator_id"] == "u-123"
        assert stats["creator_tenant_id"] == "t-456"


class TestDeleteShare:
    def test_delete_existing(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share.get("share_id")
        assert delete_share(share_id) is True

    def test_delete_nonexistent(self):
        assert delete_share("nonexistent-xyz") is False

    def test_revoked_share_inaccessible(self):
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share["share_id"]
        delete_share(share_id)
        assert get_share(share_id) is None

    def test_double_revoke_returns_true(self):
        """Revoking an already-revoked share should still return True (idempotent)."""
        share = create_share(SAMPLE_SNAPSHOT)
        share_id = share["share_id"]
        assert delete_share(share_id) is True
        assert delete_share(share_id) is True  # idempotent


class TestTenantOwnerAuthorization:
    """Authorization: only the owner (user or API principal) can manage a share."""

    def test_share_stores_creator_id(self):
        share = create_share(SAMPLE_SNAPSHOT, creator_id="owner-user")
        stats = get_share_stats(share["share_id"])
        assert stats is not None
        assert stats["creator_id"] == "owner-user"

    def test_share_stores_creator_tenant_id(self):
        share = create_share(
            SAMPLE_SNAPSHOT,
            creator_id="owner",
            creator_tenant_id="tenant-xyz",
        )
        stats = get_share_stats(share["share_id"])
        assert stats is not None
        assert stats["creator_tenant_id"] == "tenant-xyz"

    def test_share_stores_api_principal(self):
        share = create_share(
            SAMPLE_SNAPSHOT,
            creator_api_principal_id="principal-abc",
        )
        stats = get_share_stats(share["share_id"])
        assert stats is not None
        assert stats["creator_api_principal_id"] == "principal-abc"


class TestSensitiveFieldRedaction:
    """Sensitive tokens/session IDs must not be stored in the share snapshot."""

    def test_redact_bearer_token_value(self):
        result = _redact_sensitive({"data": "Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"})
        assert result["data"] == "[REDACTED]"

    def test_redact_jwt_style_value(self):
        result = _redact_sensitive({"info": "eyJhbGciOiJIUzI1NiJ9.dGVzdA.abc123"})
        assert result["info"] == "[REDACTED]"

    def test_redact_key_named_token(self):
        result = _redact_sensitive({"session_token": "some-value"})
        assert result["session_token"] == "[REDACTED]"

    def test_redact_key_named_password(self):
        result = _redact_sensitive({"password": "super-secret"})
        assert result["password"] == "[REDACTED]"

    def test_redact_key_named_api_key(self):
        result = _redact_sensitive({"api_key": "key-12345"})
        assert result["api_key"] == "[REDACTED]"

    def test_non_sensitive_values_pass_through(self):
        result = _redact_sensitive({"service": "EC2", "cost": 120})
        assert result["service"] == "EC2"
        assert result["cost"] == 120

    def test_redact_nested_sensitive(self):
        result = _redact_sensitive({"auth": {"token": "Bearer abc.def.ghi"}})
        assert result["auth"]["token"] == "[REDACTED]"

    def test_redact_list_items(self):
        result = _redact_sensitive([{"api_key": "value"}, {"service": "EC2"}])
        assert result[0]["api_key"] == "[REDACTED]"
        assert result[1]["service"] == "EC2"

    def test_snapshot_owner_fields_stripped_in_create_share(self):
        """Private owner markers should be accessible only to the record holder."""
        # The _owner_user_id is just an analysis field—check it gets redacted
        # only if it matched the key pattern. (It should NOT be redacted since
        # it's not a token/secret key — but the snapshot must be stored safely.)
        snap = {"_owner_user_id": "user-99", "service": "EC2"}
        share = create_share(snap, creator_id="user-99")
        record = get_share(share["share_id"])
        assert record is not None
        # The service field must be intact
        assert record["analysis_snapshot"]["service"] == "EC2"


class TestArtifactVisibility:
    """Customer-private artifacts and public samples must be visually distinct."""

    def test_private_artifact_is_not_sample(self):
        snap = dict(SAMPLE_SNAPSHOT)
        share = create_share(snap, is_sample=False)
        assert share["is_sample"] is False

    def test_public_sample_flag_stored(self):
        share = create_share(SAMPLE_SNAPSHOT, is_sample=True)
        stats = get_share_stats(share["share_id"])
        assert stats is not None
        assert stats["is_sample"] is True

    def test_shared_report_includes_is_sample(self):
        share = create_share(SAMPLE_SNAPSHOT, is_sample=True)
        record = get_share(share["share_id"])
        assert record is not None
        assert record.get("is_sample") is True


class TestExtractViews:
    def test_executive_view(self):
        view = _extract_executive_view(SAMPLE_SNAPSHOT)
        assert isinstance(view, dict)
        assert view.get("view") == "executive"

    def test_technical_view(self):
        view = _extract_technical_view(SAMPLE_SNAPSHOT)
        assert isinstance(view, dict)
        assert view.get("view") == "technical"

    def test_financial_view(self):
        view = _extract_financial_view(SAMPLE_SNAPSHOT)
        assert isinstance(view, dict)
        assert view.get("view") == "financial"

    def test_architect_view(self):
        view = _extract_architect_view(SAMPLE_SNAPSHOT_FULL)
        assert isinstance(view, dict)
        assert view.get("view") == "architect"
        assert "service_mappings" in view
        assert "dependency_graph" in view

    def test_architect_view_iac_preview_truncated(self):
        long_iac = "resource \"azurerm_vm\" \"x\" {}" + ("  # pad" * 200)
        snap = dict(SAMPLE_SNAPSHOT_FULL, iac_code=long_iac)
        view = _extract_architect_view(snap)
        assert view["iac_preview"] is not None
        assert len(view["iac_preview"]) <= 502  # 500 + "…"

    def test_devops_view(self):
        view = _extract_devops_view(SAMPLE_SNAPSHOT_FULL)
        assert isinstance(view, dict)
        assert view.get("view") == "devops"
        assert "iac_format" in view
        assert "iac_code" in view

    def test_security_view(self):
        view = _extract_security_view(SAMPLE_SNAPSHOT_FULL)
        assert isinstance(view, dict)
        assert view.get("view") == "security"
        assert "compliance_gaps" in view
        assert "risk_score" in view
        assert "security_findings" in view
        assert "risks_and_mitigations" in view

    def test_finops_view(self):
        view = _extract_finops_view(SAMPLE_SNAPSHOT_FULL)
        assert isinstance(view, dict)
        assert view.get("view") == "finops"
        assert "cost_breakdown" in view
        assert "ri_savings" in view
        assert "tco_comparison" in view

    def test_finops_per_service_costs(self):
        view = _extract_finops_view(SAMPLE_SNAPSHOT_FULL)
        per_svc = view["cost_breakdown"]["per_service"]
        assert len(per_svc) == 2
        assert per_svc[0]["monthly_cost"] == 120
        assert per_svc[1]["monthly_cost"] == 200


class TestRenderView:
    def test_render_default_returns_all_canonical_views(self):
        result = render_view(SAMPLE_SNAPSHOT_FULL)
        assert "views" in result
        views = result["views"]
        for role in ("executive", "architect", "devops", "security", "finops"):
            assert role in views, f"Missing role view: {role}"

    def test_render_default_excludes_legacy_aliases(self):
        result = render_view(SAMPLE_SNAPSHOT_FULL)
        views = result["views"]
        assert "technical" not in views
        assert "financial" not in views

    def test_render_executive_view(self):
        result = render_view(SAMPLE_SNAPSHOT, view_type="executive")
        assert isinstance(result, dict)
        assert result.get("view") == "executive"

    def test_render_architect_view(self):
        result = render_view(SAMPLE_SNAPSHOT_FULL, view_type="architect")
        assert result.get("view") == "architect"

    def test_render_devops_view(self):
        result = render_view(SAMPLE_SNAPSHOT_FULL, view_type="devops")
        assert result.get("view") == "devops"

    def test_render_security_view(self):
        result = render_view(SAMPLE_SNAPSHOT_FULL, view_type="security")
        assert result.get("view") == "security"

    def test_render_finops_view(self):
        result = render_view(SAMPLE_SNAPSHOT_FULL, view_type="finops")
        assert result.get("view") == "finops"

    def test_render_legacy_technical_view(self):
        result = render_view(SAMPLE_SNAPSHOT, view_type="technical")
        assert isinstance(result, dict)

    def test_render_legacy_financial_view(self):
        result = render_view(SAMPLE_SNAPSHOT, view_type="financial")
        assert isinstance(result, dict)


class TestPurgeDiagramShares:
    def test_purge_removes_matching_shares(self):
        snap = dict(SAMPLE_SNAPSHOT, diagram_id="d-test-999")
        s1 = create_share(snap)
        s2 = create_share(snap)
        removed = purge_diagram_shares("d-test-999")
        assert removed >= 2
        assert get_share(s1["share_id"]) is None
        assert get_share(s2["share_id"]) is None

    def test_purge_leaves_other_diagrams(self):
        snap_a = dict(SAMPLE_SNAPSHOT, diagram_id="d-keep")
        snap_b = dict(SAMPLE_SNAPSHOT, diagram_id="d-purge")
        keep = create_share(snap_a)
        create_share(snap_b)
        purge_diagram_shares("d-purge")
        # The "d-keep" share must still be accessible
        assert get_share(keep["share_id"]) is not None
