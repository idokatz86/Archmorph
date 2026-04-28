"""Tests for release-gated scaffold surfaces."""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from feature_flags import get_feature_flags
from main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_risky_flags():
    flags = get_feature_flags()
    for name in ("deploy_engine", "live_cloud_scanner", "enterprise_sso_scim"):
        flags.update_flag(name, {"enabled": False})
    yield
    for name in ("deploy_engine", "live_cloud_scanner", "enterprise_sso_scim"):
        flags.update_flag(name, {"enabled": False})


def test_live_scanner_is_feature_gated_before_credentials():
    response = client.post("/api/scanner/run/aws")
    assert response.status_code == 403
    assert response.json()["error"]["details"]["feature_flag"] == "live_cloud_scanner"


def test_legacy_deploy_execute_is_feature_gated():
    response = client.post(
        "/api/deploy/execute/project-1",
        json={"project_id": "project-1", "iac_code": "resource group 'rg' {}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["details"]["feature_flag"] == "deploy_engine"


def test_saml_metadata_is_feature_gated():
    response = client.post("/api/auth/saml/metadata")
    assert response.status_code == 403
    assert response.json()["error"]["details"]["feature_flag"] == "enterprise_sso_scim"


def test_scim_users_are_feature_gated_before_token_validation():
    response = client.get("/api/auth/scim/v2/Users")
    assert response.status_code == 403
    assert response.json()["error"]["details"]["feature_flag"] == "enterprise_sso_scim"


def test_sso_readiness_redacts_secret_values():
    response = client.get("/api/auth/sso/readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["feature_enabled"] is False
    assert "bearer_token_configured" in data["scim"]
    assert "token" not in data["scim"]