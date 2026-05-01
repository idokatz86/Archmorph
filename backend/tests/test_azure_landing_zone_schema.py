"""Tests for backend/azure_landing_zone_schema.py (#572).

Each helper is tested for:
- Pass-through when the field is present and well-formed.
- Inference when the field is missing.
- Graceful default when the field is malformed.
"""

from __future__ import annotations

from azure_landing_zone_schema import (
    DEFAULT_PRIMARY_REGION,
    DEFAULT_STANDBY_REGION,
    TIER_ORDER,
    infer_actors,
    infer_dr_mode,
    infer_regions,
    infer_replication,
    infer_tiers_from_mappings,
)


# ---------------------------------------------------------------------------
# infer_dr_mode
# ---------------------------------------------------------------------------

class TestInferDrMode:
    def test_explicit_value_passthrough(self):
        assert infer_dr_mode({"dr_mode": "active-active"}) == "active-active"
        assert infer_dr_mode({"dr_mode": "active-standby"}) == "active-standby"
        assert infer_dr_mode({"dr_mode": "single-region"}) == "single-region"

    def test_explicit_invalid_falls_back_to_inference(self):
        assert infer_dr_mode({"dr_mode": "nonsense"}) == "single-region"

    def test_no_regions_is_single(self):
        assert infer_dr_mode({}) == "single-region"
        assert infer_dr_mode({"regions": []}) == "single-region"
        assert infer_dr_mode({"regions": [{"name": "East US", "traffic_pct": 100}]}) == "single-region"

    def test_two_regions_one_carrying_is_active_standby(self):
        a = {"regions": [
            {"name": "East US", "traffic_pct": 100},
            {"name": "West US 3", "traffic_pct": 0},
        ]}
        assert infer_dr_mode(a) == "active-standby"

    def test_two_regions_both_carrying_is_active_active(self):
        a = {"regions": [
            {"name": "East US", "traffic_pct": 60},
            {"name": "West US 3", "traffic_pct": 40},
        ]}
        assert infer_dr_mode(a) == "active-active"

    def test_malformed_regions_does_not_crash(self):
        a = {"regions": ["not-a-dict", {"name": "East US"}, None]}
        assert infer_dr_mode(a) == "single-region"


# ---------------------------------------------------------------------------
# infer_regions
# ---------------------------------------------------------------------------

class TestInferRegions:
    def test_default_primary_when_empty(self):
        regions = infer_regions({})
        assert regions == [DEFAULT_PRIMARY_REGION]

    def test_default_dr_pair_when_empty(self):
        regions = infer_regions({}, dr_variant="dr")
        assert regions[0]["role"] == "primary"
        assert regions[1]["role"] == "standby"
        assert len(regions) == 2

    def test_explicit_regions_passthrough(self):
        a = {"regions": [
            {"name": "Sweden Central", "role": "primary", "traffic_pct": 100},
            {"name": "Norway East", "role": "standby", "traffic_pct": 0},
        ]}
        regions = infer_regions(a, dr_variant="dr")
        assert regions[0]["name"] == "Sweden Central"
        assert regions[1]["name"] == "Norway East"

    def test_dr_variant_pads_single_region_to_two(self):
        a = {"regions": [{"name": "East US", "traffic_pct": 100}]}
        regions = infer_regions(a, dr_variant="dr")
        assert len(regions) == 2
        assert regions[0]["name"] == "East US"
        assert regions[1] == DEFAULT_STANDBY_REGION

    def test_traffic_pct_clamped(self):
        a = {"regions": [{"name": "X", "traffic_pct": 250}]}
        assert infer_regions(a)[0]["traffic_pct"] == 100
        a = {"regions": [{"name": "X", "traffic_pct": -10}]}
        assert infer_regions(a)[0]["traffic_pct"] == 0

    def test_malformed_entries_filtered(self):
        a = {"regions": ["bad", {"name": ""}, {"name": "Good"}, None]}
        regions = infer_regions(a)
        assert len(regions) == 1
        assert regions[0]["name"] == "Good"

    def test_does_not_mutate_input(self):
        a = {"regions": [{"name": "East US", "traffic_pct": 100}]}
        original = a["regions"][0].copy()
        infer_regions(a, dr_variant="dr")
        assert a["regions"][0] == original


# ---------------------------------------------------------------------------
# infer_tiers_from_mappings
# ---------------------------------------------------------------------------

class TestInferTiers:
    def test_returns_all_tier_keys(self):
        out = infer_tiers_from_mappings({})
        for tier in TIER_ORDER:
            assert tier in out
            assert isinstance(out[tier], list)

    def test_explicit_tiers_passthrough(self):
        a = {"tiers": {
            "ingress": ["Application Gateway"],
            "compute": [{"name": "AKS", "source": "EKS"}],
        }}
        out = infer_tiers_from_mappings(a)
        assert out["ingress"][0]["name"] == "Application Gateway"
        assert out["compute"][0]["name"] == "AKS"
        assert out["compute"][0]["source"] == "EKS"
        assert out["compute"][0]["subtitle"] == "Replaces EKS"

    def test_explicit_tiers_filters_unknown_keys(self):
        a = {"tiers": {"unknown-tier": ["X"], "compute": ["AKS"]}}
        out = infer_tiers_from_mappings(a)
        assert "unknown-tier" not in out
        assert out["compute"][0]["name"] == "AKS"

    def test_derives_from_mappings_when_tiers_absent(self):
        a = {"mappings": [
            {"source_service": "EKS", "azure_service": "AKS", "category": "Containers"},
            {"source_service": "RDS", "azure_service": "Azure SQL", "category": "Database"},
            {"source_service": "ELB", "azure_service": "App Gateway", "category": "Networking"},
            {"source_service": "S3",  "azure_service": "Blob Storage", "category": "Storage"},
            {"source_service": "Cognito", "azure_service": "Entra ID", "category": "Identity"},
            {"source_service": "CloudWatch", "azure_service": "Azure Monitor", "category": "Monitoring"},
        ]}
        out = infer_tiers_from_mappings(a)
        assert any(s["name"] == "AKS" for s in out["compute"])
        assert any(s["name"] == "Azure SQL" for s in out["data"])
        assert any(s["name"] == "App Gateway" for s in out["ingress"])
        assert any(s["name"] == "Blob Storage" for s in out["storage"])
        assert any(s["name"] == "Entra ID" for s in out["identity"])
        assert any(s["name"] == "Azure Monitor" for s in out["observability"])

    def test_unknown_category_falls_to_compute(self):
        a = {"mappings": [{"azure_service": "X", "category": "Unknown"}]}
        out = infer_tiers_from_mappings(a)
        assert any(s["name"] == "X" for s in out["compute"])

    def test_skips_mappings_without_azure_service(self):
        a = {"mappings": [{"source_service": "EKS", "category": "Compute"}]}
        out = infer_tiers_from_mappings(a)
        assert out["compute"] == []

    def test_subtitle_synthesised_when_source_present(self):
        a = {"mappings": [{"source_service": "EFS", "azure_service": "Azure Files", "category": "Storage"}]}
        out = infer_tiers_from_mappings(a)
        assert out["storage"][0]["subtitle"] == "Replaces EFS"


# ---------------------------------------------------------------------------
# infer_actors
# ---------------------------------------------------------------------------

class TestInferActors:
    def test_default_when_missing(self):
        actors = infer_actors({})
        assert len(actors) == 1
        assert actors[0]["name"] == "End User"
        assert actors[0]["kind"] == "external"

    def test_passthrough_when_provided(self):
        a = {"actors": [
            {"name": "Self-Dev", "kind": "internal", "subtitle": "Developer", "edge_label": "RDP"},
            {"name": "API Client", "kind": "external"},
        ]}
        actors = infer_actors(a)
        assert len(actors) == 2
        assert actors[0]["name"] == "Self-Dev"
        assert actors[0]["edge_label"] == "RDP"
        assert actors[1]["edge_label"] == "HTTPS"  # default

    def test_drops_actors_without_name(self):
        a = {"actors": [{"name": ""}, {"name": "Good"}]}
        actors = infer_actors(a)
        assert len(actors) == 1
        assert actors[0]["name"] == "Good"

    def test_malformed_falls_back_to_default(self):
        a = {"actors": "not-a-list"}
        actors = infer_actors(a)
        assert len(actors) == 1
        assert actors[0]["name"] == "End User"


# ---------------------------------------------------------------------------
# infer_replication
# ---------------------------------------------------------------------------

class TestInferReplication:
    def test_empty_for_single_region(self):
        assert infer_replication({}) == []
        assert infer_replication({"dr_mode": "single-region"}) == []

    def test_default_template_for_dr(self):
        a = {"dr_mode": "active-standby"}
        rep = infer_replication(a)
        assert len(rep) >= 6  # default template has 6 entries
        names = [r["name"] for r in rep]
        assert "Storage Account" in names
        assert "Managed DB" in names
        assert "Identity" in names

    def test_explicit_replication_passthrough(self):
        a = {"dr_mode": "active-standby", "replication": [
            {"name": "PostgreSQL", "mode": "logical · async"},
            {"name": "Cosmos DB", "mode": "multi-region writes"},
        ]}
        rep = infer_replication(a)
        assert rep[0]["name"] == "PostgreSQL"
        assert rep[1]["mode"] == "multi-region writes"

    def test_explicit_replication_honoured_on_single_region(self):
        # Caller may want to surface what *would* replicate even today.
        a = {"replication": [{"name": "X", "mode": "y"}]}
        rep = infer_replication(a)
        assert len(rep) == 1
        assert rep[0]["name"] == "X"

    def test_drops_replication_entries_without_name(self):
        a = {"dr_mode": "active-standby", "replication": [{"name": ""}, {"name": "Good"}]}
        rep = infer_replication(a)
        assert len(rep) == 1
        assert rep[0]["name"] == "Good"
