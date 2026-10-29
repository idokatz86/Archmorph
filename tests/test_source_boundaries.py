from datetime import date
import json
from pathlib import Path

from scripts.check_source_boundaries import (
    Finding,
    collect_findings,
    reconcile_exceptions,
    run_check,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _manifest(exception_id: str, *, expires_on: str = "2099-01-01") -> dict:
    return {
        "version": 1,
        "exceptions": [
            {
                "id": exception_id,
                "owner": "@architecture-owner",
                "rationale": "Legacy dependency pending extraction.",
                "removal_reference": "ARC-001",
                "expires_on": expires_on,
            }
        ],
    }


def test_collects_backend_direction_violation_and_cycle(tmp_path):
    _write(tmp_path / "backend/services/orders.py", "from routers import orders\n")
    _write(tmp_path / "backend/routers/orders.py", "from services import orders\n")

    findings = collect_findings(tmp_path)

    assert any(
        finding.kind == "direction"
        and "services.orders->routers.orders" in finding.finding_id
        for finding in findings
    )
    assert any(
        finding.kind == "cycle"
        and "routers.orders,services.orders" in finding.finding_id
        for finding in findings
    )


def test_collects_every_import_from_alias_target(tmp_path):
    _write(
        tmp_path / "backend/services/orders.py",
        "from routers import first, second\n",
    )
    _write(tmp_path / "backend/routers/first.py", "ROUTER = 'first'\n")
    _write(
        tmp_path / "backend/routers/second.py",
        "from services import orders\n",
    )

    findings = collect_findings(tmp_path)

    assert any(
        finding.kind == "direction"
        and "services.orders->routers.second" in finding.finding_id
        for finding in findings
    )
    assert any(
        finding.kind == "cycle"
        and "routers.second,services.orders" in finding.finding_id
        for finding in findings
    )


def test_collects_frontend_shared_to_feature_violation(tmp_path):
    _write(
        tmp_path / "frontend/src/services/api.js",
        "import Widget from '../components/Widget.jsx'\n",
    )
    _write(tmp_path / "frontend/src/components/Widget.jsx", "export default 1\n")

    findings = collect_findings(tmp_path)

    assert any(
        finding.kind == "direction"
        and "services/api.js->components/Widget.jsx" in finding.finding_id
        for finding in findings
    )


def test_ignores_frontend_import_syntax_inside_comments_and_strings(tmp_path):
    _write(
        tmp_path / "frontend/src/services/api.js",
        "\n".join(
            [
                "// import Widget from '../components/Widget.jsx'",
                "/* require('../components/Widget.jsx') */",
                "const example = \"import Widget from '../components/Widget.jsx'\";",
            ]
        ),
    )
    _write(tmp_path / "frontend/src/components/Widget.jsx", "export default 1\n")

    findings = collect_findings(tmp_path)

    assert not any(
        "services/api.js->components/Widget.jsx" in finding.finding_id
        for finding in findings
    )


def test_nested_feature_barrel_is_not_a_public_contract(tmp_path):
    _write(
        tmp_path / "frontend/src/features/orders/model/state.js",
        "export { Widget } from '../../billing/components/index.js'\n",
    )
    _write(
        tmp_path / "frontend/src/features/billing/components/index.js",
        "export const Widget = 1\n",
    )

    findings = collect_findings(tmp_path)

    assert any(
        finding.kind == "direction"
        and "features/orders/model/state.js->features/billing/components/index.js"
        in finding.finding_id
        for finding in findings
    )


def test_feature_root_barrel_is_a_public_contract(tmp_path):
    _write(
        tmp_path / "frontend/src/features/orders/model/state.js",
        "export { Widget } from '../../billing/index.js'\n",
    )
    _write(
        tmp_path / "frontend/src/features/billing/index.js",
        "export const Widget = 1\n",
    )

    findings = collect_findings(tmp_path)

    assert not any(
        "features/orders/model/state.js->features/billing/index.js"
        in finding.finding_id
        for finding in findings
    )


def test_new_violation_fails_without_exception():
    finding = Finding("direction|python|a->b|rule", "python", "direction", "a -> b")

    result = reconcile_exceptions(
        [finding],
        {"version": 1, "exceptions": []},
        today=date(2026, 1, 1),
    )

    assert not result.passed
    assert result.errors == ("unbaselined violation: direction|python|a->b|rule",)


def test_valid_exception_baselines_existing_violation():
    finding = Finding("direction|python|a->b|rule", "python", "direction", "a -> b")

    result = reconcile_exceptions(
        [finding],
        _manifest(finding.finding_id),
        today=date(2026, 1, 1),
    )

    assert result.passed


def test_exception_requires_metadata_and_future_expiry():
    finding = Finding("cycle|frontend|a,b", "frontend", "cycle", "a -> b")
    manifest = _manifest(finding.finding_id, expires_on="2025-12-31")
    manifest["exceptions"][0]["owner"] = ""

    result = reconcile_exceptions([finding], manifest, today=date(2026, 1, 1))

    assert not result.passed
    assert "exception[0].owner must be a non-empty string" in result.errors
    assert f"{finding.finding_id}: exception expired on 2025-12-31" in result.errors


def test_resolved_violation_requires_stale_exception_removal():
    result = reconcile_exceptions(
        [],
        _manifest("direction|python|a->b|rule"),
        today=date(2026, 1, 1),
    )

    assert not result.passed
    assert result.errors == (
        "stale exception (remove it): direction|python|a->b|rule",
    )


def test_repository_manifest_matches_current_findings():
    root = Path(__file__).resolve().parents[1]
    manifest = root / "docs/architecture/source-boundary-exceptions.json"

    result = run_check(root, manifest)

    assert result.passed, "\n".join(result.errors)


def test_manifest_is_valid_json():
    root = Path(__file__).resolve().parents[1]
    manifest = root / "docs/architecture/source-boundary-exceptions.json"

    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == 1
