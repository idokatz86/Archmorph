"""Runtime/OpenAPI classification for effectful HTTP routes.

Effect metadata is attached to the registered route itself. The independent AST
classifier exists so tests can reject both an unclassified effectful GET and
stale metadata on a now-pure GET.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
import inspect
import textwrap
from typing import Any, Optional

EFFECT_SCOPE_EXTENSION = "x-archmorph-effect-scope"
EFFECTS_EXTENSION = "x-archmorph-effects"

_ALLOWED_SCOPES = frozenset({"write", "admin"})
_ALLOWED_EFFECTS = frozenset(
    {
        "artifact",
        "cache",
        "capability",
        "file",
        "job",
        "sql",
        "telemetry",
    }
)

_CALL_EFFECTS = {
    "consume_export_capability": "capability",
    "create_export_artifact": "artifact",
    "issue_export_capability_for_request": "capability",
    "persist_diagram_mutation": "sql",
    "persist_diagram_mutation_async": "sql",
    "persist_generated_export_async": "artifact",
    "record_event": "telemetry",
    "record_funnel_step": "telemetry",
}


def write_route_effects(*effects: str) -> dict[str, Any]:
    """Return validated OpenAPI metadata for a write-effect GET/HEAD route."""
    normalized = sorted({str(effect) for effect in effects})
    unknown = set(normalized) - _ALLOWED_EFFECTS
    if not normalized or unknown:
        raise ValueError(f"Unsupported or empty route effects: {sorted(unknown)}")
    return {
        EFFECT_SCOPE_EXTENSION: "write",
        EFFECTS_EXTENSION: normalized,
    }


def runtime_route_effect_scope(route: object, method: str) -> Optional[str]:
    """Return the registered route's explicit effect scope, if any."""
    if method.upper() not in set(getattr(route, "methods", ()) or ()):
        return None
    extra = getattr(route, "openapi_extra", None) or {}
    scope = extra.get(EFFECT_SCOPE_EXTENSION)
    if scope is None:
        return None
    if scope not in _ALLOWED_SCOPES:
        raise RuntimeError(f"Invalid runtime route effect scope: {scope!r}")
    return str(scope)


def runtime_route_effects(route: object) -> frozenset[str]:
    """Return validated effects attached to a registered runtime route."""
    extra = getattr(route, "openapi_extra", None) or {}
    effects = frozenset(str(value) for value in extra.get(EFFECTS_EXTENSION, []))
    unknown = effects - _ALLOWED_EFFECTS
    if unknown:
        raise RuntimeError(f"Invalid runtime route effects: {sorted(unknown)}")
    return effects


def _call_name(node: ast.Call) -> tuple[str, str]:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id, function.id
    if not isinstance(function, ast.Attribute):
        return "", ""

    parts = [function.attr]
    value = function.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    qualified = ".".join(reversed(parts))
    return qualified, function.attr


def _reference_leaf(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _file_write_call(node: ast.Call, leaf: str) -> bool:
    if leaf in {"write_text", "write_bytes", "replace", "rename"}:
        return True
    if leaf != "open":
        return False
    mode: object = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return isinstance(mode, str) and any(flag in mode for flag in "wax+")


def classify_endpoint_effects(endpoint: object) -> frozenset[str]:
    """Independently classify direct durable/cache/telemetry effects via AST."""
    function = inspect.unwrap(endpoint)
    try:
        source = inspect.getsource(function)
    except (OSError, TypeError):
        return frozenset()
    try:
        tree = ast.parse(textwrap.dedent(source))
    except (IndentationError, SyntaxError):
        return frozenset()

    effects: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified, leaf = _call_name(node)
        effect = _CALL_EFFECTS.get(leaf)
        if effect:
            effects.add(effect)
        for argument in node.args:
            referenced_effect = _CALL_EFFECTS.get(_reference_leaf(argument))
            if referenced_effect:
                effects.add(referenced_effect)
        if leaf in {
            "persist_diagram_mutation",
            "persist_diagram_mutation_async",
        } and any(keyword.arg == "artifact_type" for keyword in node.keywords):
            effects.add("artifact")
        if leaf in {"upload_blob", "delete_blob"}:
            effects.add("artifact")
        if leaf in {"enqueue", "submit", "complete", "fail"} and any(
            marker in qualified.lower() for marker in ("job", "queue", "executor")
        ):
            effects.add("job")
        if leaf in {"set", "delete", "update_if"} and any(
            marker in qualified.lower() for marker in ("cache", "store")
        ):
            effects.add("cache")
        if leaf in {"add", "commit", "flush", "delete", "execute"} and any(
            marker in qualified.lower() for marker in ("db", "session")
        ):
            effects.add("sql")
        if _file_write_call(node, leaf):
            effects.add("file")
    return frozenset(effects)


def validate_effect_names(effects: Iterable[str]) -> None:
    """Validate an externally assembled effect set."""
    unknown = set(effects) - _ALLOWED_EFFECTS
    if unknown:
        raise ValueError(f"Unsupported route effects: {sorted(unknown)}")
