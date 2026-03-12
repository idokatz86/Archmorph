"""
Archmorph — Unit Tests for HLD Export Module
=============================================

Tests the hld_export.py module:
  - DOCX generation
  - PDF generation
  - PPTX generation
  - Error handling for invalid formats
  - Diagram embedding toggle
  - Base64 output encoding
"""

import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hld_export import export_hld, export_hld_docx, export_hld_pdf, export_hld_pptx, SUPPORTED_FORMATS


# ====================================================================
# Fixtures — reuse the mock HLD from test_hld_generator
# ====================================================================

MOCK_HLD = {
    "title": "AWS to Azure Migration — High-Level Design",
    "executive_summary": "This document outlines the migration strategy from AWS to Azure.",
    "architecture_overview": {
        "description": "A serverless microservices architecture.",
        "diagram_description": "API calls flow through APIM to Functions.",
        "architecture_style": "Serverless",
        "deployment_model": "Public Cloud",
    },
    "services": [
        {
            "azure_service": "Azure Functions",
            "source_service": "Lambda",
            "justification": "Direct equivalent for serverless compute.",
            "alternatives_considered": ["Azure Container Apps"],
            "description": "Serverless compute for event-driven workloads.",
            "tier_recommendation": "Consumption plan",
            "limitations": ["Cold start latency"],
            "sla": "99.95%",
            "communication": {
                "connects_to": ["Azure Cosmos DB"],
                "protocol": "HTTPS",
                "pattern": "Sync",
            },
            "estimated_monthly_cost": "$50-200",
            "documentation_url": "https://learn.microsoft.com/en-us/azure/azure-functions/",
        },
        {
            "azure_service": "Azure Cosmos DB",
            "source_service": "DynamoDB",
            "justification": "Multi-model NoSQL database.",
            "alternatives_considered": ["Azure Table Storage"],
            "description": "Globally distributed NoSQL database.",
            "tier_recommendation": "Serverless",
            "limitations": ["Item size limit 2 MB"],
            "sla": "99.99%",
            "communication": {
                "connects_to": ["Azure Functions"],
                "protocol": "SDK",
                "pattern": "Sync",
            },
            "estimated_monthly_cost": "$25-100",
            "documentation_url": "",
        },
    ],
    "networking_design": {
        "topology": "Flat",
        "vnet_design": "N/A — Serverless architecture",
        "connectivity": "Internet",
        "dns_strategy": "Azure DNS",
        "security_controls": ["APIM policies", "Function keys", "RBAC"],
        "recommendations": ["Consider VNet integration for Functions"],
    },
    "security_design": {
        "identity": "Managed Identities for Functions",
        "data_protection": "Encryption at rest (AES-256)",
        "network_security": "APIM as single entry point",
        "secrets_management": "Azure Key Vault",
        "compliance_frameworks": ["SOC 2"],
        "recommendations": ["Enable diagnostic logging"],
    },
    "data_architecture": {
        "data_flow": "API → Functions → Cosmos DB",
        "storage_strategy": "Hot tier for active data",
        "database_strategy": "NoSQL",
        "data_residency": "West Europe",
        "backup_and_recovery": "RPO: 4 hours, RTO: 1 hour",
    },
    "azure_caf_alignment": {
        "landing_zone": "Online Landing Zone",
        "management_groups": "Tenant Root → Platform → Landing Zones",
        "subscription_design": "Single subscription",
        "naming_convention": "func-*, cosmos-*",
        "tagging_strategy": "environment, project, owner",
        "resource_organization": "Single resource group per environment",
    },
    "finops": {
        "total_estimated_monthly_cost": "$100-400",
        "cost_optimization_recommendations": [
            "Use Consumption plan for Functions",
            "Enable Cosmos DB autoscale",
        ],
        "reserved_instances_candidates": [],
        "savings_plan_eligible": ["Azure Functions Premium"],
        "cost_monitoring": "Azure Cost Management",
        "showback_chargeback": "Tag-based cost allocation",
    },
    "region_strategy": {
        "primary_region": "West Europe",
        "dr_region": "North Europe",
        "region_selection_factors": ["latency", "compliance"],
        "data_residency_considerations": "GDPR requires data within EU",
        "multi_region_considerations": "Active-passive",
    },
    "waf_assessment": {
        "reliability": {"score": "High", "notes": "Serverless with built-in HA"},
        "security": {"score": "Medium", "notes": "Needs private endpoints"},
        "cost_optimization": {"score": "High", "notes": "Consumption-based pricing"},
        "operational_excellence": {"score": "Medium", "notes": "Add IaC and CI/CD"},
        "performance_efficiency": {"score": "High", "notes": "Auto-scaling serverless"},
    },
    "migration_approach": {
        "strategy": "Replatform",
        "phases": [
            {
                "phase": 1,
                "name": "Foundation",
                "description": "Set up Azure landing zone",
                "services": ["Resource Group"],
                "duration_weeks": 2,
                "dependencies": [],
                "risks": ["Skill gap"],
            },
        ],
        "rollback_plan": "Keep AWS running for 30 days",
        "testing_strategy": "Blue-green deployment",
    },
    "considerations": [
        "Serverless cold starts may affect latency",
    ],
    "risks_and_mitigations": [
        {"risk": "Cold start latency", "impact": "Medium", "mitigation": "Use Premium plan"},
        {"risk": "Vendor lock-in", "impact": "Low", "mitigation": "Use standard APIs"},
    ],
    "next_steps": [
        "Set up Azure subscription",
        "Create proof-of-concept",
    ],
    "_metadata": {
        "generated_at": "2026-02-21T12:00:00Z",
        "model": "gpt-4o",
        "version": "3.0.0",
    },
}


# ====================================================================
# 1. Supported Formats
# ====================================================================

class TestSupportedFormats:
    def test_supported_formats(self):
        assert "docx" in SUPPORTED_FORMATS
        assert "pdf" in SUPPORTED_FORMATS
        assert "pptx" in SUPPORTED_FORMATS

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            export_hld(MOCK_HLD, format="xlsx")


# ====================================================================
# 2. DOCX Export
# ====================================================================

class TestDocxExport:
    def test_docx_generates_bytes(self):
        result = export_hld_docx(MOCK_HLD, include_diagrams=False)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # DOCX files start with PK (ZIP format)
        assert result[:2] == b"PK"

    def test_docx_via_dispatcher(self):
        result = export_hld(MOCK_HLD, format="docx", include_diagrams=False)
        assert result["format"] == "docx"
        assert result["filename"].endswith(".docx")
        assert result["content_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        # Verify base64 encoding
        decoded = base64.b64decode(result["content_b64"])
        assert decoded[:2] == b"PK"

    def test_docx_with_empty_services(self):
        hld = {**MOCK_HLD, "services": []}
        result = export_hld_docx(hld, include_diagrams=False)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_docx_with_minimal_hld(self):
        minimal = {"title": "Test HLD", "executive_summary": "Test summary"}
        result = export_hld_docx(minimal, include_diagrams=False)
        assert isinstance(result, bytes)


# ====================================================================
# 3. PDF Export
# ====================================================================

class TestPdfExport:
    def test_pdf_generates_bytes(self):
        result = export_hld_pdf(MOCK_HLD, include_diagrams=False)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PDF files start with %PDF
        assert result[:4] == b"%PDF"

    def test_pdf_via_dispatcher(self):
        result = export_hld(MOCK_HLD, format="pdf", include_diagrams=False)
        assert result["format"] == "pdf"
        assert result["filename"].endswith(".pdf")
        assert result["content_type"] == "application/pdf"
        decoded = base64.b64decode(result["content_b64"])
        assert decoded[:4] == b"%PDF"

    def test_pdf_with_empty_services(self):
        hld = {**MOCK_HLD, "services": []}
        result = export_hld_pdf(hld, include_diagrams=False)
        assert isinstance(result, bytes)

    def test_pdf_with_minimal_hld(self):
        minimal = {"title": "Test HLD", "executive_summary": "Test summary"}
        result = export_hld_pdf(minimal, include_diagrams=False)
        assert isinstance(result, bytes)

    def test_pdf_with_waf_assessment(self):
        result = export_hld_pdf(MOCK_HLD, include_diagrams=False)
        # Verify it contains enough data (WAF table adds size)
        assert len(result) > 1000


# ====================================================================
# 4. PPTX Export
# ====================================================================

class TestPptxExport:
    def test_pptx_generates_bytes(self):
        result = export_hld_pptx(MOCK_HLD, include_diagrams=False)
        assert isinstance(result, bytes)
        assert len(result) > 0
        # PPTX files start with PK (ZIP format)
        assert result[:2] == b"PK"

    def test_pptx_via_dispatcher(self):
        result = export_hld(MOCK_HLD, format="pptx", include_diagrams=False)
        assert result["format"] == "pptx"
        assert result["filename"].endswith(".pptx")
        assert result["content_type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        decoded = base64.b64decode(result["content_b64"])
        assert decoded[:2] == b"PK"

    def test_pptx_with_empty_services(self):
        hld = {**MOCK_HLD, "services": []}
        result = export_hld_pptx(hld, include_diagrams=False)
        assert isinstance(result, bytes)

    def test_pptx_with_minimal_hld(self):
        minimal = {"title": "Test HLD", "executive_summary": "Test summary"}
        result = export_hld_pptx(minimal, include_diagrams=False)
        assert isinstance(result, bytes)


# ====================================================================
# 5. Include Diagrams Toggle
# ====================================================================

class TestDiagramInclusion:
    def test_docx_without_diagrams(self):
        result = export_hld_docx(MOCK_HLD, include_diagrams=False)
        assert isinstance(result, bytes)

    def test_docx_with_diagrams_no_image(self):
        # include_diagrams=True but no image provided — should still work
        result = export_hld_docx(MOCK_HLD, include_diagrams=True, diagram_b64=None)
        assert isinstance(result, bytes)

    def test_pdf_without_diagrams(self):
        result = export_hld_pdf(MOCK_HLD, include_diagrams=False)
        assert isinstance(result, bytes)

    def test_pptx_without_diagrams(self):
        result = export_hld_pptx(MOCK_HLD, include_diagrams=False)
        assert isinstance(result, bytes)


# ====================================================================
# 6. Dispatcher Function
# ====================================================================

class TestExportDispatcher:
    def test_all_formats_return_required_keys(self):
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(MOCK_HLD, format=fmt, include_diagrams=False)
            assert "format" in result
            assert "filename" in result
            assert "content_b64" in result
            assert "content_type" in result

    def test_filename_includes_archmorph(self):
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(MOCK_HLD, format=fmt, include_diagrams=False)
            assert "archmorph" in result["filename"].lower()

    def test_content_b64_is_valid_base64(self):
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(MOCK_HLD, format=fmt, include_diagrams=False)
            # Should not raise
            decoded = base64.b64decode(result["content_b64"])
            assert len(decoded) > 0


# ====================================================================
# 7. Edge Cases
# ====================================================================

class TestEdgeCases:
    def test_hld_with_none_values(self):
        hld = {**MOCK_HLD, "architecture_overview": None, "finops": None}
        # Should not crash
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(hld, format=fmt, include_diagrams=False)
            assert result["format"] == fmt

    def test_hld_with_empty_dict(self):
        hld = {}
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(hld, format=fmt, include_diagrams=False)
            assert result["format"] == fmt

    def test_hld_with_long_text(self):
        hld = {**MOCK_HLD, "executive_summary": "A" * 10000}
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(hld, format=fmt, include_diagrams=False)
            assert len(result["content_b64"]) > 0

    def test_hld_with_unicode(self):
        hld = {**MOCK_HLD, "title": "Migration Design — résumé & über-plan 中文"}
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(hld, format=fmt, include_diagrams=False)
            assert result["format"] == fmt

    def test_hld_with_special_characters_in_risks(self):
        hld = {
            **MOCK_HLD,
            "risks_and_mitigations": [
                {"risk": "Risk with <html> & \"quotes\"", "impact": "High", "mitigation": "Escape properly"},
            ],
        }
        for fmt in SUPPORTED_FORMATS:
            result = export_hld(hld, format=fmt, include_diagrams=False)
            assert result["format"] == fmt

def test_safe_helper():
    from hld_export import _safe
    assert _safe("hello") == "hello"
    assert _safe(None) == "N/A"
    assert _safe(None, "Unknown") == "Unknown"
    assert _safe(123) == "123"

def test_pdf_safe_helper():
    from hld_export import _pdf_safe
    assert _pdf_safe("Hello \u2014 World") == "Hello -- World"
    assert _pdf_safe("Item \u2022 list") == "Item - list"
    assert _pdf_safe("\u2192 \u2190 \u00a0 \u00b7") == "-> <-   -"
    assert _pdf_safe("Emoji \U0001f600") == "Emoji ?"

def test_decode_diagram_image():
    from hld_export import _decode_diagram_image
    assert _decode_diagram_image(None) is None
    assert _decode_diagram_image("") is None
    assert _decode_diagram_image("SGVsbG8=") == b"Hello"
    assert _decode_diagram_image("data:image/png;base64,SGVsbG8=") == b"Hello"
    assert _decode_diagram_image("invalid_base_64!@#") is None

def test_export_docx_full():
    from hld_export import export_hld_docx
    MOCK_HLD_FULL = {
        "title": "Full HLD Document",
        "_metadata": {
            "source_provider": "AWS",
            "target_provider": "Azure",
            "confidence_score": 0.95
        },
        "executive_summary": "Summary text • bullet",
        "architecture_overview": {
            "description": "Overview \u2192",
            "architecture_style": "Microservices",
            "deployment_model": "PaaS"
        },
        "services": [
            {
                "azure_service": "Azure Functions",
                "source_service": "AWS Lambda",
                "justification": "Direct match for serverless functions.",
                "alternatives_considered": ["ACA", "AKS"],
                "description": "Serverless compute tier.",
                "tier_recommendation": "Consumption plan",
                "limitations": ["Cold starts"],
                "sla": "99.99%",
                "communication": {
                    "connects_to": ["Cosmos DB"],
                    "protocol": "HTTPS",
                    "pattern": "Sync"
                },
                "estimated_monthly_cost": "$20",
                "documentation_url": "https://url",
                "compliance_standards": "HIPAA"
            }
        ],
        "migration_strategy": {
            "phases": [
                {"phase": "1", "activities": ["Plan"]},
                {"phase": 2, "activities": ["Execute"]},
                {"phase": "3", "activities": None}
            ],
            "risks": [
                {"risk": "Data loss", "mitigation": "Backup"}
            ]
        }
    }
    res = export_hld_docx(MOCK_HLD_FULL, include_diagrams=True, diagram_b64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    assert res.startswith(b"PK\x03\x04") 

def test_export_pdf_full():
    from hld_export import export_hld_pdf
    MOCK_HLD_FULL = {"title": "Test HLD", "_metadata": {"source_provider": "AWS"}}
    res = export_hld_pdf(MOCK_HLD_FULL, include_diagrams=True, diagram_b64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    assert res.startswith(b"%PDF-") 

def test_export_pptx_full():
    from hld_export import export_hld_pptx
    MOCK_HLD_FULL = {"title": "Test HLD", "_metadata": {"source_provider": "AWS"}}
    res = export_hld_pptx(MOCK_HLD_FULL, include_diagrams=True, diagram_b64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    assert res.startswith(b"PK\x03\x04") 

def test_export_hld_invalid_format():
    from hld_export import export_hld
    import pytest
    with pytest.raises(ValueError):
        export_hld({}, format="txt")
