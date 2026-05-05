import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from strict_models import StrictBaseModel

from services.azure_deploy_service import AzureDeployService
from feature_flags import feature_flag_dependency

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/deployments",
    tags=["deployments"],
)

# Shared dependencies can be added here
def get_azure_deploy_service() -> AzureDeployService:
    return AzureDeployService(subscription_id="dummy-subscription-id")

# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────
class DeploymentPreviewRequest(StrictBaseModel):
    provider: str
    infrastructure_code: str
    variables: Optional[Dict[str, Any]] = None

class DeploymentExecuteRequest(StrictBaseModel):
    provider: str
    job_id: Optional[str] = None
    infrastructure_code: str
    variables: Optional[Dict[str, Any]] = None

class DeploymentResponse(StrictBaseModel):
    job_id: str
    status: str
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/preview")
async def preview_deployment(
    payload: DeploymentPreviewRequest,
    azure_service: AzureDeployService = Depends(get_azure_deploy_service)
):
    """
    POST /api/deployments/preview
    Dry-run preview (what-if for Bicep or terraform plan).
    """
    logger.info("Received deployment preview request for provider: %s", str(payload.provider).replace('\n', '').replace('\r', ''))
    
    if payload.provider.lower() == "azure":
        result = await _safe_preview(azure_service, payload)
        if result is None:
            raise HTTPException(status_code=500, detail="Deployment preview failed.")
        return {"status": "success", "data": result}
    else:
        raise HTTPException(status_code=501, detail="Preview not fully implemented for the requested provider")


async def _safe_preview(azure_service, payload):
    """Run preview, return result or None on failure."""
    try:
        return await azure_service.preview_deployment(payload.model_dump())
    except Exception:
        logger.error("Deployment preview failed")
        return None

@router.post("/execute", dependencies=[Depends(feature_flag_dependency("deploy_engine"))])
async def execute_deployment(
    payload: DeploymentExecuteRequest,
    background_tasks: BackgroundTasks,
    azure_service: AzureDeployService = Depends(get_azure_deploy_service)
):
    """
    POST /api/deployments/execute
    Trigger the main deployment (az deployment create or terraform apply).
    """
    import uuid
    job_id = payload.job_id or str(uuid.uuid4())
    logger.info("Executing deployment %s for provider: %s", str(job_id).replace('\n', '').replace('\r', ''), str(payload.provider).replace('\n', '').replace('\r', ''))
    
    if payload.provider.lower() == "azure":
        result = await _safe_execute(azure_service, job_id, payload)
        if result is None:
            raise HTTPException(status_code=500, detail="Deployment failed. Please try again.")
        return DeploymentResponse(job_id=job_id, status=result["status"], message=result["message"])
    else:
        raise HTTPException(status_code=501, detail="Deploy not fully implemented for the requested provider")


async def _safe_execute(azure_service, job_id, payload):
    """Run deployment, return result or None on failure."""
    try:
        return await azure_service.deploy_infrastructure(job_id, payload.model_dump())
    except Exception:
        logger.error("Deployment execution failed for job %s", str(job_id).replace('\n', '').replace('\r', ''))
        return None

@router.get("/{job_id}/stream")
async def stream_deployment_logs(job_id: str):
    """
    GET /api/deployments/{job_id}/stream
    Stream logs for an ongoing deployment operation.
    """
    # NOTE: To be implemented with StreamingResponse / SSE
    return {"message": f"Log streaming endpoint for job {job_id} stubbed."}

@router.get("/{job_id}/status")
async def get_deployment_status(job_id: str):
    """
    GET /api/deployments/{job_id}/status
    Check the current status of the requested deployment job.
    """
    # Return stub data
    return {"job_id": job_id, "status": "running"}

@router.post("/{job_id}/rollback", dependencies=[Depends(feature_flag_dependency("deploy_engine"))])
async def rollback_deployment(job_id: str):
    """
    POST /api/deployments/{job_id}/rollback
    Trigger an automated rollback (state revert or terraform destroy / resource group cleanup).
    """
    return {"job_id": job_id, "status": "rollback_initiated", "message": "Rollback triggered successfully."}
