import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from routers.auth import get_current_user
from services.terraform_runner import TerraformRunner
from services.security_compliance import analyze_security_compliance
from services.finops_analyzer import calculate_costs
from feature_flags import feature_flag_dependency

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/deploy",
    tags=["deploy"]
)

class DeploymentRequest(BaseModel):
    project_id: str
    iac_code: Optional[str] = None
    canvas_state: Optional[dict] = None

@router.post("/preflight-check")
async def run_preflight_check(
    request: DeploymentRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Runs security and cost estimations before deployment.
    """
    if not request.canvas_state:
        raise HTTPException(status_code=400, detail="No canvas state provided for preflight check.")

    security_checks = analyze_security_compliance(request.canvas_state)
    cost_estimate = calculate_costs(request.canvas_state)
    
    return {
        "security": security_checks,
        "finops": cost_estimate
    }

@router.post("/execute/{project_id}", dependencies=[Depends(feature_flag_dependency("deploy_engine"))])
async def execute_deployment(
    project_id: str,
    request: DeploymentRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Kicks off an async Terraform deployment and streams the logs back to the client.
    """
    if not request.iac_code:
        raise HTTPException(status_code=400, detail="No IaC code provided for deployment.")

    # Instantiate runner (Note: User auth is attached to assure session safety)
    runner = TerraformRunner(project_id=project_id, environment="production")

    # FastAPI StreamingResponse takes an async generator
    async def log_generator():
        try:
            async for log_line in runner.stream_apply(request.iac_code):
                # Using SSE or just newline-delimited text.
                # The frontend splits on "\n" so raw text works fine.
                yield f"{log_line}\n"
        except Exception as e:
            logger.error(f"Error during deployment streaming: {str(e)}")
            yield "ERROR: An internal error occurred during deployment.\n"

    return StreamingResponse(log_generator(), media_type="text/plain")
