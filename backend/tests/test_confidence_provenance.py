from __future__ import annotations

from confidence_provenance import build_provenance, _lookup_catalog_confidence
from services.mappings import CROSS_CLOUD_MAPPINGS


def test_gcp_catalog_confidence_uses_gcp_service_name():
    catalog_row = next(
        row for row in CROSS_CLOUD_MAPPINGS
        if row.get("gcp") == "GKE" and row.get("azure") == "AKS"
    )

    assert _lookup_catalog_confidence("GKE", "AKS", "gcp") == catalog_row["confidence"]


def test_provenance_uses_analysis_provider_when_mapping_omits_it():
    provenance = build_provenance(
        {"source_service": "GKE", "azure_service": "AKS", "confidence": 0.95},
        source_provider="gcp",
    )
    catalog = provenance["score_decomposition"]["components"]["catalog_match"]

    assert provenance["source_provider"] == "gcp"
    assert catalog["matched"] is True
    assert catalog["score"] == 95


def test_missing_provider_does_not_assume_aws_catalog_match():
    provenance = build_provenance(
        {"source_service": "GKE", "azure_service": "AKS", "confidence": 0.95}
    )
    catalog = provenance["score_decomposition"]["components"]["catalog_match"]

    assert provenance["source_provider"] is None
    assert catalog["matched"] is False
    assert catalog["score"] == 0
