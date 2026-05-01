"""
Export domain — routes for reports, sharing, timeline, collaboration, replay.

Consolidates router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.report_routes import router as report_router
from routers.share_routes import router as share_routes_router
from routers.timeline_routes import router as timeline_router
from routers.collaboration_routes import router as collaboration_router
from routers.replay_routes import router as replay_router

domain_router = APIRouter(tags=["export"])

domain_router.include_router(report_router)
domain_router.include_router(share_routes_router)
domain_router.include_router(timeline_router)
domain_router.include_router(collaboration_router)
domain_router.include_router(replay_router)
