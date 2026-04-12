"""
Admin domain — routes for admin dashboard, feature flags, analytics.

Consolidates 3 router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.admin_core import router as admin_router
from routers.feature_flags import router as feature_flags_router
from routers.analytics_routes import router as analytics_router

domain_router = APIRouter(tags=["admin"])

domain_router.include_router(admin_router)
domain_router.include_router(feature_flags_router)
domain_router.include_router(analytics_router)
