"""
Tests for the feature flags module and API routes.
"""

import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ── Unit tests for FeatureFlags core ─────────────────────────


class TestFeatureFlagsCore:
    """Tests for the FeatureFlags class logic."""

    def _make_fresh(self):
        """Create a fresh FeatureFlags instance (bypass singleton)."""
        from feature_flags import FeatureFlags
        return FeatureFlags()

    def test_default_flags_loaded(self):
        ff = self._make_fresh()
        flags = ff.get_all()
        assert "new_ai_model" in flags
        assert "roadmap_v2" in flags
        assert "export_pptx" in flags
        assert "dark_mode" in flags
        assert "deploy_engine" in flags
        assert "living_architecture_drift" in flags
        assert "live_cloud_scanner" in flags
        assert "enterprise_sso_scim" in flags

    def test_default_values(self):
        ff = self._make_fresh()
        assert ff.is_enabled("new_ai_model") is False
        assert ff.is_enabled("roadmap_v2") is False
        assert ff.is_enabled("export_pptx") is True
        assert ff.is_enabled("dark_mode") is True
        assert ff.is_enabled("deploy_engine") is False
        assert ff.is_enabled("living_architecture_drift") is False
        assert ff.is_enabled("live_cloud_scanner") is False
        assert ff.is_enabled("enterprise_sso_scim") is False

    def test_unknown_flag_returns_false(self):
        ff = self._make_fresh()
        assert ff.is_enabled("nonexistent_flag") is False

    def test_update_flag_enable(self):
        ff = self._make_fresh()
        assert ff.is_enabled("new_ai_model") is False
        ff.update_flag("new_ai_model", {"enabled": True})
        assert ff.is_enabled("new_ai_model") is True

    def test_update_flag_disable(self):
        ff = self._make_fresh()
        assert ff.is_enabled("dark_mode") is True
        ff.update_flag("dark_mode", {"enabled": False})
        assert ff.is_enabled("dark_mode") is False

    def test_update_nonexistent_flag_returns_none(self):
        ff = self._make_fresh()
        result = ff.update_flag("does_not_exist", {"enabled": True})
        assert result is None

    def test_get_flag(self):
        ff = self._make_fresh()
        flag = ff.get_flag("export_pptx")
        assert flag is not None
        assert flag["name"] == "export_pptx"
        assert flag["enabled"] is True

    def test_get_flag_nonexistent(self):
        ff = self._make_fresh()
        assert ff.get_flag("nope") is None

    def test_create_flag(self):
        ff = self._make_fresh()
        result = ff.create_flag("beta_feature", enabled=True, description="Beta")
        assert result["name"] == "beta_feature"
        assert result["enabled"] is True
        assert ff.is_enabled("beta_feature") is True

    def test_percentage_rollout_user_deterministic(self):
        ff = self._make_fresh()
        ff.update_flag("dark_mode", {"enabled": True, "rollout_percentage": 50})
        # Same user always gets same result
        r1 = ff.is_enabled("dark_mode", user="user-abc")
        r2 = ff.is_enabled("dark_mode", user="user-abc")
        assert r1 == r2

    def test_percentage_rollout_zero_blocks_all(self):
        ff = self._make_fresh()
        ff.update_flag("dark_mode", {"enabled": True, "rollout_percentage": 0})
        # With 0% rollout, no user should get the flag
        for i in range(20):
            assert ff.is_enabled("dark_mode", user=f"user-{i}") is False

    def test_percentage_rollout_hundred_allows_all(self):
        ff = self._make_fresh()
        ff.update_flag("new_ai_model", {"enabled": True, "rollout_percentage": 100})
        for i in range(20):
            assert ff.is_enabled("new_ai_model", user=f"user-{i}") is True

    def test_user_targeting(self):
        ff = self._make_fresh()
        ff.update_flag("new_ai_model", {
            "enabled": True,
            "rollout_percentage": 0,  # 0% rollout
            "target_users": ["vip-user"],
        })
        assert ff.is_enabled("new_ai_model", user="vip-user") is True
        assert ff.is_enabled("new_ai_model", user="random-user") is False

    @patch.dict(os.environ, {"ENVIRONMENT": "staging"})
    def test_environment_targeting_match(self):
        from feature_flags import FeatureFlags
        with patch("feature_flags.ENVIRONMENT", "staging"):
            ff = FeatureFlags()
            ff.update_flag("new_ai_model", {
                "enabled": True,
                "target_environments": ["staging", "dev"],
            })
            assert ff.is_enabled("new_ai_model") is True

    @patch.dict(os.environ, {"ENVIRONMENT": "production"})
    def test_environment_targeting_no_match(self):
        from feature_flags import FeatureFlags
        # Need to reload with patched ENVIRONMENT
        with patch("feature_flags.ENVIRONMENT", "production"):
            ff = FeatureFlags()
            ff.update_flag("new_ai_model", {
                "enabled": True,
                "target_environments": ["staging"],
            })
            assert ff.is_enabled("new_ai_model") is False

    @patch.dict(os.environ, {"FEATURE_FLAG_NEW_AI_MODEL": "true"})
    def test_env_var_override(self):
        ff = self._make_fresh()
        assert ff.is_enabled("new_ai_model") is True

    @patch.dict(os.environ, {
        "FEATURE_FLAGS_JSON": json.dumps({
            "new_ai_model": {"enabled": True, "rollout_percentage": 25}
        })
    })
    def test_json_override(self):
        ff = self._make_fresh()
        flag = ff.get_flag("new_ai_model")
        assert flag["enabled"] is True
        assert flag["rollout_percentage"] == 25


# ── API route tests ──────────────────────────────────────────


class TestFeatureFlagsAPI:
    """Tests for the /api/flags endpoints."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        """Import app fresh and create test client."""
        from main import app
        self.client = TestClient(app)

    def test_list_flags(self):
        resp = self.client.get("/api/flags")
        assert resp.status_code == 200
        data = resp.json()
        assert "flags" in data
        assert "dark_mode" in data["flags"]

    def test_get_flag(self):
        resp = self.client.get("/api/flags/export_pptx")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "export_pptx"

    def test_get_flag_not_found(self):
        resp = self.client.get("/api/flags/nonexistent")
        assert resp.status_code == 404

    def test_update_flag_requires_auth(self):
        resp = self.client.patch("/api/flags/dark_mode", json={"enabled": False})
        # Should require admin auth (401 or 503 if not configured)
        assert resp.status_code in (401, 403, 503)

    def test_flags_list_contains_defaults(self):
        resp = self.client.get("/api/flags")
        flags = resp.json()["flags"]
        expected = {
            "new_ai_model",
            "roadmap_v2",
            "export_pptx",
            "dark_mode",
            "deploy_engine",
            "living_architecture_drift",
            "live_cloud_scanner",
            "enterprise_sso_scim",
        }
        assert expected.issubset(set(flags.keys()))
