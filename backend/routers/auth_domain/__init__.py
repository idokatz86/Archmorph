"""
Auth domain — routes for authentication, API keys, credentials.

Consolidates auth-tier router files into one importable package (#503).
SSO/SAML/SCIM, profile, and organization routers were removed in CTO PR-3
(May 2026, internal-tool refocus: single tenant, Entra ID only).
"""

from fastapi import APIRouter

from routers.auth import router as auth_router
from routers.api_keys_routes import router as api_keys_router
from routers.credentials import router as credentials_router

domain_router = APIRouter(tags=["auth"])

domain_router.include_router(auth_router)
domain_router.include_router(api_keys_router)
domain_router.include_router(credentials_router)
