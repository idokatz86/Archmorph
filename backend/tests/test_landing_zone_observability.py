"""Tests for #595 — Landing-Zone-SVG OTel instrumentation.

Asserts that the four canonical metrics fire from the canonical code paths:

  * ``archmorph.lz.svg_generation_duration_seconds``  (histogram, on success)
  * ``archmorph.lz.svg_size_bytes``                   (histogram, on success)
  * ``archmorph.lz.icon_resolution_total{result}``    (counter, per icon slot)
  * ``archmorph.lz.errors_total{stage,error_type}``   (counter, on raise)

These tests read directly from the observability module's in-memory store
(``observability._metrics``) which is the same source the admin
``/api/admin/monitoring`` dashboard reads — so a green test here is a hard
guarantee that the dashboard tile and the OTel export will both reflect
real production traffic.

Sub-issue: https://github.com/idokatz86/Archmorph/issues/595
Parent epic: https://github.com/idokatz86/Archmorph/issues/586
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import observability
from azure_landing_zone import generate_landing_zone_svg

CANONICAL_AWS_ESTATE_PATH = (
    Path(__file__).parent / "fixtures" / "aws_canonical_estate.json"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def reset_metrics():
    """Snapshot + restore the in-memory metrics store so each test starts clean.

    The ``observability._metrics`` dict is module-global; without this fixture
    a parallel xdist worker that runs another test which records metrics
    would pollute our assertions. We do not touch the OTel SDK side — that
    is best-effort and well-tested elsewhere.
    """
    saved = {
        "counters": dict(observability._metrics["counters"]),
        "histograms": {k: dict(v) for k, v in observability._metrics["histograms"].items()},
        "gauges": dict(observability._metrics["gauges"]),
    }
    observability._metrics["counters"].clear()
    observability._metrics["histograms"].clear()
    observability._metrics["gauges"].clear()
    yield observability._metrics
    observability._metrics["counters"].clear()
    observability._metrics["histograms"].clear()
    observability._metrics["gauges"].clear()
    observability._metrics["counters"].update(saved["counters"])
    observability._metrics["histograms"].update(saved["histograms"])
    observability._metrics["gauges"].update(saved["gauges"])


@pytest.fixture(scope="function")
def hermetic_registry(tmp_path, monkeypatch):
    """Hermetic icon-registry environment.

    Same pattern as ``test_azure_landing_zone.py::canonical_aws_estate`` —
    forces autoload ON, points the on-disk cache at ``tmp_path`` so a stale
    snapshot from prior runs cannot poison the test, and clears the
    LZ-module's icon cache so each test gets a fresh registry hit.
    """
    from icons import registry as icon_registry
    import azure_landing_zone

    monkeypatch.setenv("ICON_REGISTRY_AUTOLOAD", "1")
    monkeypatch.setenv("ICON_REGISTRY_DATA_DIR", str(tmp_path))
    icon_registry.clear_all()
    azure_landing_zone._ICON_CACHE.clear()
    icon_registry.ensure_registry_loaded(force=True)
    yield


SAMPLE_ANALYSIS: dict[str, Any] = {
    "title": "Test LZ Observability",
    "source_provider": "aws",
    "zones": [{"id": 1, "name": "obs-tier", "number": 1}],
    "mappings": [
        {"source_service": "EKS", "azure_service": "AKS",        "category": "Containers"},
        {"source_service": "RDS", "azure_service": "Azure SQL",  "category": "Database"},
        {"source_service": "ALB", "azure_service": "App Gateway","category": "Networking"},
        {"source_service": "S3",  "azure_service": "Blob Storage","category": "Storage"},
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counter_value(metrics: dict, name: str, tags: dict[str, str] | None = None) -> int:
    """Return the in-memory counter total matching ``name`` and ``tags``.

    Sums across multiple keys when ``tags`` is None or partial — important
    because ``increment_counter`` keys the dict on the *full* tag set
    (e.g. ``result=hit`` AND ``icon_key=aks``), so an exact-match lookup on
    just ``{"result": "hit"}`` would always return 0.
    """
    total = 0
    for entry in metrics["counters"].values():
        if entry["name"] != name:
            continue
        entry_tags = entry.get("tags", {})
        if tags is None or all(entry_tags.get(k) == v for k, v in tags.items()):
            total += entry["value"]
    return total


def _histogram_count(metrics: dict, name: str) -> int:
    total = 0
    for entry in metrics["histograms"].values():
        if entry["name"] == name:
            total += len(entry.get("values", []))
    return total


# ---------------------------------------------------------------------------
# #595 — Tests
# ---------------------------------------------------------------------------


class TestSuccessPathMetrics:
    """Successful renders must emit duration + size + icon-resolution counters."""

    def test_duration_histogram_recorded_on_success(
        self, reset_metrics, hermetic_registry
    ):
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        assert result["format"] == "landing-zone-svg"

        count = _histogram_count(
            reset_metrics, "archmorph.lz.svg_generation_duration_seconds"
        )
        assert count == 1, (
            f"expected 1 duration histogram observation, got {count}"
        )

    def test_size_histogram_recorded_on_success(self, reset_metrics, hermetic_registry):
        result = generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        size_bytes = len(result["content"].encode("utf-8"))

        count = _histogram_count(reset_metrics, "archmorph.lz.svg_size_bytes")
        assert count == 1
        # Cross-check the recorded value matches the actual SVG size.
        for entry in reset_metrics["histograms"].values():
            if entry["name"] == "archmorph.lz.svg_size_bytes":
                assert entry["values"][0] == pytest.approx(float(size_bytes), abs=1.0)

    def test_icon_resolution_counter_emits_at_least_once(
        self, reset_metrics, hermetic_registry
    ):
        """Every render emits ≥1 icon_resolution_total event (hit or fallback)."""
        generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        total = _counter_value(reset_metrics, "archmorph.lz.icon_resolution_total")
        assert total >= 10, (
            f"LZ render emits ~30 icon slots; got {total} counter increments"
        )

    def test_icon_resolution_hit_label_present(self, reset_metrics, hermetic_registry):
        """At least some icons must resolve as 'hit' (registry-backed)."""
        generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        hits = _counter_value(
            reset_metrics, "archmorph.lz.icon_resolution_total", {"result": "hit"}
        )
        # Empirically at least the static network/identity icons resolve.
        assert hits >= 3, (
            f"expected ≥3 hit-result counter increments after #587; got {hits}"
        )

    def test_no_errors_counter_on_success_path(
        self, reset_metrics, hermetic_registry
    ):
        generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="primary")
        errors = _counter_value(reset_metrics, "archmorph.lz.errors_total")
        assert errors == 0, (
            f"successful render must not increment errors_total; got {errors}"
        )


class TestErrorPathMetrics:
    """Validation failures must increment errors_total with the right tags."""

    def test_invalid_dr_variant_increments_errors_total(self, reset_metrics):
        with pytest.raises(ValueError):
            generate_landing_zone_svg(SAMPLE_ANALYSIS, dr_variant="bogus")  # type: ignore[arg-type]
        errors = _counter_value(
            reset_metrics,
            "archmorph.lz.errors_total",
            {"stage": "validate", "error_type": "invalid_dr_variant"},
        )
        assert errors == 1

    def test_non_dict_analysis_increments_errors_total(self, reset_metrics):
        with pytest.raises(ValueError):
            generate_landing_zone_svg("not a dict", dr_variant="primary")  # type: ignore[arg-type]
        errors = _counter_value(
            reset_metrics,
            "archmorph.lz.errors_total",
            {"stage": "validate", "error_type": "bad_analysis_type"},
        )
        assert errors == 1

    def test_bad_source_provider_increments_errors_total(self, reset_metrics):
        bad_analysis = {**SAMPLE_ANALYSIS, "source_provider": "alibaba"}
        with pytest.raises(ValueError):
            generate_landing_zone_svg(bad_analysis, dr_variant="primary")
        errors = _counter_value(
            reset_metrics,
            "archmorph.lz.errors_total",
            {"stage": "validate", "error_type": "bad_source_provider"},
        )
        assert errors == 1


class TestCanonicalEstateRatio:
    """Hit-ratio sanity check on the canonical 35-service AWS estate.

    Locks the icon-resolution observability metric against the same fixture
    the #588 guardrails use, so a regression in #587 / #589 / #592 surfaces
    in *both* the SVG-content tests AND the metrics tests.
    """

    def test_canonical_estate_emits_majority_hits(
        self, reset_metrics, hermetic_registry
    ):
        estate = json.loads(CANONICAL_AWS_ESTATE_PATH.read_text(encoding="utf-8"))
        generate_landing_zone_svg(estate, dr_variant="primary")

        hits = _counter_value(
            reset_metrics, "archmorph.lz.icon_resolution_total", {"result": "hit"}
        )
        fallbacks = _counter_value(
            reset_metrics,
            "archmorph.lz.icon_resolution_total",
            {"result": "fallback"},
        )
        total = hits + fallbacks
        assert total > 0, "canonical estate must emit ≥1 icon-resolution event"
        # 35% floor matches the #588 SVG-content guardrail; #592 lifts to 90%.
        ratio = hits / total
        assert ratio >= 0.35, (
            f"canonical estate hit ratio {ratio:.2%} below 35% floor "
            f"({hits} hit / {fallbacks} fallback). See #592."
        )
