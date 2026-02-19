"""
Archmorph IaC Chat — GPT-4o powered Terraform/Bicep assistant.

Allows users to interactively modify generated IaC code through natural
language conversation.  The assistant can add services (VNet, subnets,
NSGs, IPs, storage, etc.), apply naming conventions, fix issues, and
explain the generated infrastructure.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Azure OpenAI config (shared with vision_analyzer)
# ─────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    "https://archmorph-openai-acm7pd.openai.azure.com/",
)
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")


def _get_openai_client() -> AzureOpenAI:
    """Create an Azure OpenAI client (API-key or Entra ID)."""
    if AZURE_OPENAI_KEY:
        return AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
        )
    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version=AZURE_OPENAI_API_VERSION,
    )


# ─────────────────────────────────────────────────────────────
# System prompt — defines the IaC assistant persona
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are **Archmorph IaC Assistant** — an expert Azure cloud architect and Terraform/Bicep engineer.

You are given the user's current IaC code (Terraform HCL or Bicep) that was generated from a cloud migration analysis.  Your job is to **modify the code** based on the user's requests.

## Capabilities
You can:
- **Add Azure services** — VNet, Subnets, NSGs, Public IPs, Private Endpoints, VPN Gateway, Application Gateway, Bastion, Storage Accounts, Key Vault, Azure Monitor, Log Analytics, Container Registry, AKS, etc.
- **Configure networking** — VNet address spaces, subnet CIDRs, NSG rules, route tables, peering, Private DNS Zones, service endpoints, NAT Gateway.
- **Apply naming conventions** — Microsoft Cloud Adoption Framework (CAF) naming, custom prefixes/suffixes, consistent tagging.
- **Set up security** — Key Vault access policies, RBAC, managed identities, Private Endpoints, DDoS Protection, WAF.
- **Configure monitoring** — Log Analytics workspace, diagnostic settings, Application Insights, alerts.
- **Add storage** — Storage accounts, Blob containers, file shares, ADLS Gen2, lifecycle policies.
- **Fix bugs** — Correct resource references, fix invalid names, add missing required attributes.
- **Explain** — Describe what each resource does and why it's needed.

## Response Format
ALWAYS respond with a JSON object containing exactly these fields:
```json
{
  "message": "<A SHORT explanation of what you changed/added — 2-4 sentences, use markdown for formatting>",
  "code": "<The COMPLETE updated IaC code — include ALL existing resources plus your additions. Never omit resources.>",
  "changes_summary": ["<Change 1>", "<Change 2>", "..."],
  "services_added": ["<Service Name 1>", "<Service Name 2>"]
}
```

## Rules
1. Return the **COMPLETE** code — never use placeholders like "..." or "# rest of code unchanged".
2. Preserve ALL existing resources and their configurations.
3. Follow Azure naming conventions: `{resource-type}-{project}-{env}` (e.g. `vnet-myproject-dev`).
4. Use `local.project`, `local.env`, `local.location`, and `local.tags` variables when they exist.
5. Add proper `tags = local.tags` to every new resource.
6. Use secure practices: no hardcoded secrets, use Key Vault references, managed identities.
7. For networking: use standard RFC 1918 ranges (10.0.0.0/16 default, /24 subnets).
8. Keep comments consistent with the existing style.
9. If the user asks to EXPLAIN something, set `code` to the current code unchanged and put the explanation in `message`.
10. If the format is Bicep, generate valid Bicep (not Terraform). If Terraform, generate valid HCL.
"""


# ─────────────────────────────────────────────────────────────
# In-memory conversation sessions  (keyed by diagram_id)
# ─────────────────────────────────────────────────────────────
IAC_CHAT_SESSIONS: Dict[str, List[Dict[str, str]]] = {}


def process_iac_chat(
    diagram_id: str,
    message: str,
    current_code: str,
    iac_format: str = "terraform",
    analysis_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Process a user message to modify IaC code via GPT-4o.

    Parameters
    ----------
    diagram_id : str
        Diagram session ID (used for conversation history).
    message : str
        The user's natural-language request.
    current_code : str
        The current Terraform/Bicep code to modify.
    iac_format : str
        ``"terraform"`` or ``"bicep"``.
    analysis_context : dict, optional
        The diagram analysis result (zones, mappings, patterns) for context.

    Returns
    -------
    dict
        ``{"reply", "code", "changes_summary", "services_added"}``
    """
    session_key = f"{diagram_id}:iac"

    # Initialize session history
    if session_key not in IAC_CHAT_SESSIONS:
        IAC_CHAT_SESSIONS[session_key] = []

    history = IAC_CHAT_SESSIONS[session_key]

    # Build context block for GPT-4o
    context_text = ""
    if analysis_context:
        zones = analysis_context.get("zones", [])
        patterns = analysis_context.get("architecture_patterns", [])
        source = analysis_context.get("source_provider", "aws")
        svc_count = analysis_context.get("services_detected", 0)
        context_text = (
            f"\n## Migration Context\n"
            f"- Source provider: {source.upper()}\n"
            f"- Services detected: {svc_count}\n"
            f"- Architecture patterns: {', '.join(patterns) if patterns else 'N/A'}\n"
            f"- Zones: {len(zones)}\n"
        )

    # Build messages array
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT + context_text},
    ]

    # Add conversation history (keep last 10 turns to manage tokens)
    recent_history = history[-10:]
    for entry in recent_history:
        messages.append({"role": entry["role"], "content": entry["content"]})

    # Current user turn — include current code + user request
    user_content = (
        f"## Current {iac_format.title()} Code\n"
        f"```{'hcl' if iac_format == 'terraform' else 'bicep'}\n"
        f"{current_code}\n"
        f"```\n\n"
        f"## User Request\n"
        f"{message}"
    )
    messages.append({"role": "user", "content": user_content})

    # Call GPT-4o
    client = _get_openai_client()

    logger.info(
        "IaC chat request for diagram %s: %s (%d history msgs)",
        diagram_id,
        message[:80],
        len(recent_history),
    )

    try:
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            max_tokens=16384,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content.strip()
        logger.info("IaC chat response received (%d chars)", len(raw_text))

        result = json.loads(raw_text)

        reply = result.get("message", "Code updated.")
        code = result.get("code", current_code)
        changes = result.get("changes_summary", [])
        services = result.get("services_added", [])

    except json.JSONDecodeError as exc:
        logger.error("Failed to parse IaC chat JSON: %s", exc)
        return {
            "reply": "I encountered an error processing the response. Please try again.",
            "code": current_code,
            "changes_summary": [],
            "services_added": [],
            "error": True,
        }
    except Exception as exc:
        logger.error("IaC chat OpenAI call failed: %s", exc)
        return {
            "reply": f"Sorry, I couldn't process your request: {str(exc)}",
            "code": current_code,
            "changes_summary": [],
            "services_added": [],
            "error": True,
        }

    # Persist to session history
    history.append({
        "role": "user",
        "content": message,  # Store just the message, not the full code
        "ts": datetime.utcnow().isoformat(),
    })
    history.append({
        "role": "assistant",
        "content": reply,
        "ts": datetime.utcnow().isoformat(),
    })
    IAC_CHAT_SESSIONS[session_key] = history

    return {
        "reply": reply,
        "code": code,
        "changes_summary": changes,
        "services_added": services,
        "error": False,
    }


def get_iac_chat_history(diagram_id: str) -> List[Dict[str, str]]:
    """Return IaC chat history for a diagram session."""
    return IAC_CHAT_SESSIONS.get(f"{diagram_id}:iac", [])


def clear_iac_chat(diagram_id: str) -> bool:
    """Clear IaC chat session for a diagram."""
    key = f"{diagram_id}:iac"
    if key in IAC_CHAT_SESSIONS:
        del IAC_CHAT_SESSIONS[key]
        return True
    return False
