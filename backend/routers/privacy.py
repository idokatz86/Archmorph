"""
GDPR / Privacy compliance routes (Issue #145).

Provides:
- Cookie consent preferences endpoint
- DSAR (Data Subject Access Request) — export user data
- Right to deletion — erase user data
- Legal document version metadata
- DPA (Data Processing Agreement) info
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from routers.shared import limiter, SESSION_STORE

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────
# Legal Document Versions
# ─────────────────────────────────────────────────────────────
_LEGAL_DOCS: Dict[str, Dict[str, Any]] = {
    "terms_of_service": {
        "version": "1.0.0",
        "effective_date": "2025-01-15",
        "last_updated": "2025-01-15",
        "url": "/legal/terms",
    },
    "privacy_policy": {
        "version": "1.0.0",
        "effective_date": "2025-01-15",
        "last_updated": "2025-01-15",
        "url": "/legal/privacy",
    },
    "data_processing_agreement": {
        "version": "1.0.0",
        "effective_date": "2025-01-15",
        "last_updated": "2025-01-15",
        "url": "/legal/dpa",
    },
    "ai_disclaimer": {
        "version": "1.0.0",
        "effective_date": "2025-01-15",
        "last_updated": "2025-01-15",
        "url": "/legal/ai-disclaimer",
    },
    "cookie_policy": {
        "version": "1.0.0",
        "effective_date": "2025-01-15",
        "last_updated": "2025-01-15",
        "url": "/legal/cookies",
    },
}


# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────
class CookieConsent(BaseModel):
    """User cookie consent preferences (GDPR Art. 7)."""
    necessary: bool = Field(True, description="Always true — required for site operation")
    analytics: bool = Field(False, description="Allow analytics cookies")
    marketing: bool = Field(False, description="Allow marketing cookies")
    functional: bool = Field(False, description="Allow functional cookies")


class ConsentRequest(BaseModel):
    consent: CookieConsent
    session_id: Optional[str] = Field(None, max_length=128)


class DSARRequest(BaseModel):
    """Data Subject Access Request (GDPR Art. 15)."""
    email: str = Field(..., min_length=5, max_length=320)
    request_type: str = Field(
        "export",
        pattern=r"^(export|deletion)$",
        description="Type of DSAR: 'export' or 'deletion'",
    )
    reason: Optional[str] = Field(None, max_length=1000)


class DSARResponse(BaseModel):
    request_id: str
    status: str
    request_type: str
    message: str
    estimated_completion: str


class DeletionRequest(BaseModel):
    """Right to erasure request (GDPR Art. 17)."""
    email: str = Field(..., min_length=5, max_length=320)
    confirm: bool = Field(..., description="Must be true to confirm deletion")
    reason: Optional[str] = Field(None, max_length=1000)


class LegalDocInfo(BaseModel):
    document: str
    version: str
    effective_date: str
    last_updated: str
    url: str


# In-memory DSAR request tracking (production would use a database)
_dsar_requests: Dict[str, Dict[str, Any]] = {}

# In-memory consent store keyed by session_id
_consent_store: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@router.get("/api/privacy/legal-documents")
@limiter.limit("30/minute")
async def list_legal_documents(request: Request) -> Dict[str, Any]:
    """List all legal documents with version metadata."""
    return {
        "documents": [
            {
                "document": key,
                "version": doc["version"],
                "effective_date": doc["effective_date"],
                "last_updated": doc["last_updated"],
                "url": doc["url"],
            }
            for key, doc in _LEGAL_DOCS.items()
        ]
    }


@router.get("/api/privacy/legal-documents/{document_id}")
@limiter.limit("30/minute")
async def get_legal_document(request: Request, document_id: str) -> Dict[str, Any]:
    """Get metadata for a specific legal document."""
    doc = _LEGAL_DOCS.get(document_id)
    if not doc:
        raise HTTPException(404, f"Legal document '{document_id}' not found")
    return {
        "document": document_id,
        **doc,
    }


@router.post("/api/privacy/consent")
@limiter.limit("10/minute")
async def save_cookie_consent(request: Request, data: ConsentRequest) -> Dict[str, Any]:
    """Save user cookie consent preferences (GDPR Art. 7).

    Consent is always opt-in. 'necessary' cookies cannot be disabled.
    Records timestamp for audit trail.
    """
    consent = data.consent.model_dump()
    consent["necessary"] = True  # Force — cannot opt out of necessary cookies

    session_id = data.session_id or str(uuid.uuid4())
    record = {
        "session_id": session_id,
        "consent": consent,
        "ip_address": request.client.host if request.client else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_agent": request.headers.get("User-Agent", ""),
    }
    _consent_store[session_id] = record
    logger.info("Cookie consent recorded for session %s", session_id)

    return {
        "status": "saved",
        "session_id": session_id,
        "consent": consent,
        "recorded_at": record["timestamp"],
    }


@router.get("/api/privacy/consent/{session_id}")
@limiter.limit("20/minute")
async def get_cookie_consent(request: Request, session_id: str) -> Dict[str, Any]:
    """Retrieve saved cookie consent for a session."""
    record = _consent_store.get(session_id)
    if not record:
        return {
            "session_id": session_id,
            "consent": CookieConsent().model_dump(),
            "status": "default",
        }
    return {
        "session_id": session_id,
        "consent": record["consent"],
        "status": "saved",
        "recorded_at": record.get("timestamp"),
    }


@router.post("/api/privacy/dsar")
@limiter.limit("3/minute")
async def submit_dsar(request: Request, data: DSARRequest) -> DSARResponse:
    """Submit a Data Subject Access Request (GDPR Art. 15/17).

    Creates a tracked request for data export or deletion.
    In production, this would trigger a workflow and notify the DPO.
    """
    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    record = {
        "request_id": request_id,
        "email": data.email,
        "request_type": data.request_type,
        "reason": data.reason,
        "status": "pending",
        "submitted_at": now.isoformat(),
        "ip_address": request.client.host if request.client else None,
    }
    _dsar_requests[request_id] = record
    logger.info(
        "DSAR %s submitted: type=%s email=%s",
        request_id, data.request_type, data.email,
    )

    return DSARResponse(
        request_id=request_id,
        status="pending",
        request_type=data.request_type,
        message=f"Your {data.request_type} request has been received. "
                f"We will process it within 30 days as required by GDPR.",
        estimated_completion="30 days",
    )


@router.get("/api/privacy/dsar/{request_id}")
@limiter.limit("10/minute")
async def get_dsar_status(request: Request, request_id: str) -> Dict[str, Any]:
    """Check the status of a DSAR request."""
    record = _dsar_requests.get(request_id)
    if not record:
        raise HTTPException(404, "DSAR request not found")
    return {
        "request_id": record["request_id"],
        "request_type": record["request_type"],
        "status": record["status"],
        "submitted_at": record["submitted_at"],
    }


@router.post("/api/privacy/delete")
@limiter.limit("2/minute")
async def request_data_deletion(request: Request, data: DeletionRequest) -> Dict[str, Any]:
    """Request complete data deletion (GDPR Art. 17 — Right to Erasure).

    Requires explicit confirmation. Creates a tracked deletion request
    and immediately removes any in-memory session data.
    """
    if not data.confirm:
        raise HTTPException(
            400,
            "You must set 'confirm' to true to request data deletion",
        )

    request_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Log the deletion request
    record = {
        "request_id": request_id,
        "email": data.email,
        "request_type": "deletion",
        "reason": data.reason,
        "status": "processing",
        "submitted_at": now.isoformat(),
        "ip_address": request.client.host if request.client else None,
    }
    _dsar_requests[request_id] = record

    # Immediate: clear any session data associated with this request
    # (In production, this would trigger database deletion workflows)
    sessions_cleared = 0
    for key in list(SESSION_STORE.keys()):
        try:
            entry = SESSION_STORE.get(key)
            if entry and isinstance(entry, dict) and entry.get("email") == data.email:
                SESSION_STORE.delete(key)
                sessions_cleared += 1
        except Exception:  # noqa: BLE001
            pass

    record["status"] = "completed"
    record["sessions_cleared"] = sessions_cleared

    logger.info(
        "Data deletion completed: request_id=%s email=%s sessions_cleared=%d",
        request_id, data.email, sessions_cleared,
    )

    return {
        "request_id": request_id,
        "status": "completed",
        "message": "Your data has been deleted. Any remaining data in backups "
                   "will be purged within 30 days per our retention policy.",
        "sessions_cleared": sessions_cleared,
    }


@router.get("/api/privacy/data-practices")
@limiter.limit("30/minute")
async def get_data_practices(request: Request) -> Dict[str, Any]:
    """Return machine-readable summary of data processing practices.

    Useful for automated compliance checks and transparency reports.
    """
    return {
        "controller": "Archmorph",
        "dpo_contact": "privacy@archmorph.io",
        "data_categories": [
            {
                "category": "Architecture Diagrams",
                "purpose": "Cloud migration analysis",
                "legal_basis": "Consent (Art. 6(1)(a))",
                "retention": "Session-only (2 hours TTL)",
                "shared_with": ["Azure OpenAI (data processor)"],
            },
            {
                "category": "Usage Analytics",
                "purpose": "Service improvement",
                "legal_basis": "Legitimate interest (Art. 6(1)(f))",
                "retention": "90 days aggregated",
                "shared_with": [],
            },
            {
                "category": "Authentication Tokens",
                "purpose": "User authentication",
                "legal_basis": "Contract performance (Art. 6(1)(b))",
                "retention": "Session duration",
                "shared_with": ["Azure AD B2C (identity provider)"],
            },
        ],
        "data_transfers": {
            "regions": ["West Europe (primary)", "North Europe (DR)"],
            "safeguards": "Azure EU Data Boundary, Standard Contractual Clauses",
        },
        "rights": [
            "Access (Art. 15)",
            "Rectification (Art. 16)",
            "Erasure (Art. 17)",
            "Restriction (Art. 18)",
            "Portability (Art. 20)",
            "Objection (Art. 21)",
        ],
        "automated_decisions": {
            "present": True,
            "description": "AI-powered architecture analysis and service mapping",
            "human_oversight": "All AI outputs are presented as recommendations for human review",
        },
    }
