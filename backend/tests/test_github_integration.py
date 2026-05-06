from unittest.mock import patch


def test_push_iac_pr_route_delegates_to_pr_service(test_client):
    with patch("routers.github_integration.push_iac_as_pr") as push:
        push.return_value = {
            "success": True,
            "pr_url": "https://github.com/acme/infra/pull/1",
            "branch_name": "archmorph/iac-terraform-20260506-181000",
        }

        response = test_client.post(
            "/api/integrations/github/push-pr",
            json={
                "repo": "acme/infra",
                "iac_code": "resource \"azurerm_resource_group\" \"main\" {}",
                "iac_format": "terraform",
                "base_branch": "develop",
                "target_path": "deploy/main.tf",
                "analysis_summary": {"source_provider": "aws"},
                "cost_estimate": {"currency": "USD"},
            },
        )

    assert response.status_code == 200
    assert response.json()["pr_url"] == "https://github.com/acme/infra/pull/1"
    push.assert_called_once_with(
        repo_full_name="acme/infra",
        iac_code="resource \"azurerm_resource_group\" \"main\" {}",
        iac_format="terraform",
        base_branch="develop",
        target_path="deploy/main.tf",
        github_token=None,
        analysis_summary={"source_provider": "aws"},
        cost_estimate={"currency": "USD"},
    )


def test_push_iac_pr_route_returns_readable_failure(test_client):
    with patch("routers.github_integration.push_iac_as_pr") as push:
        push.return_value = {"success": False, "error": "GitHub token not configured. Set GITHUB_TOKEN."}

        response = test_client.post(
            "/api/integrations/github/push-pr",
            json={
                "repo": "acme/infra",
                "iac_code": "targetScope = 'resourceGroup'",
                "iac_format": "bicep",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "GitHub token not configured. Set GITHUB_TOKEN."