"""
Terraform validation route.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from terraform_preview import validate_terraform_syntax

router = APIRouter()


class TerraformValidateRequest(BaseModel):
    code: str


@router.post("/api/terraform/validate")
async def validate_terraform_syntax_endpoint(data: TerraformValidateRequest):
    """Validate Terraform HCL syntax."""
    return validate_terraform_syntax(data.code)
