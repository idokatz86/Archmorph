import json

import pytest

from verify_migration_preflight import main, verify_preflight_logs


IMAGE_DIGEST = "sha256:" + "a" * 64
IMAGE_REFERENCE = f"archmorph.azurecr.io/api@{IMAGE_DIGEST}"
EXECUTION_MARKER = "preflight-12345-1"
ACCEPTED_REVISIONS = ("013", "014")


def _log(revision="013", **overrides):
    evidence = {
        "status": "preflight_succeeded",
        "current_revision": revision,
        "accepted_revisions": list(ACCEPTED_REVISIONS),
        "image_reference": IMAGE_REFERENCE,
        "execution_marker": EXECUTION_MARKER,
        "image_digest": IMAGE_DIGEST,
        **overrides,
    }
    return "ARCHMORPH_MIGRATION_PREFLIGHT_EVIDENCE=" + json.dumps(evidence)


def test_verifies_exact_preflight_evidence_from_json_container_logs():
    raw_logs = json.dumps(
        {
            "logs": [
                {"log": "Database secret and SELECT 1 verified"},
                {"log": _log(revision="014")},
            ]
        }
    )

    assert verify_preflight_logs(
        raw_logs,
        execution_marker=EXECUTION_MARKER,
        image_digest=IMAGE_DIGEST,
        accepted_revisions=ACCEPTED_REVISIONS,
    ) == "014"


def test_cli_writes_only_the_verified_revision_to_github_output(tmp_path):
    log_path = tmp_path / "preflight.json"
    output_path = tmp_path / "github-output"
    log_path.write_text(_log(revision="014"), encoding="utf-8")

    assert main(
        [
            "--input",
            str(log_path),
            "--execution-marker",
            EXECUTION_MARKER,
            "--image-digest",
            IMAGE_DIGEST,
            "--accepted-revision",
            "013",
            "--accepted-revision",
            "014",
            "--github-output",
            str(output_path),
        ]
    ) == 0
    assert output_path.read_text(encoding="utf-8") == "revision=014\n"


def test_rejects_missing_or_ambiguous_evidence():
    with pytest.raises(ValueError, match="exactly one"):
        verify_preflight_logs(
            "no evidence",
            execution_marker=EXECUTION_MARKER,
            image_digest=IMAGE_DIGEST,
            accepted_revisions=ACCEPTED_REVISIONS,
        )
    with pytest.raises(ValueError, match="exactly one"):
        verify_preflight_logs(
            f"{_log()}\n{_log()}",
            execution_marker=EXECUTION_MARKER,
            image_digest=IMAGE_DIGEST,
            accepted_revisions=ACCEPTED_REVISIONS,
        )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"status": "preflight_failed"}, "did not report success"),
        ({"execution_marker": "preflight-old-run"}, "another execution"),
        ({"image_digest": "sha256:" + "b" * 64}, "another image"),
        ({"current_revision": "012"}, "unsupported schema"),
        ({"accepted_revisions": ["012", "014"]}, "unexpected schema allow-list"),
        ({"image_reference": "archmorph.azurecr.io/api:latest"}, "does not match"),
    ],
)
def test_rejects_stale_or_out_of_contract_preflight_evidence(overrides, message):
    with pytest.raises(ValueError, match=message):
        verify_preflight_logs(
            _log(**overrides),
            execution_marker=EXECUTION_MARKER,
            image_digest=IMAGE_DIGEST,
            accepted_revisions=ACCEPTED_REVISIONS,
        )
