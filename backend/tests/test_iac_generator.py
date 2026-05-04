"""Tests for iac_generator module \u2014 GPT-4o powered IaC generation."""

from unittest.mock import patch, MagicMock

import pytest

from iac_generator import _apply_validation, _validate_bicep_cli, generate_iac_code


@pytest.fixture(autouse=True)
def disable_cli_validation_by_default(monkeypatch):
    monkeypatch.setenv("ARCHMORPH_DISABLE_IAC_CLI_VALIDATION", "1")


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
    @patch("iac_generator.cached_chat_completion")
    def test_generates_terraform(self, mock_cached):
        mock_cached.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='resource "azurerm_resource_group" "main" {\n  name     = "rg-test"\n  location = "westeurope"\n}'))]
        )

        code = generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="terraform",
            params={"project_name": "test", "region": "westeurope", "environment": "dev"},
        )
        assert "resource" in code or "azurerm" in code

    @patch("iac_generator.cached_chat_completion")
    def test_generates_bicep(self, mock_cached):
        mock_cached.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {\n  name: 'rg-test'\n  location: 'westeurope'\n}"))]
        )

        code = generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="bicep",
            params={"project_name": "test", "region": "westeurope", "environment": "dev"},
        )
        assert code is not None and len(code) > 0

    @patch("iac_generator._apply_validation", side_effect=lambda code, _format: code)
    @patch("iac_generator.cached_chat_completion")
    def test_generate_iac_validates_once_after_verification(self, mock_cached, mock_validation):
        mock_cached.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='resource "azurerm_resource_group" "main" {\n  name = "rg-test"\n  location = "westeurope"\n}'))]
        )

        generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="terraform",
            params={"project_name": "test", "region": "westeurope", "environment": "dev"},
        )

        mock_validation.assert_called_once()

    @patch("iac_generator.cached_chat_completion")
    def test_fallback_on_empty_analysis(self, mock_cached):
        mock_cached.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='provider "azurerm" {\n  features {}\n}'))]
        )

        code = generate_iac_code(
            analysis=None,
            iac_format="terraform",
            params={},
        )
        assert code is not None

    @patch("iac_generator.cached_chat_completion")
    def test_generate_cloudformation(self, mock_cached):
        mock_cached.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content='Resources:\n  MyBucket:\n    Type: AWS::S3::Bucket'))])
        code = generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="cloudformation",
            params={"project_name": "test", "region": "us-east-1", "environment": "prod"}
        )
        assert "Resources" in code

    @patch("iac_generator.cached_chat_completion")
    def test_generate_pulumi(self, mock_cached):
        mock_cached.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content='import pulumi_aws as aws\n\nbucket = aws.s3.Bucket("my-bucket")'))])
        code = generate_iac_code(
            analysis=MOCK_ANALYSIS,
            iac_format="pulumi",
            params={}
        )
        assert "pulumi" in code

    @patch("iac_generator.cached_chat_completion")
    def test_generate_iac_code_invalid_format(self, mock_cached):
        mock_cached.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content='provider "azurerm" {}'))])
        code = generate_iac_code(
            analysis={"mappings": []},
            iac_format="unknown_format",
            params={}
        )
        assert "azurerm" in code

    @patch("iac_generator.cached_chat_completion")
    def test_generate_iac_empty_components(self, mock_cached):
        mock_cached.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content='provider "azurerm" {}'))])
        code = generate_iac_code(
            analysis={"zones": [], "mappings": []},
            iac_format="terraform",
            params={}
        )
        assert "azurerm" in code

    @patch("iac_generator.cached_chat_completion")
    def test_cached_chat_completion_error_handling(self, mock_cached):
        mock_cached.side_effect = Exception("OpenAI Error")
        try:
            generate_iac_code(
                analysis={"mappings": [{"azure_service": "App Service"}]},
                iac_format="terraform",
                params={}
            )
        except Exception as e:
            assert "OpenAI Error" in str(e)

    @patch("iac_generator.cached_chat_completion")
    def test_clean_markdown_marks(self, mock_cached):
        mock_cached.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content='```terraform\nresource "azurerm_resource_group" "main" {}\n```'))])
        code = generate_iac_code(
            analysis={},
            iac_format="terraform",
            params={}
        )
        assert "resource" in code
        assert "```" not in code

    @patch("iac_generator._validate_terraform_cli")
    def test_terraform_cli_validation_errors_are_marked_inline(self, mock_validate):
        with patch.dict(
            "os.environ",
            {"ARCHMORPH_DISABLE_IAC_CLI_VALIDATION": "0", "ARCHMORPH_ENABLE_IAC_CLI_VALIDATION": "1"},
        ):
            mock_validate.return_value = [("error", "Unsupported argument")]
            code = _apply_validation('resource "azurerm_resource_group" "main" {}', "terraform")
        assert "failed terraform validate: Unsupported argument" in code

    @patch("iac_generator._validate_terraform_cli")
    def test_terraform_cli_failure_labels_include_failed_command(self, mock_validate):
        with patch.dict(
            "os.environ",
            {"ARCHMORPH_DISABLE_IAC_CLI_VALIDATION": "0", "ARCHMORPH_ENABLE_IAC_CLI_VALIDATION": "1"},
        ):
            mock_validate.return_value = [("error", "terraform init failed: registry unavailable")]
            code = _apply_validation('resource "azurerm_resource_group" "main" {}', "terraform")
        assert "failed terraform init: registry unavailable" in code
        assert "failed terraform validate: terraform init failed" not in code

    @patch("iac_generator.subprocess.run")
    @patch("iac_generator.shutil.which", return_value="/usr/bin/terraform")
    def test_terraform_init_failure_falls_back_to_static_validation(self, mock_which, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr="registry unavailable"),
        ]

        with patch.dict(
            "os.environ",
            {"ARCHMORPH_DISABLE_IAC_CLI_VALIDATION": "0", "ARCHMORPH_ENABLE_IAC_CLI_VALIDATION": "1"},
        ):
            code = _apply_validation(
                'resource "azurerm_resource_group" "main" {\n  name = "rg-test"\n  location = "westeurope"\n}',
                "terraform",
            )

        assert "failed terraform init" not in code
        assert "resource \"azurerm_resource_group\"" in code

    @patch("iac_generator._validate_terraform_cli")
    def test_terraform_cli_validation_can_run_by_default_when_safe(self, mock_validate, monkeypatch):
        monkeypatch.setenv("ARCHMORPH_DISABLE_IAC_CLI_VALIDATION", "0")
        mock_validate.return_value = [("error", "Unsupported argument")]
        code = _apply_validation('resource "azurerm_resource_group" "main" {}', "terraform")
        assert "failed terraform validate: Unsupported argument" in code

    @patch("iac_generator._validate_bicep_cli")
    def test_bicep_cli_validation_errors_are_marked_inline(self, mock_validate):
        with patch.dict(
            "os.environ",
            {"ARCHMORPH_DISABLE_IAC_CLI_VALIDATION": "0", "ARCHMORPH_ENABLE_IAC_CLI_VALIDATION": "1"},
        ):
            mock_validate.return_value = [("error", "Expected the \"=\" character")]
            code = _apply_validation("resource rg 'Microsoft.Resources/resourceGroups@2023-07-01'", "bicep")
        assert "// ⚠ failed az bicep build: Expected the \"=\" character" in code
        assert "# ⚠ failed az bicep build" not in code

    def test_cloudformation_validation_errors_are_marked_inline(self):
        code = _apply_validation("Resources: {}", "cloudformation")
        assert "failed CloudFormation validation" in code
        assert "failed az bicep build" not in code

    @patch("iac_generator.subprocess.run")
    @patch("iac_generator.shutil.which", return_value="/usr/bin/az")
    def test_bicep_cli_validation_falls_back_when_component_missing(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="Bicep CLI not installed", stdout="")
        assert _validate_bicep_cli("targetScope = 'subscription'") is None

    

