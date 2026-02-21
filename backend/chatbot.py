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
from typing import Dict, Any, List
from datetime import datetime, timezone

from cachetools import TTLCache

from openai_client import get_openai_client, AZURE_OPENAI_DEPLOYMENT, openai_retry

logger = logging.getLogger(__name__)

# GitHub configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "idokatz86/Archmorph")

# Conversation history per session (TTL: 2 hours, max 500 sessions)
CHAT_SESSIONS: TTLCache = TTLCache(maxsize=500, ttl=7200)


# ─────────────────────────────────────────────────────────────
# AI Assistant System Prompt
# ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are **Archmorph AI Assistant** — a friendly, knowledgeable AI assistant for Archmorph, the cloud architecture migration platform.

## About Archmorph
Archmorph is an AI-powered Cloud Architecture Translator that:
- Converts AWS and GCP architecture diagrams into Azure equivalents
- Generates production-ready Terraform and Bicep IaC code
- Uses GPT-4o Vision to analyze uploaded architecture diagrams
- Asks 8-18 guided migration questions to refine recommendations
- Provides cost estimates using Azure Retail Prices API
- Exports diagrams in Excalidraw, Draw.io, and Visio formats

## Current Version: 2.10.0 (February 21, 2026)
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
{"action": "create_bug", "title": "<bug title>", "description": "<details>"}
```

For feature requests:
```json
{"action": "create_feature", "title": "<feature title>", "description": "<details>"}
```

## Service Catalog
- AWS services: 145 (EC2, S3, RDS, Lambda, EKS, etc.)
- Azure services: 143 (VMs, Storage, SQL, Functions, AKS, etc.)
- GCP services: 117 (Compute Engine, Cloud Storage, Cloud SQL, etc.)
- Cross-cloud mappings: 122 verified service mappings

## Contact
- Email: send2katz@gmail.com
- GitHub: https://github.com/idokatz86/Archmorph
"""


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
        
        # Check for action JSON in response
        action = None
        action_match = re.search(
            r'```json\s*(\{[^}]*"action"[^}]*\})\s*```',
            reply_text,
            re.DOTALL
        )
        if action_match:
            try:
                action = json.loads(action_match.group(1))
                # Remove the JSON block from visible reply
                reply_text = re.sub(
                    r'```json\s*\{[^}]*"action"[^}]*\}\s*```',
                    '',
                    reply_text
                ).strip()
            except json.JSONDecodeError:
                pass
        
        return {
            "reply": reply_text,
            "action": action,
            "tokens_used": response.usage.total_tokens if response.usage else 0,
        }
        
    except Exception as exc:
        logger.error(f"AI assistant error: {exc}")
        return {
            "reply": "I apologize, but I'm having trouble processing your request right now. Please try again in a moment, or contact us at send2katz@gmail.com for assistance.",
            "action": None,
            "error": str(exc),
        }


def _create_github_issue(title: str, body: str, labels: List[str]) -> Dict[str, Any]:
    """Create a GitHub issue using PyGithub."""
    if not GITHUB_TOKEN:
        return {
            "success": False,
            "error": "GitHub token not configured. Set GITHUB_TOKEN environment variable.",
        }

    try:
        from github import Github

        g = Github(GITHUB_TOKEN)
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
        logger.error(f"GitHub issue creation failed: {exc}")
        return {"success": False, "error": str(exc)}


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
    "contact": "You can reach the team at send2katz@gmail.com for questions, feedback, or partnership inquiries.",
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
    # Initialize session
    if session_id not in CHAT_SESSIONS:
        CHAT_SESSIONS[session_id] = []

    history = CHAT_SESSIONS[session_id]
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
