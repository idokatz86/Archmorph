"""
Auth domain — routes for authentication, SSO, API keys, profiles, orgs.

Consolidates 6 router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.auth import router as auth_router
from routers.sso_routes import router as sso_router
from routers.api_keys_routes import router as api_keys_router
from routers.profile_routes import router as profile_router
from routers.org_routes import router as org_router
from routers.credentials import router as credentials_router

domain_router = APIRouter(tags=["auth"])

domain_router.include_router(auth_router)
domain_router.include_router(sso_router)
domain_router.include_router(api_keys_router)
domain_router.include_router(profile_router)
domain_router.include_router(org_router)
domain_router.include_router(credentials_router)
