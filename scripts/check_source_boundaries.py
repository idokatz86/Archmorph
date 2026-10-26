#!/usr/bin/env python3
"""Enforce backend and frontend source dependency direction."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

PYTHON_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "_archive",
    "htmlcov",
    "tests",
    "venv",
}
FRONTEND_EXCLUDED_DIRS = {
    "__tests__",
    "dist",
    "node_modules",
    "test",
}
FRONTEND_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")
@dataclass(frozen=True, order=True)
class Finding:
    finding_id: str
    ecosystem: str
    kind: str
    detail: str


@dataclass(frozen=True)
class CheckResult:
    findings: tuple[Finding, ...]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


def _is_source_file(path: Path, root: Path, extensions: tuple[str, ...], excluded: set[str]) -> bool:
    relative = path.relative_to(root)
    return path.suffix in extensions and not any(part in excluded for part in relative.parts)


def _iter_source_files(root: Path, extensions: tuple[str, ...], excluded: set[str]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and _is_source_file(path, root, extensions, excluded)
    )


def _python_module(path: Path, root: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _python_import_targets(
    node: ast.Import | ast.ImportFrom,
    source_module: str,
    is_package: bool,
    modules: dict[str, Path],
) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            target = _nearest_module(alias.name, modules)
            if target:
                targets.add(target)
        return targets

    if node.level:
        package = source_module.split(".") if is_package else source_module.split(".")[:-1]
        keep = len(package) - (node.level - 1)
        prefix = package[: max(keep, 0)]
    else:
        prefix = []

    if node.module:
        base = ".".join([*prefix, node.module])
        for alias in node.names:
            alias_module = f"{base}.{alias.name}"
            if alias_module in modules:
                targets.add(alias_module)
        target = _nearest_module(base, modules)
        if target:
            targets.add(target)
    else:
        for alias in node.names:
            target = _nearest_module(".".join([*prefix, alias.name]), modules)
            if target:
                targets.add(target)
    return targets


def build_python_graph(root: Path) -> dict[str, set[str]]:
    files = _iter_source_files(root, (".py",), PYTHON_EXCLUDED_DIRS)
    modules = {_python_module(path, root): path for path in files}
    graph = {module: set() for module in modules}

    for source, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        is_package = path.name == "__init__.py"
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            for target in _python_import_targets(node, source, is_package, modules):
                if target != source:
                    graph[source].add(target)
    return graph


def _nearest_module(candidate: str, modules: dict[str, Path]) -> str | None:
    current = candidate
    while current:
        if current in modules:
            return current
        current = current.rpartition(".")[0]
    return None


def _frontend_node(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _resolve_frontend_import(source: Path, specifier: str, root: Path) -> Path | None:
    if specifier.startswith("@/"):
        base = root / specifier[2:]
    elif specifier.startswith("."):
        base = source.parent / specifier
    else:
        return None

    candidates = [base]
    if not base.suffix:
        candidates.extend(base.with_suffix(extension) for extension in FRONTEND_EXTENSIONS)
        candidates.extend(base / f"index{extension}" for extension in FRONTEND_EXTENSIONS)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and root.resolve() in resolved.parents:
            return resolved
    return None


def _tokenize_frontend_source(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if char.isspace():
            index += 1
            continue
        if char == "/" and following == "/":
            newline = text.find("\n", index + 2)
            index = len(text) if newline == -1 else newline + 1
            continue
        if char == "/" and following == "*":
            closing = text.find("*/", index + 2)
            index = len(text) if closing == -1 else closing + 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            value: list[str] = []
            while index < len(text):
                char = text[index]
                if char == "\\":
                    if index + 1 < len(text):
                        value.append(text[index + 1])
                    index += 2
                    continue
                if char == quote:
                    index += 1
                    break
                value.append(char)
                index += 1
            tokens.append(("template" if quote == "`" else "string", "".join(value)))
            continue
        if char.isalpha() or char in {"_", "$"}:
            end = index + 1
            while end < len(text) and (
                text[end].isalnum() or text[end] in {"_", "$"}
            ):
                end += 1
            tokens.append(("identifier", text[index:end]))
            index = end
            continue
        tokens.append(("punctuation", char))
        index += 1
    return tokens


def _frontend_import_specifiers(text: str) -> set[str]:
    tokens = _tokenize_frontend_source(text)
    specifiers: set[str] = set()
    for index, (kind, value) in enumerate(tokens):
        if kind != "identifier" or value not in {"import", "export", "require"}:
            continue
        if value == "require":
            if (
                index + 3 < len(tokens)
                and tokens[index + 1] == ("punctuation", "(")
                and tokens[index + 2][0] == "string"
                and tokens[index + 3] == ("punctuation", ")")
            ):
                specifiers.add(tokens[index + 2][1])
            continue
        if (
            value == "import"
            and index + 3 < len(tokens)
            and tokens[index + 1] == ("punctuation", "(")
            and tokens[index + 2][0] == "string"
            and tokens[index + 3] == ("punctuation", ")")
        ):
            specifiers.add(tokens[index + 2][1])
            continue
        if index + 1 < len(tokens) and tokens[index + 1][0] == "string":
            specifiers.add(tokens[index + 1][1])
            continue
        cursor = index + 1
        while cursor + 1 < len(tokens):
            token_kind, token_value = tokens[cursor]
            if token_kind == "punctuation" and token_value == ";":
                break
            if token_kind == "identifier" and token_value in {"import", "export"}:
                break
            if (
                token_kind == "identifier"
                and token_value == "from"
                and tokens[cursor + 1][0] == "string"
            ):
                specifiers.add(tokens[cursor + 1][1])
                break
            cursor += 1
    return specifiers


def build_frontend_graph(root: Path) -> dict[str, set[str]]:
    files = _iter_source_files(root, FRONTEND_EXTENSIONS, FRONTEND_EXCLUDED_DIRS)
    graph = {_frontend_node(path, root): set() for path in files}

    for path in files:
        source = _frontend_node(path, root)
        text = path.read_text(encoding="utf-8")
        for specifier in _frontend_import_specifiers(text):
            target_path = _resolve_frontend_import(path, specifier, root)
            if target_path is None:
                continue
            target = _frontend_node(target_path, root)
            if target in graph and target != source:
                graph[source].add(target)
    return graph


def _backend_layer(module: str) -> str | None:
    parts = module.split(".")
    layer_by_segment = {
        "domain": "domain",
        "models": "domain",
        "application": "application",
        "services": "application",
        "infrastructure": "infrastructure",
        "repositories": "infrastructure",
        "platform": "infrastructure",
        "api": "api",
        "routers": "api",
        "bootstrap": "bootstrap",
    }
    return next((layer_by_segment[part] for part in parts if part in layer_by_segment), None)


def _frontend_layer(node: str) -> tuple[str | None, str | None, str | None]:
    parts = Path(node).parts
    if parts[0] == "app" or parts[0] in {"App.js", "App.jsx", "main.js", "main.jsx"}:
        return "app", None, None
    if parts[0] == "features" and len(parts) >= 2:
        sublayer = parts[2] if len(parts) >= 3 and parts[2] in {
            "api",
            "components",
            "model",
            "orchestration",
            "persistence",
        } else None
        return "feature", parts[1], sublayer
    if parts[0] == "components":
        return "feature", None, "components"
    if parts[0] == "shared" or parts[0] in {
        "generated",
        "hooks",
        "lib",
        "services",
        "stores",
        "utils",
    }:
        return "shared", None, None
    return None, None, None


def _direction_finding(ecosystem: str, source: str, target: str, rule: str) -> Finding:
    finding_id = f"direction|{ecosystem}|{source}->{target}|{rule}"
    return Finding(finding_id, ecosystem, "direction", f"{source} -> {target}: {rule}")


def find_backend_direction_violations(graph: dict[str, set[str]]) -> list[Finding]:
    allowed = {
        "domain": {"domain"},
        "application": {"application", "domain"},
        "infrastructure": {"infrastructure", "application", "domain"},
        "api": {"api", "application", "domain"},
        "bootstrap": {"bootstrap", "api", "infrastructure", "application", "domain"},
    }
    findings: list[Finding] = []
    for source, targets in graph.items():
        source_layer = _backend_layer(source)
        if source_layer is None:
            continue
        for target in targets:
            target_layer = _backend_layer(target)
            if target_layer is not None and target_layer not in allowed[source_layer]:
                findings.append(
                    _direction_finding(
                        "python",
                        source,
                        target,
                        f"{source_layer} must not depend on {target_layer}",
                    )
                )
    return findings


def _is_feature_contract(target: str) -> bool:
    path = Path(target)
    return (
        len(path.parts) == 3
        and path.parts[0] == "features"
        and path.stem in {"contract", "index"}
    )


def find_frontend_direction_violations(graph: dict[str, set[str]]) -> list[Finding]:
    findings: list[Finding] = []
    sublayer_allowed = {
        "api": {"api"},
        "model": {"api", "model"},
        "orchestration": {"api", "model", "orchestration", "persistence"},
        "persistence": {"api", "model", "persistence"},
        "components": {"api", "components", "model", "orchestration", "persistence"},
    }
    for source, targets in graph.items():
        source_layer, source_feature, source_sublayer = _frontend_layer(source)
        for target in targets:
            target_layer, target_feature, target_sublayer = _frontend_layer(target)
            if source_layer == "shared" and target_layer in {"app", "feature"}:
                findings.append(
                    _direction_finding(
                        "frontend",
                        source,
                        target,
                        f"shared must not depend on {target_layer}",
                    )
                )
            elif source_layer == "feature" and target_layer == "app":
                findings.append(
                    _direction_finding(
                        "frontend",
                        source,
                        target,
                        "feature must not depend on app",
                    )
                )
            elif (
                source_layer == target_layer == "feature"
                and source_feature
                and target_feature
                and source_feature != target_feature
                and not _is_feature_contract(target)
            ):
                findings.append(
                    _direction_finding(
                        "frontend",
                        source,
                        target,
                        "feature internals must not cross feature boundaries",
                    )
                )
            elif (
                source_layer == target_layer == "feature"
                and source_feature == target_feature
                and source_sublayer in sublayer_allowed
                and target_sublayer
                and target_sublayer not in sublayer_allowed[source_sublayer]
            ):
                findings.append(
                    _direction_finding(
                        "frontend",
                        source,
                        target,
                        f"feature {source_sublayer} must not depend on {target_sublayer}",
                    )
                )
    return findings


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for target in sorted(graph.get(node, ())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])

        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def find_cycles(ecosystem: str, graph: dict[str, set[str]]) -> list[Finding]:
    findings = []
    for component in _strongly_connected_components(graph):
        members = ",".join(component)
        findings.append(
            Finding(
                f"cycle|{ecosystem}|{members}",
                ecosystem,
                "cycle",
                f"dependency cycle: {' -> '.join(component)}",
            )
        )
    return findings


def collect_findings(repo_root: Path) -> tuple[Finding, ...]:
    python_graph = build_python_graph(repo_root / "backend")
    frontend_graph = build_frontend_graph(repo_root / "frontend" / "src")
    findings = [
        *find_backend_direction_violations(python_graph),
        *find_frontend_direction_violations(frontend_graph),
        *find_cycles("python", python_graph),
        *find_cycles("frontend", frontend_graph),
    ]
    return tuple(sorted(set(findings)))


def reconcile_exceptions(
    findings: Iterable[Finding],
    manifest: dict,
    *,
    today: date,
) -> CheckResult:
    findings_by_id = {finding.finding_id: finding for finding in findings}
    errors: list[str] = []

    if manifest.get("version") != 1:
        errors.append("exception manifest version must be 1")
    exceptions = manifest.get("exceptions")
    if not isinstance(exceptions, list):
        return CheckResult(tuple(findings_by_id.values()), tuple([*errors, "exceptions must be a list"]))

    exception_ids: set[str] = set()
    required = ("id", "owner", "rationale", "removal_reference", "expires_on")
    for index, exception in enumerate(exceptions):
        label = f"exception[{index}]"
        if not isinstance(exception, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in required:
            if not isinstance(exception.get(field), str) or not exception[field].strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        finding_id = exception.get("id")
        if not isinstance(finding_id, str) or not finding_id:
            continue
        if finding_id in exception_ids:
            errors.append(f"duplicate exception id: {finding_id}")
        exception_ids.add(finding_id)
        try:
            expiry = date.fromisoformat(exception.get("expires_on", ""))
        except ValueError:
            errors.append(f"{finding_id}: expires_on must use YYYY-MM-DD")
        else:
            if expiry < today:
                errors.append(f"{finding_id}: exception expired on {expiry.isoformat()}")

    for finding_id in sorted(findings_by_id.keys() - exception_ids):
        errors.append(f"unbaselined violation: {finding_id}")
    for finding_id in sorted(exception_ids - findings_by_id.keys()):
        errors.append(f"stale exception (remove it): {finding_id}")

    return CheckResult(tuple(sorted(findings_by_id.values())), tuple(errors))


def run_check(repo_root: Path, manifest_path: Path, *, today: date | None = None) -> CheckResult:
    findings = collect_findings(repo_root)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult(findings, (f"cannot load exception manifest: {exc}",))
    if not isinstance(manifest, dict):
        return CheckResult(findings, ("exception manifest root must be an object",))
    return reconcile_exceptions(findings, manifest, today=today or date.today())


def _parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=default_root / "docs" / "architecture" / "source-boundary-exceptions.json",
    )
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_check(args.root.resolve(), args.manifest.resolve(), today=args.today)
    if args.json_output:
        print(
            json.dumps(
                {
                    "passed": result.passed,
                    "findings": [finding.__dict__ for finding in result.findings],
                    "errors": list(result.errors),
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif result.passed:
        print(f"Source boundary check passed ({len(result.findings)} baselined exceptions)")
    else:
        print("Source boundary check failed:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
