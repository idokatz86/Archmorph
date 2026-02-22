"""
Archmorph AI Assistant — GPT-4o powered intelligent assistant.

A true AI assistant that can answer any question about Archmorph, cloud
architecture, Azure services, and migrations. Uses natural language
understanding via GPT-4o and can create GitHub issues for bugs/features.
"""

import os
import re
import json
import logging
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from cachetools import TTLCache

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry
from prompt_guard import PROMPT_ARMOR, sanitize_message, sanitize_response, validate_message
from version import __version__

logger = logging.getLogger(__name__)

# GitHub configuration — loaded lazily to avoid module-level secret exposure
_GITHUB_TOKEN: Optional[str] = None
_GITHUB_CLIENT: Optional[Any] = None  # Cached PyGithub client (#103 — S-018)
GITHUB_REPO = os.getenv("GITHUB_REPO", "idokatz86/Archmorph")

# Conversation history per session (TTL: 2 hours, max 500 sessions)
CHAT_SESSIONS: TTLCache = TTLCache(maxsize=500, ttl=7200)
_session_lock = threading.Lock()       # protects CHAT_SESSIONS mutation (#127)
_github_client_lock = threading.Lock() # protects _GITHUB_CLIENT init (#128)


def _extract_balanced_json(raw: str) -> Optional[Dict[str, Any]]:
    """Extract the first balanced JSON object from *raw*.

    Handles nested braces correctly (Issue #126).  Falls back to a
    simple ``json.loads`` attempt if brace-counting fails.
    """
    depth = 0
    start = None
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    # Fallback: try parsing the whole string
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ─────────────────────────────────────────────────────────────
# AI Assistant System Prompt
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""\
You are **Archmorph AI Assistant** — a friendly, knowledgeable AI assistant for Archmorph, the cloud architecture migration platform.

## About Archmorph
Archmorph is an AI-powered Cloud Architecture Translator that:
- Converts AWS and GCP architecture diagrams into Azure equivalents
- Generates production-ready Terraform and Bicep IaC code
- Uses GPT-4o Vision to analyze uploaded architecture diagrams
- Asks 8-18 guided migration questions to refine recommendations
- Provides cost estimates using Azure Retail Prices API
- Exports diagrams in Excalidraw, Draw.io, and Visio formats

## Current Version: {__version__} (February 2026)
Recent features include:
- Azure AD B2C authentication with user tiers (Free/Pro/Enterprise)
- Usage quotas and lead capture
- Migration runbook generator
- Architecture versioning
- Terraform plan preview
- AI-powered assistant (you!)
- Interactive roadmap timeline

## Your Capabilities
You can help users with:
1. **Archmorph Questions** — How the platform works, features, pricing, supported formats
2. **Cloud Architecture** — AWS, Azure, GCP services, best practices, migration strategies
3. **Terraform/Bicep** — IaC questions, HCL syntax, Azure resource configuration
4. **Bug Reports** — Help users report bugs (you'll structure and create GitHub issues)
5. **Feature Requests** — Capture feature ideas for the roadmap
6. **General Help** — Contact info, documentation, getting started

## Response Guidelines
- Be conversational, friendly, and helpful — not robotic
- Give direct, concise answers — don't over-explain simple questions
- Use markdown formatting for clarity (bold, lists, code blocks)
- For code examples, use proper syntax highlighting
- If you don't know something specific about Archmorph, say so honestly
- Proactively offer to create GitHub issues when users report bugs or request features

## Special Actions
When users want to report a bug or request a feature, respond with a JSON action:

For bug reports, include in your response:
```json
{{"action": "create_bug", "title": "<bug title>", "description": "<details>"}}
```

For feature requests:
```json
{{"action": "create_feature", "title": "<feature title>", "description": "<details>"}}
```

## Service Catalog
- AWS services: 145 (EC2, S3, RDS, Lambda, EKS, etc.)
- Azure services: 143 (VMs, Storage, SQL, Functions, AKS, etc.)
- GCP services: 117 (Compute Engine, Cloud Storage, Cloud SQL, etc.)
- Cross-cloud mappings: 122 verified service mappings

## Support
- GitHub Issues: https://github.com/idokatz86/Archmorph/issues
- Documentation: https://github.com/idokatz86/Archmorph#readme
""" + PROMPT_ARMOR


def _call_ai_assistant(
    message: str,
    history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Call GPT-4o to generate an intelligent response.
    
    Returns the AI response and any detected actions (bug/feature creation).
    """
    # Build messages for GPT-4o
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    
    # Add conversation history (keep last 10 turns)
    recent_history = history[-10:]
    for entry in recent_history:
        if entry.get("role") in ("user", "assistant"):
            messages.append({
                "role": entry["role"],
                "content": entry["content"],
            })
    
    # Add current message
    messages.append({"role": "user", "content": message})
    
    try:
        client = get_openai_client()
        
        response = openai_retry(client.chat.completions.create)(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
        )
        
        reply_text = response.choices[0].message.content.strip()
        reply_text = sanitize_response(reply_text)
        
        # Check for action JSON in response (#126 — handle nested braces)
        action = None
        action_match = re.search(
            r'```json\s*(\{.*?"action".*?\})\s*```',
            reply_text,
            re.DOTALL,
        )
        if action_match:
            raw_json = action_match.group(1)
            # Greedy match may grab too much; find the balanced {} block
            # starting from the first '{' that contains "action".
            action = _extract_balanced_json(raw_json)
            if action is not None:
                # Remove the JSON block from visible reply
                reply_text = reply_text[:action_match.start()] + reply_text[action_match.end():]
                reply_text = reply_text.strip()
        
        return {
            "reply": reply_text,
            "action": action,
            "tokens_used": response.usage.total_tokens if response.usage else 0,
        }
        
    except Exception as exc:
        logger.error("AI assistant error: %s", exc)
        return {
            "reply": "I apologize, but I'm having trouble processing your request right now. Please try again in a moment, or report the issue at https://github.com/idokatz86/Archmorph/issues",
            "action": None,
        }


def _create_github_issue(title: str, body: str, labels: List[str]) -> Dict[str, Any]:
    """Create a GitHub issue using PyGithub. Caches the client instance (#103 — S-018)."""
    global _GITHUB_TOKEN, _GITHUB_CLIENT
    if _GITHUB_TOKEN is None:
        _GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    if not _GITHUB_TOKEN:
        return {
            "success": False,
            "error": "GitHub token not configured. Set GITHUB_TOKEN environment variable.",
        }

    try:
        from github import Github

        # Double-checked locking for thread-safe lazy init (#128)
        if _GITHUB_CLIENT is None:
            with _github_client_lock:
                if _GITHUB_CLIENT is None:
                    _GITHUB_CLIENT = Github(_GITHUB_TOKEN)
        g = _GITHUB_CLIENT
        repo = g.get_repo(GITHUB_REPO)

        # Filter labels to only existing ones
        existing_labels = [lbl.name for lbl in repo.get_labels()]
        valid_labels = [lbl for lbl in labels if lbl in existing_labels]

        issue = repo.create_issue(
            title=title,
            body=body,
            labels=valid_labels if valid_labels else [],
        )

        return {
            "success": True,
            "issue_number": issue.number,
            "issue_url": issue.html_url,
            "title": issue.title,
            "labels": [lbl.name for lbl in issue.labels],
        }
    except Exception as exc:
        logger.error("GitHub issue creation failed: %s", exc)
        return {"success": False, "error": "Failed to create GitHub issue. Please try again."}


# ─────────────────────────────────────────────────────────────
# Archmorph Knowledge Base (for fallback/quick answers)
# ─────────────────────────────────────────────────────────────
FAQ = {
    "what is archmorph": "Archmorph is an AI-powered Cloud Architecture Translator that converts AWS and GCP architecture diagrams into Azure equivalents with ready-to-deploy Terraform/Bicep IaC code.",
    "how does it work": "Upload your AWS or GCP architecture diagram → AI analyzes and detects services → Answer guided migration questions → Get Azure service mappings with confidence scores → Export diagrams and generate Terraform/Bicep code with cost estimates.",
    "supported formats": "Archmorph supports PNG, JPG, SVG, PDF, and Draw.io (.drawio) diagram formats for upload.",
    "what services": "We have a catalog of 405 cloud services: 145 AWS, 143 Azure, and 117 GCP services with 122 cross-cloud mappings.",
    "cost": "Archmorph estimates Azure deployment costs using the Azure Retail Prices API. Development costs run ~$180-250/month, production ~$500-800/month.",
    "export": "You can export translated architecture diagrams as Excalidraw, Draw.io, or Visio files, and download generated IaC as .tf (Terraform) or .bicep files.",
    "questions": "After analysis, Archmorph asks 8-18 guided migration questions across 8 categories (compute, database, networking, security, compliance, DR, cost, integration) to refine your Azure architecture.",
    "terraform": "Archmorph generates production-ready Terraform HCL code with secure credential handling (random_password + Key Vault) — no hardcoded secrets.",
    "bicep": "Archmorph generates Bicep code with @secure() parameters for sensitive values like database passwords.",
    "contact": "For questions, feedback, or bug reports, please open a GitHub issue at https://github.com/idokatz86/Archmorph/issues",
}


# ─────────────────────────────────────────────────────────────
# Main chat handler — AI-powered
# ─────────────────────────────────────────────────────────────
def process_chat_message(
    session_id: str, message: str
) -> Dict[str, Any]:
    """
    Process an incoming chat message using GPT-4o AI.

    Returns a response dict with:
      - reply: AI's text response
      - action: None | 'issue_draft' | 'issue_created' | 'bug_created' | 'feature_created'
      - data: additional data (issue details, etc.)
    """
    # ── Input validation ──
    message = sanitize_message(message)
    is_safe, reason = validate_message(message, max_length=5000, context="chatbot")
    if not is_safe:
        logger.warning("Chatbot input rejected for session %s: %s", session_id, reason or "injection detected")
        return {
            "reply": reason or "I can only help with Archmorph, cloud architecture, and migration topics. Please rephrase your question.",
            "action": None,
            "data": None,
            "ai_powered": False,
        }

    # Initialize session — use lock to prevent race conditions (#127)
    with _session_lock:
        if session_id not in CHAT_SESSIONS:
            CHAT_SESSIONS[session_id] = []
        # Copy the list to avoid mutating a shared reference
        history = list(CHAT_SESSIONS[session_id])

    history.append({
        "role": "user",
        "content": message,
        "ts": datetime.now(timezone.utc).isoformat()
    })

    # ── Handle confirmation of pending actions ──
    msg_lower = message.lower().strip()
    if msg_lower in ("yes", "y", "confirm", "create it", "go ahead", "do it", "sure", "ok", "submit"):
        # Check for pending issue draft
        for entry in reversed(history[:-1]):  # Exclude current message
            if entry.get("role") == "assistant" and entry.get("pending_action"):
                pending = entry["pending_action"]
                
                if pending.get("type") == "bug":
                    result = _create_github_issue(
                        f"[Bug] {pending['title']}",
                        f"## Bug Report\n\n**Reported via:** Archmorph AI Assistant\n\n### Description\n{pending['description']}\n\n---\n*Auto-generated from chat*",
                        ["bug", "triage"],
                    )
                elif pending.get("type") == "feature":
                    result = _create_github_issue(
                        f"[Feature Request] {pending['title']}",
                        f"## Feature Request\n\n**Requested via:** Archmorph AI Assistant\n\n### Description\n{pending['description']}\n\n---\n*Auto-generated from chat*",
                        ["enhancement", "feature-request"],
                    )
                else:
                    result = _create_github_issue(
                        pending["title"],
                        pending.get("description", ""),
                        pending.get("labels", ["triage"]),
                    )
                
                if result["success"]:
                    reply = (
                        f"Done! I've created the issue.\n\n"
                        f"**#{result['issue_number']}** — {result['title']}\n\n"
                        f"[View on GitHub]({result['issue_url']})"
                    )
                    action_type = f"{pending.get('type', 'issue')}_created"
                else:
                    reply = f"I couldn't create the issue: {result.get('error', 'Unknown error')}"
                    action_type = None
                    result = None
                
                history.append({
                    "role": "assistant",
                    "content": reply,
                    "ts": datetime.now(timezone.utc).isoformat()
                })
                with _session_lock:
                    CHAT_SESSIONS[session_id] = history
                return {"reply": reply, "action": action_type, "data": result}

    # ── Call GPT-4o AI assistant ──
    ai_response = _call_ai_assistant(message, history[:-1])  # Exclude current msg (added to messages in function)
    
    reply = ai_response["reply"]
    action = ai_response.get("action")
    action_result = None
    pending_action = None
    
    # ── Handle AI-detected actions ──
    if action:
        action_type = action.get("action", "")
        
        if action_type == "create_bug":
            pending_action = {
                "type": "bug",
                "title": action.get("title", "Bug Report"),
                "description": action.get("description", ""),
            }
            reply += f"\n\n---\n**Ready to create bug report:**\n- **Title:** {pending_action['title']}\n\nReply **yes** to submit this to GitHub, or provide more details."
            action_result = "issue_draft"
            
        elif action_type == "create_feature":
            pending_action = {
                "type": "feature",
                "title": action.get("title", "Feature Request"),
                "description": action.get("description", ""),
            }
            reply += f"\n\n---\n**Ready to create feature request:**\n- **Title:** {pending_action['title']}\n\nReply **yes** to submit this to GitHub, or provide more details."
            action_result = "issue_draft"
    
    # Store response with any pending action
    history_entry = {
        "role": "assistant",
        "content": reply,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if pending_action:
        history_entry["pending_action"] = pending_action
    
    history.append(history_entry)
    with _session_lock:
        CHAT_SESSIONS[session_id] = history
    
    return {
        "reply": reply,
        "action": action_result,
        "data": pending_action,
        "ai_powered": True,
    }


def get_chat_history(session_id: str) -> List[Dict[str, str]]:
    """Return chat history for a session."""
    return CHAT_SESSIONS.get(session_id, [])


def clear_chat_session(session_id: str) -> bool:
    """Clear a chat session."""
    if session_id in CHAT_SESSIONS:
        del CHAT_SESSIONS[session_id]
        return True
    return False
