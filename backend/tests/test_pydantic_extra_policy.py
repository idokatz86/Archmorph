"""Regression coverage for strict API-boundary Pydantic models (#614)."""

from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOTS = (BACKEND_ROOT / "routers", BACKEND_ROOT / "services")


class _ModelVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        base_names = {_base_name(base) for base in node.bases}
        if "BaseModel" in base_names:
            extra_policy = _class_extra_policy(node)
            if extra_policy not in {"allow", "forbid"}:
                self.violations.append(
                    f"line {node.lineno}: {node.name} directly inherits BaseModel "
                    "without explicit extra='forbid' or extra='allow'"
                )
        self.generic_visit(node)


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _class_extra_policy(node: ast.ClassDef) -> str | None:
    for statement in node.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "model_config" for target in statement.targets):
            continue
        return _config_extra_value(statement.value)
    return None


def _config_extra_value(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call) and _base_name(node.func) == "ConfigDict":
        for keyword in node.keywords:
            if keyword.arg == "extra" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return None


def _audited_python_files() -> list[Path]:
    files: list[Path] = []
    for root in AUDIT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "_archive" in path.parts or "__pycache__" in path.parts:
                continue
            files.append(path)
    return sorted(files)


def _contains_extra_forbidden(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "extra_forbidden":
            return True
        return any(_contains_extra_forbidden(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_extra_forbidden(item) for item in value)
    return False


def test_router_and_service_models_use_strict_base_or_explicit_extra_policy():
    violations: list[str] = []
    for path in _audited_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _ModelVisitor()
        visitor.visit(tree)
        violations.extend(
            f"{path.relative_to(BACKEND_ROOT)}:{violation}"
            for violation in visitor.violations
        )

    assert not violations, "\n".join(violations)


def test_create_webhook_rejects_unknown_request_fields(test_client):
    response = test_client.post(
        "/api/webhooks",
        json={
            "url": "https://example.com/webhook",
            "events": ["analysis.completed"],
            "description": "strict boundary check",
            "unexpected_admin": True,
        },
    )

    assert response.status_code == 422
    assert _contains_extra_forbidden(response.json())
