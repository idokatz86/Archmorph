"""
Archmorph – White-Label SDK & Partner Branding Engine
=====================================================
Provides a config-driven branding system that allows partners to
customise the Archmorph experience with:

  - Custom product name, tagline, logos
  - Custom colour palettes (primary, secondary, accent)
  - Partner API key management
  - Embeddable widget configuration
  - Per-tenant branding overrides

Partners register via API key and supply a branding config JSON.
All frontend assets read /whitelabel/config/{partner_id} to resolve
the active brand before first render.
"""


from __future__ import annotations

from utils.logger_utils import sanitize_log
from error_envelope import ArchmorphException

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whitelabel", tags=["whitelabel"])


# ─────────────────────────────────────────────────────────────
# In-memory partner + branding store
# (Production: persistent DB table)
# ─────────────────────────────────────────────────────────────
_PARTNERS: Dict[str, Dict[str, Any]] = {}  # api_key -> partner record
_PARTNER_BY_ID: Dict[str, Dict[str, Any]] = {}  # partner_id -> partner record

DEFAULT_BRANDING = {
    "product_name": "Archmorph",
    "tagline": "AI-Powered Cloud Architecture Translation",
    "logo_url": "/assets/archmorph-logo.svg",
    "favicon_url": "/favicon.ico",
    "colors": {
        "primary": "#6366f1",
        "secondary": "#4f46e5",
        "accent": "#a78bfa",
        "background": "#0f172a",
        "surface": "#1e293b",
        "text": "#f8fafc",
        "text_secondary": "#94a3b8",
    },
    "fonts": {
        "heading": "Inter, system-ui, sans-serif",
        "body": "Inter, system-ui, sans-serif",
        "mono": "JetBrains Mono, monospace",
    },
    "features": {
        "show_powered_by": True,
        "show_community_patterns": True,
        "enable_template_gallery": True,
        "enable_iac_generation": True,
        "enable_export": True,
        "max_uploads_per_day": 50,
    },
    "embed": {
        "allowed_origins": ["*"],
        "iframe_resizable": True,
        "default_width": "100%",
        "default_height": "800px",
    },
}


class BrandingColors(BaseModel):
    primary: str = "#6366f1"
    secondary: str = "#4f46e5"
    accent: str = "#a78bfa"
    background: str = "#0f172a"
    surface: str = "#1e293b"
    text: str = "#f8fafc"
    text_secondary: str = "#94a3b8"


class BrandingFonts(BaseModel):
    heading: str = "Inter, system-ui, sans-serif"
    body: str = "Inter, system-ui, sans-serif"
    mono: str = "JetBrains Mono, monospace"


class FeatureFlags(BaseModel):
    show_powered_by: bool = True
    show_community_patterns: bool = True
    enable_template_gallery: bool = True
    enable_iac_generation: bool = True
    enable_export: bool = True
    max_uploads_per_day: int = 50


class EmbedConfig(BaseModel):
    allowed_origins: List[str] = ["*"]
    iframe_resizable: bool = True
    default_width: str = "100%"
    default_height: str = "800px"


class BrandingConfig(BaseModel):
    product_name: str = "Archmorph"
    tagline: str = "AI-Powered Cloud Architecture Translation"
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    colors: BrandingColors = Field(default_factory=BrandingColors)
    fonts: BrandingFonts = Field(default_factory=BrandingFonts)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    embed: EmbedConfig = Field(default_factory=EmbedConfig)


class PartnerRegistration(BaseModel):
    partner_name: str
    contact_email: str
    company_url: Optional[str] = None
    branding: BrandingConfig = Field(default_factory=BrandingConfig)


def _generate_partner_id(name: str) -> str:
    slug = name.lower().replace(" ", "-")[:24]
    suffix = hashlib.sha256(f"{name}-{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:6]
    return f"{slug}-{suffix}"


def _generate_api_key() -> str:
    return f"am_wl_{secrets.token_urlsafe(32)}"


def _validate_api_key(api_key: str) -> Dict[str, Any]:
    partner = _PARTNERS.get(api_key)
    if not partner:
        raise ArchmorphException(status_code=401, detail="Invalid API key")
    if not partner.get("active", True):
        raise ArchmorphException(status_code=403, detail="Partner account suspended")
    return partner


# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/partners")
async def register_partner(reg: PartnerRegistration):
    """Register a new white-label partner and receive an API key."""
    partner_id = _generate_partner_id(reg.partner_name)
    api_key = _generate_api_key()

    record = {
        "partner_id": partner_id,
        "partner_name": reg.partner_name,
        "contact_email": reg.contact_email,
        "company_url": reg.company_url,
        "api_key": api_key,
        "branding": reg.branding.model_dump(),
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    _PARTNERS[api_key] = record
    _PARTNER_BY_ID[partner_id] = record

    logger.info("Registered white-label partner: %s (%s)", sanitize_log(reg.partner_name), sanitize_log(partner_id))  # codeql[py/log-injection] Handled by custom sanitize_log

    return {
        "partner_id": partner_id,
        "api_key": api_key,
        "message": "Partner registered. Use the API key in the X-Partner-Key header.",
    }


@router.get("/config/{partner_id}")
async def get_branding_config(partner_id: str):
    """
    Get the branding configuration for a partner.
    This is the public endpoint that the frontend calls on init.
    Falls back to default Archmorph branding if partner not found.
    """
    partner = _PARTNER_BY_ID.get(partner_id)
    if not partner:
        return {"branding": DEFAULT_BRANDING, "partner_id": "archmorph"}
    return {
        "branding": partner["branding"],
        "partner_id": partner_id,
        "partner_name": partner["partner_name"],
    }


@router.put("/branding")
async def update_branding(
    branding: BrandingConfig,
    x_partner_key: str = Header(..., alias="X-Partner-Key"),
):
    """Update branding configuration for an authenticated partner."""
    partner = _validate_api_key(x_partner_key)
    partner["branding"] = branding.model_dump()
    partner["updated_at"] = datetime.now(timezone.utc).isoformat()
    logger.info("Updated branding for partner")
    return {"status": "updated", "partner_id": partner["partner_id"]}


@router.get("/embed-snippet/{partner_id}")
async def get_embed_snippet(partner_id: str):
    """Generate embeddable HTML/JS snippet for a partner."""
    partner = _PARTNER_BY_ID.get(partner_id)
    if not partner:
        raise ArchmorphException(status_code=404, detail="Partner not found")

    embed_cfg = partner["branding"].get("embed", DEFAULT_BRANDING["embed"])
    width = embed_cfg.get("default_width", "100%")
    height = embed_cfg.get("default_height", "800px")

    snippet = f"""<!-- Archmorph White-Label Embed -->
<div id="archmorph-widget" data-partner="{partner_id}"></div>
<script>
(function() {{
  var iframe = document.createElement('iframe');
  iframe.src = 'https://app.archmorph.com/embed?partner={partner_id}';
  iframe.style.width = '{width}';
  iframe.style.height = '{height}';
  iframe.style.border = 'none';
  iframe.style.borderRadius = '12px';
  iframe.allow = 'clipboard-write';
  document.getElementById('archmorph-widget').appendChild(iframe);
}})();
</script>"""

    return {
        "partner_id": partner_id,
        "snippet": snippet,
        "embed_config": embed_cfg,
    }


@router.get("/partners")
async def list_partners(x_partner_key: str = Header(None, alias="X-Partner-Key")):
    """List all registered partners (admin/internal use)."""
    # In production this would require admin auth
    return {
        "partners": [
            {
                "partner_id": p["partner_id"],
                "partner_name": p["partner_name"],
                "active": p["active"],
                "created_at": p["created_at"],
            }
            for p in _PARTNER_BY_ID.values()
        ],
        "total": len(_PARTNER_BY_ID),
    }


@router.get("/default-config")
async def get_default_config():
    """Return the default Archmorph branding configuration."""
    return {"branding": DEFAULT_BRANDING}
