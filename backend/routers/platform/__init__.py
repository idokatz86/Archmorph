"""
Platform domain — routes for health, services, legal, jobs, etc.

Consolidates 14 router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.health import router as health_router
from routers.services import router as services_router
from routers.roadmap import router as roadmap_router
from routers.feedback import router as feedback_router
from routers.jobs import router as jobs_router
from routers.webhook_routes import router as webhook_routes_router
from routers.integrations_routes import router as integrations_router
from routers.cost_routes import router as cost_router
from routers.cost_comparison_routes import router as cost_comparison_router
from routers.network_routes import router as network_router
from routers.sku_routes import router as sku_router

domain_router = APIRouter(tags=["platform"])

domain_router.include_router(health_router)
domain_router.include_router(services_router)
domain_router.include_router(roadmap_router)
domain_router.include_router(feedback_router)
domain_router.include_router(jobs_router)
domain_router.include_router(webhook_routes_router)
domain_router.include_router(integrations_router)
domain_router.include_router(cost_router)
domain_router.include_router(cost_comparison_router)
domain_router.include_router(network_router)
domain_router.include_router(sku_router)
