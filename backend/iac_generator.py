"""
Archmorph – Dynamic IaC Generator
Uses GPT-4o to generate Terraform or Bicep code from analysis results.
Falls back to base templates when no analysis is available.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> str:
    """Load a base template file."""
    path = TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {name}")
    return path.read_text()


def _build_terraform_prompt(analysis: dict, params: dict) -> str:
    """Build the GPT-4o prompt for Terraform generation."""
    mappings = analysis.get("mappings", [])
    services_detected = analysis.get("services_detected", 0)
    source_provider = analysis.get("source_provider", "AWS")
    project_name = params.get("project_name", "cloud-migration")
    region = params.get("region", "westeurope")
    env = params.get("environment", "dev")
    sku_strategy = params.get("sku_strategy", "balanced")

    mapping_lines = []
    for m in mappings:
        src = m.get("source_service", "unknown")
        tgt = m.get("azure_service", "unknown")
        cat = m.get("category", "")
        conf = m.get("confidence", 0)
        mapping_lines.append(f"  - {src} → {tgt} (category: {cat}, confidence: {conf})")

    mapping_text = "\n".join(mapping_lines) if mapping_lines else "  (no specific mappings available)"

    return f"""You are an expert Azure infrastructure engineer. Generate production-ready Terraform code 
to deploy the Azure architecture described below.

## Source Architecture
- Provider: {source_provider}
- Services detected: {services_detected}
- Service mappings (source → Azure):
{mapping_text}

## Parameters
- Project name: {project_name}
- Environment: {env}
- Region: {region}
- SKU strategy: {sku_strategy} (cost-optimized | balanced | performance)

## Requirements
1. Use azurerm provider ~> 3.85
2. Follow Azure naming conventions (e.g., rg-, st, kv-, etc.)
3. Use locals for project, env, location, and tags
4. Include a resource group as the foundation
5. Generate EVERY Azure resource from the mappings above
6. Group resources by logical zone/function with clear comments
7. Use appropriate SKUs based on the strategy ({sku_strategy})
8. Include managed identities where applicable
9. Store secrets in Key Vault
10. Include meaningful outputs (endpoints, hostnames, URLs)
11. Do NOT include any markdown formatting — return ONLY valid Terraform HCL code
12. Add comments explaining which source service each resource replaces

Return ONLY the Terraform code, no markdown fences, no explanations."""


def _build_bicep_prompt(analysis: dict, params: dict) -> str:
    """Build the GPT-4o prompt for Bicep generation."""
    mappings = analysis.get("mappings", [])
    services_detected = analysis.get("services_detected", 0)
    source_provider = analysis.get("source_provider", "AWS")
    project_name = params.get("project_name", "cloud-migration")
    region = params.get("region", "westeurope")
    env = params.get("environment", "dev")
    sku_strategy = params.get("sku_strategy", "balanced")

    mapping_lines = []
    for m in mappings:
        src = m.get("source_service", "unknown")
        tgt = m.get("azure_service", "unknown")
        cat = m.get("category", "")
        conf = m.get("confidence", 0)
        mapping_lines.append(f"  - {src} → {tgt} (category: {cat}, confidence: {conf})")

    mapping_text = "\n".join(mapping_lines) if mapping_lines else "  (no specific mappings available)"

    return f"""You are an expert Azure infrastructure engineer. Generate production-ready Bicep code 
to deploy the Azure architecture described below.

## Source Architecture
- Provider: {source_provider}
- Services detected: {services_detected}
- Service mappings (source → Azure):
{mapping_text}

## Parameters
- Project name: {project_name}
- Environment: {env}
- Region: {region}
- SKU strategy: {sku_strategy} (cost-optimized | balanced | performance)

## Requirements
1. Use targetScope = 'subscription'
2. Follow Azure naming conventions
3. Use parameters for env, location, and any secrets
4. Include a resource group as the foundation
5. Generate EVERY Azure resource from the mappings above
6. Group resources by logical zone/function with clear comments
7. Use appropriate SKUs based on the strategy ({sku_strategy})
8. Include managed identities where applicable
9. Include meaningful outputs
10. Do NOT include any markdown formatting — return ONLY valid Bicep code
11. Add comments explaining which source service each resource replaces

Return ONLY the Bicep code, no markdown fences, no explanations."""


def generate_iac_code(analysis: Optional[dict], iac_format: str = "terraform", params: Optional[dict] = None) -> str:
    """
    Generate IaC code from analysis results using GPT-4o.
    
    If no analysis is available, returns a base template.
    
    Args:
        analysis: The diagram analysis result (mappings, services_detected, etc.)
        iac_format: "terraform" or "bicep"
        params: Optional parameters (project_name, region, environment, sku_strategy)
    
    Returns:
        Generated IaC code as a string
    """
    params = params or {}

    # If no analysis with mappings, return a populated base template
    if not analysis or not analysis.get("mappings"):
        template_name = "terraform_base.tf" if iac_format == "terraform" else "bicep_base.bicep"
        try:
            template = _load_template(template_name)
            return template.replace(
                "{{PROJECT_NAME}}", params.get("project_name", "cloud-migration")
            ).replace(
                "{{ENVIRONMENT}}", params.get("environment", "dev")
            ).replace(
                "{{REGION}}", params.get("region", "westeurope")
            )
        except FileNotFoundError:
            logger.warning("Base template %s not found, generating from scratch", template_name)

    # Build prompt and call GPT-4o
    if iac_format == "terraform":
        prompt = _build_terraform_prompt(analysis or {}, params)
    else:
        prompt = _build_bicep_prompt(analysis or {}, params)

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": "You are an Azure infrastructure expert. Generate clean, production-ready IaC code. Return ONLY code, no markdown formatting.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=40000,
        )

        code = response.choices[0].message.content.strip()

        # Strip markdown code fences if GPT accidentally includes them
        if code.startswith("```"):
            lines = code.split("\n")
            # Remove first line (```terraform or ```bicep) and last line (```)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            else:
                lines = lines[1:]
            code = "\n".join(lines)

        return code

    except Exception as exc:
        logger.error("GPT-4o IaC generation failed: %s — falling back to base template", exc)
        # Fallback to base template
        template_name = "terraform_base.tf" if iac_format == "terraform" else "bicep_base.bicep"
        try:
            template = _load_template(template_name)
            return template.replace(
                "{{PROJECT_NAME}}", params.get("project_name", "cloud-migration")
            ).replace(
                "{{ENVIRONMENT}}", params.get("environment", "dev")
            ).replace(
                "{{REGION}}", params.get("region", "westeurope")
            ) + f"\n\n# NOTE: Dynamic generation failed ({exc}). This is a base template.\n# Re-run after fixing the OpenAI configuration to get full IaC output.\n"
        except FileNotFoundError:
            return f"# IaC generation failed: {exc}\n# Please check your OpenAI configuration.\n"
