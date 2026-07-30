#!/usr/bin/env python3
"""Create and verify immutable image build provenance for release workflows."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


_IMAGE_RE = re.compile(r"^(?P<repository>[^\s@]+)@sha256:(?P<digest>[0-9a-f]{64})$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_WORKFLOW_PATH_RE = re.compile(r"^\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml$")
_PLATFORM_RE = re.compile(r"^linux/(amd64|arm64)$")
_SCHEMA_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ROLE_VALUES = frozenset({"bridge", "final"})
_SLSA_PROVENANCE_V1 = "https://slsa.dev/provenance/v1"
_BUILD_SCHEMA_VERSION = 1
_BUILD_FIELDS = {
    "schema_version",
    "role",
    "image",
    "image_repository",
    "image_digest",
    "source_sha",
    "source_repository",
    "source_ref",
    "workflow",
    "workflow_path",
    "run_id",
    "run_attempt",
    "platform",
    "schema_contract",
    "schema_contract_digest",
    "oci_labels",
}
_CONTRACT_FIELDS = {
    "contract_version",
    "migration_target_revision",
    "minimum_revision",
    "maximum_revision",
    "accepted_revisions",
    "alias_read_through_until",
}


def _strict_json(path: Path) -> object:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate
    )


def _signing_key() -> bytes:
    key = os.environ.get("RELEASE_MANIFEST_HMAC_KEY", "").encode()
    if len(key) < 32:
        raise ValueError("RELEASE_MANIFEST_HMAC_KEY must contain at least 32 bytes")
    return key


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def normalize_schema_contract(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _CONTRACT_FIELDS:
        raise ValueError("schema contract fields are incomplete or unexpected")
    if payload.get("contract_version") != 1:
        raise ValueError("schema contract version is unsupported")
    accepted = payload.get("accepted_revisions")
    if (
        not isinstance(accepted, list)
        or not accepted
        or any(
            not isinstance(item, str) or not _SCHEMA_RE.fullmatch(item)
            for item in accepted
        )
        or accepted != sorted(set(accepted))
    ):
        raise ValueError("schema contract accepted revisions are invalid")
    normalized: dict[str, object] = {"contract_version": 1}
    for field in (
        "migration_target_revision",
        "minimum_revision",
        "maximum_revision",
        "alias_read_through_until",
    ):
        value = payload.get(field)
        if not isinstance(value, str) or not _SCHEMA_RE.fullmatch(value):
            raise ValueError(f"schema contract {field} is invalid")
        normalized[field] = value
    normalized["accepted_revisions"] = accepted
    if normalized["minimum_revision"] != accepted[0]:
        raise ValueError("schema contract minimum does not match accepted revisions")
    if normalized["maximum_revision"] != accepted[-1]:
        raise ValueError("schema contract maximum does not match accepted revisions")
    if normalized["migration_target_revision"] not in accepted:
        raise ValueError("schema contract target is not accepted")
    if normalized["alias_read_through_until"] not in accepted:
        raise ValueError("schema contract alias window is not accepted")
    return normalized


def schema_contract_digest(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            _canonical_bytes(normalize_schema_contract(payload))
        ).hexdigest()
    )


def _identity(
    *,
    repository: str,
    workflow: str,
    workflow_path: str,
    source_ref: str,
    run_id: str,
    run_attempt: int,
) -> dict[str, object]:
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("build repository identity is invalid")
    if not workflow or len(workflow) > 128:
        raise ValueError("build workflow name is invalid")
    if not _WORKFLOW_PATH_RE.fullmatch(workflow_path):
        raise ValueError("build workflow path is invalid")
    if source_ref != "refs/heads/main":
        raise ValueError("release build source ref must be refs/heads/main")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("build run ID must be a positive integer")
    if (
        isinstance(run_attempt, bool)
        or not isinstance(run_attempt, int)
        or run_attempt < 1
    ):
        raise ValueError("build run attempt must be a positive integer")
    return {
        "source_repository": repository,
        "workflow": workflow,
        "workflow_path": workflow_path,
        "source_ref": source_ref,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }


def expected_oci_labels(payload: dict[str, object]) -> dict[str, str]:
    contract = normalize_schema_contract(payload["schema_contract"])
    accepted = ",".join(str(value) for value in contract["accepted_revisions"])
    return {
        "io.archmorph.build.run-attempt": str(payload["run_attempt"]),
        "io.archmorph.build.run-id": str(payload["run_id"]),
        "io.archmorph.build.workflow": str(payload["workflow_path"]),
        "io.archmorph.image.platform": str(payload["platform"]),
        "io.archmorph.release-role": str(payload["role"]),
        "io.archmorph.schema-accepted-revisions": accepted,
        "io.archmorph.schema-contract-digest": str(payload["schema_contract_digest"]),
        "org.opencontainers.image.revision": str(payload["source_sha"]),
        "org.opencontainers.image.source": (
            f"https://github.com/{payload['source_repository']}"
        ),
    }


def build_provenance_payload(
    *,
    role: str,
    image: str,
    source_sha: str,
    source_repository: str,
    source_ref: str,
    workflow: str,
    workflow_path: str,
    run_id: str,
    run_attempt: int,
    platform: str,
    schema_contract: object,
) -> dict[str, object]:
    if role not in _ROLE_VALUES:
        raise ValueError("build provenance role must be bridge or final")
    image_match = _IMAGE_RE.fullmatch(image)
    if image_match is None:
        raise ValueError("build provenance image must be immutable")
    if not _SHA_RE.fullmatch(source_sha):
        raise ValueError("build provenance source SHA is invalid")
    if not _PLATFORM_RE.fullmatch(platform):
        raise ValueError("build provenance platform is unsupported")
    identity = _identity(
        repository=source_repository,
        workflow=workflow,
        workflow_path=workflow_path,
        source_ref=source_ref,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    contract = normalize_schema_contract(schema_contract)
    payload: dict[str, object] = {
        "schema_version": _BUILD_SCHEMA_VERSION,
        "role": role,
        "image": image,
        "image_repository": image_match.group("repository"),
        "image_digest": "sha256:" + image_match.group("digest"),
        "source_sha": source_sha,
        **identity,
        "platform": platform,
        "schema_contract": contract,
        "schema_contract_digest": schema_contract_digest(contract),
    }
    payload["oci_labels"] = expected_oci_labels(payload)
    return payload


def write_build_provenance(path: Path, **kwargs: object) -> dict[str, object]:
    payload = build_provenance_payload(**kwargs)
    payload["signature"] = (
        "sha256="
        + hmac.new(
            _signing_key(),
            _canonical_bytes(payload),
            hashlib.sha256,
        ).hexdigest()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return payload


def validate_unsigned_build_provenance(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _BUILD_FIELDS:
        raise ValueError("build provenance fields are incomplete or unexpected")
    unsigned = dict(payload)
    if unsigned.get("schema_version") != _BUILD_SCHEMA_VERSION:
        raise ValueError("build provenance schema version is unsupported")
    rebuilt = build_provenance_payload(
        role=str(unsigned.get("role") or ""),
        image=str(unsigned.get("image") or ""),
        source_sha=str(unsigned.get("source_sha") or ""),
        source_repository=str(unsigned.get("source_repository") or ""),
        source_ref=str(unsigned.get("source_ref") or ""),
        workflow=str(unsigned.get("workflow") or ""),
        workflow_path=str(unsigned.get("workflow_path") or ""),
        run_id=str(unsigned.get("run_id") or ""),
        run_attempt=unsigned.get("run_attempt"),
        platform=str(unsigned.get("platform") or ""),
        schema_contract=unsigned.get("schema_contract"),
    )
    if unsigned != rebuilt:
        raise ValueError("build provenance does not match its canonical claims")
    return unsigned


def validate_build_provenance_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("build provenance must be a JSON object")
    signed = dict(payload)
    signature = str(signed.pop("signature", ""))
    expected_signature = (
        "sha256="
        + hmac.new(
            _signing_key(),
            _canonical_bytes(signed),
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("build provenance signature is invalid")
    return validate_unsigned_build_provenance(signed)


def verify_build_provenance(
    path: Path,
    *,
    expected_role: str | None = None,
    expected_image: str | None = None,
    expected_source_sha: str | None = None,
    expected_repository: str | None = None,
    expected_workflow: str | None = None,
    expected_workflow_path: str | None = None,
    expected_run_id: str | None = None,
    expected_run_attempt: int | None = None,
    expected_platform: str | None = None,
    expected_contract: object | None = None,
) -> dict[str, object]:
    payload = validate_build_provenance_payload(_strict_json(path))
    expectations = {
        "role": expected_role,
        "image": expected_image,
        "source_sha": expected_source_sha,
        "source_repository": expected_repository,
        "workflow": expected_workflow,
        "workflow_path": expected_workflow_path,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
        "platform": expected_platform,
    }
    for field, expected in expectations.items():
        if expected is not None and payload[field] != expected:
            raise ValueError(
                f"build provenance {field} does not match release evidence"
            )
    if expected_contract is not None:
        expected = normalize_schema_contract(expected_contract)
        if payload["schema_contract"] != expected:
            raise ValueError(
                "build provenance schema contract does not match release evidence"
            )
    return payload


def provenance_digest(payload: object) -> str:
    if isinstance(payload, dict) and "signature" in payload:
        canonical = validate_build_provenance_payload(payload)
    else:
        canonical = validate_unsigned_build_provenance(payload)
    return "sha256:" + hashlib.sha256(_canonical_bytes(canonical)).hexdigest()


def verify_attestation(payload: object, provenance: dict[str, object]) -> None:
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError(
            "exactly one verified build provenance attestation is required"
        )
    result = payload[0]
    if not isinstance(result, dict):
        raise ValueError("verified attestation result is malformed")
    verification = result.get("verificationResult")
    statement = (
        verification.get("statement") if isinstance(verification, dict) else None
    )
    if not isinstance(statement, dict):
        raise ValueError("verified attestation statement is missing")
    if statement.get("predicateType") != _SLSA_PROVENANCE_V1:
        raise ValueError(
            "verified attestation predicate type is not SLSA provenance v1"
        )
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError("verified attestation must bind exactly one image subject")
    subject = subjects[0]
    expected_digest = str(provenance["image_digest"]).split(":", 1)[1]
    if (
        not isinstance(subject, dict)
        or subject.get("name") != provenance["image_repository"]
    ):
        raise ValueError(
            "verified attestation image repository does not match provenance"
        )
    if subject.get("digest") != {"sha256": expected_digest}:
        raise ValueError("verified attestation digest does not match provenance")
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        raise ValueError("verified attestation predicate is missing")
    run_details = predicate.get("runDetails")
    metadata = run_details.get("metadata") if isinstance(run_details, dict) else None
    invocation = metadata.get("invocationId") if isinstance(metadata, dict) else None
    expected_invocation = (
        f"https://github.com/{provenance['source_repository']}/actions/runs/"
        f"{provenance['run_id']}/attempts/{provenance['run_attempt']}"
    )
    if invocation != expected_invocation:
        raise ValueError("verified attestation run identity does not match provenance")
    definition = predicate.get("buildDefinition")
    parameters = (
        definition.get("externalParameters") if isinstance(definition, dict) else None
    )
    workflow = parameters.get("workflow") if isinstance(parameters, dict) else None
    expected_workflow = {
        "repository": f"https://github.com/{provenance['source_repository']}",
        "ref": provenance["source_ref"],
        "path": provenance["workflow_path"],
    }
    if workflow != expected_workflow:
        raise ValueError(
            "verified attestation workflow identity does not match provenance"
        )


def verify_image_inspection(
    inspection: object,
    *,
    embedded_contract: object,
    provenance: dict[str, object],
) -> None:
    if not isinstance(inspection, list) or len(inspection) != 1:
        raise ValueError("image inspection must contain exactly one local image")
    image = inspection[0]
    if not isinstance(image, dict):
        raise ValueError("image inspection payload is malformed")
    operating_system = image.get("Os")
    architecture = image.get("Architecture")
    if (
        not isinstance(operating_system, str)
        or not isinstance(architecture, str)
        or f"{operating_system}/{architecture}" != provenance["platform"]
    ):
        raise ValueError("image platform does not match build provenance")
    digests = image.get("RepoDigests")
    if not isinstance(digests, list) or digests.count(provenance["image"]) != 1:
        raise ValueError("image inspection does not contain the exact immutable digest")
    config = image.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    if not isinstance(labels, dict):
        raise ValueError("image inspection omitted OCI labels")
    expected_labels = provenance["oci_labels"]
    if any(labels.get(key) != value for key, value in expected_labels.items()):
        raise ValueError("image OCI labels do not match build provenance")
    contract = normalize_schema_contract(embedded_contract)
    if contract != provenance["schema_contract"]:
        raise ValueError(
            "embedded image schema contract does not match build provenance"
        )
    if schema_contract_digest(contract) != provenance["schema_contract_digest"]:
        raise ValueError(
            "embedded image schema contract digest does not match provenance"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    write = commands.add_parser("write-build-provenance")
    write.add_argument("--output", required=True, type=Path)
    write.add_argument("--role", required=True, choices=sorted(_ROLE_VALUES))
    write.add_argument("--image", required=True)
    write.add_argument("--source-sha", required=True)
    write.add_argument("--source-repository", required=True)
    write.add_argument("--source-ref", required=True)
    write.add_argument("--workflow", required=True)
    write.add_argument("--workflow-path", required=True)
    write.add_argument("--run-id", required=True)
    write.add_argument("--run-attempt", required=True, type=int)
    write.add_argument("--platform", required=True)
    write.add_argument("--schema-contract", required=True, type=Path)

    verify = commands.add_parser("verify-build-provenance")
    verify.add_argument("--input", required=True, type=Path)
    verify.add_argument("--expected-role", choices=sorted(_ROLE_VALUES))
    verify.add_argument("--expected-image")
    verify.add_argument("--expected-source-sha")
    verify.add_argument("--expected-repository")
    verify.add_argument("--expected-workflow")
    verify.add_argument("--expected-workflow-path")
    verify.add_argument("--expected-run-id")
    verify.add_argument("--expected-run-attempt", type=int)
    verify.add_argument("--expected-platform")
    verify.add_argument("--expected-contract", type=Path)
    verify.add_argument(
        "--field",
        choices=(
            "image",
            "image_repository",
            "image_digest",
            "source_sha",
            "source_repository",
            "source_ref",
            "workflow",
            "workflow_path",
            "run_id",
            "run_attempt",
            "platform",
            "schema_contract_digest",
        ),
    )

    attestation = commands.add_parser("verify-attestation")
    attestation.add_argument("--input", required=True, type=Path)
    attestation.add_argument("--provenance", required=True, type=Path)

    image = commands.add_parser("verify-image")
    image.add_argument("--inspection", required=True, type=Path)
    image.add_argument("--embedded-contract", required=True, type=Path)
    image.add_argument("--provenance", required=True, type=Path)

    digest = commands.add_parser("provenance-digest")
    digest.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "write-build-provenance":
        payload = write_build_provenance(
            args.output,
            role=args.role,
            image=args.image,
            source_sha=args.source_sha,
            source_repository=args.source_repository,
            source_ref=args.source_ref,
            workflow=args.workflow,
            workflow_path=args.workflow_path,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            platform=args.platform,
            schema_contract=_strict_json(args.schema_contract),
        )
        print(json.dumps({"status": "written", "digest": provenance_digest(payload)}))
    elif args.command == "verify-build-provenance":
        payload = verify_build_provenance(
            args.input,
            expected_role=args.expected_role,
            expected_image=args.expected_image,
            expected_source_sha=args.expected_source_sha,
            expected_repository=args.expected_repository,
            expected_workflow=args.expected_workflow,
            expected_workflow_path=args.expected_workflow_path,
            expected_run_id=args.expected_run_id,
            expected_run_attempt=args.expected_run_attempt,
            expected_platform=args.expected_platform,
            expected_contract=(
                _strict_json(args.expected_contract) if args.expected_contract else None
            ),
        )
        print(
            payload[args.field] if args.field else json.dumps(payload, sort_keys=True)
        )
    elif args.command == "verify-attestation":
        provenance = verify_build_provenance(args.provenance)
        verify_attestation(_strict_json(args.input), provenance)
        print(json.dumps({"status": "verified"}))
    elif args.command == "verify-image":
        provenance = verify_build_provenance(args.provenance)
        verify_image_inspection(
            _strict_json(args.inspection),
            embedded_contract=_strict_json(args.embedded_contract),
            provenance=provenance,
        )
        print(json.dumps({"status": "verified"}))
    else:
        print(provenance_digest(_strict_json(args.input)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
