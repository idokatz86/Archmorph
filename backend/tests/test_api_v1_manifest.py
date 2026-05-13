import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import app  # noqa: E402


MANIFEST_PATH = Path(__file__).resolve().parent.parent / "api_v1_mirror_exemptions.json"


def _build_route_index() -> set[tuple[str, str]]:
    indexed: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = set(route.methods or ()) - {"HEAD", "OPTIONS"}
        for method in methods:
            indexed.add((route.path, method))
    return indexed


def _load_exemptions() -> set[tuple[str, str]]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    exemptions = data.get("exemptions", [])
    parsed: set[tuple[str, str]] = set()
    for exemption in exemptions:
        path = exemption["path"]
        methods = exemption.get("methods", ["*"])
        for method in methods:
            parsed.add((path, method.upper()))
    return parsed


@pytest.mark.contract
def test_live_api_routes_have_v1_mirrors_or_documented_exemption():
    routes = _build_route_index()
    exemptions = _load_exemptions()
    missing: list[str] = []

    for path, method in sorted(routes):
        if not path.startswith("/api/") or path.startswith("/api/v1/"):
            continue
        mirror_path = f"/api/v1{path[4:]}"
        has_mirror = (mirror_path, method) in routes
        is_exempt = (path, method) in exemptions or (path, "*") in exemptions
        if not has_mirror and not is_exempt:
            missing.append(f"{method} {path} -> {method} {mirror_path}")

    assert not missing, (
        "Found unversioned /api routes without /api/v1 mirror and without exemption:\n"
        + "\n".join(missing)
    )
