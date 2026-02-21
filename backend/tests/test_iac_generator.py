"""Tests for iac_generator module — GPT-4o powered IaC generation."""

from unittest.mock import patch, MagicMock


from iac_generator import generate_iac_code


MOCK_ANALYSIS = {
    "title": "Test Architecture",
    "source_provider": "AWS",
    "services_detected": 3,
    "mappings": [
        {"source_service": "EC2", "azure_service": "Azure Virtual Machines", "category": "Compute", "confidence": 0.9},
        {"source_service": "S3", "azure_service": "Azure Blob Storage", "category": "Storage", "confidence": 0.95},
        {"source_service": "RDS", "azure_service": "Azure SQL Database", "category": "Database", "confidence": 0.85},
    ],
    "zones": [],
}


class TestGenerateIaCCode:
    @patch("iac_generator.get_openai_client")
    def test_generates_terraform(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='resource "azurerm_resource_group" "main" {\n  name     = "rg-test"\n  location = "westeurope"\n}'))]
        )

        code = generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="terraform",
            params={"project_name": "test", "region": "westeurope", "environment": "dev"},
        )
        assert "resource" in code or "azurerm" in code

    @patch("iac_generator.get_openai_client")
    def test_generates_bicep(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='resource rg \'Microsoft.Resources/resourceGroups@2023-07-01\' = {\n  name: \'rg-test\'\n  location: \'westeurope\'\n}'))]
        )

        code = generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="bicep",
            params={"project_name": "test", "region": "westeurope", "environment": "dev"},
        )
        assert code is not None and len(code) > 0

    @patch("iac_generator.get_openai_client")
    def test_fallback_on_empty_analysis(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='provider "azurerm" {\n  features {}\n}'))]
        )

        code = generate_iac_code(
            analysis=None,
            iac_format="terraform",
            params={},
        )
        assert code is not None
