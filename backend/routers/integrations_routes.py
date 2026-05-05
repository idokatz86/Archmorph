from error_envelope import ArchmorphException
"""
Enterprise integration endpoints (Issue #259).

Stateless endpoints that post analysis results to Slack, Teams,
Jira, and GitHub.  Each call receives the target webhook/API URL
directly — nothing is persisted.
Uses only stdlib ``urllib.request`` for outbound HTTP (no new deps).
"""

import json
import logging
import ssl
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import ConfigDict, Field
from strict_models import StrictBaseModel

from routers.shared import limiter, verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Integrations"])


# ---------------------------------------------------------------------------
# Shared HTTP helper (stdlib only, no new deps)
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST JSON to an HTTPS URL using stdlib. Returns status info."""
    # SSRF protection: only allow HTTPS to known external service hostnames
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        return {"success": False, "status_code": 0, "body": "Only HTTPS URLs are allowed"}
    _ALLOWED_HOSTS = {
        "hooks.slack.com", "api.github.com",
    }
    hostname = (parsed.hostname or "").lower()
    # Allow *.atlassian.net for Jira, *.webhook.office.com for Teams
    # Use dot-prefixed matching to prevent subdomain spoofing (e.g. evil-atlassian.net)
    host_ok = (
        hostname in _ALLOWED_HOSTS
        or hostname.endswith(".atlassian.net") and hostname.count(".") >= 2
        or hostname.endswith(".webhook.office.com") and hostname.count(".") >= 3
    )
    if not host_ok:
        return {"success": False, "status_code": 0, "body": "Hostname not in allowlist"}
    sanitized_url = urllib.parse.urlunparse(parsed)  # rebuild from parsed parts
    data = json.dumps(payload, default=str).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "User-Agent": "Archmorph-Integrations/1.0"}
    if headers:
        hdrs.update(headers)

    req = urllib.request.Request(sanitized_url, data=data, headers=hdrs, method="POST")
    ctx = ssl.create_default_context()

    from circuit_breakers import webhook_breaker
    try:
        with webhook_breaker.call(urllib.request.urlopen, req, timeout=15, context=ctx) as resp:  # nosec B310 # noqa: S310 — URL validated against allowlist above
            return {
                "success": True,
                "status_code": resp.status,
                "body": resp.read().decode("utf-8", errors="replace")[:500],
            }
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "status_code": exc.code,
            "error_body": exc.read().decode("utf-8", errors="replace")[:500],
        }
    except Exception:
        return {"success": False, "status_code": None, "error": "Request failed"}


def _validate_https(url: str, field_name: str = "webhook_url") -> None:
    if not url.startswith("https://"):
        raise ArchmorphException(400, f"{field_name} must use HTTPS")


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class SlackNotifyRequest(StrictBaseModel):
    webhook_url: str = Field(..., description="Slack incoming webhook URL (HTTPS)")
    diagram_id: str = Field("unknown", description="Diagram/analysis identifier")
    total_services: int = Field(0, ge=0, description="Number of services detected")
    confidence: str = Field("N/A", description="Analysis confidence level")
    cost_estimate: Optional[str] = Field(None, description="Monthly cost estimate string")
    summary: str = Field("", max_length=1000, description="Optional analysis summary text")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "webhook_url": "https://hooks.slack.com/services/T.../B.../xxx",
                "diagram_id": "diag-abc123",
                "total_services": 12,
                "confidence": "high",
                "cost_estimate": "$450/month",
                "summary": "Migration from AWS to Azure — 12 services mapped",
            }
        }
    )


class TeamsNotifyRequest(StrictBaseModel):
    webhook_url: str = Field(..., description="Teams incoming webhook URL (HTTPS)")
    diagram_id: str = Field("unknown")
    total_services: int = Field(0, ge=0)
    confidence: str = Field("N/A")
    cost_estimate: Optional[str] = None
    summary: str = Field("", max_length=1000)


class JiraCreateRequest(StrictBaseModel):
    api_url: str = Field(..., description="Jira REST API base URL, e.g. https://myorg.atlassian.net")
    email: str = Field(..., description="Jira user email for basic auth")
    api_token: str = Field(..., description="Jira API token")
    project_key: str = Field(..., description="Jira project key, e.g. MIG")
    diagram_id: str = Field("unknown")
    title: str = Field("Archmorph Migration", max_length=256)
    phases: List[str] = Field(
        default_factory=lambda: ["Assessment", "Planning", "Migration", "Validation", "Cutover"],
        description="Migration runbook phases — each becomes a sub-task",
    )
    summary: str = Field("", max_length=2000)


class GitHubIssueRequest(StrictBaseModel):
    repo: str = Field(..., description="GitHub repo in owner/repo format")
    token: str = Field(..., description="GitHub personal access token")
    title: str = Field("Archmorph Migration Tracking", max_length=256)
    diagram_id: str = Field("unknown")
    total_services: int = Field(0, ge=0)
    confidence: str = Field("N/A")
    summary: str = Field("", max_length=4000)
    labels: List[str] = Field(default_factory=lambda: ["archmorph", "migration"])


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

@router.post(
    "/api/integrations/slack/notify",
    summary="Post analysis summary to Slack",
    description="Send a rich Slack message with service count, confidence, and cost estimate "
                "via an incoming webhook URL.",
)
@limiter.limit("10/minute")
async def slack_notify(body: SlackNotifyRequest, request: Request, _auth=Depends(verify_api_key)):
    _validate_https(body.webhook_url)

    fields = [
        {"type": "mrkdwn", "text": f"*Services:* {body.total_services}"},
        {"type": "mrkdwn", "text": f"*Confidence:* {body.confidence}"},
    ]
    if body.cost_estimate:
        fields.append({"type": "mrkdwn", "text": f"*Est. Cost:* {body.cost_estimate}"})

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":rocket: Archmorph Analysis Complete"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Diagram:* `{body.diagram_id}`",
            },
        },
        {"type": "section", "fields": fields},
    ]

    if body.summary:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": body.summary[:3000]},
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"_Sent by Archmorph at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_"},
        ],
    })

    result = _post_json(body.webhook_url, {"blocks": blocks})

    if not result["success"]:
        raise ArchmorphException(502, f"Slack delivery failed: {result.get('error') or result.get('body', 'unknown')}")

    return {"status": "sent", "platform": "slack", "diagram_id": body.diagram_id}


# ---------------------------------------------------------------------------
# Microsoft Teams
# ---------------------------------------------------------------------------

@router.post(
    "/api/integrations/teams/notify",
    summary="Post adaptive card to Microsoft Teams",
    description="Send a Teams adaptive card with migration summary via incoming webhook.",
)
@limiter.limit("10/minute")
async def teams_notify(body: TeamsNotifyRequest, request: Request, _auth=Depends(verify_api_key)):
    _validate_https(body.webhook_url)

    facts = [
        {"title": "Diagram", "value": body.diagram_id},
        {"title": "Services", "value": str(body.total_services)},
        {"title": "Confidence", "value": body.confidence},
    ]
    if body.cost_estimate:
        facts.append({"title": "Est. Cost", "value": body.cost_estimate})

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "Large",
                            "weight": "Bolder",
                            "text": "Archmorph Analysis Complete",
                        },
                        {
                            "type": "FactSet",
                            "facts": facts,
                        },
                    ],
                },
            }
        ],
    }

    if body.summary:
        card["attachments"][0]["content"]["body"].append({
            "type": "TextBlock",
            "text": body.summary[:2000],
            "wrap": True,
        })

    result = _post_json(body.webhook_url, card)

    if not result["success"]:
        raise ArchmorphException(502, f"Teams delivery failed: {result.get('error') or result.get('body', 'unknown')}")

    return {"status": "sent", "platform": "teams", "diagram_id": body.diagram_id}


# ---------------------------------------------------------------------------
# Jira — Create Epic + Sub-tasks
# ---------------------------------------------------------------------------

@router.post(
    "/api/integrations/jira/create",
    summary="Create Jira migration epic with tasks",
    description="Create an Epic in Jira from an analysis runbook. Each migration phase "
                "becomes a sub-task under the Epic.",
)
@limiter.limit("5/minute")
async def jira_create(body: JiraCreateRequest, request: Request, _auth=Depends(verify_api_key)):
    _validate_https(body.api_url, "api_url")

    import base64
    auth_str = base64.b64encode(f"{body.email}:{body.api_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth_str}",
        "Accept": "application/json",
    }

    base = body.api_url.rstrip("/")

    # 1. Create Epic
    epic_payload = {
        "fields": {
            "project": {"key": body.project_key},
            "summary": f"[Archmorph] {body.title} — {body.diagram_id}",
            "description": body.summary or f"Migration tracking epic created by Archmorph for diagram {body.diagram_id}",
            "issuetype": {"name": "Epic"},
        }
    }
    epic_result = _post_json(f"{base}/rest/api/3/issue", epic_payload, headers)

    if not epic_result["success"]:
        logger.warning("Jira Epic creation failed: HTTP %s", epic_result.get('status_code'))
        raise ArchmorphException(
            502,
            "Jira Epic creation failed. Please check your API URL and credentials.",
        )

    try:
        epic_data = json.loads(epic_result["body"])
        epic_key = epic_data.get("key", "UNKNOWN")
    except (json.JSONDecodeError, KeyError):
        epic_key = "UNKNOWN"

    # 2. Create sub-tasks for each phase
    created_tasks = []
    for idx, phase in enumerate(body.phases, 1):
        task_payload = {
            "fields": {
                "project": {"key": body.project_key},
                "parent": {"key": epic_key},
                "summary": f"Phase {idx}: {phase}",
                "description": f"Migration phase: {phase}\nDiagram: {body.diagram_id}",
                "issuetype": {"name": "Sub-task"},
            }
        }
        task_result = _post_json(f"{base}/rest/api/3/issue", task_payload, headers)
        if task_result["success"]:
            try:
                task_data = json.loads(task_result["body"])
                task_key = task_data.get("key")
                created_tasks.append(task_key if task_key else f"task-{idx}")
            except (json.JSONDecodeError, KeyError):
                created_tasks.append(f"task-{idx}")
        else:
            logger.warning("Jira sub-task %d failed: HTTP %s", idx, task_result.get('status_code'))

    return {
        "status": "created",
        "platform": "jira",
        "epic_key": epic_key,
        "sub_tasks": created_tasks,
        "diagram_id": body.diagram_id,
    }


# ---------------------------------------------------------------------------
# GitHub — Create tracking issue
# ---------------------------------------------------------------------------

@router.post(
    "/api/integrations/github/issue",
    summary="Create GitHub tracking issue",
    description="Create a GitHub issue with a markdown summary from the analysis.",
)
@limiter.limit("5/minute")
async def github_issue(body: GitHubIssueRequest, request: Request, _auth=Depends(verify_api_key)):
    if "/" not in body.repo or len(body.repo.split("/")) != 2:
        raise ArchmorphException(400, "repo must be in owner/repo format")

    md_body = (
        f"## Archmorph Migration Tracking\n\n"
        f"**Diagram:** `{body.diagram_id}`\n"
        f"**Services:** {body.total_services}\n"
        f"**Confidence:** {body.confidence}\n\n"
    )
    if body.summary:
        md_body += f"### Summary\n\n{body.summary}\n\n"

    md_body += (
        f"---\n"
        f"_Generated by [Archmorph](https://archmorphai.com) on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n"
    )

    url = f"https://api.github.com/repos/{body.repo}/issues"
    payload = {
        "title": body.title,
        "body": md_body,
        "labels": body.labels,
    }
    headers = {
        "Authorization": f"Bearer {body.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    result = _post_json(url, payload, headers)

    if not result["success"]:
        logger.warning("GitHub issue creation failed: HTTP %s", result.get('status_code'))
        raise ArchmorphException(
            502,
            "GitHub issue creation failed. Please check your token and repository settings.",
        )

    try:
        issue_data = json.loads(result["body"])
        issue_number = issue_data.get("number")
        issue_url_raw = issue_data.get("html_url", "")
        # Sanitize: only return URL if it looks like a GitHub URL
        issue_url = issue_url_raw if isinstance(issue_url_raw, str) and issue_url_raw.startswith("https://github.com/") else ""
    except (json.JSONDecodeError, KeyError):
        issue_number = None
        issue_url = ""

    return {
        "status": "created",
        "platform": "github",
        "issue_number": issue_number,
        "issue_url": issue_url,
        "diagram_id": body.diagram_id,
    }
