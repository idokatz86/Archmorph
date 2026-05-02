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
