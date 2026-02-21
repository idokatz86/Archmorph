"""
Archmorph Authentication Module
Azure AD B2C and GitHub OAuth2 Support with Usage Quota Management
"""

import os
import logging
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

import httpx
from jose import jwt, JWTError
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
AZURE_AD_B2C_TENANT = os.getenv("AZURE_AD_B2C_TENANT", "archmorphb2c")
AZURE_AD_B2C_POLICY = os.getenv("AZURE_AD_B2C_POLICY", "B2C_1_signupsignin")
AZURE_AD_B2C_CLIENT_ID = os.getenv("AZURE_AD_B2C_CLIENT_ID", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

# JWKS cache (refresh every hour)
JWKS_CACHE: TTLCache = TTLCache(maxsize=10, ttl=3600)

# User session cache (5 min TTL for validated tokens)
USER_CACHE: TTLCache = TTLCache(maxsize=1000, ttl=300)


# ─────────────────────────────────────────────────────────────
# Enums and Models
# ─────────────────────────────────────────────────────────────
class AuthProvider(str, Enum):
    AZURE_AD_B2C = "azure_ad_b2c"
    GITHUB = "github"
    ANONYMOUS = "anonymous"


class UserTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass
class UsageQuota:
    """User usage quotas based on tier."""
    analyses_per_month: int = 5
    iac_downloads_per_month: int = 3
    hld_generations_per_month: int = 2
    cost_estimates_per_month: int = 10
    share_links_per_month: int = 3
    
    @classmethod
    def for_tier(cls, tier: UserTier) -> "UsageQuota":
        """Get quota limits for a user tier."""
        if tier == UserTier.FREE:
            return cls(
                analyses_per_month=5,
                iac_downloads_per_month=3,
                hld_generations_per_month=2,
                cost_estimates_per_month=10,
                share_links_per_month=3,
            )
        elif tier == UserTier.PRO:
            return cls(
                analyses_per_month=50,
                iac_downloads_per_month=30,
                hld_generations_per_month=20,
                cost_estimates_per_month=100,
                share_links_per_month=50,
            )
        elif tier == UserTier.ENTERPRISE:
            return cls(
                analyses_per_month=10000,
                iac_downloads_per_month=10000,
                hld_generations_per_month=10000,
                cost_estimates_per_month=10000,
                share_links_per_month=10000,
            )
        else:
            raise ValueError(f"Unknown user tier: {tier}")


@dataclass
class User:
    """Authenticated user with quota tracking."""
    id: str
    email: Optional[str] = None
    name: Optional[str] = None
    provider: AuthProvider = AuthProvider.ANONYMOUS
    tier: UserTier = UserTier.FREE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Usage tracking
    analyses_used: int = 0
    iac_downloads_used: int = 0
    hld_generations_used: int = 0
    cost_estimates_used: int = 0
    share_links_used: int = 0
    usage_reset_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def get_quota(self) -> UsageQuota:
        return UsageQuota.for_tier(self.tier)
    
    def check_quota(self, action: str) -> Dict[str, Any]:
        """Check if user has remaining quota for an action."""
        quota = self.get_quota()
        
        quota_map = {
            "analyze": ("analyses_used", quota.analyses_per_month),
            "iac_download": ("iac_downloads_used", quota.iac_downloads_per_month),
            "hld_generation": ("hld_generations_used", quota.hld_generations_per_month),
            "cost_estimate": ("cost_estimates_used", quota.cost_estimates_per_month),
            "share_link": ("share_links_used", quota.share_links_per_month),
        }
        
        if action not in quota_map:
            return {"allowed": True, "message": "No quota limit for this action"}
        
        field_name, limit = quota_map[action]
        used = getattr(self, field_name)
        remaining = max(0, limit - used)
        
        return {
            "allowed": remaining > 0,
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "message": f"{remaining} of {limit} {action.replace('_', ' ')}s remaining this month",
            "upgrade_prompt": remaining <= 1 and self.tier == UserTier.FREE,
        }
    
    def increment_usage(self, action: str) -> bool:
        """Increment usage counter for an action. Returns True if successful."""
        quota_check = self.check_quota(action)
        if not quota_check["allowed"]:
            return False
        
        field_map = {
            "analyze": "analyses_used",
            "iac_download": "iac_downloads_used",
            "hld_generation": "hld_generations_used",
            "cost_estimate": "cost_estimates_used",
            "share_link": "share_links_used",
        }
        
        if action in field_map:
            setattr(self, field_map[action], getattr(self, field_map[action]) + 1)
            return True
        return True
    
    def reset_monthly_usage(self):
        """Reset usage counters for a new month."""
        self.analyses_used = 0
        self.iac_downloads_used = 0
        self.hld_generations_used = 0
        self.cost_estimates_used = 0
        self.share_links_used = 0
        self.usage_reset_date = datetime.now(timezone.utc)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize user to dictionary."""
        quota = self.get_quota()
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "provider": self.provider.value,
            "tier": self.tier.value,
            "created_at": self.created_at.isoformat(),
            "usage": {
                "analyses": {"used": self.analyses_used, "limit": quota.analyses_per_month},
                "iac_downloads": {"used": self.iac_downloads_used, "limit": quota.iac_downloads_per_month},
                "hld_generations": {"used": self.hld_generations_used, "limit": quota.hld_generations_per_month},
                "cost_estimates": {"used": self.cost_estimates_used, "limit": quota.cost_estimates_per_month},
                "share_links": {"used": self.share_links_used, "limit": quota.share_links_per_month},
            },
            "usage_reset_date": self.usage_reset_date.isoformat(),
        }


# In-memory user store (replace with database in production)
USER_STORE: Dict[str, User] = {}

# Anonymous session tracking (IP-based for unauthenticated users)
ANONYMOUS_USAGE: TTLCache = TTLCache(maxsize=10000, ttl=86400 * 30)  # 30 days


# ─────────────────────────────────────────────────────────────
# JWKS & Token Validation
# ─────────────────────────────────────────────────────────────
async def get_azure_ad_b2c_jwks() -> Dict[str, Any]:
    """Fetch Azure AD B2C JWKS for token validation."""
    cache_key = f"azure_b2c_{AZURE_AD_B2C_TENANT}_{AZURE_AD_B2C_POLICY}"
    
    if cache_key in JWKS_CACHE:
        return JWKS_CACHE[cache_key]
    
    openid_config_url = (
        f"https://{AZURE_AD_B2C_TENANT}.b2clogin.com/"
        f"{AZURE_AD_B2C_TENANT}.onmicrosoft.com/{AZURE_AD_B2C_POLICY}/v2.0/.well-known/openid-configuration"
    )
    
    try:
        async with httpx.AsyncClient() as client:
            config_resp = await client.get(openid_config_url, timeout=10)
            config_resp.raise_for_status()
            config = config_resp.json()
            
            jwks_resp = await client.get(config["jwks_uri"], timeout=10)
            jwks_resp.raise_for_status()
            jwks = jwks_resp.json()
            
            JWKS_CACHE[cache_key] = jwks
            return jwks
    except Exception as exc:
        logger.error("Failed to fetch Azure AD B2C JWKS: %s", exc)
        raise ValueError("Unable to validate token: JWKS fetch failed")


async def validate_azure_ad_b2c_token(token: str) -> User:
    """Validate Azure AD B2C JWT token and return user."""
    if not AZURE_AD_B2C_CLIENT_ID:
        raise ValueError("Azure AD B2C not configured")
    
    try:
        # Get JWKS
        jwks = await get_azure_ad_b2c_jwks()
        
        # Decode header to find key
        unverified_header = jwt.get_unverified_header(token)
        
        # Find matching key
        rsa_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == unverified_header.get("kid"):
                rsa_key = key
                break
        
        if not rsa_key:
            raise ValueError("Unable to find matching key in JWKS")
        
        # Validate token
        issuer = f"https://{AZURE_AD_B2C_TENANT}.b2clogin.com/{AZURE_AD_B2C_TENANT}.onmicrosoft.com/{AZURE_AD_B2C_POLICY}/v2.0/"
        
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=AZURE_AD_B2C_CLIENT_ID,
            issuer=issuer,
        )
        
        # Extract user info
        user_id = payload.get("sub", payload.get("oid", ""))
        email = payload.get("emails", [None])[0] or payload.get("email")
        name = payload.get("name", payload.get("given_name", ""))
        
        # Get or create user
        if user_id in USER_STORE:
            user = USER_STORE[user_id]
        else:
            user = User(
                id=user_id,
                email=email,
                name=name,
                provider=AuthProvider.AZURE_AD_B2C,
            )
            USER_STORE[user_id] = user
        
        # Check and reset monthly usage if needed
        now = datetime.now(timezone.utc)
        if (now - user.usage_reset_date).days >= 30:
            user.reset_monthly_usage()
        
        return user
        
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise ValueError(f"Invalid token: {exc}")


async def exchange_github_code(code: str) -> User:
    """Exchange GitHub OAuth code for access token and get user."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise ValueError("GitHub OAuth not configured")
    
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for token
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": code,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            
            if "error" in token_data:
                raise ValueError(f"GitHub OAuth error: {token_data['error_description']}")
            
            access_token = token_data["access_token"]
            
            # Get user info
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            user_resp.raise_for_status()
            github_user = user_resp.json()
            
            # Get email if not public
            email = github_user.get("email")
            if not email:
                email_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    timeout=10,
                )
                if email_resp.status_code == 200:
                    emails = email_resp.json()
                    primary = next((e for e in emails if e.get("primary")), None)
                    if primary:
                        email = primary["email"]
            
            user_id = f"github_{github_user['id']}"
            
            if user_id in USER_STORE:
                user = USER_STORE[user_id]
            else:
                user = User(
                    id=user_id,
                    email=email,
                    name=github_user.get("name", github_user["login"]),
                    provider=AuthProvider.GITHUB,
                )
                USER_STORE[user_id] = user
            
            # Reset monthly usage if needed
            now = datetime.now(timezone.utc)
            if (now - user.usage_reset_date).days >= 30:
                user.reset_monthly_usage()
            
            return user
            
    except httpx.HTTPError as exc:
        logger.error("GitHub OAuth failed: %s", exc)
        raise ValueError(f"GitHub OAuth failed: {exc}")


def get_anonymous_user(client_ip: str) -> User:
    """Get or create anonymous user based on client IP."""
    # Hash IP for privacy
    ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]
    user_id = f"anon_{ip_hash}"
    
    if user_id in ANONYMOUS_USAGE:
        return ANONYMOUS_USAGE[user_id]
    
    user = User(
        id=user_id,
        provider=AuthProvider.ANONYMOUS,
        tier=UserTier.FREE,
    )
    ANONYMOUS_USAGE[user_id] = user
    return user


def generate_session_token(user: User) -> str:
    """Generate a session token for an authenticated user."""
    token = secrets.token_urlsafe(32)
    USER_CACHE[token] = user
    return token


def get_user_from_session(token: str) -> Optional[User]:
    """Get user from session token."""
    return USER_CACHE.get(token)


# ─────────────────────────────────────────────────────────────
# Email Capture for Lead Generation
# ─────────────────────────────────────────────────────────────
@dataclass
class LeadCapture:
    """Captured lead information."""
    email: str
    diagram_id: str
    action: str  # "iac_download", "hld_download", "share"
    company: Optional[str] = None
    role: Optional[str] = None
    use_case: Optional[str] = None
    marketing_consent: bool = False
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "diagram_id": self.diagram_id,
            "action": self.action,
            "company": self.company,
            "role": self.role,
            "use_case": self.use_case,
            "marketing_consent": self.marketing_consent,
            "captured_at": self.captured_at.isoformat(),
        }


# Lead storage (replace with database in production)
LEAD_STORE: list[LeadCapture] = []


def capture_lead(
    email: str,
    diagram_id: str,
    action: str,
    company: Optional[str] = None,
    role: Optional[str] = None,
    use_case: Optional[str] = None,
    marketing_consent: bool = False,
) -> LeadCapture:
    """Capture lead information before gated action."""
    lead = LeadCapture(
        email=email,
        diagram_id=diagram_id,
        action=action,
        company=company,
        role=role,
        use_case=use_case,
        marketing_consent=marketing_consent,
    )
    LEAD_STORE.append(lead)
    logger.info("Lead captured: %s for action %s", email, action)
    return lead


def get_leads_summary() -> Dict[str, Any]:
    """Get summary of captured leads."""
    return {
        "total_leads": len(LEAD_STORE),
        "by_action": {
            action: len([lead for lead in LEAD_STORE if lead.action == action])
            for action in ["iac_download", "hld_download", "share"]
        },
        "with_marketing_consent": len([lead for lead in LEAD_STORE if lead.marketing_consent]),
        "recent": [lead.to_dict() for lead in sorted(LEAD_STORE, key=lambda x: x.captured_at, reverse=True)[:10]],
    }


# ─────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────
def is_auth_enabled() -> bool:
    """Check if any authentication provider is configured."""
    return bool(AZURE_AD_B2C_CLIENT_ID or GITHUB_CLIENT_ID)


def get_auth_config() -> Dict[str, Any]:
    """Get public authentication configuration."""
    return {
        "auth_enabled": is_auth_enabled(),
        "providers": {
            "azure_ad_b2c": {
                "enabled": bool(AZURE_AD_B2C_CLIENT_ID),
                "tenant": AZURE_AD_B2C_TENANT if AZURE_AD_B2C_CLIENT_ID else None,
                "policy": AZURE_AD_B2C_POLICY if AZURE_AD_B2C_CLIENT_ID else None,
                "client_id": AZURE_AD_B2C_CLIENT_ID or None,
            },
            "github": {
                "enabled": bool(GITHUB_CLIENT_ID),
                "client_id": GITHUB_CLIENT_ID or None,
            },
        },
        "anonymous_allowed": True,
        "free_tier_limits": UsageQuota.for_tier(UserTier.FREE).__dict__,
    }
