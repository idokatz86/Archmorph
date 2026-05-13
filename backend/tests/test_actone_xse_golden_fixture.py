"""Golden fixture regression gate for ActOne/XSE production-style AWS architecture (#1033).

This test suite enforces fidelity for dense enterprise architecture translation:
  - All expected P0 source services must be present in source_topology.
  - Source topology is preserved as a separate section (not merged into target mappings).
  - Every custom workload (ActOne, AVA, UDM, IR, CMaaS, DataExtract, XSight) is preserved
    by its original name and is NOT forced into an incorrect Azure service.
  - HA/DR labels (active-active, failover, multi-az) survive from source to mapping output.
  - P0 flows are declared in source_topology and none may be silently dropped.
  - The traceability map can be built from the full fixture without losing any mapping entry.
  - Multi-AZ services are annotated in source_topology.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from traceability_map import build_traceability_map  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures"

GOLDEN = json.loads((FIXTURES / "actone_xse_golden.json").read_text(encoding="utf-8"))
SOURCE_TOPOLOGY = GOLDEN["source_topology"]
EXPECTED = GOLDEN["expected_detections"]

# Mappings with confidence above this threshold should not also have unresolved blockers.
MAX_CONFIDENCE_WITH_UNRESOLVED_BLOCKERS = 0.9

# Custom pods — subset of EXPECTED["custom_workload_names"] excluding XSight, which is
# a custom observability integration (not a pod) and is asserted separately.
CUSTOM_POD_WORKLOADS = [w for w in EXPECTED["custom_workload_names"] if w != "XSight"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _component_service_types() -> list[str]:
    return [c["service_type"] for c in SOURCE_TOPOLOGY["components"]]


def _component_names() -> list[str]:
    return [c["name"] for c in SOURCE_TOPOLOGY["components"]]


def _mapping_source_services() -> list[str]:
    return [m["source_service"] for m in GOLDEN["mappings"]]


def _mapping_azure_services() -> list[str]:
    return [m["azure_service"] for m in GOLDEN["mappings"]]


# ===========================================================================
# 1. Fixture schema integrity
# ===========================================================================

class TestFixtureSchema:
    def test_golden_fixture_loads_and_has_required_top_level_keys(self):
        required = {"title", "source_provider", "target_provider", "source_topology", "mappings", "expected_detections"}
        missing = required - set(GOLDEN.keys())
        assert not missing, f"Golden fixture missing top-level keys: {missing}"

    def test_source_topology_has_schema_version(self):
        assert SOURCE_TOPOLOGY.get("schema_version") == "source-topology/v1"

    def test_source_topology_has_boundaries_components_flows_ha_dr(self):
        for section in ("boundaries", "components", "flows", "ha_dr"):
            assert section in SOURCE_TOPOLOGY, f"source_topology missing section: {section}"

    def test_source_topology_is_separate_from_azure_mappings(self):
        """source_topology must preserve source architecture without Azure service names."""
        for component in SOURCE_TOPOLOGY["components"]:
            azure_terms = {"azure", "microsoft", "arm", "bicep"}
            name_lower = component["name"].lower()
            service_lower = component["service_type"].lower()
            assert not any(term in name_lower for term in azure_terms), (
                f"Source topology component '{component['name']}' contains Azure-side terminology"
            )
            assert not any(term in service_lower for term in azure_terms), (
                f"Source topology service_type '{component['service_type']}' contains Azure-side terminology"
            )

    def test_every_mapping_has_required_fidelity_fields(self):
        required_fields = {"source_service", "azure_service", "category", "confidence", "rationale", "unresolved_blockers"}
        for mapping in GOLDEN["mappings"]:
            missing = required_fields - set(mapping.keys())
            assert not missing, f"Mapping for '{mapping.get('source_service')}' missing fields: {missing}"


# ===========================================================================
# 2. Expected P0 service detections
# ===========================================================================

class TestExpectedDetections:
    @pytest.mark.parametrize("expected_service", EXPECTED["source_services"])
    def test_expected_source_service_in_source_topology(self, expected_service: str):
        """Every P0 source service must appear in source_topology components (exact match)."""
        all_names_and_types = set(_component_names()) | set(_component_service_types())
        assert expected_service in all_names_and_types, (
            f"Expected source service '{expected_service}' not found in source_topology components"
        )

    @pytest.mark.parametrize("expected_service", EXPECTED["source_services"])
    def test_expected_source_service_has_mapping(self, expected_service: str):
        """Every P0 source service must have a corresponding mapping entry (exact match)."""
        assert expected_service in set(_mapping_source_services()), (
            f"Expected source service '{expected_service}' has no mapping entry"
        )

    def test_sftp_to_s3_ingestion_flow_detected(self):
        flow_ids = [f["id"] for f in SOURCE_TOPOLOGY["flows"]]
        assert "flow-sftp-s3" in flow_ids

    def test_albs_both_detected(self):
        # Identify ALBs by category to avoid fragile substring matching on service_type or id
        alb_components = [c for c in SOURCE_TOPOLOGY["components"] if c.get("category") == "LoadBalancer"]
        assert len(alb_components) >= 2, "Expected at least two ALB entries (frontend and internal)"

    def test_multi_az_services_annotated(self):
        multi_az_types = {c["service_type"] for c in SOURCE_TOPOLOGY["components"] if c.get("multi_az") is True}
        for service in EXPECTED["multi_az_services"]:
            assert service in multi_az_types, (
                f"Multi-AZ service '{service}' not annotated with multi_az=true in source_topology"
            )

    def test_vpc_and_subnet_boundaries_present(self):
        boundary_types = {b["type"] for b in SOURCE_TOPOLOGY["boundaries"]}
        for expected_type in EXPECTED["boundary_types"]:
            assert expected_type in boundary_types, f"Expected boundary type '{expected_type}' missing"

    def test_private_app_and_db_subnets_present(self):
        tiers = {b.get("tier") for b in SOURCE_TOPOLOGY["boundaries"] if b["type"] == "subnet"}
        assert "private_app" in tiers, "Private app subnet not found in boundaries"
        assert "private_db" in tiers, "Private DB subnet not found in boundaries"


# ===========================================================================
# 3. Custom workload preservation
# ===========================================================================

class TestCustomWorkloadPreservation:
    @pytest.mark.parametrize("workload_name", EXPECTED["custom_workload_names"])
    def test_custom_workload_preserved_by_original_name_in_source_topology(self, workload_name: str):
        """Custom workloads must appear in source_topology under their original names (exact name match)."""
        assert any(c["name"] == workload_name for c in SOURCE_TOPOLOGY["components"]), (
            f"Custom workload '{workload_name}' not found in source_topology components"
        )

    # XSight is intentionally omitted here because it is a custom observability integration,
    # not a pod, and is asserted separately in test_xsight_preserved_and_has_unresolved_blocker.
    @pytest.mark.parametrize("workload_name", CUSTOM_POD_WORKLOADS)
    def test_custom_pod_not_forced_into_wrong_azure_service(self, workload_name: str):
        """Custom pods must retain their original name in the azure_service field rather than being silently mapped to a generic Azure service."""
        matching_mappings = [m for m in GOLDEN["mappings"] if m["source_service"] == workload_name]
        assert matching_mappings, f"No mapping entry found for custom workload '{workload_name}'"
        for mapping in matching_mappings:
            azure_svc = mapping["azure_service"]
            # Must preserve the original name at the start of the azure_service field
            assert azure_svc.startswith(workload_name), (
                f"Custom workload '{workload_name}' was silently dropped or renamed in azure_service: '{azure_svc}'"
            )
            # Confidence must be 0 when there is no resolved mapping
            assert mapping["confidence"] == 0.0, (
                f"Custom workload '{workload_name}' has non-zero confidence {mapping['confidence']} but no Azure mapping is resolved"
            )
            # Must have at least one unresolved blocker listed
            assert mapping.get("unresolved_blockers"), (
                f"Custom workload '{workload_name}' has no unresolved_blockers listed"
            )

    def test_xsight_preserved_and_has_unresolved_blocker(self):
        xsight_mapping = next((m for m in GOLDEN["mappings"] if "XSight" in m["source_service"]), None)
        assert xsight_mapping is not None, "XSight mapping entry missing"
        assert "XSight" in xsight_mapping["azure_service"], "XSight not preserved by name in azure_service"
        assert xsight_mapping["unresolved_blockers"], "XSight must have at least one unresolved blocker"


# ===========================================================================
# 4. HA/DR semantics
# ===========================================================================

class TestHaDrSemantics:
    def test_ha_labels_present_in_source_topology(self):
        labels = SOURCE_TOPOLOGY["ha_dr"].get("labels", [])
        for label in EXPECTED["ha_labels"]:
            assert label in labels, f"HA/DR label '{label}' not found in source_topology.ha_dr.labels"

    def test_active_active_and_failover_coexist(self):
        labels = SOURCE_TOPOLOGY["ha_dr"].get("labels", [])
        assert "active-active" in labels
        assert "failover" in labels

    def test_rpo_rto_are_present(self):
        ha_dr = SOURCE_TOPOLOGY["ha_dr"]
        assert "rpo_hours" in ha_dr, "RPO not specified in ha_dr"
        assert "rto_hours" in ha_dr, "RTO not specified in ha_dr"

    def test_rds_multi_az_annotated_as_active_standby(self):
        rds_service_type = "Amazon RDS (PostgreSQL Multi-AZ)"
        rds = next((c for c in SOURCE_TOPOLOGY["components"] if c.get("service_type") == rds_service_type), None)
        assert rds is not None, f"RDS component with service_type '{rds_service_type}' not found"
        assert rds.get("ha_mode") == "active-standby", "RDS Multi-AZ must be annotated as active-standby"

    def test_kafka_annotated_as_active_active(self):
        kafka_service_type = "Amazon MSK (Kafka)"
        kafka = next((c for c in SOURCE_TOPOLOGY["components"] if c.get("service_type") == kafka_service_type), None)
        assert kafka is not None, f"Kafka component with service_type '{kafka_service_type}' not found"
        assert kafka.get("ha_mode") == "active-active", "Kafka multi-AZ must be annotated as active-active"


# ===========================================================================
# 5. P0 flow regression gate
# ===========================================================================

class TestP0FlowRegressionGate:
    @pytest.mark.parametrize("flow_id", EXPECTED["p0_flows"])
    def test_p0_flow_present_and_marked(self, flow_id: str):
        """Each P0 flow must exist in source_topology.flows with p0=True."""
        flows_by_id = {f["id"]: f for f in SOURCE_TOPOLOGY["flows"]}
        assert flow_id in flows_by_id, f"P0 flow '{flow_id}' missing from source_topology.flows"
        assert flows_by_id[flow_id].get("p0") is True, f"Flow '{flow_id}' is not marked as p0=True"

    def test_no_p0_flow_missing_from_topology(self):
        """Regression: P0 flows listed in expected_detections must all appear in source_topology."""
        topology_flow_ids = {f["id"] for f in SOURCE_TOPOLOGY["flows"]}
        missing = [fid for fid in EXPECTED["p0_flows"] if fid not in topology_flow_ids]
        assert not missing, f"P0 flows silently dropped from source_topology: {missing}"


# ===========================================================================
# 6. Source-to-target traceability
# ===========================================================================

class TestSourceToTargetTraceability:
    def test_traceability_map_builds_from_golden_fixture(self):
        trace_map = build_traceability_map(GOLDEN)
        assert trace_map["schema_version"] == "source-to-azure-iac-traceability/v1"
        # Minimum of 5 reflects the fixture's resolvable non-custom mappings at confidence > 0;
        # the actual count is higher — this is a floor guard, not a strict count.
        min_resolvable = sum(1 for m in GOLDEN["mappings"] if m["confidence"] > 0)
        assert len(trace_map["entries"]) >= min(5, min_resolvable), (
            "Traceability map should have at least as many entries as resolvable mappings"
        )

    def test_known_azure_mappings_appear_in_traceability_entries(self):
        trace_map = build_traceability_map(GOLDEN)
        resolved_azure = {e["azure_service"] for e in trace_map["entries"]}
        known_azure_services = [
            "Azure Blob Storage (SFTP)",
            "Azure Blob Storage",
            "Azure Application Gateway",
            "Azure Database for PostgreSQL Flexible Server",
        ]
        for svc in known_azure_services:
            assert svc in resolved_azure, f"Expected resolved Azure service '{svc}' not in traceability map entries"

    def test_custom_workloads_have_zero_confidence_in_mappings(self):
        custom_workloads = set(EXPECTED["custom_workload_names"])
        for mapping in GOLDEN["mappings"]:
            if mapping["source_service"] in custom_workloads:
                assert mapping["confidence"] == 0.0, (
                    f"Custom workload '{mapping['source_service']}' must have confidence=0.0 until resolved"
                )

    def test_all_resolved_mappings_have_positive_confidence(self):
        """Resolved (non-custom) mappings must have confidence > 0.5 to be meaningful."""
        custom_workloads = set(EXPECTED["custom_workload_names"])
        for mapping in GOLDEN["mappings"]:
            if mapping["source_service"] not in custom_workloads:
                assert mapping["confidence"] > 0.5, (
                    f"Resolved mapping for '{mapping['source_service']}' has unexpectedly low confidence {mapping['confidence']}"
                )

    def test_unresolved_blockers_only_on_uncertain_mappings(self):
        """Only mappings with unresolved semantics should have non-empty unresolved_blockers."""
        for mapping in GOLDEN["mappings"]:
            blockers = mapping.get("unresolved_blockers", [])
            if blockers:
                # If blockers are present, confidence should be at or below the threshold
                assert mapping["confidence"] <= MAX_CONFIDENCE_WITH_UNRESOLVED_BLOCKERS, (
                    f"Mapping for '{mapping['source_service']}' has both high confidence ({mapping['confidence']}) "
                    f"and unresolved blockers — review required"
                )

    def test_traceability_entries_count_matches_resolvable_mappings(self):
        """Traceability map entries should cover all non-zero-confidence mappings."""
        resolvable = [m for m in GOLDEN["mappings"] if m["confidence"] > 0]
        trace_map = build_traceability_map(GOLDEN)
        # Allow for platform guardrail entries added by the map builder
        assert len(trace_map["entries"]) >= len(resolvable), (
            f"Traceability map has fewer entries ({len(trace_map['entries'])}) "
            f"than resolvable mappings ({len(resolvable)})"
        )
