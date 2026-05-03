#!/usr/bin/env python3
"""Fail when tests send JSON bodies to query-only FastAPI routes."""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
HTTP_METHODS = {"delete", "get", "patch", "post", "put"}
ROUTE_PARAM_RE = re.compile(r"\{[^}/]+\}")


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    key: tuple[str, str]


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    route: Route

    def render(self) -> str:
        try:
            location = self.path.relative_to(REPO_ROOT)
        except ValueError:
            location = self.path
        return (
            f"{location}:{self.line}: route {self.route.method} {self.route.path} "
            "is query-only; replace json= with params="
        )


def main() -> int:
    schema = _load_openapi_schema()
    query_only_routes = collect_query_only_routes(schema)
    violations = scan_test_files(query_only_routes)

    if not violations:
        print("FastAPI query-only JSON body lint passed")
        return 0

    print("FastAPI query-only JSON body lint failed:", file=sys.stderr)
    for violation in violations:
        print(f"  {violation.render()}", file=sys.stderr)
    return 1


def _load_openapi_schema() -> dict:
    sys.path.insert(0, str(BACKEND_ROOT))
    from export_openapi import export_schema  # noqa: PLC0415

    return json.loads(export_schema())


def collect_query_only_routes(schema: dict) -> dict[tuple[str, str], Route]:
    manual_body_routes = _collect_manual_body_routes()
    query_only: dict[tuple[str, str], Route] = {}

    for path, operations in schema.get("paths", {}).items():
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            route = Route(method.upper(), path, _route_key(method, path))
            if "requestBody" in operation or route.key in manual_body_routes:
                continue
            query_only[route.key] = route

    return query_only


def scan_test_files(query_only_routes: dict[tuple[str, str], Route]) -> list[Violation]:
    violations: list[Violation] = []
    for test_file in _iter_test_files():
        violations.extend(scan_file(test_file, query_only_routes))
    return violations


def scan_file(
    path: Path,
    query_only_routes: dict[tuple[str, str], Route],
) -> list[Violation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = _http_method(node)
        if method is None or not _has_json_keyword(node):
            continue
        request_path = _request_path(node)
        if request_path is None:
            continue
        route = query_only_routes.get(_route_key(method, request_path))
        if route is not None:
            violations.append(Violation(path, node.lineno, route))

    return violations


def _collect_manual_body_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    routers_root = BACKEND_ROOT / "routers"
    if not routers_root.exists():
        return routes

    for source_path in routers_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _function_reads_request_body(node):
                continue
            routes.update(_decorated_routes(node))
    return routes


def _decorated_routes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        method = _decorator_method(decorator.func)
        if method is None or not decorator.args:
            continue
        path = _static_path(decorator.args[0])
        if path is not None:
            routes.add(_route_key(method, path))
    return routes


def _function_reads_request_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if child.func.attr in {"body", "json"}:
                return True
    return False


def _iter_test_files() -> list[Path]:
    roots = [BACKEND_ROOT / "tests", REPO_ROOT / "tests"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _http_method(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute) and node.func.attr in HTTP_METHODS:
        return node.func.attr
    return None


def _decorator_method(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr in HTTP_METHODS:
        return node.attr
    return None


def _has_json_keyword(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg == "json" and not _is_none(keyword.value):
            return True
    return False


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _request_path(node: ast.Call) -> str | None:
    if node.args:
        return _static_path(node.args[0])
    for keyword in node.keywords:
        if keyword.arg == "url":
            return _static_path(keyword.value)
    return None


def _static_path(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _normalize_path(node.value)
    if isinstance(node, ast.JoinedStr):
        chunks: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                chunks.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                chunks.append("{}")
            else:
                return None
        return _normalize_path("".join(chunks))
    return None


def _normalize_path(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme and parsed.netloc else value.split("?", 1)[0]
    return path.rstrip("/") or "/"


def _route_key(method: str, path: str) -> tuple[str, str]:
    return method.upper(), ROUTE_PARAM_RE.sub("{}", _normalize_path(path))


if __name__ == "__main__":
    raise SystemExit(main())
