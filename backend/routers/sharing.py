from error_envelope import ArchmorphException
"""
Sharing routes — legacy module, now superseded by share_routes.py.

Routes moved to routers/share_routes.py which adds role-based views
(executive, technical, financial) and share link management.

This module is kept empty to avoid import errors from existing references.
"""

from fastapi import APIRouter

router = APIRouter()

# All sharing endpoints now live in routers/share_routes.py

