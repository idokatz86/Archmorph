import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from check_openapi_contract import (
    APPROVAL_ATTESTATION_PREFIX,
    EXPECTED_GITHUB_REPOSITORY,
    _current_pull_request_context,
    breaking_change_id,
    detect_breaking_changes,
    schema_sha256,
    validate_authenticated_github_reviews,
    verify_authenticated_github_approval,
)


PR_NUMBER = 1234
HEAD_SHA = "a" * 40
NOW = datetime(2026, 10, 26, 7, 10, tzinfo=timezone.utc)
AUTHORIZED_APPROVER = "trusted-api-owner"
PR_AUTHOR = "pull-request-author"


def _schemas() -> tuple[dict, dict, list[str]]:
    base = {
        "paths": {
            "/api/contact": {
                "get": {"responses": {"200": {"description": "OK"}}}
            }
        },
        "components": {"schemas": {}},
    }
    head = {"paths": {}, "components": {"schemas": {}}}
    return base, head, detect_breaking_changes(base, head)


def _attestation(base: dict, head: dict, breaking: list[str]) -> dict:
    return {
        "version": 1,
        "repository": EXPECTED_GITHUB_REPOSITORY,
        "pull_request": PR_NUMBER,
        "base_schema_sha256": schema_sha256(base),
        "head_schema_sha256": schema_sha256(head),
        "break_ids": [breaking_change_id(item) for item in breaking],
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
    }


def _review(
    attestation: dict,
    *,
    login: str = AUTHORIZED_APPROVER,
    state: str = "APPROVED",
    commit_id: str = HEAD_SHA,
    html_url: str | None = None,
    review_id: int = 1,
) -> dict:
    return {
        "id": review_id,
        "user": {"login": login},
        "state": state,
        "commit_id": commit_id,
        "submitted_at": f"2026-10-26T07:{review_id:02d}:00Z",
        "html_url": html_url
        or (
            f"https://github.com/{EXPECTED_GITHUB_REPOSITORY}/pull/"
            f"{PR_NUMBER}#pullrequestreview-{review_id}"
        ),
        "body": f"{APPROVAL_ATTESTATION_PREFIX}{json.dumps(attestation)}",
    }


def _validate(reviews: list[dict], base: dict, head: dict, breaking: list[str]):
    return validate_authenticated_github_reviews(
        reviews,
        repository=EXPECTED_GITHUB_REPOSITORY,
        pull_request_number=PR_NUMBER,
        head_sha=HEAD_SHA,
        pull_request_author=PR_AUTHOR,
        authorized_approvers={AUTHORIZED_APPROVER},
        base_schema=base,
        head_schema=head,
        breaking_changes=breaking,
        now=NOW,
    )


def test_detect_breaking_changes_flags_removed_operation():
    base = {
        "paths": {
            "/api/contact": {
                "get": {
                    "responses": {
                        "200": {"description": "OK"},
                    }
                }
            }
        },
        "components": {"schemas": {}},
    }
    target = {
        "paths": {},
        "components": {"schemas": {}},
    }

    breaking = detect_breaking_changes(base, target)
    assert any("Removed path: /api/contact" in item for item in breaking)


def test_authenticated_review_accepts_exact_approval():
    base, head, breaking = _schemas()

    assert _validate([_review(_attestation(base, head, breaking))], base, head, breaking) == []


def test_forged_attacker_domain_approval_is_rejected():
    base, head, breaking = _schemas()
    forged_review = _review(
        _attestation(base, head, breaking),
        html_url=f"https://attacker.invalid/pull/{PR_NUMBER}#pullrequestreview-1",
    )

    errors = _validate([forged_review], base, head, breaking)
    assert any("untrusted GitHub review URL" in error for error in errors)


def test_self_asserted_approver_is_rejected():
    base, head, breaking = _schemas()
    forged_review = _review(
        _attestation(base, head, breaking), login="attacker-controlled-user"
    )

    errors = _validate([forged_review], base, head, breaking)
    assert errors == ["No authenticated review exists from an authorized API approver"]


def test_authenticated_review_rejects_stale_head_commit():
    base, head, breaking = _schemas()

    errors = _validate(
        [_review(_attestation(base, head, breaking), commit_id="b" * 40)],
        base,
        head,
        breaking,
    )
    assert any("is stale for current head" in error for error in errors)


def test_authenticated_review_rejects_stale_schema_hash():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    attestation["head_schema_sha256"] = "0" * 64

    errors = _validate([_review(attestation)], base, head, breaking)
    assert any("head_schema_sha256 does not match" in error for error in errors)


def test_authenticated_review_rejects_stale_base_schema_hash():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    attestation["base_schema_sha256"] = "0" * 64

    errors = _validate([_review(attestation)], base, head, breaking)
    assert any("base_schema_sha256 does not match" in error for error in errors)


def test_authenticated_review_rejects_unrelated_pr():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    attestation["pull_request"] = PR_NUMBER + 1

    errors = _validate([_review(attestation)], base, head, breaking)
    assert any("pull_request does not match" in error for error in errors)


def test_authenticated_review_rejects_unrelated_break_ids():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    attestation["break_ids"] = [breaking_change_id("Removed path: /api/unrelated")]

    errors = _validate([_review(attestation)], base, head, breaking)
    assert any("do not exactly match" in error for error in errors)


def test_authenticated_review_rejects_expired_evidence():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    attestation["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()

    errors = _validate([_review(attestation)], base, head, breaking)
    assert any("expired" in error for error in errors)


def test_latest_change_request_supersedes_earlier_approval():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    reviews = [
        _review(attestation, review_id=1),
        _review(attestation, state="CHANGES_REQUESTED", review_id=2),
    ]

    errors = _validate(reviews, base, head, breaking)
    assert any("is not APPROVED" in error for error in errors)


def test_comment_only_review_does_not_supersede_earlier_approval():
    base, head, breaking = _schemas()
    attestation = _attestation(base, head, breaking)
    reviews = [
        _review(attestation, review_id=1),
        _review(attestation, state="COMMENTED", review_id=2),
    ]

    assert _validate(reviews, base, head, breaking) == []


def test_pull_request_author_cannot_approve_own_breaking_change():
    base, head, breaking = _schemas()

    errors = validate_authenticated_github_reviews(
        [_review(_attestation(base, head, breaking), login=PR_AUTHOR)],
        repository=EXPECTED_GITHUB_REPOSITORY,
        pull_request_number=PR_NUMBER,
        head_sha=HEAD_SHA,
        pull_request_author=PR_AUTHOR,
        authorized_approvers={PR_AUTHOR},
        base_schema=base,
        head_schema=head,
        breaking_changes=breaking,
        now=NOW,
    )

    assert errors == [
        "No independent authorized API approver is configured for this pull request author"
    ]


def test_review_validation_rejects_untrusted_repository():
    base, head, breaking = _schemas()

    errors = validate_authenticated_github_reviews(
        [_review(_attestation(base, head, breaking))],
        repository="attacker.invalid/Archmorph",
        pull_request_number=PR_NUMBER,
        head_sha=HEAD_SHA,
        pull_request_author=PR_AUTHOR,
        authorized_approvers={AUTHORIZED_APPROVER},
        base_schema=base,
        head_schema=head,
        breaking_changes=breaking,
        now=NOW,
    )
    assert errors == ["Repository is not trusted: 'attacker.invalid/Archmorph'"]


def test_current_pull_request_context_comes_from_github_event(
    tmp_path: Path, monkeypatch
):
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": EXPECTED_GITHUB_REPOSITORY},
                "pull_request": {
                    "number": PR_NUMBER,
                    "head": {"sha": HEAD_SHA},
                    "user": {"login": PR_AUTHOR},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    context, errors = _current_pull_request_context()
    assert errors == []
    assert context == {
        "repository": EXPECTED_GITHUB_REPOSITORY,
        "pull_request": PR_NUMBER,
        "head_sha": HEAD_SHA,
        "author": PR_AUTHOR,
    }


def test_verification_fails_closed_without_github_token(tmp_path: Path, monkeypatch):
    base, head, breaking = _schemas()
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "repository": {"full_name": EXPECTED_GITHUB_REPOSITORY},
                "pull_request": {
                    "number": PR_NUMBER,
                    "head": {"sha": HEAD_SHA},
                    "user": {"login": PR_AUTHOR},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", EXPECTED_GITHUB_REPOSITORY)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    errors = verify_authenticated_github_approval(
        base_schema=base,
        head_schema=head,
        breaking_changes=breaking,
        now=NOW,
    )
    assert errors == ["GITHUB_TOKEN is required to authenticate GitHub review data"]
