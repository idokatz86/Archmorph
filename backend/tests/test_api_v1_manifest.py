import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import V1_ROUTE_SPECS, app  # noqa: E402


MANIFEST_PATH = Path(__file__).resolve().parent.parent / "api_v1_mirror_exemptions.json"


def _route_entries() -> list[tuple[str, str, APIRoute]]:
    indexed: list[tuple[str, str, APIRoute]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = set(route.methods or ()) - {"HEAD", "OPTIONS"}
        for method in methods:
            indexed.append((route.path, method, route))
    return indexed


def _build_route_index() -> set[tuple[str, str]]:
    return {(path, method) for path, method, _ in _route_entries()}


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


@pytest.mark.contract
def test_live_route_table_has_no_duplicate_method_paths():
    counts = Counter((path, method) for path, method, _ in _route_entries())
    duplicates = sorted(key for key, count in counts.items() if count > 1)
    assert not duplicates, "Duplicate runtime routes:\n" + "\n".join(
        f"{method} {path}" for path, method in duplicates
    )


@pytest.mark.contract
def test_live_route_table_has_no_parameter_alias_collisions():
    normalized = Counter(
        (re.sub(r"\{[^}]+\}", "{}", path), method)
        for path, method, _ in _route_entries()
    )
    collisions = sorted(key for key, count in normalized.items() if count > 1)
    assert not collisions, "Runtime routes differ only by path-parameter name:\n" + "\n".join(
        f"{method} {path}" for path, method in collisions
    )


@pytest.mark.contract
def test_v1_router_specs_are_explicit_and_compatibility_is_documented():
    assert V1_ROUTE_SPECS
    compatibility_specs = [spec for spec in V1_ROUTE_SPECS if spec.stability == "compatibility"]
    assert compatibility_specs
    assert all(spec.rationale.strip() for spec in compatibility_specs)

    router_ids = [id(spec.router) for spec in V1_ROUTE_SPECS]
    assert len(router_ids) == len(set(router_ids)), "A router is classified more than once in V1_ROUTE_SPECS"


@pytest.mark.contract
def test_representative_v1_routes_have_expected_classification():
    stability_by_router = {id(spec.router): spec.stability for spec in V1_ROUTE_SPECS}
    from main import health_router, roadmap_router

    assert stability_by_router[id(health_router)] == "public"
    assert stability_by_router[id(roadmap_router)] == "compatibility"


@pytest.mark.contract
def test_feature_flag_routes_keep_admin_api_grouping():
    routes = {(path, method): route for path, method, route in _route_entries()}

    assert "admin" in routes[("/api/flags", "GET")].tags
    assert "admin" in routes[("/api/v1/flags", "GET")].tags


@pytest.mark.contract
def test_version_route_family_uses_one_canonical_history(test_client):
    from routers.shared import SESSION_STORE
    from versioning import VERSION_STORE

    diagram_id = "route-coherence-version-history"
    VERSION_STORE.pop(diagram_id, None)
    SESSION_STORE.set(
        diagram_id,
        {
            "mappings": [
                {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 90},
            ],
        },
    )

    try:
        first = test_client.post(
            f"/api/diagrams/{diagram_id}/versions/save",
            json={"label": "initial"},
        )
        assert first.status_code == 200
        assert first.json()["version_number"] == 1

        session = SESSION_STORE.get(diagram_id)
        session["mappings"].append(
            {"source_service": "Lambda", "azure_service": "Functions", "confidence": 85},
        )
        SESSION_STORE.set(diagram_id, session)

        second = test_client.post(
            f"/api/diagrams/{diagram_id}/versions/save",
            json={"label": "add compute"},
        )
        assert second.status_code == 200
        assert second.json()["version_number"] == 2

        history = test_client.get(f"/api/diagrams/{diagram_id}/versions")
        assert history.status_code == 200
        assert history.json()["current_version"] == 2
        assert history.json()["total_versions"] == 2

        diff = test_client.get(f"/api/diagrams/{diagram_id}/diff?v1=1&v2=2")
        assert diff.status_code == 200
        assert diff.json()["summary"]["added"] == 1

        branch = test_client.post(
            f"/api/diagrams/{diagram_id}/versions/1/branch",
            json={"label": "what-if"},
        )
        assert branch.status_code == 200
        assert branch.json()["version_number"] == 3
        assert branch.json()["branched_from"] == 1
    finally:
        SESSION_STORE.delete(diagram_id)
        VERSION_STORE.pop(diagram_id, None)
