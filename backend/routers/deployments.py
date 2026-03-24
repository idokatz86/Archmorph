import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel

from services.azure_deploy_service import AzureDeployService

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
class DeploymentPreviewRequest(BaseModel):
    provider: str
    infrastructure_code: str
    variables: Optional[Dict[str, Any]] = None

class DeploymentExecuteRequest(BaseModel):
    provider: str
    job_id: Optional[str] = None
    infrastructure_code: str
    variables: Optional[Dict[str, Any]] = None

class DeploymentResponse(BaseModel):
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
        _failed = False
        try:
            result = await azure_service.preview_deployment(payload.model_dump())
        except Exception:
            _failed = True
            logger.error("Deployment preview failed")
        if _failed:
            raise HTTPException(status_code=500, detail="Deployment preview failed.")
        return {"status": "success", "data": result}
    else:
        raise HTTPException(status_code=501, detail="Preview not fully implemented for the requested provider")

@router.post("/execute")
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
        _failed = False
        try:
            result = await azure_service.deploy_infrastructure(job_id, payload.model_dump())
        except Exception:
            _failed = True
            logger.error("Deployment execution failed for job %s", str(job_id).replace('\n', '').replace('\r', ''))
        if _failed:
            raise HTTPException(status_code=500, detail="Deployment failed. Please try again.")
        return DeploymentResponse(job_id=job_id, status=result["status"], message=result["message"])
    else:
        raise HTTPException(status_code=501, detail="Deploy not fully implemented for the requested provider")

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

@router.post("/{job_id}/rollback")
async def rollback_deployment(job_id: str):
    """
    POST /api/deployments/{job_id}/rollback
    Trigger an automated rollback (state revert or terraform destroy / resource group cleanup).
    """
    return {"job_id": job_id, "status": "rollback_initiated", "message": "Rollback triggered successfully."}
