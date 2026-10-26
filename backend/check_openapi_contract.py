#!/usr/bin/env python3
"""Fail CI on OpenAPI drift and unapproved breaking changes.

Checks:
- Generated schema must match the committed snapshot.
- Snapshot must remain compatible with base-branch snapshot for PRs.
- Breaking changes against base require explicit approval metadata.
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from export_openapi import export_schema


ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT / "openapi.snapshot.json"
EXPECTED_GITHUB_REPOSITORY = "idokatz86/Archmorph"
AUTHORIZED_GITHUB_APPROVERS = frozenset({"idokatz86"})
APPROVAL_VERSION = 1
APPROVAL_ATTESTATION_PREFIX = "OpenAPI-Breaking-Change-Approval:"
REQUIRED_APPROVAL_ATTESTATION_FIELDS = (
    "version",
    "repository",
    "pull_request",
    "base_schema_sha256",
    "head_schema_sha256",
    "break_ids",
    "expires_at",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    args = _parse_args()

    try:
        expected = _normalized_lines(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        sys.stderr.write(f"OpenAPI snapshot not found or unreadable: {SNAPSHOT_PATH}\n")
        sys.stderr.write("Generate it with: cd backend && python export_openapi.py > openapi.snapshot.json\n")
        sys.stderr.write(f"Original error: {exc}\n")
        return 1

    current_schema_raw = _read_current_schema(args.generated_schema_path)
    current = _normalized_lines(current_schema_raw)

    expected_schema = json.loads("".join(expected))
    # CI sets ARCHMORPH_OPENAPI_BASE_SNAPSHOT on pull_request runs to enforce
    # compatibility between the base branch snapshot and this branch snapshot.
    base_snapshot_path = args.base_snapshot_path or os.getenv("ARCHMORPH_OPENAPI_BASE_SNAPSHOT")
    if base_snapshot_path:
        base_path = Path(base_snapshot_path)
        if base_path.exists():
            base_schema = json.loads(base_path.read_text(encoding="utf-8"))
            breaking_changes = detect_breaking_changes(base_schema, expected_schema)
            if breaking_changes:
                approval_errors = verify_authenticated_github_approval(
                    base_schema=base_schema,
                    head_schema=expected_schema,
                    breaking_changes=breaking_changes,
                )
                if approval_errors:
                    _write_breaking_change_failure(
                        breaking_changes,
                        approval_errors,
                        base_path,
                        base_schema,
                        expected_schema,
                    )
                    return 1
        else:
            sys.stderr.write(
                f"Warning: ARCHMORPH_OPENAPI_BASE_SNAPSHOT not found: {base_path}. "
                "Skipping base-branch compatibility check.\n"
            )

    if current == expected:
        print("OpenAPI contract matches backend/openapi.snapshot.json")
        return 0

    diff = difflib.unified_diff(
        expected,
        current,
        fromfile="backend/openapi.snapshot.json",
        tofile="generated-openapi.json",
        n=3,
    )
    sys.stderr.write("OpenAPI contract drift detected.\n")
    sys.stderr.write("If this API change is intentional, regenerate the snapshot with:\n")
    sys.stderr.write("  cd backend && python export_openapi.py > openapi.snapshot.json\n\n")
    sys.stderr.writelines(diff)
    return 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "generated_schema_path",
        nargs="?",
        help="Optional path to a generated OpenAPI schema JSON file.",
    )
    parser.add_argument(
        "--base-snapshot-path",
        dest="base_snapshot_path",
        default=None,
        help=(
            "Optional path to a base-branch OpenAPI snapshot. "
            "When provided, breaking changes from base->snapshot require metadata."
        ),
    )
    return parser.parse_args()


def _read_current_schema(schema_path: str | None) -> str:
    if schema_path:
        return Path(schema_path).read_text(encoding="utf-8")
    return export_schema()


def _normalized_lines(value: str) -> list[str]:
    return f"{value.rstrip()}\n".splitlines(keepends=True)


def detect_breaking_changes(base_schema: dict, target_schema: dict) -> list[str]:
    """Detect coarse breaking changes between two OpenAPI schemas."""
    breaks: list[str] = []
    base_paths = base_schema.get("paths", {})
    target_paths = target_schema.get("paths", {})
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

    for path, base_ops in base_paths.items():
        target_ops = target_paths.get(path)
        if target_ops is None:
            breaks.append(f"Removed path: {path}")
            continue

        for method, base_op in base_ops.items():
            if method not in http_methods:
                continue
            target_op = target_ops.get(method)
            if target_op is None:
                breaks.append(f"Removed operation: {method.upper()} {path}")
                continue

            base_success = _extract_success_codes(base_op)
            target_success = _extract_success_codes(target_op)
            removed_success = sorted(base_success - target_success)
            if removed_success:
                breaks.append(
                    f"Removed success response(s) on {method.upper()} {path}: {', '.join(removed_success)}"
                )

    base_components = base_schema.get("components", {}).get("schemas", {})
    target_components = target_schema.get("components", {}).get("schemas", {})
    for schema_name, base_def in base_components.items():
        target_def = target_components.get(schema_name)
        if target_def is None:
            breaks.append(f"Removed component schema: {schema_name}")
            continue
        if not isinstance(base_def, dict) or not isinstance(target_def, dict):
            continue
        if base_def.get("type") != "object" or target_def.get("type") != "object":
            continue

        base_props = set((base_def.get("properties") or {}).keys())
        target_props = set((target_def.get("properties") or {}).keys())
        removed_props = sorted(base_props - target_props)
        if removed_props:
            breaks.append(f"Removed schema properties from {schema_name}: {', '.join(removed_props)}")

        base_required = set(base_def.get("required") or [])
        target_required = set(target_def.get("required") or [])
        removed_required = sorted(base_required - target_required)
        if removed_required:
            breaks.append(
                f"Removed required properties from {schema_name}: {', '.join(removed_required)}"
            )

    return breaks


def schema_sha256(schema: dict) -> str:
    payload = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def breaking_change_id(breaking_change: str) -> str:
    digest = hashlib.sha256(breaking_change.encode("utf-8")).hexdigest()
    return f"openapi-break-v1:{digest}"


def verify_authenticated_github_approval(
    *,
    base_schema: dict,
    head_schema: dict,
    breaking_changes: list[str],
    now: datetime | None = None,
) -> list[str]:
    context, context_errors = _current_pull_request_context()
    if context_errors:
        return context_errors

    repository = context["repository"]
    pull_request_number = context["pull_request"]
    head_sha = context["head_sha"]
    pull_request_author = context["author"]
    if repository != EXPECTED_GITHUB_REPOSITORY:
        return [
            f"GitHub event repository is not trusted: {repository!r}; "
            f"expected {EXPECTED_GITHUB_REPOSITORY!r}"
        ]
    if os.getenv("GITHUB_REPOSITORY") != EXPECTED_GITHUB_REPOSITORY:
        return [
            "GITHUB_REPOSITORY does not match the trusted repository "
            f"{EXPECTED_GITHUB_REPOSITORY!r}"
        ]

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        return ["GITHUB_TOKEN is required to authenticate GitHub review data"]

    try:
        reviews = _fetch_github_reviews(
            repository=repository,
            pull_request_number=pull_request_number,
            token=github_token,
        )
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return [f"Unable to retrieve authenticated GitHub reviews: {exc}"]

    return validate_authenticated_github_reviews(
        reviews,
        repository=repository,
        pull_request_number=pull_request_number,
        head_sha=head_sha,
        pull_request_author=pull_request_author,
        authorized_approvers=_authorized_github_approvers(),
        base_schema=base_schema,
        head_schema=head_schema,
        breaking_changes=breaking_changes,
        now=now,
    )


def validate_authenticated_github_reviews(
    reviews: object,
    *,
    repository: str,
    pull_request_number: int,
    head_sha: str,
    pull_request_author: str,
    authorized_approvers: set[str],
    base_schema: dict,
    head_schema: dict,
    breaking_changes: list[str],
    now: datetime | None = None,
) -> list[str]:
    if repository != EXPECTED_GITHUB_REPOSITORY:
        return [f"Repository is not trusted: {repository!r}"]
    if not isinstance(reviews, list):
        return ["GitHub reviews response must be a JSON array"]

    authorized = {login.casefold() for login in authorized_approvers}
    authorized.discard(pull_request_author.casefold())
    if not authorized:
        return [
            "No independent authorized API approver is configured for this pull request author"
        ]
    latest_reviews: dict[str, dict] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(login, str) or login.casefold() not in authorized:
            continue
        if review.get("state") not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        previous = latest_reviews.get(login.casefold())
        if previous is None or _review_sort_key(review) > _review_sort_key(previous):
            latest_reviews[login.casefold()] = review

    rejection_reasons: list[str] = []
    for login, review in latest_reviews.items():
        if review.get("state") != "APPROVED":
            rejection_reasons.append(
                f"Latest review from authorized approver {login!r} is not APPROVED"
            )
            continue
        if review.get("commit_id") != head_sha:
            rejection_reasons.append(
                f"Approval from {login!r} is stale for current head {head_sha}"
            )
            continue
        if not _is_trusted_review_url(
            review.get("html_url"), repository, pull_request_number
        ):
            rejection_reasons.append(
                f"Approval from {login!r} has an untrusted GitHub review URL"
            )
            continue

        attestation, attestation_errors = _parse_review_attestation(review.get("body"))
        if attestation_errors:
            rejection_reasons.extend(
                f"Approval from {login!r}: {error}" for error in attestation_errors
            )
            continue
        binding_errors = _validate_review_attestation(
            attestation,
            repository=repository,
            pull_request_number=pull_request_number,
            base_schema=base_schema,
            head_schema=head_schema,
            breaking_changes=breaking_changes,
            now=now,
        )
        if not binding_errors:
            return []
        rejection_reasons.extend(
            f"Approval from {login!r}: {error}" for error in binding_errors
        )

    if not latest_reviews:
        return ["No authenticated review exists from an authorized API approver"]
    return rejection_reasons or [
        "No authorized GitHub review contains valid breaking-change approval evidence"
    ]


def _validate_review_attestation(
    metadata: dict,
    *,
    repository: str,
    pull_request_number: int,
    base_schema: dict,
    head_schema: dict,
    breaking_changes: list[str],
    now: datetime | None,
) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_APPROVAL_ATTESTATION_FIELDS:
        if field not in metadata:
            errors.append(f"Missing required attestation field: {field}")
    if errors:
        return errors

    if metadata["version"] != APPROVAL_VERSION:
        errors.append(
            f"Unsupported approval evidence version: {metadata['version']!r}; "
            f"expected {APPROVAL_VERSION}"
        )
    if metadata["repository"] != repository:
        errors.append("Attested repository does not match the current repository")
    if metadata["pull_request"] != pull_request_number:
        errors.append("Attested pull_request does not match the current PR")

    _validate_hash_binding(
        errors,
        metadata,
        field="base_schema_sha256",
        expected=schema_sha256(base_schema),
    )
    _validate_hash_binding(
        errors,
        metadata,
        field="head_schema_sha256",
        expected=schema_sha256(head_schema),
    )

    expected_break_ids = {breaking_change_id(item) for item in breaking_changes}
    actual_break_ids = metadata["break_ids"]
    if (
        not isinstance(actual_break_ids, list)
        or not actual_break_ids
        or not all(isinstance(item, str) and item.strip() for item in actual_break_ids)
    ):
        errors.append("break_ids must be a non-empty list of strings")
    elif len(actual_break_ids) != len(set(actual_break_ids)):
        errors.append("break_ids must not contain duplicates")
    elif set(actual_break_ids) != expected_break_ids:
        errors.append(
            "Attested break_ids do not exactly match detected breaking changes; "
            f"expected {sorted(expected_break_ids)!r}"
        )

    expiry = _parse_utc_timestamp(metadata["expires_at"])
    if expiry is None:
        errors.append("expires_at must be an ISO 8601 UTC timestamp")
    elif expiry <= (now or datetime.now(timezone.utc)):
        errors.append(f"Approval evidence expired at {metadata['expires_at']}")
    return errors


def _parse_review_attestation(body: object) -> tuple[dict, list[str]]:
    if not isinstance(body, str):
        return {}, ["Review body does not contain approval attestation"]
    matching_lines = [
        line[len(APPROVAL_ATTESTATION_PREFIX) :].strip()
        for line in body.splitlines()
        if line.startswith(APPROVAL_ATTESTATION_PREFIX)
    ]
    if len(matching_lines) != 1:
        return {}, ["Review body must contain exactly one approval attestation line"]
    try:
        attestation = json.loads(matching_lines[0])
    except json.JSONDecodeError as exc:
        return {}, [f"Approval attestation is not valid JSON: {exc}"]
    if not isinstance(attestation, dict):
        return {}, ["Approval attestation must be a JSON object"]
    return attestation, []


def _fetch_github_reviews(
    *, repository: str, pull_request_number: int, token: str
) -> list[dict]:
    reviews: list[dict] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repository}/pulls/"
            f"{pull_request_number}/reviews?per_page=100&page={page}"
        )
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
        if not isinstance(payload, list):
            raise ValueError("GitHub reviews API returned a non-array response")
        reviews.extend(payload)
        if len(payload) < 100:
            return reviews
        page += 1


def _authorized_github_approvers() -> set[str]:
    configured = {
        login.strip()
        for login in os.getenv("ARCHMORPH_OPENAPI_APPROVERS", "").split(",")
        if login.strip()
    }
    return {*AUTHORIZED_GITHUB_APPROVERS, *configured}


def _review_sort_key(review: dict) -> tuple[str, int]:
    submitted_at = review.get("submitted_at")
    review_id = review.get("id")
    return (
        submitted_at if isinstance(submitted_at, str) else "",
        review_id if isinstance(review_id, int) else 0,
    )


def _is_trusted_review_url(value: object, repository: str, pull_request_number: int) -> bool:
    if not isinstance(value, str):
        return False
    prefix = f"https://github.com/{repository}/pull/{pull_request_number}#pullrequestreview-"
    return value.startswith(prefix) and value[len(prefix) :].isdigit()


def _validate_hash_binding(
    errors: list[str], metadata: dict, *, field: str, expected: str
) -> None:
    actual = metadata[field]
    if not isinstance(actual, str) or not SHA256_PATTERN.fullmatch(actual):
        errors.append(f"{field} must be a lowercase SHA-256 hex digest")
    elif actual != expected:
        errors.append(f"{field} does not match the current schema: {actual} != {expected}")


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timedelta(0)
    ):
        return None
    return parsed


def _current_pull_request_context() -> tuple[dict, list[str]]:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return {}, ["GITHUB_EVENT_PATH is required for breaking-change approval"]
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"Unable to read GitHub pull request event: {exc}"]
    if not isinstance(event, dict):
        return {}, ["GitHub event must be a JSON object"]

    repository = event.get("repository")
    pull_request = event.get("pull_request")
    repository_name = (
        repository.get("full_name") if isinstance(repository, dict) else None
    )
    pull_request_number = (
        pull_request.get("number") if isinstance(pull_request, dict) else None
    )
    head = pull_request.get("head") if isinstance(pull_request, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None
    author = pull_request.get("user") if isinstance(pull_request, dict) else None
    author_login = author.get("login") if isinstance(author, dict) else None

    errors: list[str] = []
    if not isinstance(repository_name, str) or not repository_name:
        errors.append("GitHub event repository.full_name is missing")
    if (
        not isinstance(pull_request_number, int)
        or isinstance(pull_request_number, bool)
        or pull_request_number <= 0
    ):
        errors.append("GitHub event pull_request.number is invalid")
    if (
        not isinstance(head_sha, str)
        or re.fullmatch(r"[0-9a-f]{40,64}", head_sha) is None
    ):
        errors.append("GitHub event pull_request.head.sha is invalid")
    if not isinstance(author_login, str) or not author_login:
        errors.append("GitHub event pull_request.user.login is missing")
    if errors:
        return {}, errors
    return {
        "repository": repository_name,
        "pull_request": pull_request_number,
        "head_sha": head_sha,
        "author": author_login,
    }, []


def _extract_success_codes(operation: dict) -> set[str]:
    return {str(code) for code in operation.get("responses", {}) if str(code).startswith("2")}


def _write_breaking_change_failure(
    breaking_changes: list[str],
    approval_errors: list[str],
    base_snapshot_path: Path,
    base_schema: dict,
    head_schema: dict,
) -> None:
    sys.stderr.write(
        "OpenAPI breaking changes detected against base snapshot "
        f"({base_snapshot_path}).\n"
    )
    for item in breaking_changes:
        sys.stderr.write(f"  - {breaking_change_id(item)}: {item}\n")
    sys.stderr.write(
        "\nBreaking changes require an authenticated GitHub review from an "
        "authorized API approver.\n"
        f"  - repository: {EXPECTED_GITHUB_REPOSITORY}\n"
        f"  - base_schema_sha256: {schema_sha256(base_schema)}\n"
        f"  - head_schema_sha256: {schema_sha256(head_schema)}\n"
    )
    for error in approval_errors:
        sys.stderr.write(f"  - {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
