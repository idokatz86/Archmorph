"""Review-only IaC patch artifacts for drift findings.

The patch builder is deterministic and never applies infrastructure changes.
When current IaC is supplied, simple scalar drift can become a real unified
diff against that file. Otherwise the builder emits a small review artifact
file that records the remediation intent in Terraform/Bicep syntax.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Any, Dict, Iterable, List, Literal, Optional

IacFormat = Literal["terraform", "bicep"]

TRACKED_PATCH_FIELDS = ("sku", "tier", "region", "location", "public_access", "encryption", "replication")
SECRET_MARKERS = ("password", "secret", "token", "api_key", "apikey", "connection_string", "access_key")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _is_secret_like(key: str, value: Any) -> bool:
    normalized_key = key.lower()
    if any(marker in normalized_key for marker in SECRET_MARKERS):
        return True
    text = _as_text(value)
    if not text:
        return False
    return bool(re.search(r"(?i)(password|secret|token|api[_-]?key|AccountKey=|SharedAccessKey=)", text))


def _safe_value(key: str, value: Any, warnings: List[str]) -> Any:
    if _is_secret_like(key, value):
        warning = f"Redacted secret-like value for {key}."
        if warning not in warnings:
            warnings.append(warning)
        return "[REDACTED]"
    return value


def _tf_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(_as_text(value))


def _bicep_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + _as_text(value).replace("'", "''") + "'"


def _changed_fields(finding: Dict[str, Any], warnings: List[str]) -> List[Dict[str, Any]]:
    designed = finding.get("designed_data") or {}
    live = finding.get("live_data") or {}
    changes: List[Dict[str, Any]] = []
    extra_secret_fields = sorted(
        key for key in set(designed) | set(live)
        if key not in TRACKED_PATCH_FIELDS and (_is_secret_like(key, designed.get(key)) or _is_secret_like(key, live.get(key)))
    )
    for field in (*TRACKED_PATCH_FIELDS, *extra_secret_fields):
        if field not in designed and field not in live:
            continue
        before = designed.get(field)
        after = live.get(field)
        if before == after:
            continue
        changes.append({
            "field": field,
            "from": _safe_value(field, before, warnings),
            "to": _safe_value(field, after, warnings),
        })
    return changes


def _finding_resource_id(finding: Dict[str, Any]) -> Any:
    live = finding.get("live_data") or {}
    designed = finding.get("designed_data") or {}
    if finding.get("status") == "red":
        return live.get("resource_id") or live.get("resourceId") or live.get("name") or finding.get("id")
    return (
        finding.get("id")
        or live.get("resource_id")
        or live.get("resourceId")
        or live.get("name")
        or designed.get("id")
        or designed.get("resource_id")
        or designed.get("name")
    )


def _replacement_candidates(field: str, before: Any, after: Any) -> Iterable[tuple[re.Pattern[str], str]]:
    before_text = re.escape(_as_text(before))
    terraform_after = _tf_literal(after)
    bicep_after = _bicep_literal(after)
    yield re.compile(rf"(\b{re.escape(field)}\s*=\s*)\"{before_text}\""), rf"\1{terraform_after}"
    yield re.compile(rf"(\b{re.escape(field)}\s*:\s*)'({before_text})'"), rf"\1{bicep_after}"
    if field == "region":
        yield from _replacement_candidates("location", before, after)


def _apply_simple_replacements(current_iac: str, changes: List[Dict[str, Any]]) -> tuple[str, List[str]]:
    updated = current_iac
    applied: List[str] = []
    for change in changes:
        if change["from"] == "[REDACTED]" or change["to"] == "[REDACTED]":
            continue
        for pattern, replacement in _replacement_candidates(change["field"], change["from"], change["to"]):
            updated_next, count = pattern.subn(replacement, updated, count=1)
            if count:
                updated = updated_next
                applied.append(change["field"])
                break
    return updated, applied


def _unified_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    if after and not after.endswith("\n"):
        after_lines[-1] += "\n"
    return "".join(difflib.unified_diff(before_lines, after_lines, fromfile=fromfile, tofile=tofile))


def _review_artifact(findings: List[Dict[str, Any]], iac_format: IacFormat, warnings: List[str]) -> str:
    entries = []
    for finding in findings:
        if finding.get("status") == "green":
            continue
        changes = _changed_fields(finding, warnings)
        entries.append({
            "id": _finding_resource_id(finding),
            "status": finding.get("status"),
            "message": finding.get("message"),
            "recommendation": finding.get("recommendation"),
            "changes": changes,
        })
    payload = json.dumps(entries, indent=2, sort_keys=True)
    if iac_format == "bicep":
        escaped = payload.replace("'''", "'' ''")
        return f"""// Archmorph drift remediation artifact. Review before applying changes.
var archmorphDriftRemediation = '''
{escaped}
'''
"""
    heredoc = payload.replace("EOT", "E_O_T")
    return f"""# Archmorph drift remediation artifact. Review before applying changes.
locals {{
  archmorph_drift_remediation = jsondecode(<<EOT
{heredoc}
EOT
  )
}}
"""


def build_drift_iac_patch(
    findings: List[Dict[str, Any]],
    *,
    current_iac: Optional[str] = None,
    iac_format: IacFormat = "terraform",
) -> Dict[str, Any]:
    """Build a deterministic, review-only IaC patch artifact from drift findings."""
    warnings: List[str] = []
    actionable = [finding for finding in findings if finding.get("status") != "green"]
    if not actionable:
        return {
            "format": iac_format,
            "patch": "",
            "validates": True,
            "review_only": True,
            "applied_changes": [],
            "warnings": [],
            "summary": "No drift findings require IaC changes.",
        }

    all_changes: List[Dict[str, Any]] = []
    for finding in actionable:
        for change in _changed_fields(finding, warnings):
            all_changes.append({"resource_id": finding.get("id"), **change})

    applied_changes: List[str] = []
    if current_iac:
        updated, applied_fields = _apply_simple_replacements(current_iac, all_changes)
        if updated != current_iac:
            applied_changes = applied_fields
            patch = _unified_diff(current_iac, updated, f"a/main.{ 'tf' if iac_format == 'terraform' else 'bicep'}", f"b/main.{ 'tf' if iac_format == 'terraform' else 'bicep'}")
            return {
                "format": iac_format,
                "patch": patch,
                "validates": not warnings,
                "review_only": True,
                "applied_changes": applied_changes,
                "warnings": warnings,
                "summary": f"Generated review diff for {len(applied_changes)} tracked drift field(s).",
            }
        warnings.append("No exact scalar replacements were found in the supplied IaC; emitted a remediation artifact instead.")

    artifact = _review_artifact(actionable, iac_format, warnings)
    extension = "tf" if iac_format == "terraform" else "bicep"
    patch = _unified_diff("", artifact, "/dev/null", f"b/archmorph-drift-remediation.{extension}")
    return {
        "format": iac_format,
        "patch": patch,
        "validates": not warnings,
        "review_only": True,
        "applied_changes": applied_changes,
        "warnings": warnings,
        "summary": f"Generated remediation artifact for {len(actionable)} drift finding(s).",
    }