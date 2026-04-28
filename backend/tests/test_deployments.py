import pytest
import os
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from main import app
from services.azure_deploy_service import AzureDeployService
from routers.deployments import get_azure_deploy_service
from feature_flags import get_feature_flags

client = TestClient(app)

def mock_get_azure_deploy_service():
    mock_service = AsyncMock(spec=AzureDeployService)
    
    mock_service.preview_deployment.return_value = {
        "status": "success",
        "preview_data": {
            "to_add": -1,
            "to_update": -1,
            "to_destroy": -1,
            "output": '{"status": "mocked"}'
        }
    }
    
    mock_service.deploy_infrastructure.return_value = {
        "job_id": "mock_job_id",
        "status": "in_progress",
        "message": "Deployment triggered successfully.",
        "output": '{"status": "mocked_submit"}'
    }
    
    return mock_service

# Override the dependency for the tests
app.dependency_overrides[get_azure_deploy_service] = mock_get_azure_deploy_service


@pytest.fixture(autouse=True)
def reset_deploy_flag():
    flags = get_feature_flags()
    flags.update_flag("deploy_engine", {"enabled": False})
    yield
    flags.update_flag("deploy_engine", {"enabled": False})

def test_preview_deployment_azure():
    payload = {
        "provider": "azure",
        "infrastructure_code": "resource group 'my-rg' {}",
        "variables": {"resource_group": "test-rg"}
    }
    response = client.post("/api/deployments/preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data

def test_preview_deployment_non_azure():
    payload = {
        "provider": "aws",
        "infrastructure_code": "test"
    }
    response = client.post("/api/deployments/preview", json=payload)
    # The endpoint raises HTTP 501 for non-azure
    assert response.status_code == 501

def test_execute_deployment_azure():
    get_feature_flags().update_flag("deploy_engine", {"enabled": True})
    payload = {
        "provider": "azure",
        "infrastructure_code": "test",
        "variables": {"resource_group": "test-rg"}
    }
    response = client.post("/api/deployments/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "in_progress"
    assert "job_id" in data

def test_execute_deployment_requires_feature_flag():
    payload = {
        "provider": "azure",
        "infrastructure_code": "test",
        "variables": {"resource_group": "test-rg"}
    }
    response = client.post("/api/deployments/execute", json=payload)
    assert response.status_code == 403
    assert response.json()["error"]["details"]["feature_flag"] == "deploy_engine"

def test_execute_deployment_non_azure():
    get_feature_flags().update_flag("deploy_engine", {"enabled": True})
    payload = {
        "provider": "gcp",
        "infrastructure_code": "test"
    }
    response = client.post("/api/deployments/execute", json=payload)
    assert response.status_code == 501

def test_stream_deployment_logs():
    job_id = "test-job-123"
    response = client.get(f"/api/deployments/{job_id}/stream")
    assert response.status_code == 200
    assert "stubbed" in response.json()["message"]

def test_get_deployment_status():
    job_id = "test-job-456"
    response = client.get(f"/api/deployments/{job_id}/status")
    assert response.status_code == 200
    assert response.json()["status"] == "running"

def test_rollback_deployment():
    get_feature_flags().update_flag("deploy_engine", {"enabled": True})
    job_id = "test-job-789"
    response = client.post(f"/api/deployments/{job_id}/rollback")
    assert response.status_code == 200
    assert response.json()["status"] == "rollback_initiated"


# Tests for checking the AzureDeployService explicitly
@pytest.mark.asyncio
async def test_azure_deploy_service_methods():
    # Make sure we don't try to run real az commands
    os.environ["MOCK_AZURE_CLI"] = "1"
    
    service = AzureDeployService()
    
    creds = await service.get_credentials()
    assert creds["status"] == "authenticated"
    
    preview = await service.preview_deployment({"variables": {"resource_group": "test-rg"}})
    assert preview["status"] == "success"
    
    deploy = await service.deploy_infrastructure("job123", {"variables": {"resource_group": "test-rg"}})
    assert deploy["status"] == "in_progress"

@pytest.mark.asyncio
async def test_azure_deploy_service_exception():
    os.environ["MOCK_AZURE_CLI"] = "1"
    service = AzureDeployService()
    
    # Force exception inside _run_command to check except block
    with patch.object(service, '_run_command', new_callable=AsyncMock) as run_cmd_mock:
        run_cmd_mock.side_effect = Exception("Simulated Failure")
        
        preview_fail = await service.preview_deployment({})
        assert preview_fail["status"] == "failed"
        assert "Simulated Failure" in preview_fail["preview_data"]["error"]
        
        deploy_fail = await service.deploy_infrastructure("j123", {})
        assert deploy_fail["status"] == "failed"
        assert deploy_fail["message"] == "Simulated Failure"

@pytest.mark.asyncio
async def test_run_command_process_failed():
    os.environ["MOCK_AZURE_CLI"] = "0"
    service = AzureDeployService()
    
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"stdout", b"stderr_error")
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        import pytest
        with pytest.raises(RuntimeError) as excinfo:
            await service._run_command(["az", "fail"])
        assert "failed: stderr_error" in str(excinfo.value)
