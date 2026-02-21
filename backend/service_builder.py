"""
Archmorph Service Builder — Natural Language Component Addition

Allows users to add Azure services to their architecture using natural language
descriptions after the initial diagram analysis. Detected services are integrated
into the existing analysis result.

Usage:
    from service_builder import add_services_from_text, deduplicate_questions

    # Add services via natural language
    updated_analysis = add_services_from_text(
        analysis=current_analysis,
        user_text="Add a Redis cache and API Gateway with WAF"
    )

    # Deduplicate questions based on user-provided context
    filtered_questions = deduplicate_questions(
        questions=generated_questions,
        analysis=analysis,
        user_context={"natural_language_additions": [...]}
    )
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from difflib import SequenceMatcher

from services import AZURE_SERVICES
from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Azure Service Name Index for Fuzzy Matching
# ─────────────────────────────────────────────────────────────
_AZURE_NAME_INDEX: Dict[str, Dict] = {}
for svc in AZURE_SERVICES:
    _AZURE_NAME_INDEX[svc["name"].lower()] = svc
    _AZURE_NAME_INDEX[svc["fullName"].lower()] = svc
    # Also index common aliases
    aliases = {
        "redis": "Azure Cache for Redis",
        "redis cache": "Azure Cache for Redis",
        "api gateway": "Azure API Management",
        "apim": "Azure API Management",
        "waf": "Azure Web Application Firewall",
        "app gateway": "Azure Application Gateway",
        "application gateway": "Azure Application Gateway",
        "cdn": "Azure CDN",
        "content delivery": "Azure CDN",
        "functions": "Azure Functions",
        "serverless": "Azure Functions",
        "aks": "Azure Kubernetes Service",
        "kubernetes": "Azure Kubernetes Service",
        "k8s": "Azure Kubernetes Service",
        "cosmos": "Azure Cosmos DB",
        "cosmosdb": "Azure Cosmos DB",
        "sql": "Azure SQL Database",
        "sql database": "Azure SQL Database",
        "postgres": "Azure Database for PostgreSQL",
        "postgresql": "Azure Database for PostgreSQL",
        "mysql": "Azure Database for MySQL",
        "blob": "Azure Blob Storage",
        "blob storage": "Azure Blob Storage",
        "storage": "Azure Storage Account",
        "keyvault": "Azure Key Vault",
        "key vault": "Azure Key Vault",
        "secrets": "Azure Key Vault",
        "vnet": "Azure Virtual Network",
        "virtual network": "Azure Virtual Network",
        "networking": "Azure Virtual Network",
        "load balancer": "Azure Load Balancer",
        "lb": "Azure Load Balancer",
        "container apps": "Azure Container Apps",
        "container instances": "Azure Container Instances",
        "aci": "Azure Container Instances",
        "acr": "Azure Container Registry",
        "container registry": "Azure Container Registry",
        "app service": "Azure App Service",
        "web app": "Azure App Service",
        "static web app": "Azure Static Web Apps",
        "swa": "Azure Static Web Apps",
        "service bus": "Azure Service Bus",
        "event hub": "Azure Event Hubs",
        "event grid": "Azure Event Grid",
        "logic apps": "Azure Logic Apps",
        "data factory": "Azure Data Factory",
        "adf": "Azure Data Factory",
        "synapse": "Azure Synapse Analytics",
        "databricks": "Azure Databricks",
        "machine learning": "Azure Machine Learning",
        "ml": "Azure Machine Learning",
        "cognitive services": "Azure Cognitive Services",
        "openai": "Azure OpenAI Service",
        "search": "Azure AI Search",
        "ai search": "Azure AI Search",
        "monitor": "Azure Monitor",
        "app insights": "Application Insights",
        "application insights": "Application Insights",
        "log analytics": "Azure Log Analytics",
        "bastion": "Azure Bastion",
        "vpn": "Azure VPN Gateway",
        "expressroute": "Azure ExpressRoute",
        "front door": "Azure Front Door",
        "firewall": "Azure Firewall",
        "ddos": "Azure DDoS Protection",
        "private link": "Azure Private Link",
        "private endpoint": "Azure Private Endpoint",
        "managed identity": "Azure Managed Identity",
        "entra": "Microsoft Entra ID",
        "active directory": "Microsoft Entra ID",
        "ad": "Microsoft Entra ID",
    }
    for alias, full_name in aliases.items():
        matching = next((s for s in AZURE_SERVICES if s["fullName"] == full_name), None)
        if matching:
            _AZURE_NAME_INDEX[alias] = matching


def _fuzzy_match_azure_service(name: str) -> Optional[Dict]:
    """Find the best matching Azure service using fuzzy matching."""
    name_lower = name.lower().strip()
    
    # Exact match first
    if name_lower in _AZURE_NAME_INDEX:
        return _AZURE_NAME_INDEX[name_lower]
    
    # Fuzzy match
    best_match = None
    best_score = 0.0
    
    for svc in AZURE_SERVICES:
        for candidate in [svc["name"].lower(), svc["fullName"].lower()]:
            score = SequenceMatcher(None, name_lower, candidate).ratio()
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = svc
    
    return best_match


# ─────────────────────────────────────────────────────────────
# GPT-4o Prompt for Service Extraction
# ─────────────────────────────────────────────────────────────
SERVICE_EXTRACTION_PROMPT = """\
You are an Azure cloud architecture expert. Extract Azure services from the user's natural language description.

## Task
Identify Azure services the user wants to add to their architecture. Return a JSON object with the detected services.

## Response Format
```json
{
  "services": [
    {
      "name": "<Azure service short name>",
      "full_name": "<Azure service full name>",
      "category": "<Compute|Storage|Database|Networking|Security|AI/ML|Integration|Monitoring|Other>",
      "configuration": {
        "sku": "<suggested SKU if mentioned>",
        "region": "<region if mentioned>",
        "notes": "<any specific config mentioned>"
      },
      "reason": "<why this service was inferred from the text>"
    }
  ],
  "inferred_requirements": [
    "<any architectural requirements inferred, e.g., 'high availability', 'multi-region'>"
  ]
}
```

## Rules
1. Only include Azure services (not AWS or GCP equivalents).
2. If the user mentions a generic concept (e.g., "caching"), map it to the appropriate Azure service.
3. Include configuration details if the user specifies them.
4. If the request is unclear, include your best interpretation with a reason.
5. Do not include services that are already in the architecture (unless user says "another" or "additional").

## Azure Service Reference (partial list)
- Compute: Azure Functions, App Service, Container Apps, AKS, Virtual Machines
- Storage: Blob Storage, Files, Queue, Table, Data Lake
- Database: Cosmos DB, SQL Database, PostgreSQL, MySQL, Redis Cache
- Networking: Virtual Network, Load Balancer, Application Gateway, Front Door, CDN, VPN Gateway
- Security: Key Vault, Firewall, WAF, DDoS Protection, Bastion, Private Link
- AI/ML: OpenAI Service, Cognitive Services, Machine Learning
- Integration: Service Bus, Event Hubs, Event Grid, Logic Apps, API Management
- Monitoring: Monitor, Application Insights, Log Analytics
"""


def add_services_from_text(
    analysis: Dict[str, Any],
    user_text: str,
) -> Dict[str, Any]:
    """
    Add services to an existing analysis based on natural language description.
    
    Parameters
    ----------
    analysis : dict
        The current diagram analysis result with zones and mappings.
    user_text : str
        User's natural language description of services to add.
    
    Returns
    -------
    dict
        Updated analysis with new services added.
        Includes 'services_added' list with the newly detected services.
    """
    import copy
    
    if not user_text or not user_text.strip():
        return {
            **analysis,
            "services_added": [],
            "add_services_error": "No input provided",
        }
    
    # Build context from existing services
    existing_services = set()
    for mapping in analysis.get("mappings", []):
        existing_services.add(mapping.get("azure_service", "").lower())
    
    context = f"Existing Azure services in architecture: {', '.join(existing_services) if existing_services else 'None'}"
    
    # Call GPT-4o to extract services
    client = get_openai_client()
    
    messages = [
        {"role": "system", "content": SERVICE_EXTRACTION_PROMPT},
        {"role": "user", "content": f"{context}\n\n## User Request\n{user_text}"},
    ]
    
    try:
        response = openai_retry(client.chat.completions.create)(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            max_tokens=2048,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        
        raw_text = response.choices[0].message.content.strip()
        result = json.loads(raw_text)
        
        detected_services = result.get("services", [])
        requirements = result.get("inferred_requirements", [])
        
    except Exception as exc:
        logger.error("Service extraction failed: %s", exc)
        return {
            **analysis,
            "services_added": [],
            "add_services_error": str(exc),
        }
    
    # Add detected services to analysis
    updated_analysis = copy.deepcopy(analysis)
    services_added = []
    
    # Find or create a "User Added" zone
    user_zone = None
    for zone in updated_analysis.get("zones", []):
        if zone.get("name") == "User Added":
            user_zone = zone
            break
    
    if not user_zone:
        zone_id = len(updated_analysis.get("zones", [])) + 1
        user_zone = {
            "id": zone_id,
            "name": "User Added",
            "number": zone_id,
            "services": [],
        }
        updated_analysis.setdefault("zones", []).append(user_zone)
    
    for svc in detected_services:
        svc_name = svc.get("name", "")
        full_name = svc.get("full_name", svc_name)
        
        # Skip if already exists
        if full_name.lower() in existing_services or svc_name.lower() in existing_services:
            continue
        
        # Find in Azure catalog
        matched_svc = _fuzzy_match_azure_service(full_name) or _fuzzy_match_azure_service(svc_name)
        
        if matched_svc:
            azure_name = matched_svc["fullName"]
            category = matched_svc.get("category", svc.get("category", "Other"))
        else:
            azure_name = full_name
            category = svc.get("category", "Other")
        
        # Add to mapping
        new_mapping = {
            "source_service": f"User Added: {svc_name}",
            "source_provider": "user",
            "azure_service": azure_name,
            "confidence": 1.0,  # User explicitly requested
            "notes": f"Zone {user_zone['number']} – {user_zone['name']} (via natural language)",
        }
        updated_analysis.setdefault("mappings", []).append(new_mapping)
        
        # Add to zone services
        zone_service = {
            "user_added": svc_name,
            "azure": azure_name,
            "confidence": 1.0,
        }
        user_zone["services"].append(zone_service)
        
        services_added.append({
            "name": svc_name,
            "azure_service": azure_name,
            "category": category,
            "reason": svc.get("reason", "User requested"),
            "configuration": svc.get("configuration", {}),
        })
    
    # Update service count
    updated_analysis["services_detected"] = len(updated_analysis.get("mappings", []))
    updated_analysis["services_added"] = services_added
    updated_analysis["inferred_requirements"] = requirements
    
    # Update confidence summary
    mappings = updated_analysis.get("mappings", [])
    if mappings:
        confidences = [m.get("confidence", 0.5) for m in mappings]
        updated_analysis["confidence_summary"] = {
            "high": sum(1 for c in confidences if c >= 0.85),
            "medium": sum(1 for c in confidences if 0.7 <= c < 0.85),
            "low": sum(1 for c in confidences if c < 0.7),
            "average": round(sum(confidences) / len(confidences), 2),
        }
    
    logger.info(
        "Added %d services from natural language: %s",
        len(services_added),
        [s["name"] for s in services_added],
    )
    
    return updated_analysis


# ─────────────────────────────────────────────────────────────
# Smart Question Deduplication
# ─────────────────────────────────────────────────────────────

# Keywords that indicate certain answers were implicitly provided
IMPLICIT_ANSWER_PATTERNS = {
    "env_target": {
        "production": ["production", "prod", "live", "enterprise", "critical"],
        "development": ["development", "dev", "testing", "sandbox", "poc"],
        "staging": ["staging", "uat", "qa", "pre-prod"],
    },
    "sec_compliance": {
        "HIPAA": ["hipaa", "healthcare", "medical", "patient"],
        "PCI-DSS": ["pci", "payment", "credit card", "cardholder"],
        "GDPR": ["gdpr", "european", "eu data", "privacy"],
        "SOC 2": ["soc 2", "soc2", "audit"],
    },
    "env_data_volume": {
        ">10 TB": ["petabyte", "massive", "huge scale", "big data"],
        "1–10 TB": ["terabyte", "large scale"],
        "100 GB–1 TB": ["medium scale", "moderate"],
    },
    "ha_sla": {
        "99.99%": ["four nines", "99.99", "mission critical", "zero downtime"],
        "99.9%": ["three nines", "99.9", "high availability"],
    },
    "net_connectivity": {
        "ExpressRoute": ["expressroute", "dedicated connection", "private circuit"],
        "VPN": ["vpn", "site-to-site", "point-to-site"],
    },
}


def deduplicate_questions(
    questions: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    user_context: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Filter out questions that have been implicitly answered by user context.
    
    Parameters
    ----------
    questions : list
        List of generated questions from guided_questions.generate_questions().
    analysis : dict
        The current analysis result.
    user_context : dict, optional
        Contains 'natural_language_additions' or 'user_messages' that may
        implicitly answer some questions.
    
    Returns
    -------
    tuple
        (filtered_questions, inferred_answers)
        - filtered_questions: Questions that still need to be asked
        - inferred_answers: Dict of question_id -> inferred answer value
    """
    if not user_context:
        return questions, {}
    
    # Collect all user-provided text
    user_texts = []
    
    if "natural_language_additions" in user_context:
        for addition in user_context["natural_language_additions"]:
            if isinstance(addition, str):
                user_texts.append(addition.lower())
            elif isinstance(addition, dict) and "text" in addition:
                user_texts.append(addition["text"].lower())
    
    if "user_messages" in user_context:
        user_texts.extend(msg.lower() for msg in user_context["user_messages"] if isinstance(msg, str))
    
    combined_text = " ".join(user_texts)
    
    if not combined_text:
        return questions, {}
    
    # Check for implicit answers
    inferred_answers = {}
    
    for question_id, answer_patterns in IMPLICIT_ANSWER_PATTERNS.items():
        for answer_value, keywords in answer_patterns.items():
            if any(kw in combined_text for kw in keywords):
                inferred_answers[question_id] = answer_value
                logger.info(
                    "Inferred answer for %s: %s (from user text)",
                    question_id,
                    answer_value,
                )
                break  # Take first match for this question
    
    # Also check services_added for implicit requirements
    services_added = analysis.get("services_added", [])
    for svc in services_added:
        config = svc.get("configuration", {})
        if config.get("sku"):
            # High SKU suggests production
            if "premium" in config["sku"].lower() or "standard" in config["sku"].lower():
                if "env_target" not in inferred_answers:
                    inferred_answers["env_target"] = "Production"
    
    inferred_requirements = analysis.get("inferred_requirements", [])
    for req in inferred_requirements:
        req_lower = req.lower()
        if "high availability" in req_lower or "multi-region" in req_lower:
            if "ha_sla" not in inferred_answers:
                inferred_answers["ha_sla"] = "99.9%"
        if "compliance" in req_lower:
            if "sec_compliance" not in inferred_answers:
                inferred_answers["sec_compliance"] = "SOC 2"  # Default guess
    
    # Filter questions
    filtered_questions = []
    for q in questions:
        q_id = q.get("id")
        if q_id not in inferred_answers:
            filtered_questions.append(q)
    
    logger.info(
        "Deduplicated questions: %d -> %d (inferred %d answers)",
        len(questions),
        len(filtered_questions),
        len(inferred_answers),
    )
    
    return filtered_questions, inferred_answers


def get_smart_defaults_from_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Infer smart default answers based on the analysis result.
    
    This uses heuristics like:
    - Number of services detected → scale
    - Service types → compliance guesses
    - Architecture patterns → HA requirements
    
    Returns a dict of question_id -> suggested default value.
    """
    defaults = {}
    
    # Service count → data volume / scale
    svc_count = analysis.get("services_detected", 0)
    if svc_count >= 20:
        defaults["env_data_volume"] = "1–10 TB"
        defaults["env_concurrent_users"] = "10 K–100 K"
    elif svc_count >= 10:
        defaults["env_data_volume"] = "100 GB–1 TB"
        defaults["env_concurrent_users"] = "1 K–10 K"
    else:
        defaults["env_data_volume"] = "1–100 GB"
        defaults["env_concurrent_users"] = "100–1 K"
    
    # Architecture patterns → HA
    patterns = analysis.get("architecture_patterns", [])
    pattern_str = " ".join(patterns).lower()
    
    if "multi-az" in pattern_str or "multi-region" in pattern_str:
        defaults["ha_sla"] = "99.99%"
        defaults["ha_dr_tier"] = "Active-Active (multi-region)"
    elif "high-availability" in pattern_str:
        defaults["ha_sla"] = "99.9%"
        defaults["ha_dr_tier"] = "Active-Passive with warm standby"
    
    # Database services → specific SKUs
    mappings = analysis.get("mappings", [])
    has_database = any("database" in m.get("azure_service", "").lower() or 
                       "cosmos" in m.get("azure_service", "").lower() or
                       "sql" in m.get("azure_service", "").lower()
                       for m in mappings)
    
    if has_database:
        defaults["db_backup_retention"] = "14 days"
    
    # IoT services → specific patterns
    has_iot = any("iot" in m.get("source_service", "").lower() for m in mappings)
    if has_iot:
        defaults["iot_scale_tier"] = "S2" if svc_count > 10 else "S1"
    
    return defaults
