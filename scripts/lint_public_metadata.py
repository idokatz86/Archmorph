#!/usr/bin/env python3
"""Reject public source metadata that discloses environment-specific inventory."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "config/public-metadata-allowlist.json"
SKIP_PARTS = {
    ".git",
    ".terraform",
    "dist",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "test-results",
}
SKIP_PREFIXES = (
    "backend/tests/test_release_metadata_hygiene.py",
    "scripts/lint_public_metadata.py",
)
SKIP_NAMES = {
    "package-lock.json",
    ".terraform.lock.hcl",
}
FORBIDDEN_TRACKED_ARTIFACTS = {
    "backend/coverage_report.txt": "generated coverage report",
    "backend/failed_tests.txt": "generated test failure log",
    "doit.py": "environment-bound operator script",
}
AZURE_GENERATED_SUFFIXES = (
    ".azurecontainerapps.io",
    ".azurecr.io",
    ".azurefd.net",
    ".azurestaticapps.net",
    ".blob.core.windows.net",
    ".openai.azure.com",
    ".vault.azure.net",
)
URL_RE = re.compile(r"https?://[^\s\"'`\])}]+", re.IGNORECASE)
AZURE_HOST_RE = re.compile(
    r"(?<![A-Za-z0-9.-])([A-Za-z0-9][A-Za-z0-9.-]*"
    r"(?:\.azurecontainerapps\.io|\.azurecr\.io|\.azurefd\.net|"
    r"\.azurestaticapps\.net|\.blob\.core\.windows\.net|"
    r"\.openai\.azure\.com|\.vault\.azure\.net))",
    re.IGNORECASE,
)
TEMPLATED_AZURE_HOST_RE = re.compile(
    r"(?<![A-Za-z0-9.-])(?P<prefix>[A-Za-z0-9.-]*\$\{[^}\s]+\}[A-Za-z0-9.-]*)"
    r"(?P<suffix>\.azurecontainerapps\.io|\.azurecr\.io|\.azurefd\.net|"
    r"\.azurestaticapps\.net|\.blob\.core\.windows\.net|"
    r"\.openai\.azure\.com|\.vault\.azure\.net)",
    re.IGNORECASE,
)
LOCAL_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+/")
GUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
RESOURCE_ID_RE = re.compile(r"/subscriptions/([^/\s\"'`<>]+)/", re.IGNORECASE)
RESOURCE_FIELD_RE = re.compile(
    r"[\"'](?:resource_group|account_name|storage_account_name|container_app_name)[\"']"
    r"\s*:\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
YAML_RESOURCE_FIELD_RE = re.compile(
    r"^\s*(?:AZURE_RESOURCE_GROUP|ACR_NAME|CONTAINER_APP_NAME|CONTAINER_APP_ENV|"
    r"TFSTATE_RESOURCE_GROUP|TFSTATE_STORAGE_ACCOUNT)\s*:\s*([^#\n]+)",
    re.MULTILINE,
)
ENV_RESOURCE_RE = re.compile(
    r"\barchmorph-(?:rg-(?:dev|staging|prod)|openai-[a-z0-9-]{4,}|"
    r"cae-(?:dev|staging|prod)|api-(?:dev|staging|prod)-?[a-z0-9-]*)\b",
    re.IGNORECASE,
)
STATIC_TF_ENV_RE = re.compile(
    r"^\s*TF_VAR_(?:resource_group_environment|redis_name_override)\s*:\s*(?!\$\{\{)([^#\s]+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    category: str
    guidance: str


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().strip("`\"'").lower()
    placeholder_host = lowered.split("/", 1)[0].split(":", 1)[0]
    return (
        not lowered
        or lowered.startswith(("<", "${", "{", "example", "sample", "your", "configured"))
        or any(token in lowered for token in ("[^", "[a-", ".*", ".+"))
        or placeholder_host == "example.com"
        or placeholder_host.endswith(".example.com")
        or lowered == "00000000-0000-0000-0000-000000000000"
        or lowered == "000"
    )


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _load_allowlist(repo_root: Path = REPO_ROOT) -> tuple[set[str], set[str]]:
    payload = json.loads((repo_root / "config/public-metadata-allowlist.json").read_text(encoding="utf-8"))
    domains = payload.get("public_product_domains", [])
    if not domains or not payload.get("reviewed_on"):
        raise ValueError("Public metadata allowlist requires reviewed_on and at least one domain")
    identifiers = payload.get("public_platform_identifiers", [])
    return (
        {str(domain).lower().rstrip(".") for domain in domains},
        {str(identifier).lower() for identifier in identifiers},
    )


def scan_text(
    path: str,
    text: str,
    public_domains: set[str],
    public_identifiers: set[str] | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    public_identifiers = public_identifiers or set()

    for match in LOCAL_PATH_RE.finditer(text):
        violations.append(Violation(path, _line_number(text, match.start()), "operator-local-path", "use a repository-relative path or placeholder"))

    for match in TEMPLATED_AZURE_HOST_RE.finditer(text):
        concrete_prefix = re.sub(r"\$\{[^}]+\}", "", match.group("prefix")).strip(".-")
        if concrete_prefix:
            violations.append(Violation(path, _line_number(text, match.start()), "generated-azure-hostname", "replace the deployment hostname with a placeholder or configuration variable"))

    for match in URL_RE.finditer(text):
        raw_url = match.group(0).rstrip(".,;:")
        try:
            hostname = (urlsplit(raw_url).hostname or "").lower().rstrip(".")
        except ValueError:
            continue
        if not hostname:
            continue
        if ".privatelink." in hostname or hostname.startswith("privatelink."):
            continue
        if hostname.endswith(AZURE_GENERATED_SUFFIXES) and not _is_placeholder(hostname.split(".", 1)[0]):
            violations.append(Violation(path, _line_number(text, match.start()), "generated-azure-hostname", "replace the deployment hostname with a placeholder or configuration variable"))
        if "archmorph" in hostname and hostname not in public_domains and not hostname.endswith(".example.com"):
            violations.append(Violation(path, _line_number(text, match.start()), "unreviewed-product-domain", "replace with example.com or add an explicitly reviewed customer-facing domain to the allowlist"))

    for match in AZURE_HOST_RE.finditer(text):
        hostname = match.group(1).lower().rstrip(".")
        if ".privatelink." in hostname or hostname.startswith("privatelink."):
            continue
        prefix = hostname.removesuffix(next(suffix for suffix in AZURE_GENERATED_SUFFIXES if hostname.endswith(suffix)))
        if not _is_placeholder(prefix) and not any(
            item.path == path and item.line == _line_number(text, match.start()) and item.category == "generated-azure-hostname"
            for item in violations
        ):
            violations.append(Violation(path, _line_number(text, match.start()), "generated-azure-hostname", "replace the deployment hostname with a placeholder or configuration variable"))

    for match in GUID_RE.finditer(text):
        if (
            match.group(0) != "00000000-0000-0000-0000-000000000000"
            and match.group(0).lower() not in public_identifiers
        ):
            violations.append(Violation(path, _line_number(text, match.start()), "concrete-guid", "replace tenant, subscription, principal, or resource IDs with a zero/placeholder value"))

    for match in RESOURCE_ID_RE.finditer(text):
        if not _is_placeholder(match.group(1)):
            violations.append(Violation(path, _line_number(text, match.start()), "azure-resource-id", "replace the subscription/resource ID with a placeholder"))

    for pattern in (RESOURCE_FIELD_RE, YAML_RESOURCE_FIELD_RE):
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            if not _is_placeholder(value) and not value.startswith("${{"):
                violations.append(Violation(path, _line_number(text, match.start()), "concrete-resource-field", "move environment inventory to repository secrets/variables or private operator notes"))

    if path.endswith((".md", ".json")) or path == "backend/eval/model_bench.py":
        for match in ENV_RESOURCE_RE.finditer(text):
            if not _is_placeholder(match.group(0)):
                violations.append(Violation(path, _line_number(text, match.start()), "environment-resource-name", "replace the concrete Azure resource name with a role-based placeholder"))

    for match in STATIC_TF_ENV_RE.finditer(text):
        violations.append(Violation(path, _line_number(text, match.start()), "workflow-inventory-default", "source this production inventory value from a GitHub secret or variable"))

    return violations


def _source_files(repo_root: Path, *, include_untracked: bool = False) -> list[str]:
    git = shutil.which("git") or "/usr/bin/git"
    command = [git, "ls-files", "-z", "--cached"]
    if include_untracked:
        command.extend(("--others", "--exclude-standard"))
    completed = subprocess.run(
        command,
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def _should_scan(relative: str) -> bool:
    path = Path(relative)
    if relative in FORBIDDEN_TRACKED_ARTIFACTS:
        return False
    if any(relative.startswith(prefix) for prefix in SKIP_PREFIXES):
        return False
    if any(part in SKIP_PARTS for part in path.parts) or path.name in SKIP_NAMES:
        return False
    return True


def scan_repository(repo_root: Path = REPO_ROOT, *, include_untracked: bool = False) -> list[Violation]:
    tracked = _source_files(repo_root, include_untracked=include_untracked)
    tracked_set = set(tracked)
    violations = [
        Violation(path, 1, "forbidden-tracked-artifact", f"remove the {description} from source control")
        for path, description in FORBIDDEN_TRACKED_ARTIFACTS.items()
        if path in tracked_set and (repo_root / path).exists()
    ]
    public_domains, public_identifiers = _load_allowlist(repo_root)

    for relative in tracked:
        if not _should_scan(relative):
            continue
        path = repo_root / relative
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        violations.extend(scan_text(relative, text, public_domains, public_identifiers))

    for relative in ("infra/main.tf", "infra/staging/main.tf"):
        text = (repo_root / relative).read_text(encoding="utf-8")
        for block in re.finditer(r'backend\s+"azurerm"\s*\{(.*?)\}', text, re.DOTALL):
            if re.search(r"^\s*(?:resource_group_name|storage_account_name|container_name|key)\s*=", block.group(1), re.MULTILINE):
                violations.append(Violation(relative, _line_number(text, block.start()), "terraform-backend-inventory", "use partial backend configuration supplied by private CI/operator settings"))

    main_text = (repo_root / "backend/main.py").read_text(encoding="utf-8")
    if re.search(r"\bdefault_origins\s*=", main_text):
        violations.append(Violation("backend/main.py", 1, "cors-source-default", "derive non-development CORS origins exclusively from ALLOWED_ORIGINS"))

    return sorted(set(violations), key=lambda item: (item.path, item.line, item.category))


def main() -> int:
    include_untracked = "--include-untracked" in sys.argv[1:]
    unknown = [argument for argument in sys.argv[1:] if argument != "--include-untracked"]
    if unknown:
        print(f"Unknown arguments: {' '.join(unknown)}", file=sys.stderr)
        return 2
    try:
        violations = scan_repository(include_untracked=include_untracked)
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Public metadata lint error: {exc}", file=sys.stderr)
        return 1

    if violations:
        print("Public metadata hygiene violations:", file=sys.stderr)
        for violation in violations:
            print(
                f"  - {violation.path}:{violation.line} [{violation.category}] {violation.guidance}",
                file=sys.stderr,
            )
        return 1

    print("Public metadata hygiene passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
