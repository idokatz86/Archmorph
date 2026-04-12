"""
Agent domain — routes for AI agents, PaaS, memory, executions, policies.

Consolidates 6 router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.agents import router as agents_router
from routers.agent_paas import router as agent_paas_router
from routers.agent_memory import router as agent_memory_router
from routers.executions import router as executions_router
from routers.policies import router as policies_router
from routers.models import router as models_router

domain_router = APIRouter(tags=["agent"])

domain_router.include_router(agents_router)
domain_router.include_router(agent_paas_router)
domain_router.include_router(agent_memory_router)
domain_router.include_router(executions_router)
domain_router.include_router(policies_router)
domain_router.include_router(models_router)
