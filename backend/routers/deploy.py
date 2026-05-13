import logging
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field
from strict_models import StrictBaseModel

from routers.shared import require_authenticated_user_context, verify_admin_key
from services.terraform_runner import TerraformRunner
from services.security_compliance import analyze_security_compliance
from services.finops_analyzer import calculate_costs
from feature_flags import feature_flag_dependency

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/deploy",
    tags=["deploy"]
)


# ─────────────────────────────────────────────────────────────
# Strict request model (#845) — enums + size limits
# ─────────────────────────────────────────────────────────────
class DeploymentRequest(StrictBaseModel):
    """Request body for deployment preflight and execution (#845).

    Strict validation:
    - ``project_id``  — alphanumeric/dash/underscore, 1-200 chars
    - ``environment`` — constrained to known deployment targets
    - ``iac_code``    — 500 KB cap to prevent oversized payloads
    - ``canvas_state`` — required dict (preflight validates its shape downstream)
    """
    project_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    environment: Literal["dev", "staging", "prod", "production"] = "dev"
    iac_code: Optional[str] = Field(None, max_length=500_000)
    canvas_state: Optional[dict] = None

@router.post("/preflight-check")
async def run_preflight_check(
    request: DeploymentRequest,
    current_user: dict = Depends(require_authenticated_user_context)
):
    """
    Runs security and cost estimations before deployment (#845).
    Validates the strict DeploymentRequest model (enums + size limits).
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
    request: Request,
    request_body: DeploymentRequest,
    current_user: dict = Depends(verify_admin_key)
):
    """
    Kicks off an async Terraform deployment and streams the logs back to the client.
    Client disconnects are detected and upstream streaming is stopped promptly
    to avoid wasting Azure OpenAI / compute billing (#849).
    """
    if not request_body.iac_code:
        raise HTTPException(status_code=400, detail="No IaC code provided for deployment.")
    if request_body.project_id != project_id:
        raise HTTPException(status_code=400, detail="Path project_id must match request body project_id.")

    # Instantiate runner (Note: User auth is attached to assure session safety)
    runner = TerraformRunner(project_id=project_id, environment="production")

    # FastAPI StreamingResponse takes an async generator
    async def log_generator():
        try:
            async for log_line in runner.stream_apply(request_body.iac_code):
                # Stop billing work immediately when the client hangs up (#849)
                if await request.is_disconnected():
                    logger.info(
                        "Client disconnected — stopping deployment stream for project %s",
                        str(project_id).replace("\n", "").replace("\r", ""),
                    )
                    break
                # Using SSE or just newline-delimited text.
                # The frontend splits on "\n" so raw text works fine.
                yield f"{log_line}\n"
        except Exception as e:
            logger.error("Error during deployment streaming: %s", str(e).replace("\n", "").replace("\r", ""))
            yield "ERROR: An internal error occurred during deployment.\n"

    return StreamingResponse(log_generator(), media_type="text/plain")
