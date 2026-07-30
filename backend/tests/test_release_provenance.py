from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release_provenance.py"
ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("release_provenance", SCRIPT)
assert SPEC and SPEC.loader
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)


def _contract(*accepted: str) -> dict:
    return {
        "contract_version": 1,
        "migration_target_revision": "014",
        "minimum_revision": accepted[0],
        "maximum_revision": accepted[-1],
        "accepted_revisions": list(accepted),
        "alias_read_through_until": "014",
    }


def _write(
    path: Path, monkeypatch, *, role: str = "final", contract: dict | None = None
):
    monkeypatch.setenv("RELEASE_MANIFEST_HMAC_KEY", "p" * 32)
    contract = contract or _contract("014")
    return provenance.write_build_provenance(
        path,
        role=role,
        image=f"registry.example/archmorph-api{'-bridge' if role == 'bridge' else ''}@sha256:"
        + "a" * 64,
        source_sha="b" * 40,
        source_repository="example/archmorph",
        source_ref="refs/heads/main",
        workflow="CI/CD",
        workflow_path=".github/workflows/ci.yml",
        run_id="12345",
        run_attempt=2,
        platform="linux/amd64",
        schema_contract=contract,
    )


def _attestation(build: dict) -> list[dict]:
    return [
        {
            "attestation": {"bundle": "verified-by-gh-cli"},
            "verificationResult": {
                "statement": {
                    "predicateType": "https://slsa.dev/provenance/v1",
                    "subject": [
                        {
                            "name": build["image_repository"],
                            "digest": {
                                "sha256": build["image_digest"].split(":", 1)[1]
                            },
                        }
                    ],
                    "predicate": {
                        "buildDefinition": {
                            "externalParameters": {
                                "workflow": {
                                    "repository": "https://github.com/example/archmorph",
                                    "ref": "refs/heads/main",
                                    "path": ".github/workflows/ci.yml",
                                }
                            }
                        },
                        "runDetails": {
                            "metadata": {
                                "invocationId": (
                                    "https://github.com/example/archmorph/actions/"
                                    "runs/12345/attempts/2"
                                )
                            }
                        },
                    },
                }
            },
        }
    ]


def _inspection(build: dict) -> list[dict]:
    return [
        {
            "Os": "linux",
            "Architecture": "amd64",
            "RepoDigests": [build["image"]],
            "Config": {"Labels": dict(build["oci_labels"])},
        }
    ]


def test_build_provenance_binds_digest_source_workflow_contract_and_platform(
    tmp_path, monkeypatch
):
    path = tmp_path / "build.json"
    build = _write(path, monkeypatch)

    verified = provenance.verify_build_provenance(
        path,
        expected_role="final",
        expected_image=build["image"],
        expected_source_sha="b" * 40,
        expected_repository="example/archmorph",
        expected_workflow="CI/CD",
        expected_workflow_path=".github/workflows/ci.yml",
        expected_run_id="12345",
        expected_run_attempt=2,
        expected_platform="linux/amd64",
        expected_contract=_contract("014"),
    )

    assert verified["image_digest"] == "sha256:" + "a" * 64
    assert verified["schema_contract_digest"].startswith("sha256:")
    assert verified["oci_labels"]["org.opencontainers.image.revision"] == "b" * 40
    assert provenance.provenance_digest(build).startswith("sha256:")


def test_signed_build_provenance_fsyncs_file_and_directory(tmp_path, monkeypatch):
    path = tmp_path / "build.json"
    original_fsync = provenance.os.fsync

    with patch.object(provenance.os, "fsync", wraps=original_fsync) as fsync:
        build = _write(path, monkeypatch)

    assert fsync.call_count >= 2
    assert json.loads(path.read_text())["signature"] == build["signature"]
    assert provenance.verify_build_provenance(path)["image"] == build["image"]
    assert not list(tmp_path.glob(".build.json.*.tmp"))


@pytest.mark.parametrize(
    ("field", "expected", "message"),
    [
        (
            "expected_image",
            "registry.example/archmorph-api@sha256:" + "c" * 64,
            "image",
        ),
        ("expected_source_sha", "c" * 40, "source_sha"),
        ("expected_repository", "attacker/fork", "source_repository"),
        ("expected_workflow", "Other", "workflow"),
        ("expected_workflow_path", ".github/workflows/other.yml", "workflow_path"),
        ("expected_run_id", "999", "run_id"),
        ("expected_run_attempt", 3, "run_attempt"),
        ("expected_platform", "linux/arm64", "platform"),
    ],
)
def test_build_provenance_rejects_release_substitution(
    tmp_path, monkeypatch, field, expected, message
):
    path = tmp_path / "build.json"
    _write(path, monkeypatch)
    with pytest.raises(ValueError, match=message):
        provenance.verify_build_provenance(path, **{field: expected})


def test_build_provenance_rejects_contract_substitution_and_resigned_extra_fields(
    tmp_path, monkeypatch
):
    path = tmp_path / "build.json"
    _write(path, monkeypatch)
    with pytest.raises(ValueError, match="schema contract"):
        provenance.verify_build_provenance(
            path,
            expected_contract=_contract("013", "014"),
        )

    payload = json.loads(path.read_text())
    payload["unexpected"] = "claim"
    signed = {key: value for key, value in payload.items() if key != "signature"}
    payload["signature"] = (
        "sha256="
        + __import__("hmac")
        .new(
            b"p" * 32,
            json.dumps(signed, separators=(",", ":"), sort_keys=True).encode(),
            __import__("hashlib").sha256,
        )
        .hexdigest()
    )
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="incomplete or unexpected"):
        provenance.verify_build_provenance(path)


@pytest.mark.parametrize("attestations", [[], [{}, {}], {}, None])
def test_missing_duplicate_or_malformed_attestation_fails_closed(
    tmp_path, monkeypatch, attestations
):
    build = _write(tmp_path / "build.json", monkeypatch)
    with pytest.raises(ValueError, match="exactly one"):
        provenance.verify_attestation(attestations, build)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda item: item[0]["verificationResult"]["statement"]["subject"][
                0
            ].update({"name": "registry.example/other"}),
            "repository",
        ),
        (
            lambda item: item[0]["verificationResult"]["statement"]["subject"][0][
                "digest"
            ].update({"sha256": "c" * 64}),
            "digest",
        ),
        (
            lambda item: item[0]["verificationResult"]["statement"]["predicate"][
                "runDetails"
            ]["metadata"].update({"invocationId": "https://github.com/attacker/run"}),
            "run identity",
        ),
        (
            lambda item: item[0]["verificationResult"]["statement"]["predicate"][
                "buildDefinition"
            ]["externalParameters"]["workflow"].update(
                {"path": ".github/workflows/other.yml"}
            ),
            "workflow identity",
        ),
    ],
)
def test_attestation_statement_rejects_digest_repository_run_and_workflow_mismatch(
    tmp_path, monkeypatch, mutator, message
):
    build = _write(tmp_path / "build.json", monkeypatch)
    attestation = _attestation(build)
    mutator(attestation)
    with pytest.raises(ValueError, match=message):
        provenance.verify_attestation(attestation, build)


def test_image_inspection_requires_exact_digest_labels_platform_and_embedded_contract(
    tmp_path, monkeypatch
):
    build = _write(tmp_path / "build.json", monkeypatch)
    provenance.verify_image_inspection(
        _inspection(build),
        embedded_contract=_contract("014"),
        provenance=build,
    )

    wrong_digest = _inspection(build)
    wrong_digest[0]["RepoDigests"] = [
        "registry.example/archmorph-api@sha256:" + "c" * 64
    ]
    with pytest.raises(ValueError, match="exact immutable digest"):
        provenance.verify_image_inspection(
            wrong_digest,
            embedded_contract=_contract("014"),
            provenance=build,
        )

    wrong_label = _inspection(build)
    wrong_label[0]["Config"]["Labels"]["org.opencontainers.image.revision"] = "c" * 40
    with pytest.raises(ValueError, match="OCI labels"):
        provenance.verify_image_inspection(
            wrong_label,
            embedded_contract=_contract("014"),
            provenance=build,
        )

    wrong_platform = _inspection(build)
    wrong_platform[0]["Architecture"] = "arm64"
    with pytest.raises(ValueError, match="platform"):
        provenance.verify_image_inspection(
            wrong_platform,
            embedded_contract=_contract("014"),
            provenance=build,
        )

    with pytest.raises(ValueError, match="embedded image schema contract"):
        provenance.verify_image_inspection(
            _inspection(build),
            embedded_contract=_contract("013", "014"),
            provenance=build,
        )


def test_backend_and_bridge_images_embed_required_labels_and_contracts():
    backend = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    bridge = (ROOT / "backend" / "bridge_overlay" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    for dockerfile, role in ((backend, "final"), (bridge, "bridge")):
        for label in (
            "org.opencontainers.image.revision",
            "org.opencontainers.image.source",
            "io.archmorph.build.workflow",
            "io.archmorph.build.run-id",
            "io.archmorph.build.run-attempt",
            "io.archmorph.image.platform",
            "io.archmorph.release-role",
            "io.archmorph.schema-accepted-revisions",
            "io.archmorph.schema-contract-digest",
        ):
            assert label in dockerfile
        assert f'io.archmorph.release-role="{role}"' in dockerfile
        assert "/app/release/schema-contract.json" in dockerfile
    assert "COPY --chown=appuser:appgroup schema-contract.json" in backend
    assert "COPY --chown=appuser:appgroup bridge-schema-contract.json" in bridge
