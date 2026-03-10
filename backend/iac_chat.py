"""
Archmorph IaC Chat — GPT-4o powered Terraform/Bicep assistant.

Allows users to interactively modify generated IaC code through natural
language conversation.  The assistant can add services (VNet, subnets,
NSGs, IPs, storage, etc.), apply naming conventions, fix issues, and
explain the generated infrastructure.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from cachetools import TTLCache

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from prompt_guard import (
    PROMPT_ARMOR,
    sanitize_message,
    sanitize_response,
    validate_code_input,
    validate_message,
)

logger = logging.getLogger(__name__)


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
6. **CRITICAL credential security** — NEVER use inline/hardcoded passwords or credentials in ANY resource:
   - For VMs: use SSH keys or `random_password` stored in `azurerm_key_vault_secret`
   - For SQL/PostgreSQL/MySQL: use `azuread_administrator` blocks with Azure AD auth — NEVER use `administrator_login_password` inline
   - For any other secret: use `random_password` → `azurerm_key_vault_secret` → data reference pattern
   - If the code already contains inline passwords, refactor them to use Key Vault references
7. For networking: use standard RFC 1918 ranges (10.0.0.0/16 default, /24 subnets).
8. Keep comments consistent with the existing style.
9. If the user asks to EXPLAIN something, set `code` to the current code unchanged and put the explanation in `message`.
10. If the format is Bicep, generate valid Bicep (not Terraform). If Terraform, generate valid HCL.
""" + PROMPT_ARMOR


# ─────────────────────────────────────────────────────────────
# In-memory conversation sessions  (keyed by diagram_id, TTL: 2 hours, max 200)
# ─────────────────────────────────────────────────────────────
IAC_CHAT_SESSIONS: TTLCache = TTLCache(maxsize=200, ttl=7200)


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

    # ── Input validation ──
    message = sanitize_message(message)
    is_safe, reason = validate_message(message, max_length=5000, context="iac_chat")
    if not is_safe:
        logger.warning("IaC chat input rejected for diagram %s: %s", diagram_id, reason or "injection detected")
        return {
            "reply": reason or "I can only help with Terraform and Bicep infrastructure code. Please rephrase your request.",
            "code": current_code,
            "changes_summary": [],
            "services_added": [],
            "error": True,
        }

    code_ok, code_reason = validate_code_input(current_code)
    if not code_ok:
        return {
            "reply": code_reason,
            "code": current_code,
            "changes_summary": [],
            "services_added": [],
            "error": True,
        }

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
    client = get_openai_client()

    logger.info(
        "IaC chat request for diagram %s: %s (%d history msgs)",
        diagram_id,
        message[:80],
        len(recent_history),
    )

    try:
        response = openai_retry(client.chat.completions.create)(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            max_tokens=4000,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        raw_text = response.choices[0].message.content.strip()
        logger.info("IaC chat response received (%d chars)", len(raw_text))

        result = json.loads(raw_text)

        reply = sanitize_response(result.get("message", "Code updated."))
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
            "reply": "Sorry, I couldn't process your request. Please try again.",
            "code": current_code,
            "changes_summary": [],
            "services_added": [],
            "error": True,
        }

    # Persist to session history
    history.append({
        "role": "user",
        "content": message,  # Store just the message, not the full code
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    history.append({
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
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
