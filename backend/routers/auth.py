from error_envelope import ArchmorphException
"""
Authentication & User Management routes (v2.9.0).
"""

from fastapi import APIRouter, HTTPException, Request, Header, Query
from pydantic import BaseModel, Field, EmailStr
from typing import Optional

from routers.shared import limiter
from auth import (
    get_auth_config as _get_auth_config,
    validate_azure_ad_b2c_token,
    exchange_github_code,
    generate_session_token,
    get_user_from_session,
    capture_lead,
)

router = APIRouter()


class LoginRequest(BaseModel):
    provider: str = Field(..., description="azure_ad_b2c or github")
    token: Optional[str] = None
    code: Optional[str] = None


class LeadCaptureRequest(BaseModel):
    email: EmailStr
    diagram_id: str
    action: str = Field(..., description="iac_download, hld_download, or share")
    company: Optional[str] = None
    role: Optional[str] = None
    use_case: Optional[str] = None
    marketing_consent: bool = False


@router.get("/api/auth/config")
async def get_auth_config():
    """Get public authentication configuration."""
    return _get_auth_config()


@router.post("/api/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    """Login with Azure AD B2C or GitHub OAuth."""
    try:
        if body.provider == "azure_ad_b2c":
            if not body.token:
                raise ArchmorphException(400, "Token required for Azure AD B2C")
            user = await validate_azure_ad_b2c_token(body.token)
        elif body.provider == "github":
            if not body.code:
                raise ArchmorphException(400, "Code required for GitHub OAuth")
            user = await exchange_github_code(body.code)
        elif body.provider == "anonymous":
            from auth import get_anonymous_user
            client_ip = request.client.host if request.client else "127.0.0.1"
            user = get_anonymous_user(client_ip)
        else:
            raise ArchmorphException(400, f"Unknown provider: {body.provider}")
        
        session_token = generate_session_token(user)
        
        return {
            "user": user.to_dict(),
            "session_token": session_token,
        }
    except ValueError as e:
        raise ArchmorphException(401, str(e))


@router.get("/api/auth/me")
@limiter.limit("30/minute")
async def get_current_user(request: Request, authorization: Optional[str] = Header(None)):
    """Get current authenticated user."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        user = get_user_from_session(token)
        if user:
            user_dict = user.to_dict()
            user_dict["session_token"] = token
            return user_dict
    

    # Return anonymous user info
    return {"authenticated": False, "tier": "free", "roles": [], "tenant_id": "default_tenant"}



@router.get("/api/auth/quota")
@limiter.limit("30/minute")
async def check_quota(request: Request, action: str = Query(...), authorization: Optional[str] = Header(None)):
    """Check user quota for an action."""
    user = None
    if authorization and authorization.startswith("Bearer "):
        user = get_user_from_session(authorization[7:])

    if not user:
        # Return minimal info for unauthenticated users (Issue #142 — no internal details)
        return {
            "allowed": True,
            "message": "Login for detailed quota information",
            "authenticated": False,
        }

    return user.check_quota(action)


@router.post("/api/leads/capture")
@limiter.limit("10/minute")
async def capture_lead_endpoint(request: Request, data: LeadCaptureRequest):
    """Capture lead information before gated action."""
    lead = capture_lead(
        email=data.email,
        diagram_id=data.diagram_id,
        action=data.action,
        company=data.company,
        role=data.role,
        use_case=data.use_case,
        marketing_consent=data.marketing_consent,
    )
    
    return {"success": True, "captured_at": lead.captured_at.isoformat()}
