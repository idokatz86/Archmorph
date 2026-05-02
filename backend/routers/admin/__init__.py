"""
Admin domain — routes for admin dashboard and feature flags.

Consolidates admin tier routers into one importable package (#503).
Product-analytics router was removed in CTO PR-2 (May 2026, internal-tool refocus).
"""

from fastapi import APIRouter

from routers.admin_core import router as admin_router
from routers.feature_flags import router as feature_flags_router

domain_router = APIRouter(tags=["admin"])

domain_router.include_router(admin_router)
domain_router.include_router(feature_flags_router)
