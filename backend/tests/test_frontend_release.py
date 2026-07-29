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
    (tmp_path / "dist" / "assets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "api" / "src" / "functions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "dist" / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/main.css">'
        '<script type="module" src="/assets/main.js"></script>'
    )
    (tmp_path / "dist" / "assets" / "main.css").write_text(
        'body{background:url("./background.svg")}'
    )
    (tmp_path / "dist" / "assets" / "background.svg").write_text("<svg/>")
    (tmp_path / "dist" / "assets" / "main.js").write_text('import "./chunk.js";')
    (tmp_path / "dist" / "assets" / "chunk.js").write_text("export default 1;")
    (tmp_path / "api" / "host.json").write_text('{"version":"2.0"}')
    (tmp_path / "api" / "package.json").write_text('{"name":"api"}')
    (tmp_path / "api" / "package-lock.json").write_text(
        '{"name":"api","lockfileVersion":3}'
    )
    (tmp_path / "api" / "src" / "functions" / "swa-session.js").write_text(
        "export async function handler() { return {}; }"
    )
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
    assert {
        "dist/index.html",
        "dist/assets/main.js",
        "api/host.json",
        "api/src/functions/swa-session.js",
    } <= payload["files"].keys()


def test_missing_previous_frontend_artifact_fails_before_mutation(tmp_path):
    manifest = _snapshot(tmp_path)
    (tmp_path / "dist" / "index.html").unlink()
    with pytest.raises(ValueError, match="dist/index.html"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_unpinned_restore_tool_is_rejected(tmp_path):
    manifest = _snapshot(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["restore_image"] = "mcr.microsoft.com/example/staticappsclient:stable"
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="immutable digest"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_write_fails_atomically_before_replacing_manifest_on_missing_asset(tmp_path):
    _snapshot(tmp_path)
    output = tmp_path / "next-manifest.json"
    output.write_text("preserve-existing-evidence")
    (tmp_path / "dist" / "assets" / "chunk.js").unlink()

    with pytest.raises(ValueError, match="missing referenced file"):
        frontend_release.write_manifest(tmp_path, IMAGE, output)

    assert output.read_text() == "preserve-existing-evidence"
    assert not list(tmp_path.glob(".next-manifest.json.*.tmp"))


@pytest.mark.parametrize(
    "required_api_file",
    [
        "host.json",
        "package.json",
        "package-lock.json",
        "src/functions/swa-session.js",
    ],
)
def test_write_rejects_missing_required_api_bundle_file(tmp_path, required_api_file):
    _snapshot(tmp_path)
    (tmp_path / "api" / required_api_file).unlink()

    with pytest.raises(ValueError, match="required API files"):
        frontend_release.write_manifest(tmp_path, IMAGE, tmp_path / "next.json")


def test_write_and_verify_reject_symlinks(tmp_path):
    _snapshot(tmp_path)
    (tmp_path / "dist" / "assets" / "linked.js").symlink_to(
        tmp_path / "dist" / "assets" / "main.js"
    )

    with pytest.raises(ValueError, match="symlink"):
        frontend_release.write_manifest(tmp_path, IMAGE, tmp_path / "next.json")


def test_verify_rejects_case_colliding_artifact_paths(tmp_path):
    manifest = _snapshot(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["files"]["dist/assets/MAIN.JS"] = payload["files"]["dist/assets/main.js"]
    manifest.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="case-collision"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_verify_rejects_normalized_manifest_traversal(tmp_path):
    manifest = _snapshot(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["files"]["dist/../../outside"] = "a" * 64
    manifest.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="unsafe path"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_verify_rejects_encoded_manifest_traversal(tmp_path):
    manifest = _snapshot(tmp_path)
    payload = json.loads(manifest.read_text())
    payload["files"]["dist/%2e%2e/outside"] = "a" * 64
    manifest.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="encoded path"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_write_rejects_normalized_static_graph_traversal(tmp_path):
    _snapshot(tmp_path)
    (tmp_path / "dist" / "index.html").write_text(
        '<script type="module" src="/../../outside.js"></script>'
    )

    with pytest.raises(ValueError, match="unsafe path"):
        frontend_release.write_manifest(tmp_path, IMAGE, tmp_path / "next.json")


def test_verify_rejects_tampering_and_unmanifested_files(tmp_path):
    manifest = _snapshot(tmp_path)
    (tmp_path / "dist" / "assets" / "main.js").write_text("tampered")
    with pytest.raises(ValueError, match="failed integrity"):
        frontend_release.verify_snapshot(tmp_path, manifest)

    manifest = _snapshot(tmp_path)
    (tmp_path / "dist" / "assets" / "unexpected.js").write_text("extra")
    with pytest.raises(ValueError, match="failed integrity"):
        frontend_release.verify_snapshot(tmp_path, manifest)


def test_verify_rejects_duplicate_json_keys(tmp_path):
    _snapshot(tmp_path)
    manifest = tmp_path / "duplicate.json"
    manifest.write_text(
        '{"schema_version":1,"restore_image":"x","files":{},"files":{}}'
    )
    with pytest.raises(ValueError, match="duplicate key"):
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


def test_chart_schema_contract_applies_environment_values_overlay(tmp_path):
    base = tmp_path / "values.yaml"
    base.write_text(
        "migrations:\n"
        '  expectedAlembicHead: "013"\n'
        "  acceptedCurrentAlembicRevisions:\n"
        '    - "013"\n'
    )
    environment = tmp_path / "values-production.yaml"
    environment.write_text(
        "migrations:\n"
        '  expectedAlembicHead: "014"\n'
        "  acceptedCurrentAlembicRevisions:\n"
        '    - "013"\n'
        '    - "014"\n'
    )

    assert frontend_release.chart_schema_contract([base, environment]) == {
        "expected_head": "014",
        "accepted_current": ["013", "014"],
    }
