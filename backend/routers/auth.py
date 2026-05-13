from error_envelope import ArchmorphException
"""
Authentication & User Management routes (v2.9.0).
Social Authentication — Microsoft, Google, GitHub (Issue #246).
"""

from fastapi import APIRouter, Request, Response, Header, Query
from pydantic import Field, EmailStr
from strict_models import StrictBaseModel
from typing import Optional

from routers.shared import limiter
from csrf import generate_csrf_token, set_csrf_cookie
from auth import (
    get_auth_config as _get_auth_config,
    validate_azure_ad_b2c_token,
    exchange_github_code,
    generate_session_token,
    generate_refresh_token,
    get_user_from_session,
    get_user_from_request_headers,
    parse_swa_client_principal,
    request_has_untrusted_swa_principal,
    refresh_session,
    invalidate_session,
    capture_lead,
)

router = APIRouter()


class LoginRequest(StrictBaseModel):
    provider: str = Field(..., description="azure_ad_b2c or github")
    token: Optional[str] = None
    code: Optional[str] = None


class LeadCaptureRequest(StrictBaseModel):
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
    """Login with Azure AD B2C, GitHub OAuth, or SWA provider."""
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
        elif body.provider == "swa":
            # Login via Azure SWA — client principal is in the header
            swa_header = request.headers.get("x-ms-client-principal")
            if not swa_header:
                raise ArchmorphException(400, "Missing x-ms-client-principal header for SWA login")
            if request_has_untrusted_swa_principal(request.headers):
                raise ArchmorphException(
                    401,
                    "SWA principal auth is disabled on this deployment. Use the standard sign-in flow through the trusted frontend.",
                )
            user = parse_swa_client_principal(swa_header)
            if not user:
                raise ArchmorphException(401, "Invalid SWA client principal")
        else:
            raise ArchmorphException(400, f"Unknown provider: {body.provider}")
        
        session_token = generate_session_token(user)
        refresh_token = generate_refresh_token(user)
        
        return {
            "user": user.to_dict(),
            "session_token": session_token,
            "refresh_token": refresh_token,
        }
    except ValueError as e:
        raise ArchmorphException(401, str(e))


@router.get("/api/auth/me")
@limiter.limit("30/minute")
async def get_current_user(request: Request, authorization: Optional[str] = Header(None)):
    """Get current authenticated user (SWA header or Bearer JWT)."""
    # Try SWA + Bearer via unified helper
    user = get_user_from_request_headers(dict(request.headers))
    if user:
        user_dict = user.to_dict()
        # If we came through a Bearer token, echo it back
        if authorization and authorization.startswith("Bearer "):
            user_dict["session_token"] = authorization[7:]
        return user_dict

    # Return anonymous user info
    return {"authenticated": False, "tier": "free", "roles": [], "tenant_id": "default_tenant"}


@router.get("/api/auth/csrf")
async def get_csrf_token(response: Response):
    """Issue a double-submit CSRF token for SWA cookie-auth mutations."""
    token = generate_csrf_token()
    set_csrf_cookie(response, token)
    return {"csrf_token": token}


@router.get("/api/auth/providers")
async def list_providers():
    """List available auth providers and their SWA login URLs."""
    config = _get_auth_config()
    providers = []
    for key, info in config.get("providers", {}).items():
        if key in ("microsoft", "google", "github") and info.get("swa_login_url"):
            providers.append({
                "id": key,
                "name": key.capitalize(),
                "enabled": info.get("enabled", False),
                "login_url": info["swa_login_url"],
            })
    return {"providers": providers, "anonymous_allowed": config.get("anonymous_allowed", True)}


class RefreshRequest(StrictBaseModel):
    refresh_token: str


@router.post("/api/auth/refresh")
@limiter.limit("10/minute")
async def refresh_token_endpoint(request: Request, body: RefreshRequest):
    """Refresh session token using a refresh token."""
    result = refresh_session(body.refresh_token)
    if not result:
        raise ArchmorphException(401, "Invalid or expired refresh token")
    return result


@router.post("/api/auth/logout")
@limiter.limit("10/minute")
async def logout(request: Request, authorization: Optional[str] = Header(None)):
    """Logout — invalidate session token."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        invalidate_session(token)
    return {"success": True}



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
