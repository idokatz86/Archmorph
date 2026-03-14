from error_envelope import ArchmorphException
"""Legal & Compliance routes (Issue #108).

Provides:
- Terms of Service
- Privacy Policy
- AI Usage Disclaimer
- Data Processing Agreement (DPA)
- Cookie consent management
- Data deletion requests (GDPR Art.17)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from routers.shared import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────────────────
# Legal document versions
# ─────────────────────────────────────────────────────────
LEGAL_VERSION = "1.0.0"
LEGAL_EFFECTIVE_DATE = "2025-01-15"
COMPANY_NAME = os.getenv("COMPANY_NAME", "Archmorph Ltd.")
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "legal@archmorph.dev")
DPO_EMAIL = os.getenv("DPO_EMAIL", "dpo@archmorph.dev")


# ─────────────────────────────────────────────────────────
# Terms of Service
# ─────────────────────────────────────────────────────────
TERMS_OF_SERVICE = {
    "version": LEGAL_VERSION,
    "effective_date": LEGAL_EFFECTIVE_DATE,
    "title": "Archmorph Terms of Service",
    "sections": [
        {
            "id": "acceptance",
            "title": "1. Acceptance of Terms",
            "content": (
                "By accessing or using the Archmorph platform ('Service'), you agree to be bound by these "
                "Terms of Service. If you do not agree, do not use the Service."
            ),
        },
        {
            "id": "description",
            "title": "2. Service Description",
            "content": (
                "Archmorph is an AI-powered cloud architecture translation platform that analyzes infrastructure "
                "diagrams and source cloud configurations (AWS, GCP) and generates equivalent Azure architecture "
                "proposals, Infrastructure as Code (IaC), and High-Level Design documents."
            ),
        },
        {
            "id": "user_obligations",
            "title": "3. User Obligations",
            "content": (
                "You agree to: (a) provide accurate information; (b) maintain the security of your account; "
                "(c) not upload malicious content or infrastructure containing sensitive credentials; "
                "(d) comply with all applicable laws and regulations; (e) not reverse-engineer the Service."
            ),
        },
        {
            "id": "ip_ownership",
            "title": "4. Intellectual Property",
            "content": (
                "You retain ownership of any diagrams, configurations, or data you upload. Archmorph retains "
                "ownership of the Service, AI models, and generated mapping data. Generated IaC and HLD outputs "
                "are licensed to you for use in your projects."
            ),
        },
        {
            "id": "ai_disclaimer",
            "title": "5. AI-Generated Content Disclaimer",
            "content": (
                "The Service uses AI (Azure OpenAI GPT-4o) to generate architecture translations, IaC code, and "
                "recommendations. AI outputs are provided 'as-is' and may contain errors, omissions, or "
                "suboptimal configurations. You are solely responsible for reviewing, testing, and validating "
                "all AI-generated outputs before deploying to production environments."
            ),
        },
        {
            "id": "liability",
            "title": "6. Limitation of Liability",
            "content": (
                "TO THE MAXIMUM EXTENT PERMITTED BY LAW, ARCHMORPH SHALL NOT BE LIABLE FOR ANY INDIRECT, "
                "INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS "
                "OF DATA, BUSINESS INTERRUPTION, OR INFRASTRUCTURE FAILURES ARISING FROM USE OF AI-GENERATED "
                "OUTPUTS, REGARDLESS OF WHETHER ADVISED OF THE POSSIBILITY OF SUCH DAMAGES."
            ),
        },
        {
            "id": "subscription",
            "title": "7. Subscription & Billing",
            "content": (
                "Paid plans are billed monthly or annually. You may cancel at any time; access continues until "
                "the end of your billing period. Refunds are not provided for partial periods. Usage quotas "
                "reset at the start of each billing cycle."
            ),
        },
        {
            "id": "termination",
            "title": "8. Termination",
            "content": (
                "We reserve the right to suspend or terminate accounts that violate these terms, engage in "
                "abuse, or exceed rate limits. Upon termination, your data will be retained for 30 days "
                "before permanent deletion, unless required by law."
            ),
        },
        {
            "id": "governing_law",
            "title": "9. Governing Law",
            "content": (
                "These terms are governed by the laws of the State of Israel. Any disputes shall be resolved "
                "in the competent courts of Tel Aviv, Israel."
            ),
        },
    ],
}


# ─────────────────────────────────────────────────────────
# Privacy Policy
# ─────────────────────────────────────────────────────────
PRIVACY_POLICY = {
    "version": LEGAL_VERSION,
    "effective_date": LEGAL_EFFECTIVE_DATE,
    "title": "Archmorph Privacy Policy",
    "dpo_contact": DPO_EMAIL,
    "sections": [
        {
            "id": "data_collected",
            "title": "1. Data We Collect",
            "content": (
                "We collect: (a) Account data (email, name, organization); (b) Usage data (feature usage, "
                "session analytics); (c) Uploaded diagrams and infrastructure configurations; (d) AI interaction "
                "logs (prompts and responses, without PII); (e) Technical data (IP address, browser, device)."
            ),
        },
        {
            "id": "data_processing",
            "title": "2. How We Process Data",
            "content": (
                "Uploaded diagrams are processed by Azure OpenAI (GPT-4o) for analysis. Diagrams are NOT "
                "stored permanently — they exist in-memory during the analysis session and are cleared after "
                "session expiry (default: 1 hour). Generated outputs (IaC, HLD) are stored temporarily for "
                "download and then purged."
            ),
        },
        {
            "id": "data_storage",
            "title": "3. Data Storage & Security",
            "content": (
                "Data is stored in Azure West Europe (Netherlands) region. All data is encrypted at rest "
                "(AES-256) and in transit (TLS 1.2+). Database connections use SSL. Access is controlled via "
                "Azure AD RBAC and managed identities."
            ),
        },
        {
            "id": "third_parties",
            "title": "4. Third-Party Services",
            "content": (
                "We use: Azure OpenAI (AI processing), Azure Blob Storage (file storage), Stripe (payment "
                "processing), Application Insights (monitoring). Each operates under their own privacy policy "
                "and data processing agreements."
            ),
        },
        {
            "id": "retention",
            "title": "5. Data Retention",
            "content": (
                "Session data: cleared after 1 hour of inactivity. Account data: retained while account is "
                "active. Usage analytics: retained for 90 days (aggregated). Audit logs: retained for 1 year "
                "(compliance). Upon account deletion, all personal data is purged within 30 days."
            ),
        },
        {
            "id": "gdpr_rights",
            "title": "6. Your Rights (GDPR)",
            "content": (
                "Under GDPR, you have the right to: (a) Access your data; (b) Rectify inaccurate data; "
                "(c) Erase your data (right to be forgotten); (d) Restrict processing; (e) Data portability; "
                "(f) Object to processing; (g) Withdraw consent. Contact our DPO at " + DPO_EMAIL + "."
            ),
        },
        {
            "id": "cookies",
            "title": "7. Cookies",
            "content": (
                "We use strictly necessary cookies for authentication and session management. Analytics cookies "
                "(Application Insights) are optional and require your consent. You can manage cookie preferences "
                "at any time through the cookie consent banner."
            ),
        },
    ],
}


# ─────────────────────────────────────────────────────────
# Cookie categories
# ─────────────────────────────────────────────────────────
COOKIE_CATEGORIES = [
    {
        "id": "necessary",
        "name": "Strictly Necessary",
        "description": "Required for authentication, session management, and security. Cannot be disabled.",
        "required": True,
        "cookies": ["session_id", "csrf_token", "auth_token"],
    },
    {
        "id": "analytics",
        "name": "Analytics",
        "description": "Help us understand how the platform is used via Application Insights.",
        "required": False,
        "cookies": ["ai_session", "ai_user"],
    },
    {
        "id": "preferences",
        "name": "Preferences",
        "description": "Remember your settings like theme, language, and layout preferences.",
        "required": False,
        "cookies": ["theme", "language", "sidebar_state"],
    },
]

# In-memory consent store
_consent_store: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────
# Data deletion request store
# ─────────────────────────────────────────────────────────
_deletion_requests: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────
class CookieConsentRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    analytics: bool = False
    preferences: bool = False


class DataDeletionRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    email: str = Field(..., min_length=5)
    reason: Optional[str] = None


# ─────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────
@router.get("/api/legal/terms", tags=["legal"])
@limiter.limit("30/minute")
async def get_terms(request: Request):
    """Return Terms of Service."""
    return TERMS_OF_SERVICE


@router.get("/api/legal/privacy", tags=["legal"])
@limiter.limit("30/minute")
async def get_privacy(request: Request):
    """Return Privacy Policy."""
    return PRIVACY_POLICY


@router.get("/api/legal/ai-disclaimer", tags=["legal"])
@limiter.limit("30/minute")
async def get_ai_disclaimer(request: Request):
    """Return AI usage disclaimer."""
    return {
        "version": LEGAL_VERSION,
        "title": "AI-Generated Content Disclaimer",
        "content": TERMS_OF_SERVICE["sections"][4]["content"],
        "key_points": [
            "AI outputs are generated by Azure OpenAI GPT-4o",
            "Outputs may contain errors, omissions, or suboptimal configurations",
            "You are responsible for reviewing and testing all generated code",
            "Never deploy AI-generated IaC to production without human review",
            "Confidence scores indicate mapping certainty, not deployment readiness",
            "Cost estimates are approximate and may differ from actual Azure pricing",
        ],
    }


@router.get("/api/legal/cookies", tags=["legal"])
@limiter.limit("30/minute")
async def get_cookie_policy(request: Request):
    """Return cookie categories and current consent status."""
    return {"categories": COOKIE_CATEGORIES}


@router.post("/api/legal/cookies/consent", tags=["legal"])
@limiter.limit("10/minute")
async def save_cookie_consent(request: Request, body: CookieConsentRequest):
    """Save user cookie consent preferences."""
    _consent_store[body.user_id] = {
        "necessary": True,  # Always required
        "analytics": body.analytics,
        "preferences": body.preferences,
        "consented_at": datetime.now(timezone.utc).isoformat(),
        "ip": request.client.host if request.client else "unknown",
    }
    return {"status": "saved", "consent": _consent_store[body.user_id]}


@router.get("/api/legal/cookies/consent/{user_id}", tags=["legal"])
@limiter.limit("30/minute")
async def get_cookie_consent(request: Request, user_id: str):
    """Get user's current cookie consent preferences."""
    consent = _consent_store.get(user_id)
    if not consent:
        return {"status": "no_consent", "consent": None}
    return {"status": "found", "consent": consent}


@router.post("/api/legal/data-deletion", tags=["legal"])
@limiter.limit("5/minute")
async def request_data_deletion(request: Request, body: DataDeletionRequest):
    """Request account and data deletion (GDPR Art. 17)."""
    import uuid

    request_id = str(uuid.uuid4())
    _deletion_requests[request_id] = {
        "request_id": request_id,
        "user_id": body.user_id,
        "email": body.email,
        "reason": body.reason,
        "status": "pending",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "estimated_completion": "30 days",
    }

    logger.info("Data deletion requested: %s for user %s", str(request_id).replace('\n', '').replace('\r', ''), str(body.user_id).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    return {
        "status": "accepted",
        "request_id": request_id,
        "message": "Your data deletion request has been received. "
                   "All personal data will be erased within 30 days. "
                   f"Contact {DPO_EMAIL} for questions.",
    }


@router.get("/api/legal/data-deletion/{request_id}", tags=["legal"])
@limiter.limit("10/minute")
async def get_deletion_status(request: Request, request_id: str):
    """Check status of a data deletion request."""
    req = _deletion_requests.get(request_id)
    if not req:
        raise ArchmorphException(status_code=404, detail="Deletion request not found")
    return req
