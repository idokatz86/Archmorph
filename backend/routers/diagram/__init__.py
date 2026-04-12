"""
Diagram domain — routes for diagram lifecycle, analysis, HLD, IaC, versioning.

Consolidates 8 router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.diagrams import router as diagrams_router
from routers.analysis import router as analysis_router
from routers.hld_routes import router as hld_routes_router
from routers.iac_routes import router as iac_routes_router
from routers.insights import router as insights_router
from routers.diff_routes import router as diff_routes_router
from routers.versioning import router as versioning_router
from routers.samples import router as samples_router

domain_router = APIRouter(tags=["diagram"])

domain_router.include_router(diagrams_router)
domain_router.include_router(analysis_router)
domain_router.include_router(hld_routes_router)
domain_router.include_router(iac_routes_router)
domain_router.include_router(insights_router)
domain_router.include_router(diff_routes_router)
domain_router.include_router(versioning_router)
domain_router.include_router(samples_router)
