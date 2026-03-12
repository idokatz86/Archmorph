"""
Archmorph Roadmap — Version history timeline and feature request system.

Provides timeline of all releases from Day 0 to current, upcoming features,
and integration with GitHub for feature requests and bug reports.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)

# GitHub configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "idokatz86/Archmorph")


class ReleaseStatus(str, Enum):
    """Release status types."""
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    PLANNED = "planned"
    IDEA = "idea"


class IssueType(str, Enum):
    """GitHub issue types."""
    BUG = "bug"
    FEATURE = "feature_request"
    ENHANCEMENT = "enhancement"
    DOCUMENTATION = "documentation"


# ─────────────────────────────────────────────────────────────
# Complete Release Timeline (Day 0 to Present)
# ─────────────────────────────────────────────────────────────

import json
import os

_data_file_RELEASE_TIMELINE = os.path.join(os.path.dirname(__file__), 'data', 'roadmap.json')
try:
    with open(_data_file_RELEASE_TIMELINE, 'r') as _f:
        RELEASE_TIMELINE = json.load(_f)
except FileNotFoundError:
    RELEASE_TIMELINE = [] if True else {}




import time
_github_issues_cache = None
_github_issues_last_fetched = 0

def fetch_github_ideas() -> List[str]:
    global _github_issues_cache, _github_issues_last_fetched
    now = time.time()
    
    # 15 minute cache to avoid rate limits
    if _github_issues_cache is not None and now - _github_issues_last_fetched < 900:
        return _github_issues_cache
        
    if not GITHUB_TOKEN:
        return []
        
    try:
        from github import Github
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        # Get only open issues
        issues = repo.get_issues(state="open")
        highlights = []
        for issue in issues:
            # Skip pull requests
            if issue.pull_request:
                continue
                
            labels = [label.name.lower() for label in issue.labels]
            
            # Format: Title (#123)
            # Add emojis based on labels
            prefix = ""
            if "bug" in labels:
                continue # Skip bugs for roadmap features mostly
            elif "enhancement" in labels or "feature" in labels:
                prefix = "✨ "
            
            # Use markdown formatting for Github links in the UI
            highlights.append(f"{prefix}{issue.title} ([#{issue.number}]({issue.html_url}))")
            
        _github_issues_cache = highlights
        _github_issues_last_fetched = now
        return highlights
    except Exception as exc:
        logger.error(f"Failed to fetch GitHub issues for roadmap: {exc}")
        return _github_issues_cache or []

def get_roadmap() -> Dict[str, Any]:
    """
    Get the complete roadmap with timeline.
    
    Returns grouped releases by status with statistics.
    """
    released = []
    in_progress = []
    planned = []
    ideas = []
    
    for release in RELEASE_TIMELINE:
        status = release["status"]
        if status == ReleaseStatus.RELEASED:
            released.append(release)
        elif status == ReleaseStatus.IN_PROGRESS:
            in_progress.append(release)
        elif status == ReleaseStatus.PLANNED:
            planned.append(release)
        else:
            ideas.append(release)
            
    # ------ GITHUB SYNC INJECTION ------
    gh_ideas = fetch_github_ideas()
    if gh_ideas:
        ideas.insert(0, {
            "version": "Live Sync",
            "name": "Community Feedback & GitHub Issues",
            "date": "Auto-Updated",
            "status": ReleaseStatus.IDEA,
            "highlights": gh_ideas,
        })

            
    # ------ GITHUB SYNC INJECTION ------
    gh_ideas = fetch_github_ideas()
    if gh_ideas:
        ideas.insert(0, {
            "version": "Live Sync",
            "name": "Community Feedback & GitHub Issues",
            "date": "Auto-Updated",
            "status": ReleaseStatus.IDEA,
            "highlights": gh_ideas,
        })

    
    # Calculate statistics
    total_features = sum(
        len(r.get("highlights", [])) 
        for r in released + in_progress
    )
    
    days_since_start = (
        datetime.now(timezone.utc) - datetime(2025, 12, 1, tzinfo=timezone.utc)
    ).days
    
    return {
        "timeline": {
            "released": released,
            "in_progress": in_progress,
            "planned": planned,
            "ideas": ideas,
        },
        "stats": {
            "total_releases": len(released),
            "features_shipped": total_features,
            "days_since_launch": days_since_start,
            "current_version": in_progress[0]["version"] if in_progress else released[-1]["version"],
            "services_supported": 405,
            "cloud_mappings": 122,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_release_by_version(version: str) -> Optional[Dict[str, Any]]:
    """Get details for a specific release version."""
    for release in RELEASE_TIMELINE:
        if release["version"] == version:
            return release
    return None


# ─────────────────────────────────────────────────────────────
# GitHub Issue Creation
# ─────────────────────────────────────────────────────────────
ISSUE_TEMPLATES = {
    IssueType.BUG: {
        "labels": ["bug", "triage"],
        "body_template": """## Bug Report

**Reported via:** Archmorph Assistant
**Date:** {date}

### Description
{description}

### Steps to Reproduce
{steps}

### Expected Behavior
{expected}

### Actual Behavior
{actual}

### Environment
- Browser: {browser}
- OS: {os}

### Additional Context
{context}

---
*This issue was automatically created via the Archmorph bug report system.*
""",
    },
    IssueType.FEATURE: {
        "labels": ["enhancement", "feature-request"],
        "body_template": """## Feature Request

**Requested via:** Archmorph Roadmap
**Date:** {date}

### Description
{description}

### Use Case
{use_case}

### Proposed Solution
{solution}

### Alternatives Considered
{alternatives}

### Additional Context
{context}

---
*This feature request was submitted via the Archmorph roadmap.*
""",
    },
    IssueType.ENHANCEMENT: {
        "labels": ["enhancement"],
        "body_template": """## Enhancement Request

**Requested via:** Archmorph Assistant
**Date:** {date}

### Current Behavior
{current}

### Desired Enhancement
{description}

### Benefits
{benefits}

---
*This enhancement was suggested via the Archmorph assistant.*
""",
    },
}


def create_github_issue(
    issue_type: IssueType,
    title: str,
    details: Dict[str, str],
    user_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a GitHub issue for bug reports or feature requests.
    
    Parameters
    ----------
    issue_type : IssueType
        Type of issue (bug, feature, enhancement)
    title : str
        Issue title
    details : dict
        Details to fill in the template
    user_email : str, optional
        Email of the submitter for follow-up
        
    Returns
    -------
    dict
        Result with success status and issue URL
    """
    if not GITHUB_TOKEN:
        return {
            "success": False,
            "error": "GitHub integration not configured. Please contact support.",
        }
    
    try:
        from github import Github
        
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        
        # Get template
        template = ISSUE_TEMPLATES.get(issue_type, ISSUE_TEMPLATES[IssueType.FEATURE])
        
        # Fill in template
        body_params = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "description": details.get("description", "No description provided"),
            "steps": details.get("steps", "N/A"),
            "expected": details.get("expected", "N/A"),
            "actual": details.get("actual", "N/A"),
            "browser": details.get("browser", "Unknown"),
            "os": details.get("os", "Unknown"),
            "context": details.get("context", ""),
            "use_case": details.get("use_case", ""),
            "solution": details.get("solution", ""),
            "alternatives": details.get("alternatives", "None provided"),
            "current": details.get("current", ""),
            "benefits": details.get("benefits", ""),
        }
        
        body = template["body_template"].format(**body_params)
        
        if user_email:
            body += f"\n\n**Submitter contact:** {user_email}"
        
        # Get valid labels
        existing_labels = [label.name for label in repo.get_labels()]
        valid_labels = [lbl for lbl in template["labels"] if lbl in existing_labels]
        
        # Create issue
        issue = repo.create_issue(
            title=title,
            body=body,
            labels=valid_labels if valid_labels else [],
        )
        
        logger.info("Created GitHub issue #%d: %s", issue.number, title)
        
        return {
            "success": True,
            "issue_number": issue.number,
            "issue_url": issue.html_url,
            "title": issue.title,
            "type": issue_type.value,
        }
        
    except Exception as exc:
        logger.error("Failed to create GitHub issue: %s", exc)
        return {
            "success": False,
            "error": str(exc),
        }


def submit_feature_request(
    title: str,
    description: str,
    use_case: str = "",
    user_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submit a feature request to GitHub.
    
    Convenience wrapper for create_github_issue with feature type.
    """
    return create_github_issue(
        issue_type=IssueType.FEATURE,
        title=f"[Feature Request] {title}",
        details={
            "description": description,
            "use_case": use_case,
            "solution": "",
            "alternatives": "",
            "context": "",
        },
        user_email=user_email,
    )


def submit_bug_report(
    title: str,
    description: str,
    steps: str = "",
    expected: str = "",
    actual: str = "",
    browser: str = "Unknown",
    os_info: str = "Unknown",
    user_email: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submit a bug report to GitHub.
    
    Convenience wrapper for create_github_issue with bug type.
    """
    return create_github_issue(
        issue_type=IssueType.BUG,
        title=f"[Bug] {title}",
        details={
            "description": description,
            "steps": steps,
            "expected": expected,
            "actual": actual,
            "browser": browser,
            "os": os_info,
            "context": "",
        },
        user_email=user_email,
    )
