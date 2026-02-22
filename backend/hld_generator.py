"""
Archmorph HLD Generator — AI-powered High-Level Design document.

Generates a comprehensive HLD document from migration analysis results,
covering service justification, communication patterns, costs, networking,
compliance, Azure CAF alignment, FinOps, limitations, and more.
"""

from version import __version__

import json
import logging
from typing import Any, Dict, Optional

from openai_client import cached_chat_completion, AZURE_OPENAI_DEPLOYMENT
from prompt_guard import PROMPT_ARMOR

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Azure service documentation links
# ─────────────────────────────────────────────────────────────
AZURE_DOC_LINKS: Dict[str, str] = {
    "Azure Virtual Machines": "https://learn.microsoft.com/en-us/azure/virtual-machines/",
    "Azure App Service": "https://learn.microsoft.com/en-us/azure/app-service/",
    "Azure Functions": "https://learn.microsoft.com/en-us/azure/azure-functions/",
    "Azure Kubernetes Service (AKS)": "https://learn.microsoft.com/en-us/azure/aks/",
    "Azure Container Apps": "https://learn.microsoft.com/en-us/azure/container-apps/",
    "Azure Container Instances": "https://learn.microsoft.com/en-us/azure/container-instances/",
    "Azure Blob Storage": "https://learn.microsoft.com/en-us/azure/storage/blobs/",
    "Azure Files": "https://learn.microsoft.com/en-us/azure/storage/files/",
    "Azure Data Lake Storage": "https://learn.microsoft.com/en-us/azure/storage/blobs/data-lake-storage-introduction",
    "Azure SQL Database": "https://learn.microsoft.com/en-us/azure/azure-sql/",
    "Azure Cosmos DB": "https://learn.microsoft.com/en-us/azure/cosmos-db/",
    "Azure Database for PostgreSQL": "https://learn.microsoft.com/en-us/azure/postgresql/",
    "Azure Database for MySQL": "https://learn.microsoft.com/en-us/azure/mysql/",
    "Azure Cache for Redis": "https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/",
    "Azure Virtual Network": "https://learn.microsoft.com/en-us/azure/virtual-network/",
    "Azure Load Balancer": "https://learn.microsoft.com/en-us/azure/load-balancer/",
    "Azure Application Gateway": "https://learn.microsoft.com/en-us/azure/application-gateway/",
    "Azure Front Door": "https://learn.microsoft.com/en-us/azure/frontdoor/",
    "Azure CDN": "https://learn.microsoft.com/en-us/azure/cdn/",
    "Azure DNS": "https://learn.microsoft.com/en-us/azure/dns/",
    "Azure Firewall": "https://learn.microsoft.com/en-us/azure/firewall/",
    "Azure VPN Gateway": "https://learn.microsoft.com/en-us/azure/vpn-gateway/",
    "Azure ExpressRoute": "https://learn.microsoft.com/en-us/azure/expressroute/",
    "Azure Bastion": "https://learn.microsoft.com/en-us/azure/bastion/",
    "Azure DDoS Protection": "https://learn.microsoft.com/en-us/azure/ddos-protection/",
    "Azure Key Vault": "https://learn.microsoft.com/en-us/azure/key-vault/",
    "Microsoft Entra ID": "https://learn.microsoft.com/en-us/entra/identity/",
    "Azure Monitor": "https://learn.microsoft.com/en-us/azure/azure-monitor/",
    "Azure Log Analytics": "https://learn.microsoft.com/en-us/azure/azure-monitor/logs/",
    "Application Insights": "https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview",
    "Azure Policy": "https://learn.microsoft.com/en-us/azure/governance/policy/",
    "Azure Event Hubs": "https://learn.microsoft.com/en-us/azure/event-hubs/",
    "Azure Service Bus": "https://learn.microsoft.com/en-us/azure/service-bus-messaging/",
    "Azure Logic Apps": "https://learn.microsoft.com/en-us/azure/logic-apps/",
    "Azure API Management": "https://learn.microsoft.com/en-us/azure/api-management/",
    "Azure Data Factory": "https://learn.microsoft.com/en-us/azure/data-factory/",
    "Azure Synapse Analytics": "https://learn.microsoft.com/en-us/azure/synapse-analytics/",
    "Azure Databricks": "https://learn.microsoft.com/en-us/azure/databricks/",
    "Azure Machine Learning": "https://learn.microsoft.com/en-us/azure/machine-learning/",
    "Azure Cognitive Services": "https://learn.microsoft.com/en-us/azure/ai-services/",
    "Azure OpenAI Service": "https://learn.microsoft.com/en-us/azure/ai-services/openai/",
    "Azure IoT Hub": "https://learn.microsoft.com/en-us/azure/iot-hub/",
    "Azure IoT Edge": "https://learn.microsoft.com/en-us/azure/iot-edge/",
    "Azure Digital Twins": "https://learn.microsoft.com/en-us/azure/digital-twins/",
    "Azure Stream Analytics": "https://learn.microsoft.com/en-us/azure/stream-analytics/",
    "Azure Purview": "https://learn.microsoft.com/en-us/azure/purview/",
    "Microsoft Purview": "https://learn.microsoft.com/en-us/azure/purview/",
    "Azure DevOps": "https://learn.microsoft.com/en-us/azure/devops/",
    "Azure Managed Grafana": "https://learn.microsoft.com/en-us/azure/managed-grafana/",
    "Azure Site Recovery": "https://learn.microsoft.com/en-us/azure/site-recovery/",
    "Azure Backup": "https://learn.microsoft.com/en-us/azure/backup/",
    "Azure Stack Edge": "https://learn.microsoft.com/en-us/azure/databox-online/",
    "Power BI": "https://learn.microsoft.com/en-us/power-bi/",
    "Azure AI Search": "https://learn.microsoft.com/en-us/azure/search/",
    "Azure Notification Hubs": "https://learn.microsoft.com/en-us/azure/notification-hubs/",
    "Azure Communication Services": "https://learn.microsoft.com/en-us/azure/communication-services/",
    "Azure Static Web Apps": "https://learn.microsoft.com/en-us/azure/static-web-apps/",
    "Azure NAT Gateway": "https://learn.microsoft.com/en-us/azure/nat-gateway/",
    "VM Scale Sets": "https://learn.microsoft.com/en-us/azure/virtual-machine-scale-sets/",
    "Network Security Group (NSG)": "https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview",
    "HDInsight": "https://learn.microsoft.com/en-us/azure/hdinsight/",
}


def _find_doc_link(service_name: str) -> str:
    """Find the best documentation link for an Azure service."""
    if service_name in AZURE_DOC_LINKS:
        return AZURE_DOC_LINKS[service_name]
    # Fuzzy search
    svc_lower = service_name.lower()
    for key, url in AZURE_DOC_LINKS.items():
        if key.lower() in svc_lower or svc_lower in key.lower():
            return url
    # Generic fallback
    slug = service_name.lower().replace(" ", "-").replace("(", "").replace(")", "")
    return f"https://learn.microsoft.com/en-us/azure/{slug}/"


# ─────────────────────────────────────────────────────────────
# HLD system prompt
# ─────────────────────────────────────────────────────────────
HLD_SYSTEM_PROMPT = """\
You are a **Senior Azure Cloud Architect** creating a comprehensive **High-Level Design (HLD)** document for a cloud migration project. You have deep expertise in Azure Cloud Adoption Framework (CAF), Well-Architected Framework (WAF), FinOps, and enterprise architecture patterns.

You will be given the analysis of a source cloud architecture (AWS/GCP) and its Azure service mappings. Generate a complete HLD document.

## Required HLD Sections

Return a JSON object with these EXACT keys:

```json
{
  "title": "<Project title>",
  "executive_summary": "<2-3 paragraph executive summary>",
  "architecture_overview": {
    "description": "<High-level description of the target Azure architecture>",
    "diagram_description": "<Text description of the architecture flow>",
    "architecture_style": "<Microservices/Serverless/Event-driven/Monolithic/Hybrid>",
    "deployment_model": "<Public Cloud / Hybrid / Multi-Cloud>"
  },
  "services": [
    {
      "azure_service": "<Service name>",
      "source_service": "<Original AWS/GCP service>",
      "justification": "<Why this Azure service was chosen over alternatives>",
      "alternatives_considered": ["<Alt 1>", "<Alt 2>"],
      "description": "<What this service does and its role in the architecture>",
      "tier_recommendation": "<SKU/tier recommendation with reasoning>",
      "limitations": ["<Limitation 1>", "<Limitation 2>"],
      "sla": "<SLA percentage>",
      "communication": {
        "connects_to": ["<Service 1>", "<Service 2>"],
        "protocol": "<HTTPS/gRPC/AMQP/TCP/Event-driven>",
        "pattern": "<Sync/Async/Event/Streaming>"
      },
      "estimated_monthly_cost": "<Cost range>",
      "documentation_url": "<Microsoft Learn URL>"
    }
  ],
  "networking_design": {
    "topology": "<Hub-Spoke / Flat / Mesh>",
    "vnet_design": "<VNet address space and subnet layout>",
    "connectivity": "<ExpressRoute / VPN / Internet>",
    "dns_strategy": "<Azure DNS / Private DNS Zones>",
    "security_controls": ["NSG", "Azure Firewall", "Private Endpoints", "etc"],
    "recommendations": ["<Rec 1>", "<Rec 2>"]
  },
  "security_design": {
    "identity": "<Entra ID / RBAC / Managed Identities strategy>",
    "data_protection": "<Encryption at rest and in transit>",
    "network_security": "<Zero Trust / Defense in depth>",
    "secrets_management": "<Key Vault strategy>",
    "compliance_frameworks": ["<Framework 1>"],
    "recommendations": ["<Rec 1>"]
  },
  "data_architecture": {
    "data_flow": "<How data moves through the system>",
    "storage_strategy": "<Hot/Cool/Archive tiering>",
    "database_strategy": "<SQL vs NoSQL choices and reasoning>",
    "data_residency": "<Region considerations for data sovereignty>",
    "backup_and_recovery": "<RPO/RTO targets and strategy>"
  },
  "azure_caf_alignment": {
    "landing_zone": "<Landing Zone recommendation>",
    "management_groups": "<MG hierarchy>",
    "subscription_design": "<Single vs multiple subscriptions>",
    "naming_convention": "<CAF naming standard applied>",
    "tagging_strategy": "<Required tags and governance>",
    "resource_organization": "<Resource Group strategy>"
  },
  "finops": {
    "total_estimated_monthly_cost": "<Cost range>",
    "cost_optimization_recommendations": ["<Rec 1>", "<Rec 2>"],
    "reserved_instances_candidates": ["<Service 1>"],
    "savings_plan_eligible": ["<Service 1>"],
    "cost_monitoring": "<Azure Cost Management + Budgets strategy>",
    "showback_chargeback": "<Cost allocation strategy>"
  },
  "region_strategy": {
    "primary_region": "<Recommended region with reasoning>",
    "dr_region": "<DR region>",
    "region_selection_factors": ["latency", "compliance", "service availability", "cost"],
    "data_residency_considerations": "<GDPR/sovereignty notes>",
    "multi_region_considerations": "<Active-active vs active-passive>"
  },
  "waf_assessment": {
    "reliability": {"score": "<High/Medium/Low>", "notes": "<Assessment>"},
    "security": {"score": "<High/Medium/Low>", "notes": "<Assessment>"},
    "cost_optimization": {"score": "<High/Medium/Low>", "notes": "<Assessment>"},
    "operational_excellence": {"score": "<High/Medium/Low>", "notes": "<Assessment>"},
    "performance_efficiency": {"score": "<High/Medium/Low>", "notes": "<Assessment>"}
  },
  "migration_approach": {
    "strategy": "<Rehost/Replatform/Refactor/Rebuild>",
    "phases": [
      {
        "phase": 1,
        "name": "<Phase name>",
        "description": "<What happens in this phase>",
        "services": ["<Service 1>", "<Service 2>"],
        "duration_weeks": 4,
        "dependencies": ["<Dep 1>"],
        "risks": ["<Risk 1>"]
      }
    ],
    "rollback_plan": "<Rollback strategy>",
    "testing_strategy": "<Validation approach>"
  },
  "considerations": [
    "<Important consideration 1>",
    "<Important consideration 2>"
  ],
  "risks_and_mitigations": [
    {"risk": "<Risk>", "impact": "<High/Medium/Low>", "mitigation": "<Strategy>"}
  ],
  "next_steps": ["<Action item 1>", "<Action item 2>"]
}
```

## Rules
1. Be thorough and specific — this is an enterprise HLD, not a summary.
2. Include real Azure service tiers, SKUs, and pricing estimates.
3. Reference Azure CAF naming conventions (e.g., rg-*, vnet-*, st*, kv-*).
4. Consider data residency, compliance (GDPR, HIPAA, PCI-DSS), and sovereignty.
5. Provide actionable migration phases with realistic timelines.
6. Include service limitations that could impact the architecture.
7. Apply Well-Architected Framework principles to each recommendation.
8. Focus on FinOps — cost optimization, reserved instances, right-sizing.
9. Keep service descriptions concise but technically accurate.
""" + PROMPT_ARMOR


def generate_hld(
    analysis: Dict[str, Any],
    cost_estimate: Optional[Dict[str, Any]] = None,
    iac_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate a comprehensive High-Level Design document.

    Parameters
    ----------
    analysis : dict
        The diagram analysis result with mappings, zones, patterns.
    cost_estimate : dict, optional
        Cost estimation data from azure_pricing.
    iac_params : dict, optional
        IaC parameters from guided questions.

    Returns
    -------
    dict
        Complete HLD document structure.
    """
    # Build context for GPT-4o
    mappings = analysis.get("mappings", [])
    zones = analysis.get("zones", [])
    patterns = analysis.get("architecture_patterns", [])
    connections = analysis.get("service_connections", [])
    source_provider = analysis.get("source_provider", "aws")
    diagram_type = analysis.get("diagram_type", "Cloud Architecture")
    warnings = analysis.get("warnings", [])

    # Deduplicate services
    seen = set()
    unique_mappings = []
    for m in mappings:
        svc = m.get("azure_service", "")
        if svc not in seen and not svc.startswith("[Manual mapping needed]"):
            seen.add(svc)
            unique_mappings.append(m)

    # Build context text
    context = f"""## Source Architecture
- Type: {diagram_type}
- Source Provider: {source_provider.upper()}
- Architecture Patterns: {', '.join(patterns) if patterns else 'N/A'}
- Total Services Detected: {len(mappings)}
- Zones: {len(zones)}

## Service Mappings
"""
    for m in unique_mappings:
        context += f"- {m.get('source_service', '?')} → {m.get('azure_service', '?')} (confidence: {m.get('confidence', 0):.0%})\n"

    if zones:
        context += "\n## Architecture Zones\n"
        for z in zones:
            context += f"- Zone {z.get('number', '?')}: {z.get('name', '?')} ({len(z.get('services', []))} services)\n"

    if connections:
        context += "\n## Service Connections\n"
        for c in connections:
            context += f"- {c.get('from', '?')} → {c.get('to', '?')} ({c.get('protocol', 'unknown')})\n"

    if cost_estimate and cost_estimate.get("services"):
        context += "\n## Cost Estimates\n"
        for s in cost_estimate["services"][:20]:
            context += f"- {s.get('service', '?')}: ${s.get('monthly_low', 0)}-${s.get('monthly_high', 0)}/mo\n"

    if iac_params:
        context += f"\n## IaC Parameters\n{json.dumps(iac_params, indent=2)}\n"

    if warnings:
        context += "\n## Warnings\n"
        for w in warnings[:10]:
            context += f"- {w}\n"

    # Call GPT-4o via cached wrapper (#183)
    logger.info("Generating HLD for %s (%d services)", diagram_type, len(unique_mappings))

    try:
        response = cached_chat_completion(
            messages=[
                {"role": "system", "content": HLD_SYSTEM_PROMPT},
                {"role": "user", "content": f"Generate a comprehensive HLD document for this migration:\n\n{context}"},
            ],
            model=AZURE_OPENAI_DEPLOYMENT,
            max_tokens=16384,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content.strip()
        logger.info("HLD response received (%d chars)", len(raw_text))
        hld = json.loads(raw_text)

    except Exception as exc:
        logger.error("HLD generation failed: %s", exc)
        raise ValueError(f"HLD generation failed: {exc}") from exc

    # Enrich with documentation links
    for svc in hld.get("services", []):
        azure_name = svc.get("azure_service", "")
        if not svc.get("documentation_url"):
            svc["documentation_url"] = _find_doc_link(azure_name)

    # Add metadata
    hld["_metadata"] = {
        "source_provider": source_provider,
        "diagram_type": diagram_type,
        "services_count": len(unique_mappings),
        "zones_count": len(zones),
        "generated_by": "Archmorph HLD Generator v1.0",
    }

    return hld


def generate_hld_markdown(hld: Dict[str, Any]) -> str:
    """Convert HLD JSON to a formatted Markdown document."""
    md = []

    md.append(f"# {hld.get('title', 'High-Level Design Document')}")
    md.append("\n*Generated by Archmorph — AI-powered Cloud Architecture Translator*\n")
    md.append("---\n")

    # Executive Summary
    md.append("## 1. Executive Summary\n")
    md.append(hld.get("executive_summary", "N/A"))
    md.append("")

    # Architecture Overview
    arch = hld.get("architecture_overview", {})
    md.append("\n## 2. Architecture Overview\n")
    md.append(f"**Architecture Style:** {arch.get('architecture_style', 'N/A')}\n")
    md.append(f"**Deployment Model:** {arch.get('deployment_model', 'N/A')}\n")
    md.append(f"\n{arch.get('description', '')}\n")
    if arch.get("diagram_description"):
        md.append(f"\n### Data Flow\n{arch['diagram_description']}\n")

    # Services Detail
    services = hld.get("services", [])
    if services:
        md.append("\n## 3. Azure Services — Detailed Design\n")
        for i, svc in enumerate(services, 1):
            md.append(f"\n### 3.{i}. {svc.get('azure_service', 'Unknown')}\n")
            if svc.get("source_service"):
                md.append(f"**Replaces:** {svc['source_service']}\n")
            md.append(f"\n{svc.get('description', '')}\n")
            md.append(f"\n**Justification:** {svc.get('justification', 'N/A')}\n")
            if svc.get("alternatives_considered"):
                md.append(f"**Alternatives Considered:** {', '.join(svc['alternatives_considered'])}\n")
            md.append(f"**Recommended Tier:** {svc.get('tier_recommendation', 'N/A')}\n")
            md.append(f"**SLA:** {svc.get('sla', 'N/A')}\n")
            md.append(f"**Estimated Cost:** {svc.get('estimated_monthly_cost', 'N/A')}\n")

            comm = svc.get("communication", {})
            if comm.get("connects_to"):
                md.append(f"**Connects To:** {', '.join(comm['connects_to'])} ({comm.get('protocol', 'N/A')} — {comm.get('pattern', 'N/A')})\n")

            if svc.get("limitations"):
                md.append("\n**Limitations:**")
                for lim in svc["limitations"]:
                    md.append(f"- {lim}")
                md.append("")

            if svc.get("documentation_url"):
                md.append(f"\n📖 [Documentation]({svc['documentation_url']})\n")

    # Networking Design
    net = hld.get("networking_design", {})
    if net:
        md.append("\n## 4. Networking Design\n")
        md.append(f"**Topology:** {net.get('topology', 'N/A')}\n")
        md.append(f"**VNet Design:** {net.get('vnet_design', 'N/A')}\n")
        md.append(f"**Connectivity:** {net.get('connectivity', 'N/A')}\n")
        md.append(f"**DNS Strategy:** {net.get('dns_strategy', 'N/A')}\n")
        if net.get("security_controls"):
            md.append(f"**Security Controls:** {', '.join(net['security_controls'])}\n")
        if net.get("recommendations"):
            md.append("\n**Recommendations:**")
            for r in net["recommendations"]:
                md.append(f"- {r}")

    # Security Design
    sec = hld.get("security_design", {})
    if sec:
        md.append("\n\n## 5. Security Design\n")
        for field, label in [("identity", "Identity & Access"), ("data_protection", "Data Protection"),
                             ("network_security", "Network Security"), ("secrets_management", "Secrets Management")]:
            if sec.get(field):
                md.append(f"**{label}:** {sec[field]}\n")
        if sec.get("compliance_frameworks"):
            md.append(f"**Compliance Frameworks:** {', '.join(sec['compliance_frameworks'])}\n")

    # Data Architecture
    data = hld.get("data_architecture", {})
    if data:
        md.append("\n## 6. Data Architecture\n")
        for field, label in [("data_flow", "Data Flow"), ("storage_strategy", "Storage Strategy"),
                             ("database_strategy", "Database Strategy"), ("data_residency", "Data Residency"),
                             ("backup_and_recovery", "Backup & Recovery")]:
            if data.get(field):
                md.append(f"**{label}:** {data[field]}\n")

    # Azure CAF Alignment
    caf = hld.get("azure_caf_alignment", {})
    if caf:
        md.append("\n## 7. Azure Cloud Adoption Framework Alignment\n")
        for field, label in [("landing_zone", "Landing Zone"), ("management_groups", "Management Groups"),
                             ("subscription_design", "Subscription Design"), ("naming_convention", "Naming Convention"),
                             ("tagging_strategy", "Tagging Strategy"), ("resource_organization", "Resource Organization")]:
            if caf.get(field):
                md.append(f"**{label}:** {caf[field]}\n")

    # FinOps
    fin = hld.get("finops", {})
    if fin:
        md.append("\n## 8. FinOps — Cost Management\n")
        md.append(f"**Total Estimated Monthly Cost:** {fin.get('total_estimated_monthly_cost', 'N/A')}\n")
        if fin.get("cost_optimization_recommendations"):
            md.append("\n**Cost Optimization Recommendations:**")
            for r in fin["cost_optimization_recommendations"]:
                md.append(f"- {r}")
        if fin.get("reserved_instances_candidates"):
            md.append(f"\n**Reserved Instance Candidates:** {', '.join(fin['reserved_instances_candidates'])}\n")
        if fin.get("cost_monitoring"):
            md.append(f"**Cost Monitoring:** {fin['cost_monitoring']}\n")

    # Region Strategy
    region = hld.get("region_strategy", {})
    if region:
        md.append("\n## 9. Region Strategy\n")
        md.append(f"**Primary Region:** {region.get('primary_region', 'N/A')}\n")
        md.append(f"**DR Region:** {region.get('dr_region', 'N/A')}\n")
        if region.get("region_selection_factors"):
            md.append(f"**Selection Factors:** {', '.join(region['region_selection_factors'])}\n")
        if region.get("data_residency_considerations"):
            md.append(f"**Data Residency:** {region['data_residency_considerations']}\n")
        if region.get("multi_region_considerations"):
            md.append(f"**Multi-Region:** {region['multi_region_considerations']}\n")

    # WAF Assessment
    waf = hld.get("waf_assessment", {})
    if waf:
        md.append("\n## 10. Well-Architected Framework Assessment\n")
        md.append("| Pillar | Score | Notes |")
        md.append("|--------|-------|-------|")
        for pillar in ["reliability", "security", "cost_optimization", "operational_excellence", "performance_efficiency"]:
            p = waf.get(pillar, {})
            label = pillar.replace("_", " ").title()
            md.append(f"| {label} | {p.get('score', 'N/A')} | {p.get('notes', '')} |")

    # Migration Approach
    mig = hld.get("migration_approach", {})
    if mig:
        md.append("\n\n## 11. Migration Roadmap\n")
        md.append(f"**Strategy:** {mig.get('strategy', 'N/A')}\n")
        phases = mig.get("phases", [])
        for phase in phases:
            md.append(f"\n### Phase {phase.get('phase', '?')}: {phase.get('name', 'N/A')}")
            md.append(f"\n{phase.get('description', '')}\n")
            if phase.get("services"):
                md.append(f"**Services:** {', '.join(phase['services'])}\n")
            md.append(f"**Duration:** {phase.get('duration_weeks', '?')} weeks\n")
            if phase.get("dependencies"):
                md.append(f"**Dependencies:** {', '.join(phase['dependencies'])}\n")
            if phase.get("risks"):
                md.append(f"**Risks:** {', '.join(phase['risks'])}\n")
        if mig.get("rollback_plan"):
            md.append(f"\n**Rollback Plan:** {mig['rollback_plan']}\n")
        if mig.get("testing_strategy"):
            md.append(f"**Testing Strategy:** {mig['testing_strategy']}\n")

    # Considerations
    considerations = hld.get("considerations", [])
    if considerations:
        md.append("\n## 12. Key Considerations\n")
        for c in considerations:
            md.append(f"- {c}")

    # Risks & Mitigations
    risks = hld.get("risks_and_mitigations", [])
    if risks:
        md.append("\n\n## 13. Risks & Mitigations\n")
        md.append("| Risk | Impact | Mitigation |")
        md.append("|------|--------|------------|")
        for r in risks:
            md.append(f"| {r.get('risk', '')} | {r.get('impact', '')} | {r.get('mitigation', '')} |")

    # Next Steps
    next_steps = hld.get("next_steps", [])
    if next_steps:
        md.append("\n\n## 14. Next Steps\n")
        for i, s in enumerate(next_steps, 1):
            md.append(f"{i}. {s}")

    md.append(f"\n\n---\n*Document generated by Archmorph v{__version__}*")

    return "\n".join(md)
