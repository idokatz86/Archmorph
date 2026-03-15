import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock

@pytest.fixture
def mcp_client():
    return DiagramMCPClient(mcp_gateway_url="http://mocked:8080/mcp")

@pytest.mark.asyncio
async def test_generate_diagram_success(mcp_client):
    analysis_data = {"zones": []}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"diagram_payload": "{\"test\": \"ok\"}"}

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await mcp_client.generate_diagram("excalidraw", analysis_data)
        assert result == "{\"test\": \"ok\"}"

@pytest.mark.asyncio
async def test_generate_diagram_fallback_on_connect_error(mcp_client):
    analysis_data = {"zones": []}
    
    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Mock error")), \
         patch.object(mcp_client, "_fallback_generation", return_value="fallback_content") as mock_fallback:
        result = await mcp_client.generate_diagram("excalidraw", analysis_data)
        assert result == "fallback_content"
        mock_fallback.assert_called_once_with("excalidraw", analysis_data)

@pytest.mark.asyncio
async def test_generate_diagram_retry_and_timeout(mcp_client):
    analysis_data = {"zones": []}
    
    with patch("httpx.AsyncClient.post", side_effect=httpx.ReadTimeout("Mock timeout")), \
         patch.object(mcp_client, "_fallback_generation") as mock_fallback:
        with pytest.raises(TimeoutError, match="MCP Gateway timed out after"):
            await mcp_client.generate_diagram("excalidraw", analysis_data)
        mock_fallback.assert_not_called()
