"""
Terraform validation route.

Issue #123 — Auth + rate limiting added.
"""

from fastapi import APIRouter, Request, Depends
from pydantic import Field
from strict_models import StrictBaseModel

from terraform_preview import validate_terraform_syntax
from routers.shared import limiter, verify_api_key

router = APIRouter()


class TerraformValidateRequest(StrictBaseModel):
    code: str = Field(..., max_length=100_000)  # Cap input to 100 KB


@router.post("/api/terraform/validate")
@limiter.limit("10/minute")
async def validate_terraform_syntax_endpoint(
    request: Request,
    data: TerraformValidateRequest,
    _key=Depends(verify_api_key),
):
    """Validate Terraform HCL syntax."""
    return validate_terraform_syntax(data.code)
