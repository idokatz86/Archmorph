"""Zero-traffic Container Apps revision document contracts."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_containerapp_revision.py"
SPEC = importlib.util.spec_from_file_location("build_containerapp_revision", SCRIPT)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
DIGEST = "registry.example.com/api@sha256:" + "a" * 64


def _source() -> dict:
    return {
        "name": "example-app",
        "location": "example-region",
        "properties": {
            "configuration": {"ingress": {"external": True}},
            "template": {
                "revisionSuffix": "blue",
                "scale": {"minReplicas": 1},
                "containers": [
                    {
                        "name": "api",
                        "image": "registry.example.com/api@sha256:" + "b" * 64,
                        "env": [{"name": "DATABASE_URL", "secretRef": "db-connection"}],
                        "probes": [
                            {
                                "type": "Liveness",
                                "httpGet": {"path": "/healthz", "port": 8000},
                            }
                        ],
                    }
                ],
            },
        },
    }


def test_builder_preserves_source_and_adds_readyz_only_to_new_template():
    source = _source()
    original = copy.deepcopy(source)

    document = builder.build_revision_document(
        source,
        image=DIGEST,
        revision_suffix="sha-12345678-run-1",
        readiness_path="/readyz",
        env_values={"APP_SCHEMA_MIN_REVISION": "014", "APP_SCHEMA_MAX_REVISION": "014"},
        env_secret_refs={"JWT_SECRET": "jwt-secret"},
    )

    assert source == original
    assert "configuration" not in document["properties"]
    template = document["properties"]["template"]
    container = template["containers"][0]
    assert template["revisionSuffix"] == "sha-12345678-run-1"
    assert container["image"] == DIGEST
    assert {item["name"]: item for item in container["env"]}["DATABASE_URL"] == {
        "name": "DATABASE_URL",
        "secretRef": "db-connection",
    }
    assert {item["name"]: item for item in container["env"]}["JWT_SECRET"] == {
        "name": "JWT_SECRET",
        "secretRef": "jwt-secret",
    }
    assert next(probe for probe in container["probes"] if probe["type"] == "Readiness")["httpGet"]["path"] == "/readyz"
    assert next(probe for probe in container["probes"] if probe["type"] == "Liveness")["httpGet"]["path"] == "/healthz"


def test_builder_rejects_mutable_or_malformed_images():
    for image in ("registry.example.com/api:latest", "registry.example.com/api:sha", ""):
        with pytest.raises(ValueError, match="immutable sha256"):
            builder.build_revision_document(
                _source(),
                image=image,
                revision_suffix="sha-12345678-run-1",
                readiness_path="/readyz",
                env_values={},
                env_secret_refs={},
            )
