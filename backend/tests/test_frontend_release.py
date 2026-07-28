"""Verified frontend rollback bundle contracts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "frontend_release.py"
SPEC = importlib.util.spec_from_file_location("frontend_release", SCRIPT)
assert SPEC and SPEC.loader
frontend_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frontend_release)
IMAGE = "mcr.microsoft.com/example/staticappsclient@sha256:" + "a" * 64


def _snapshot(tmp_path: Path) -> Path:
    (tmp_path / "dist").mkdir(parents=True)
    (tmp_path / "api").mkdir()
    (tmp_path / "dist" / "index.html").write_text("prior")
    (tmp_path / "api" / "route.js").write_text("prior-api")
    manifest = tmp_path / "frontend-rollback-manifest.json"
    frontend_release.write_manifest(
        tmp_path,
        IMAGE,
        manifest,
    )
    return manifest


def test_verified_previous_frontend_snapshot_is_accepted(tmp_path):
    manifest = _snapshot(tmp_path)
    payload = frontend_release.verify_snapshot(tmp_path, manifest)
    assert payload["restore_image"] == IMAGE
    assert {"dist/index.html", "api/route.js"} <= payload["files"].keys()


def test_missing_previous_frontend_artifact_fails_before_mutation(tmp_path):
    manifest = _snapshot(tmp_path)
    (tmp_path / "dist" / "index.html").unlink()
    with pytest.raises(ValueError, match="failed integrity"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_unpinned_restore_tool_is_rejected(tmp_path):
    manifest = _snapshot(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["restore_image"] = "mcr.microsoft.com/example/staticappsclient:stable"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="immutable digest"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_chart_schema_contract_is_read_from_single_values_source(tmp_path):
    values = tmp_path / "values.yaml"
    values.write_text(
        "migrations:\n"
        '  expectedAlembicHead: "014"\n'
        "  acceptedCurrentAlembicRevisions:\n"
        '    - "013"\n'
        '    - "014"\n'
    )
    assert frontend_release.chart_schema_contract(values) == {
        "expected_head": "014",
        "accepted_current": ["013", "014"],
    }
