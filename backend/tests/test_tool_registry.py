import pytest
import json
from unittest.mock import patch, MagicMock

from services.tool_registry import tool_registry

@pytest.mark.asyncio
@patch('services.tool_registry.AWSScanner')
async def test_tool_registry_executes_cloud_scan(mock_aws_scanner):
    # Setup mock scanner
    mock_instance = MagicMock()
    mock_instance.perform_full_scan.return_value = {"metadata": {"provider": "aws"}}
    mock_aws_scanner.return_value = mock_instance
    
    with patch('services.tool_registry.get_credentials') as mock_get_creds:
        mock_get_creds.return_value = {"client_id": "test"}
        
        args = json.dumps({"provider": "aws"})
        response_json = await tool_registry.execute("scan_cloud_infrastructure", args, session_token="test_token")
        
        response = json.loads(response_json)
        assert response["status"] == "success"
        assert response["result"]["metadata"]["provider"] == "aws"
