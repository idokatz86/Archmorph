"""Strict migration runtime-envelope and command-argv contracts."""

from __future__ import annotations

import json

import pytest

import migration_runtime_contract as contract


DIGEST = "sha256:" + "a" * 64
MARKER = "migration-123-1"


def _canonical(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _preflight() -> str:
    return contract.build_runtime_envelope(
        mode="preflight",
        accepted_current=("013", "014"),
        execution_marker="preflight-123-1",
        image_digest=DIGEST,
    )


def _migration() -> str:
    return contract.build_runtime_envelope(
        mode="migrate",
        expected_head="014",
        execution_marker=MARKER,
        image_digest=DIGEST,
    )


def test_builds_canonical_mode_specific_envelopes_without_secret_fields():
    preflight = _preflight()
    migration = _migration()

    assert preflight.startswith("{")
    assert migration.startswith("{")
    assert preflight == (
        '{"accept_current":["013","014"],"bootstrap":false,'
        '"execution_marker":"preflight-123-1","image_digest":"'
        + DIGEST
        + '","mode":"preflight"}'
    )
    assert migration == (
        '{"bootstrap":false,"execution_marker":"migration-123-1",'
        '"expected_head":"014","image_digest":"'
        + DIGEST
        + '","mode":"migrate"}'
    )
    assert "secret" not in preflight.lower()
    assert "secret" not in migration.lower()


def test_container_args_and_azure_cli_argv_preserve_exactly_one_envelope_token():
    envelope = _preflight()
    assert contract.parse_container_args([envelope]) == json.loads(envelope)

    argv = contract.containerapp_job_start_argv(
        job_name="placeholder-job",
        resource_group="placeholder-rg",
        container_name="migrate",
        command=("python", "run_migrations.py"),
        runtime_envelope=envelope,
    )

    args_index = argv.index("--args")
    assert argv[args_index + 1] == envelope
    assert argv[args_index + 2 : args_index + 4] == ["--query", "name"]
    assert argv.count(envelope) == 1
    assert "--preflight-only" not in argv
    assert "--accept-current" not in argv


@pytest.mark.parametrize(
    "payload",
    [
        [],
        ["{}", "{}"],
        [1],
        {"arg": _migration()},
        _migration(),
    ],
)
def test_container_args_reject_every_non_single_string_shape(payload):
    with pytest.raises(contract.RuntimeEnvelopeError, match="exactly one"):
        contract.parse_container_args(payload)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "size"),
        (" []", "begin"),
        ("[]", "begin"),
        ("null", "begin"),
        ("{", "valid JSON"),
        (
            '{"accept_current":["013"],"bootstrap":false,'
            '"execution_marker":"preflight-1","image_digest":"'
            + DIGEST
            + '","mode":"preflight","mode":"preflight"}',
            "duplicate key",
        ),
        (
            _canonical(
                {
                    "accept_current": ["013"],
                    "bootstrap": False,
                    "execution_marker": "preflight-1",
                    "image_digest": DIGEST,
                    "mode": "other",
                }
            ),
            "unsupported",
        ),
        (
            _canonical(
                {
                    "accept_current": ["013"],
                    "bootstrap": False,
                    "execution_marker": "preflight-1",
                    "image_digest": DIGEST,
                }
            ),
            "mode must be a string",
        ),
        (
            _canonical(
                {
                    "accept_current": ["013"],
                    "bootstrap": False,
                    "execution_marker": "preflight-1",
                    "image_digest": DIGEST,
                    "mode": "preflight",
                    "DATABASE_URL": "postgresql://secret.invalid/db",
                }
            ),
            "unknown DATABASE_URL",
        ),
        (
            _canonical(
                {
                    "bootstrap": False,
                    "execution_marker": "migration-1",
                    "image_digest": DIGEST,
                    "mode": "migrate",
                }
            ),
            "missing expected_head",
        ),
        (
            _canonical(
                {
                    "accept_current": ["013"],
                    "bootstrap": False,
                    "execution_marker": "preflight-1",
                    "expected_head": "014",
                    "image_digest": DIGEST,
                    "mode": "preflight",
                }
            ),
            "unknown expected_head",
        ),
        (
            _canonical(
                {
                    "accept_current": ["013"],
                    "bootstrap": False,
                    "execution_marker": "preflight-1",
                    "image_digest": DIGEST,
                    "mode": "migrate",
                }
            ),
            "missing expected_head",
        ),
        (
            '{"mode":"preflight","accept_current":["013"],'
            '"bootstrap":false,"execution_marker":"preflight-1",'
            '"image_digest":"'
            + DIGEST
            + '"}',
            "canonical JSON",
        ),
        (
            '{"accept_current":["013"],"bootstrap":false,'
            '"execution_marker":"preflight-1","image_digest":"'
            + DIGEST
            + '","mode":NaN}',
            "unsupported JSON constant",
        ),
        ("{" + "x" * contract.MAX_RUNTIME_ENVELOPE_BYTES + "}", "size"),
    ],
)
def test_rejects_malformed_noncanonical_or_secret_bearing_envelopes(raw, message):
    with pytest.raises(contract.RuntimeEnvelopeError, match=message):
        contract.parse_runtime_envelope(raw)


@pytest.mark.parametrize("bootstrap", [0, 1, "false", None, []])
def test_rejects_non_boolean_bootstrap(bootstrap):
    payload = json.loads(_migration())
    payload["bootstrap"] = bootstrap
    with pytest.raises(contract.RuntimeEnvelopeError, match="boolean"):
        contract.parse_runtime_envelope(_canonical(payload))


@pytest.mark.parametrize(
    "marker",
    ["", "Migration-1", "migration 1", "../migration", "migration_1", "a" * 129, 1],
)
def test_rejects_unsafe_execution_markers(marker):
    payload = json.loads(_migration())
    payload["execution_marker"] = marker
    with pytest.raises(contract.RuntimeEnvelopeError, match="execution_marker"):
        contract.parse_runtime_envelope(_canonical(payload))


@pytest.mark.parametrize(
    "digest",
    ["", "latest", "sha256:abc", "SHA256:" + "a" * 64, "sha256:" + "A" * 64, 1],
)
def test_rejects_mutable_or_malformed_image_digests(digest):
    payload = json.loads(_migration())
    payload["image_digest"] = digest
    with pytest.raises(contract.RuntimeEnvelopeError, match="immutable"):
        contract.parse_runtime_envelope(_canonical(payload))


@pytest.mark.parametrize(
    "revision",
    ["", "head", "013,014", "013 014", "../014", "014\n", "a" * 129, 14, True],
)
def test_rejects_unsafe_expected_revisions(revision):
    payload = json.loads(_migration())
    payload["expected_head"] = revision
    with pytest.raises(contract.RuntimeEnvelopeError, match="safe revision"):
        contract.parse_runtime_envelope(_canonical(payload))


@pytest.mark.parametrize(
    "accepted",
    [
        [],
        "013",
        ["013", "013"],
        ["013", "../014"],
        ["013", 14],
        ["014"] * (contract.MAX_ACCEPTED_REVISIONS + 1),
    ],
)
def test_rejects_invalid_accepted_revision_contracts(accepted):
    payload = json.loads(_preflight())
    payload["accept_current"] = accepted
    with pytest.raises(contract.RuntimeEnvelopeError):
        contract.parse_runtime_envelope(_canonical(payload))


def test_builder_rejects_cross_mode_fields():
    with pytest.raises(contract.RuntimeEnvelopeError, match="expected_head"):
        contract.build_runtime_envelope(
            mode="preflight",
            expected_head="014",
            accepted_current=("013",),
            execution_marker="preflight-1",
            image_digest=DIGEST,
        )
    with pytest.raises(contract.RuntimeEnvelopeError, match="accept_current"):
        contract.build_runtime_envelope(
            mode="migrate",
            expected_head="014",
            accepted_current=("013",),
            execution_marker="migration-1",
            image_digest=DIGEST,
        )


def test_validate_container_args_cli_checks_structural_provenance(tmp_path, capsys):
    args_json = tmp_path / "args.json"
    args_json.write_text(json.dumps([_migration()]), encoding="utf-8")

    assert (
        contract.main(
            [
                "validate-container-args",
                "--args-json",
                str(args_json),
                "--mode",
                "migrate",
                "--expected-head",
                "014",
                "--expected-bootstrap",
                "false",
                "--execution-marker",
                MARKER,
                "--image-digest",
                DIGEST,
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == _migration()

    with pytest.raises(contract.RuntimeEnvelopeError, match="image_digest"):
        contract.main(
            [
                "validate-container-args",
                "--args-json",
                str(args_json),
                "--mode",
                "migrate",
                "--expected-head",
                "014",
                "--expected-bootstrap",
                "false",
                "--execution-marker",
                MARKER,
                "--image-digest",
                "sha256:" + "b" * 64,
            ]
        )

    with pytest.raises(contract.RuntimeEnvelopeError, match="requires an execution marker"):
        contract.main(
            [
                "validate-container-args",
                "--args-json",
                str(args_json),
                "--mode",
                "migrate",
                "--expected-head",
                "014",
                "--expected-bootstrap",
                "false",
                "--image-digest",
                DIGEST,
            ]
        )

    with pytest.raises(contract.RuntimeEnvelopeError, match="expected_head"):
        contract.main(
            [
                "validate-container-args",
                "--args-json",
                str(args_json),
                "--mode",
                "migrate",
                "--expected-bootstrap",
                "false",
                "--execution-marker",
                MARKER,
                "--image-digest",
                DIGEST,
            ]
        )