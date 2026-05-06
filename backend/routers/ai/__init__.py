"""
AI domain — routes for chat, suggestions, provenance.

Consolidates AI router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.chat import router as chat_router
from routers.suggestions import router as suggestions_router
from routers.provenance import router as provenance_router

domain_router = APIRouter(tags=["ai"])

domain_router.include_router(chat_router)
domain_router.include_router(suggestions_router)
domain_router.include_router(provenance_router)
