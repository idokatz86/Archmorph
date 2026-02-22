"""
Archmorph — Unit Tests for HLD Generator Module
=================================================

Tests the hld_generator.py module:
  - Documentation link lookup
  - HLD JSON → Markdown conversion
  - GPT-4o HLD generation (mocked)
  - API endpoint integration tests
"""

import copy
import io
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hld_generator import (
    _find_doc_link,
    generate_hld,
    generate_hld_markdown,
    AZURE_DOC_LINKS,
)


# ====================================================================
# Fixtures
# ====================================================================

MOCK_ANALYSIS = {
    "diagram_type": "Cloud Architecture",
    "source_provider": "aws",
    "target_provider": "azure",
    "architecture_patterns": ["multi-AZ", "event-driven"],
    "services_detected": 4,
    "zones": [
        {
            "id": 1, "name": "Compute", "number": 1,
            "services": [
                {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
                {"aws": "Amazon S3", "azure": "Azure Blob Storage", "confidence": 0.95},
            ],
        },
        {
            "id": 2, "name": "Database", "number": 2,
            "services": [
                {"aws": "DynamoDB", "azure": "Cosmos DB", "confidence": 0.85},
            ],
        },
    ],
    "mappings": [
        {"source_service": "Lambda", "source_provider": "aws", "azure_service": "Azure Functions", "confidence": 0.95, "notes": "Zone 1"},
        {"source_service": "Amazon S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.95, "notes": "Zone 1"},
        {"source_service": "DynamoDB", "source_provider": "aws", "azure_service": "Cosmos DB", "confidence": 0.85, "notes": "Zone 2"},
        {"source_service": "API Gateway", "source_provider": "aws", "azure_service": "Azure API Management", "confidence": 0.85, "notes": "Zone 1"},
    ],
    "service_connections": [
        {"from": "API Gateway", "to": "Lambda", "protocol": "HTTPS"},
        {"from": "Lambda", "to": "DynamoDB", "protocol": "SDK"},
    ],
    "warnings": ["Some services may require manual configuration"],
    "confidence_summary": {"high": 2, "medium": 2, "low": 0, "average": 0.90},
}

MOCK_HLD_RESPONSE = {
    "title": "AWS to Azure Migration — High-Level Design",
    "executive_summary": "This document outlines the migration strategy from AWS to Azure for a serverless event-driven architecture.",
    "architecture_overview": {
        "description": "A serverless microservices architecture using Azure Functions, Cosmos DB, and API Management.",
        "diagram_description": "API calls flow through APIM to Functions, which read/write Cosmos DB.",
        "architecture_style": "Serverless",
        "deployment_model": "Public Cloud",
    },
    "services": [
        {
            "azure_service": "Azure Functions",
            "source_service": "Lambda",
            "justification": "Direct equivalent for serverless compute with consumption-based pricing.",
            "alternatives_considered": ["Azure Container Apps", "Azure App Service"],
            "description": "Serverless compute for event-driven workloads.",
            "tier_recommendation": "Consumption plan",
            "limitations": ["Cold start latency", "5-minute timeout on Consumption plan"],
            "sla": "99.95%",
            "communication": {
                "connects_to": ["Azure Cosmos DB", "Azure API Management"],
                "protocol": "HTTPS",
                "pattern": "Sync",
            },
            "estimated_monthly_cost": "$50-200",
            "documentation_url": "",
        },
        {
            "azure_service": "Azure Cosmos DB",
            "source_service": "DynamoDB",
            "justification": "Multi-model NoSQL database with global distribution.",
            "alternatives_considered": ["Azure Table Storage"],
            "description": "Globally distributed NoSQL database.",
            "tier_recommendation": "Serverless",
            "limitations": ["400 RU/s minimum on provisioned", "Item size limit 2 MB"],
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
        "recommendations": ["Consider VNet integration for Functions if accessing on-prem resources"],
    },
    "security_design": {
        "identity": "Managed Identities for Functions, Entra ID for APIM",
        "data_protection": "Encryption at rest (AES-256) and in transit (TLS 1.2+)",
        "network_security": "APIM as single entry point, Function access keys",
        "secrets_management": "Azure Key Vault for connection strings",
        "compliance_frameworks": ["SOC 2"],
        "recommendations": ["Enable diagnostic logging"],
    },
    "data_architecture": {
        "data_flow": "API → Functions → Cosmos DB",
        "storage_strategy": "Hot tier for active data",
        "database_strategy": "NoSQL (Cosmos DB) for low-latency reads",
        "data_residency": "West Europe for GDPR compliance",
        "backup_and_recovery": "RPO: 4 hours, RTO: 1 hour — Cosmos DB continuous backup",
    },
    "azure_caf_alignment": {
        "landing_zone": "Online Landing Zone",
        "management_groups": "Tenant Root → Platform → Landing Zones → Online",
        "subscription_design": "Single subscription for workload",
        "naming_convention": "func-*, cosmos-*, apim-*",
        "tagging_strategy": "environment, project, owner, cost-center",
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
        "cost_monitoring": "Azure Cost Management with monthly budgets and alerts",
        "showback_chargeback": "Tag-based cost allocation by project",
    },
    "region_strategy": {
        "primary_region": "West Europe (Netherlands)",
        "dr_region": "North Europe (Ireland)",
        "region_selection_factors": ["latency", "compliance", "cost"],
        "data_residency_considerations": "GDPR requires data within EU",
        "multi_region_considerations": "Active-passive with Cosmos DB multi-region writes",
    },
    "waf_assessment": {
        "reliability": {"score": "High", "notes": "Serverless with built-in HA"},
        "security": {"score": "Medium", "notes": "Needs private endpoints for production"},
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
                "description": "Set up Azure landing zone and networking",
                "services": ["Resource Group", "Azure Monitor"],
                "duration_weeks": 2,
                "dependencies": [],
                "risks": ["Skill gap in Azure"],
            },
            {
                "phase": 2,
                "name": "Data Migration",
                "description": "Migrate DynamoDB to Cosmos DB",
                "services": ["Azure Cosmos DB"],
                "duration_weeks": 3,
                "dependencies": ["Phase 1"],
                "risks": ["Data consistency during migration"],
            },
        ],
        "rollback_plan": "Keep AWS environment running in parallel for 30 days",
        "testing_strategy": "Blue-green deployment with traffic splitting",
    },
    "considerations": [
        "Serverless cold starts may affect latency",
        "Cosmos DB pricing model differs from DynamoDB",
    ],
    "risks_and_mitigations": [
        {"risk": "Cold start latency", "impact": "Medium", "mitigation": "Use Premium plan or pre-warming"},
        {"risk": "Vendor lock-in", "impact": "Low", "mitigation": "Use standard APIs where possible"},
    ],
    "next_steps": [
        "Set up Azure subscription and landing zone",
        "Create proof-of-concept with single Function + Cosmos DB",
    ],
}


# ====================================================================
# 1. Documentation Link Lookup
# ====================================================================

class TestDocLinks:
    def test_exact_match(self):
        url = _find_doc_link("Azure Functions")
        assert url == "https://learn.microsoft.com/en-us/azure/azure-functions/"

    def test_exact_match_cosmos(self):
        url = _find_doc_link("Azure Cosmos DB")
        assert url == "https://learn.microsoft.com/en-us/azure/cosmos-db/"

    def test_partial_match(self):
        url = _find_doc_link("Cosmos DB")
        assert "cosmos-db" in url

    def test_partial_match_case(self):
        url = _find_doc_link("Azure Key Vault")
        assert "key-vault" in url

    def test_fallback_generic(self):
        url = _find_doc_link("Azure Quantum Madeup Service")
        assert url.startswith("https://learn.microsoft.com/en-us/azure/")

    def test_all_links_are_valid_urls(self):
        for svc, url in AZURE_DOC_LINKS.items():
            assert url.startswith("https://learn.microsoft.com/"), f"Bad URL for {svc}: {url}"

    def test_doc_links_has_common_services(self):
        common = [
            "Azure Virtual Machines", "Azure Blob Storage", "Azure SQL Database",
            "Azure Kubernetes Service (AKS)", "Azure Key Vault", "Azure Monitor",
        ]
        for svc in common:
            assert svc in AZURE_DOC_LINKS, f"Missing doc link for {svc}"


# ====================================================================
# 2. Markdown Generation
# ====================================================================

class TestMarkdownGeneration:
    def test_generates_markdown_string(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert isinstance(md, str)
        assert len(md) > 500

    def test_has_title(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "# AWS to Azure Migration — High-Level Design" in md

    def test_has_executive_summary_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 1. Executive Summary" in md
        assert "migration strategy" in md.lower()

    def test_has_services_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 3. Azure Services" in md
        assert "Azure Functions" in md
        assert "Azure Cosmos DB" in md

    def test_has_documentation_links(self):
        # Enrich doc URLs
        for svc in MOCK_HLD_RESPONSE["services"]:
            svc["documentation_url"] = "https://learn.microsoft.com/en-us/azure/test/"
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "Documentation" in md

    def test_has_networking_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 4. Networking Design" in md
        assert "Flat" in md

    def test_has_security_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 5. Security Design" in md

    def test_has_finops_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 8. FinOps" in md
        assert "$100-400" in md

    def test_has_waf_table(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 10. Well-Architected Framework" in md
        assert "| Reliability" in md
        assert "High" in md

    def test_has_migration_phases(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 11. Migration Roadmap" in md
        assert "Phase 1" in md
        assert "Foundation" in md

    def test_has_risks(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 13. Risks & Mitigations" in md
        assert "Cold start" in md

    def test_has_next_steps(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 14. Next Steps" in md
        assert "proof-of-concept" in md.lower()

    def test_has_caf_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 7. Azure Cloud Adoption Framework" in md
        assert "func-*" in md

    def test_has_region_section(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "## 9. Region Strategy" in md
        assert "West Europe" in md

    def test_empty_hld_produces_minimal_markdown(self):
        md = generate_hld_markdown({"title": "Empty HLD"})
        assert "# Empty HLD" in md

    def test_markdown_has_footer(self):
        md = generate_hld_markdown(MOCK_HLD_RESPONSE)
        assert "Archmorph v" in md


# ====================================================================
# 3. HLD Generation (GPT-4o mocked)
# ====================================================================

class TestHldGeneration:
    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_calls_gpt4o(self, mock_cached):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        generate_hld(MOCK_ANALYSIS)

        # Should call cached_chat_completion
        mock_cached.assert_called_once()
        call_kwargs = mock_cached.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["response_format"] == {"type": "json_object"}

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_returns_dict(self, mock_cached):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        hld = generate_hld(MOCK_ANALYSIS)
        assert isinstance(hld, dict)
        assert "title" in hld
        assert "services" in hld
        assert "_metadata" in hld

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_enriches_doc_links(self, mock_cached):
        response = copy.deepcopy(MOCK_HLD_RESPONSE)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(response)
        mock_cached.return_value = mock_response

        hld = generate_hld(MOCK_ANALYSIS)
        for svc in hld.get("services", []):
            assert svc.get("documentation_url"), f"Missing doc URL for {svc.get('azure_service')}"
            assert svc["documentation_url"].startswith("https://learn.microsoft.com")

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_metadata(self, mock_cached):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        hld = generate_hld(MOCK_ANALYSIS)
        meta = hld["_metadata"]
        assert meta["source_provider"] == "aws"
        assert meta["services_count"] == 4
        assert meta["generated_by"] == "Archmorph HLD Generator v1.0"

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_with_cost_estimate(self, mock_cached):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        cost = {
            "services": [
                {"service": "Azure Functions", "monthly_low": 50, "monthly_high": 200},
                {"service": "Cosmos DB", "monthly_low": 25, "monthly_high": 100},
            ],
            "total_monthly_estimate": {"low": 75, "high": 300},
        }
        hld = generate_hld(MOCK_ANALYSIS, cost_estimate=cost)
        # Should succeed with cost data included in context
        assert isinstance(hld, dict)

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_deduplicates_services(self, mock_cached):
        # Analysis with duplicate azure services
        analysis = copy.deepcopy(MOCK_ANALYSIS)
        analysis["mappings"].append({
            "source_service": "Lambda (2nd instance)",
            "source_provider": "aws",
            "azure_service": "Azure Functions",  # duplicate
            "confidence": 0.90,
            "notes": "Zone 3",
        })

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        hld = generate_hld(analysis)
        # Metadata should show deduplicated count
        assert hld["_metadata"]["services_count"] == 4  # not 5

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_skips_manual_mappings(self, mock_cached):
        analysis = copy.deepcopy(MOCK_ANALYSIS)
        analysis["mappings"].append({
            "source_service": "Unknown",
            "azure_service": "[Manual mapping needed]",
            "confidence": 0.0,
        })

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        hld = generate_hld(analysis)
        assert hld["_metadata"]["services_count"] == 4  # manual mapping excluded

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_failure_raises(self, mock_cached):
        mock_cached.side_effect = Exception("API error")

        with pytest.raises(ValueError, match="HLD generation failed"):
            generate_hld(MOCK_ANALYSIS)

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_includes_connections_in_context(self, mock_cached):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        generate_hld(MOCK_ANALYSIS)

        # Verify the user message includes service connections
        call_kwargs = mock_cached.call_args.kwargs
        messages = call_kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "Service Connections" in user_msg
        assert "API Gateway" in user_msg


# ====================================================================
# 4. HLD API Endpoint Integration Tests
# ====================================================================

class TestHldEndpoints:
    @pytest.fixture(scope="module")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    @pytest.fixture
    def analyzed_diagram(self, client):
        from main import SESSION_STORE, IMAGE_STORE
        SESSION_STORE.clear()
        IMAGE_STORE.clear()

        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-hld/diagrams",
            files={"file": ("arch.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        with patch("routers.diagrams.analyze_image", return_value=copy.deepcopy(MOCK_ANALYSIS)):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        yield diagram_id
        SESSION_STORE.clear()
        IMAGE_STORE.clear()

    @patch("hld_generator.cached_chat_completion")
    def test_generate_hld_endpoint(self, mock_cached, client, analyzed_diagram):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        resp = client.post(f"/api/diagrams/{analyzed_diagram}/generate-hld")
        assert resp.status_code == 200
        data = resp.json()
        assert "hld" in data
        assert "markdown" in data
        assert data["hld"]["title"] == "AWS to Azure Migration — High-Level Design"
        assert len(data["markdown"]) > 100

    def test_generate_hld_404_no_analysis(self, client):
        resp = client.post("/api/diagrams/nonexistent-diag/generate-hld")
        assert resp.status_code == 404

    @patch("hld_generator.cached_chat_completion")
    def test_get_hld_after_generation(self, mock_cached, client, analyzed_diagram):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_HLD_RESPONSE)
        mock_cached.return_value = mock_response

        # Generate first
        client.post(f"/api/diagrams/{analyzed_diagram}/generate-hld")

        # Then GET
        resp = client.get(f"/api/diagrams/{analyzed_diagram}/hld")
        assert resp.status_code == 200
        data = resp.json()
        assert "hld" in data
        assert "markdown" in data

    def test_get_hld_404_not_generated(self, client, analyzed_diagram):
        resp = client.get(f"/api/diagrams/{analyzed_diagram}/hld")
        assert resp.status_code == 404
