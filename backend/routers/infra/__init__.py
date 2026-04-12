"""
Infra domain — routes for Terraform, deployments, scanning, drift detection.

Consolidates 8 router files into one importable package (#503).
"""

from fastapi import APIRouter

from routers.infra_import import router as infra_router
from routers.terraform import router as terraform_router
from routers.terraform_import_routes import router as terraform_import_router
from routers.tf_backend import router as tf_backend_router
from routers.scanner_routes import router as scanner_router
from routers.deploy import router as deploy_router
from routers.deployments import router as deployments_router
from routers.drift import router as drift_router

domain_router = APIRouter(tags=["infra"])

domain_router.include_router(infra_router)
domain_router.include_router(terraform_router)
domain_router.include_router(terraform_import_router)
domain_router.include_router(tf_backend_router)
domain_router.include_router(scanner_router)
domain_router.include_router(deploy_router)
domain_router.include_router(deployments_router)
domain_router.include_router(drift_router)
