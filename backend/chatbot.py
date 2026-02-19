"""
Archmorph Chatbot — AI-powered assistant that can create GitHub issues.

Supports general Q&A about Archmorph features and structured issue creation
through natural conversation. Uses Azure OpenAI for intent detection and
GitHub API for issue management.
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# GitHub configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "idokatz86/Archmorph")

# Conversation history per session (TTL: 2 hours, max 500 sessions)
CHAT_SESSIONS: TTLCache = TTLCache(maxsize=500, ttl=7200)

# ─────────────────────────────────────────────────────────────
# Label mapping for auto-categorization
# ─────────────────────────────────────────────────────────────
LABEL_KEYWORDS = {
    "bug": ["bug", "broken", "error", "crash", "not working", "fails", "issue", "problem", "fix"],
    "enhancement": ["feature", "enhance", "improve", "add", "request", "suggestion", "want", "could you", "would be nice"],
    "documentation": ["docs", "documentation", "readme", "guide", "explain", "how to"],
    "question": ["question", "how", "why", "what", "where", "when", "help"],
}


def _detect_labels(text: str) -> List[str]:
    """Auto-detect appropriate GitHub labels from text content."""
    text_lower = text.lower()
    labels = []
    for label, keywords in LABEL_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            labels.append(label)
    return labels if labels else ["triage"]


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
        existing_labels = [l.name for l in repo.get_labels()]
        valid_labels = [l for l in labels if l in existing_labels]

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
            "labels": [l.name for l in issue.labels],
        }
    except Exception as exc:
        logger.error(f"GitHub issue creation failed: {exc}")
        return {"success": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Intent detection
# ─────────────────────────────────────────────────────────────
ISSUE_PATTERNS = [
    r"create\s+(?:a\s+)?(?:github\s+)?issue",
    r"open\s+(?:a\s+)?(?:github\s+)?issue",
    r"file\s+(?:a\s+)?(?:github\s+)?issue",
    r"report\s+(?:a\s+)?(?:github\s+)?(?:bug|issue)",
    r"submit\s+(?:a\s+)?(?:github\s+)?(?:bug|issue|feature)",
    r"new\s+issue",
    r"i\s+want\s+to\s+report",
    r"i\s+found\s+a\s+bug",
    r"can\s+you\s+create\s+(?:an?\s+)?issue",
]


def _detect_intent(message: str) -> str:
    """Detect user intent: 'create_issue', 'confirm_issue', or 'general'."""
    msg_lower = message.lower().strip()

    for pattern in ISSUE_PATTERNS:
        if re.search(pattern, msg_lower):
            return "create_issue"

    return "general"


def _extract_issue_details(message: str, history: List[Dict]) -> Dict[str, str]:
    """Extract title and body from conversation context."""
    # Look for explicit title patterns
    title_match = re.search(
        r"(?:title|subject|name)[\s:]+[\"']?(.+?)[\"']?(?:\n|$|\.(?:\s|$))",
        message,
        re.IGNORECASE,
    )
    body_match = re.search(
        r"(?:body|description|details|content)[\s:]+[\"']?(.+?)(?:[\"']?$)",
        message,
        re.IGNORECASE | re.DOTALL,
    )

    title = title_match.group(1).strip() if title_match else ""
    body = body_match.group(1).strip() if body_match else ""

    # If no explicit title, try to extract from the message
    if not title:
        # Remove the "create issue" trigger phrase and use the rest
        cleaned = re.sub(
            r"(?:please\s+)?(?:create|open|file|report|submit)\s+(?:a\s+)?(?:new\s+)?(?:github\s+)?(?:issue|bug|feature)\s*(?:for|about|regarding|:)?\s*",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned and len(cleaned) > 5:
            # Take first sentence as title
            first_sentence = re.split(r"[.\n]", cleaned)[0].strip()
            title = first_sentence[:120] if first_sentence else ""
            body = cleaned if len(cleaned) > len(first_sentence) + 5 else ""

    return {"title": title, "body": body}


# ─────────────────────────────────────────────────────────────
# Archmorph FAQ knowledge base
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


def _find_faq_answer(message: str) -> Optional[str]:
    """Find a matching FAQ answer."""
    msg_lower = message.lower()
    best_match = None
    best_score = 0

    for key, answer in FAQ.items():
        keywords = key.split()
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > best_score and score >= len(keywords) * 0.5:
            best_score = score
            best_match = answer

    return best_match


# ─────────────────────────────────────────────────────────────
# Main chat handler
# ─────────────────────────────────────────────────────────────
def process_chat_message(
    session_id: str, message: str
) -> Dict[str, Any]:
    """
    Process an incoming chat message.

    Returns a response dict with:
      - reply: bot's text response
      - action: None | 'issue_draft' | 'issue_created'
      - data: additional data (issue details, etc.)
    """
    # Initialize session
    if session_id not in CHAT_SESSIONS:
        CHAT_SESSIONS[session_id] = []

    history = CHAT_SESSIONS[session_id]
    history.append({"role": "user", "content": message, "ts": datetime.now(timezone.utc).isoformat()})

    intent = _detect_intent(message)

    # ── Create Issue flow ──
    if intent == "create_issue":
        details = _extract_issue_details(message, history)
        labels = _detect_labels(message)

        if details["title"]:
            # We have enough info — present a draft
            draft = {
                "title": details["title"],
                "body": details["body"] or f"Issue reported via Archmorph chatbot.\n\nOriginal message:\n> {message}",
                "labels": labels,
            }
            reply = (
                f"I've prepared a GitHub issue draft:\n\n"
                f"**Title:** {draft['title']}\n"
                f"**Labels:** {', '.join(draft['labels'])}\n\n"
                f"Would you like me to create this issue? Reply **yes** to confirm, or tell me what to change."
            )
            history.append({"role": "assistant", "content": reply, "ts": datetime.now(timezone.utc).isoformat()})
            CHAT_SESSIONS[session_id] = history

            return {
                "reply": reply,
                "action": "issue_draft",
                "data": draft,
            }
        else:
            reply = (
                "I can create a GitHub issue for you. Please tell me:\n\n"
                "1. **Title** — A short summary of the issue\n"
                "2. **Description** — Details about what happened or what you'd like\n\n"
                "For example: *Create an issue: Add dark mode toggle — The app should have a button to switch between light and dark themes.*"
            )
            history.append({"role": "assistant", "content": reply, "ts": datetime.now(timezone.utc).isoformat()})
            return {"reply": reply, "action": None, "data": None}

    # ── Confirm issue creation ──
    msg_lower = message.lower().strip()
    if msg_lower in ("yes", "y", "confirm", "create it", "go ahead", "do it", "sure", "ok"):
        # Check if there's a pending draft
        last_draft = None
        for entry in reversed(history):
            if entry.get("role") == "assistant" and "issue_draft" in str(entry.get("content", "")):
                break

        # Look for draft in recent bot responses
        for i, entry in enumerate(reversed(history)):
            if entry.get("role") == "assistant":
                if "**Title:**" in entry.get("content", ""):
                    # Extract from the formatted draft
                    content = entry["content"]
                    title_match = re.search(r"\*\*Title:\*\*\s*(.+?)(?:\n|$)", content)
                    if title_match:
                        last_draft = {
                            "title": title_match.group(1).strip(),
                            "body": f"Issue reported via Archmorph chatbot.\n\nConversation context:\n",
                            "labels": _detect_labels(title_match.group(1)),
                        }
                        # Build body from user messages
                        user_msgs = [e["content"] for e in history if e["role"] == "user"]
                        last_draft["body"] += "\n".join(f"> {m}" for m in user_msgs[:-1])
                    break

        if last_draft:
            result = _create_github_issue(
                last_draft["title"],
                last_draft["body"],
                last_draft["labels"],
            )
            if result["success"]:
                reply = (
                    f"Issue created successfully!\n\n"
                    f"**#{result['issue_number']}** — {result['title']}\n"
                    f"[View on GitHub]({result['issue_url']})"
                )
                history.append({"role": "assistant", "content": reply, "ts": datetime.now(timezone.utc).isoformat()})
                return {"reply": reply, "action": "issue_created", "data": result}
            else:
                reply = f"Sorry, I couldn't create the issue: {result['error']}"
                history.append({"role": "assistant", "content": reply, "ts": datetime.now(timezone.utc).isoformat()})
                return {"reply": reply, "action": None, "data": result}
        else:
            reply = "I don't have a pending issue draft. Tell me what issue you'd like to create."
            history.append({"role": "assistant", "content": reply, "ts": datetime.now(timezone.utc).isoformat()})
            return {"reply": reply, "action": None, "data": None}

    # ── General Q&A ──
    faq_answer = _find_faq_answer(message)
    if faq_answer:
        reply = faq_answer
    else:
        reply = (
            "I'm the Archmorph assistant. I can help you with:\n\n"
            "- **Create a GitHub issue** — Just say 'create an issue about...'\n"
            "- **Learn about Archmorph** — Ask me how it works, supported formats, pricing, etc.\n"
            "- **Get support** — Contact us at send2katz@gmail.com\n\n"
            "What would you like to know?"
        )

    history.append({"role": "assistant", "content": reply, "ts": datetime.now(timezone.utc).isoformat()})
    return {"reply": reply, "action": None, "data": None}


def get_chat_history(session_id: str) -> List[Dict[str, str]]:
    """Return chat history for a session."""
    return CHAT_SESSIONS.get(session_id, [])


def clear_chat_session(session_id: str) -> bool:
    """Clear a chat session."""
    if session_id in CHAT_SESSIONS:
        del CHAT_SESSIONS[session_id]
        return True
    return False
