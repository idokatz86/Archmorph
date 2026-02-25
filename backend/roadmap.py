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
RELEASE_TIMELINE: List[Dict[str, Any]] = [
    # ═══════════════════════════════════════════════════════════
    # Phase 1: Foundation (Dec 2025)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "1.0.0",
        "name": "Initial Release",
        "date": "2025-12-01",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Core architecture diagram upload",
            "Basic AWS to Azure service mapping",
            "Simple Terraform code generation",
            "Manual service selection",
        ],
        "metrics": {"services": 50, "mappings": 30},
    },
    {
        "version": "1.1.0",
        "name": "GCP Support",
        "date": "2025-12-08",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "GCP to Azure migration support",
            "Expanded service catalog to 120 services",
            "Basic cost estimation",
            "SVG/PNG diagram export",
        ],
        "metrics": {"services": 120, "mappings": 65},
    },
    {
        "version": "1.2.0",
        "name": "Vision Analysis",
        "date": "2025-12-15",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "GPT-4o Vision integration for diagram analysis",
            "Automatic service detection from images",
            "Architecture pattern recognition",
            "Multi-zone diagram support",
        ],
        "metrics": {"services": 150, "mappings": 80},
    },
    # ═══════════════════════════════════════════════════════════
    # Phase 2: Intelligence (Jan 2026)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "2.0.0",
        "name": "Guided Migration",
        "date": "2026-01-05",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "8-18 guided migration questions",
            "Context-aware question generation",
            "Architecture recommendations",
            "Confidence scoring for mappings",
        ],
        "metrics": {"services": 200, "mappings": 95},
    },
    {
        "version": "2.1.0",
        "name": "IaC Chat Assistant",
        "date": "2026-01-12",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "GPT-4o powered Terraform/Bicep assistant",
            "Natural language code modifications",
            "Add VNet, NSG, storage via chat",
            "Code explanation capabilities",
        ],
        "metrics": {"services": 250, "mappings": 100},
    },
    {
        "version": "2.2.0",
        "name": "Bicep Support",
        "date": "2026-01-19",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Native Bicep code generation",
            "Toggle between Terraform and Bicep",
            "Secure parameter handling (@secure())",
            "Module-based architecture",
        ],
        "metrics": {"services": 280, "mappings": 105},
    },
    {
        "version": "2.3.0",
        "name": "Advanced Diagrams",
        "date": "2026-01-26",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Excalidraw native integration",
            "Draw.io export support",
            "Visio format generation",
            "High-level design (HLD) documents",
        ],
        "metrics": {"services": 320, "mappings": 110},
    },
    # ═══════════════════════════════════════════════════════════
    # Phase 3: Enterprise (Feb 2026)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "2.4.0",
        "name": "Service Builder",
        "date": "2026-02-02",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Dynamic Azure service recommendations",
            "Pattern-based service selection",
            "Compliance-aware suggestions",
            "Cost optimization hints",
        ],
        "metrics": {"services": 350, "mappings": 115},
    },
    {
        "version": "2.5.0",
        "name": "Icon System",
        "date": "2026-02-07",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Official Azure icon packs",
            "Custom icon color variants",
            "SVG sanitization pipeline",
            "Icon registry with 500+ icons",
        ],
        "metrics": {"services": 380, "mappings": 118},
    },
    {
        "version": "2.6.0",
        "name": "Cost Intelligence",
        "date": "2026-02-10",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Azure Retail Prices API integration",
            "SKU-level cost breakdown",
            "Monthly/annual projections",
            "Cost comparison reports",
        ],
        "metrics": {"services": 395, "mappings": 120},
    },
    {
        "version": "2.7.0",
        "name": "Production Ready",
        "date": "2026-02-14",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Azure Container Apps deployment",
            "CI/CD with GitHub Actions",
            "Terraform infrastructure code",
            "Application Insights monitoring",
        ],
        "metrics": {"services": 400, "mappings": 122},
    },
    {
        "version": "2.8.0",
        "name": "E2E Testing",
        "date": "2026-02-18",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Playwright E2E test suite",
            "85+ unit tests",
            "Visual regression testing",
            "Performance benchmarks",
        ],
        "metrics": {"services": 405, "mappings": 122},
    },
    {
        "version": "2.9.0",
        "name": "Enterprise Security",
        "date": "2026-02-21",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Azure AD B2C authentication",
            "Usage quotas (Free/Pro/Enterprise)",
            "Lead capture for downloads",
            "Migration runbook generator",
            "Architecture versioning",
            "Terraform plan preview",
            "Enhanced Azure Monitor alerts",
            "Application analytics dashboard",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 72},
    },
    # ═══════════════════════════════════════════════════════════
    # Current Release
    # ═══════════════════════════════════════════════════════════
    {
        "version": "2.10.0",
        "name": "AI Assistant & Roadmap",
        "date": "2026-02-21",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "GPT-4o powered AI assistant",
            "Natural language conversations",
            "Interactive roadmap timeline",
            "Feature request integration",
            "Bug reporting to GitHub",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 78},
    },
    # ═══════════════════════════════════════════════════════════
    # v2.11.0 - Security & Auth (Released)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "2.11.0",
        "name": "Security & Authentication",
        "date": "2026-02-21",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "JWT admin authentication (HS256)",
            "CORS security hardening",
            "Persistent analytics with Azure Blob Storage",
            "Security remediation (rate limiting, input validation)",
            "81+ API endpoints verified",
            "719 passing tests",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 81},
    },
    # ═══════════════════════════════════════════════════════════
    # v2.11.1 - UX Polish & Document Export (Released)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "2.11.1",
        "name": "UX Polish & Document Export",
        "date": "2026-02-21",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Drag & drop upload zone with file preview",
            "HLD export to Word, PDF, and PowerPoint",
            "Copy/download feedback toasts",
            "Questions grouped by category with progress pills",
            "Cost estimate visual progress bars",
            "IaC code line numbers & copy feedback",
            "IaC Chat quick action pills",
            "Confirm before reset dialog",
            "HLD tab navigation icons",
            "Mobile stepper labels fix",
            "Updated sample diagrams with provider badges",
            "Monitoring 'None' option in guided questions",
            "Error dismiss tooltip & hover state",
            "README React 19 documentation fix",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 82},
    },
    # ═══════════════════════════════════════════════════════════
    # v3.0.0 - Multi-Cloud & Enterprise (Released)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "3.0.0",
        "name": "Multi-Cloud & Enterprise",
        "date": "2026-02-24",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Multi-cloud target support (AWS, GCP, Azure)",
            "Reverse migration & cloud repatriation",
            "Live infrastructure scanning via SDK",
            "Drift detection for running infrastructure",
            "SSO/SAML integration with Azure AD/Okta",
            "Audit logging & compliance reports",
            "GitHub App integration for PR analysis",
            "Background job queue (Redis + Celery)",
            "OpenTelemetry observability stack",
            "API versioning (/v1/ prefix)",
            "Inter-question constraint system for guided questions",
            "Compliance/data-residency filters for region selection",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 85},
    },
    # ═══════════════════════════════════════════════════════════
    # Sprint 1 — Production Critical (Released)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "3.0.1",
        "name": "Sprint 1 — Production Critical",
        "date": "2026-02-25",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Error envelope middleware with correlation IDs (#260)",
            "Visio (.vsdx) import parser (#262)",
            "White-label theming engine with custom branding (#273)",
            "Session restore & UX improvements (#274, #279)",
            "API versioning with /v1/ prefix (#291)",
            "Best-practice validation engine (#287)",
            "Cost optimizer engine (#293)",
            "Migration assessment scoring (#294)",
            "Compliance mapper (GDPR/HIPAA/SOC2/PCI DSS) (#296)",
            "Living architecture health monitoring (#286)",
            "AI-powered service suggestions (#303)",
            "Migration risk scoring (#294)",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 90},
    },
    # ═══════════════════════════════════════════════════════════
    # Sprint 2 — Reliability & DX (Released)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "3.0.2",
        "name": "Sprint 2 — Reliability & Developer Experience",
        "date": "2026-02-25",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "API client rewrite with retry/backoff/timeout (#268, #305)",
            "User-friendly error messages for all HTTP codes (#305)",
            "Configurable OpenAI timeout & fallback model (#278, #285, #298)",
            "GPT output truncation detection (#278)",
            "Vision analysis cache layer with TTLCache (#295)",
            "IaC security scanning (8 rules) (#276)",
            "Session cache for IaC/HLD persistence (#263)",
            "Session expiry countdown warning (#261)",
            "Cancel analysis button (#227)",
            "Error clearing on new file upload (#304)",
            "Mobile responsive button layout (#306)",
            "Docker Compose with PostgreSQL 16 & Redis 7 (#283)",
            "Configurable user cache TTL (#266)",
            "Image store TTL aligned to session store (#264)",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 90},
    },
    # ═══════════════════════════════════════════════════════════
    # Sprint 3 — Advanced Features (Released)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "3.0.3",
        "name": "Sprint 3 — Advanced Features & Polish",
        "date": "2026-02-25",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Azure/GCP services pagination fix (#265)",
            "Prompt guard for IaC chat (#267)",
            "Migration runbook generator (#269)",
            "CloudFormation IaC format (#270)",
            "Terraform plan preview (#275)",
            "Architecture versioning with diff (#277)",
            "Migration intelligence with community data (#280)",
            "Infrastructure import from live cloud (#281)",
            "Organization & team management (#289)",
            "Journey analytics tracking (#297)",
            "Dependency graph visualization (#307)",
            "Risk score & compliance panels (#308, #309)",
            "URL hash sync for tab navigation (#310)",
            "Feature flags system (#311)",
            "Admin dashboard with analytics (#314)",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 95},
    },
    # ═══════════════════════════════════════════════════════════
    # v3.1.0 — Current Release
    # ═══════════════════════════════════════════════════════════
    {
        "version": "3.1.0",
        "name": "Landing Page Redesign & GA",
        "date": "2026-02-25",
        "status": ReleaseStatus.RELEASED,
        "highlights": [
            "Complete landing page redesign with 9 feature cards",
            "Stats bar (405+ services, 120+ mappings, 3 IaC formats)",
            "100% free forever — removed all beta language",
            "Buy Me a Coffee link restored in footer",
            "Updated FAQs with accurate feature descriptions",
            "Removed beta preview banner",
            "Roadmap updated with complete release history",
            "1,900+ tests (274 frontend, 1,653 backend)",
        ],
        "metrics": {"services": 405, "mappings": 122, "api_endpoints": 95},
    },
    # ═══════════════════════════════════════════════════════════
    # Planned Releases
    # ═══════════════════════════════════════════════════════════
    {
        "version": "3.2.0",
        "name": "QA & Testing Excellence",
        "date": "2026-03-14",
        "status": ReleaseStatus.PLANNED,
        "highlights": [
            "Contract testing for API endpoints",
            "Visual regression testing with Percy",
            "Load testing with k6/Locust",
            "Chaos engineering framework",
            "Test coverage reporting (95%+ target)",
            "Mutation testing integration",
        ],
    },
    {
        "version": "3.3.0",
        "name": "DevOps & Platform",
        "date": "2026-03-21",
        "status": ReleaseStatus.PLANNED,
        "highlights": [
            "Blue-green deployments",
            "Canary release support",
            "Auto-rollback on failure",
            "Multi-region deployment",
            "Helm charts for Kubernetes",
        ],
    },
    {
        "version": "3.4.0",
        "name": "Security Hardening",
        "date": "2026-03-28",
        "status": ReleaseStatus.PLANNED,
        "highlights": [
            "SAST/DAST pipeline integration",
            "Secrets scanning with Gitleaks",
            "SBOM generation (CycloneDX)",
            "WAF integration",
            "Zero-trust networking",
            "Penetration testing automation",
        ],
    },
    {
        "version": "3.5.0",
        "name": "Team Collaboration",
        "date": "2026-04-04",
        "status": ReleaseStatus.PLANNED,
        "highlights": [
            "Shared diagram workspaces",
            "Real-time collaboration",
            "Comments and annotations",
            "Version history with diff",
        ],
    },
    {
        "version": "4.0.0",
        "name": "Enterprise Platform",
        "date": "2026-04-30",
        "status": ReleaseStatus.PLANNED,
        "highlights": [
            "Self-hosted deployment option",
            "Multi-tenancy & org hierarchy",
            "Role-based access control",
            "Custom service catalog",
            "API for CI/CD integration",
            "VS Code extension",
            "CLI tool",
        ],
    },
    # ═══════════════════════════════════════════════════════════
    # Future Ideas (Under Consideration)
    # ═══════════════════════════════════════════════════════════
    {
        "version": "Future",
        "name": "AI Architecture Advisor",
        "date": None,
        "status": ReleaseStatus.IDEA,
        "highlights": [
            "AI-driven architecture optimization",
            "Security vulnerability detection",
            "Performance bottleneck analysis",
            "Auto-scaling recommendations",
        ],
    },
    {
        "version": "Future",
        "name": "Native Cloud Integrations",
        "date": None,
        "status": ReleaseStatus.IDEA,
        "highlights": [
            "Direct Azure deployment",
            "AWS CloudFormation import",
            "Kubernetes manifest generation",
            "Pulumi / CDK support",
        ],
    },
]


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
