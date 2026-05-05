"""
API route for pushing generated IaC to GitHub as a Pull Request (#504).
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import Field
from strict_models import StrictBaseModel
from typing import Optional

from iac_pr_push import push_iac_as_pr
from routers.shared import verify_api_key

router = APIRouter()


class PushIaCRequest(StrictBaseModel):
    repo: str = Field(..., description="GitHub repo in owner/repo format")
    iac_code: str = Field(..., description="Generated IaC code content")
    iac_format: str = Field("terraform", description="terraform, bicep, cloudformation, pulumi, aws-cdk")
    base_branch: str = Field("main", description="Target branch for the PR")
    target_path: Optional[str] = Field(None, description="File path in the repo (default: infra/main.<ext>)")
    github_token: Optional[str] = Field(None, description="GitHub PAT (optional, uses server token if not provided)")
    analysis_summary: Optional[dict] = Field(None, description="Migration analysis summary for PR description")
    cost_estimate: Optional[dict] = Field(None, description="Cost estimate data for PR description")


@router.post(
    "/api/integrations/github/push-pr",
    summary="Push IaC to GitHub as a PR",
    tags=["integrations"],
)
async def push_iac_pr(req: PushIaCRequest, _auth=Depends(verify_api_key)):
    """Push generated IaC code to a GitHub repository as a Pull Request."""
    result = push_iac_as_pr(
        repo_full_name=req.repo,
        iac_code=req.iac_code,
        iac_format=req.iac_format,
        base_branch=req.base_branch,
        target_path=req.target_path,
        github_token=req.github_token,
        analysis_summary=req.analysis_summary,
        cost_estimate=req.cost_estimate,
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create PR"))

    return result
