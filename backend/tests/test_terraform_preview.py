"""
Tests for Terraform Plan Preview
"""

import pytest
from terraform_preview import (
    ResourceChange, TerraformPlanResult, ResourceAction,
    preview_terraform_plan, validate_terraform_syntax,
    _simulate_plan_from_hcl, render_plan_preview,
)


class TestResourceChange:
    """Tests for ResourceChange class."""
    
    def test_resource_change_creation(self):
        change = ResourceChange(
            address="azurerm_resource_group.main",
            resource_type="azurerm_resource_group",
            name="main",
            action=ResourceAction.CREATE,
        )
        assert change.address == "azurerm_resource_group.main"
        assert change.action == ResourceAction.CREATE
    
    def test_resource_change_to_dict(self):
        change = ResourceChange(
            address="azurerm_storage_account.main",
            resource_type="azurerm_storage_account",
            name="main",
            action=ResourceAction.UPDATE,
            reason="Configuration changed",
        )
        data = change.to_dict()
        assert data["action"] == "update"
        assert data["reason"] == "Configuration changed"


class TestTerraformPlanResult:
    """Tests for TerraformPlanResult class."""
    
    def test_plan_result_creation(self):
        result = TerraformPlanResult(
            success=True,
            plan_id="plan-123",
        )
        assert result.success is True
        assert result.plan_id == "plan-123"
    
    def test_plan_result_summary(self):
        result = TerraformPlanResult(
            success=True,
            plan_id="plan-123",
            resources=[
                ResourceChange("rg.main", "azurerm_resource_group", "main", ResourceAction.CREATE),
                ResourceChange("sa.main", "azurerm_storage_account", "main", ResourceAction.CREATE),
                ResourceChange("vm.web", "azurerm_virtual_machine", "web", ResourceAction.UPDATE),
            ],
        )
        summary = result.get_summary()
        assert summary["total_resources"] == 3
        assert summary["to_create"] == 2
        assert summary["to_update"] == 1
    
    def test_plan_result_to_dict(self):
        result = TerraformPlanResult(
            success=True,
            plan_id="plan-123",
            warnings=["No tags defined"],
        )
        data = result.to_dict()
        assert data["success"] is True
        assert len(data["warnings"]) == 1


class TestHCLParsing:
    """Tests for HCL parsing and simulation."""
    
    def test_parse_simple_resource(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name     = "example-rg"
  location = "West Europe"
}
'''
        resources = _simulate_plan_from_hcl(hcl)
        assert len(resources) == 1
        assert resources[0].resource_type == "azurerm_resource_group"
        assert resources[0].name == "main"
    
    def test_parse_multiple_resources(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name = "rg"
}

resource "azurerm_storage_account" "main" {
  name = "storage"
}

resource "azurerm_virtual_network" "main" {
  name = "vnet"
}
'''
        resources = _simulate_plan_from_hcl(hcl)
        assert len(resources) == 3
    
    def test_parse_nested_resource(self):
        hcl = '''
resource "azurerm_container_app" "backend" {
  name = "api"
  
  template {
    container {
      image = "myimage"
    }
  }
}
'''
        resources = _simulate_plan_from_hcl(hcl)
        assert len(resources) == 1
        assert resources[0].resource_type == "azurerm_container_app"


class TestPlanPreview:
    """Tests for plan preview generation."""
    
    def test_preview_basic_hcl(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name     = "example"
  location = "westeurope"
}
'''
        result = preview_terraform_plan(hcl, "diag-123", use_simulation=True)
        
        assert result.success is True
        assert len(result.resources) == 1
    
    def test_preview_warns_on_hardcoded_password(self):
        hcl = '''
resource "azurerm_postgresql_flexible_server" "main" {
  name     = "db"
  administrator_password = "hardcoded123"
}
'''
        result = preview_terraform_plan(hcl, "diag-123")
        assert any("password" in w.lower() for w in result.warnings)
    
    def test_preview_warns_on_no_tags(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name     = "example"
  location = "westeurope"
}
'''
        result = preview_terraform_plan(hcl, "diag-123")
        assert any("tags" in w.lower() for w in result.warnings)


class TestSyntaxValidation:
    """Tests for Terraform syntax validation."""
    
    def test_valid_syntax(self):
        hcl = '''
terraform {
  required_providers {
    azurerm = {
      source = "hashicorp/azurerm"
    }
  }
}

provider "azurerm" {}

resource "azurerm_resource_group" "main" {
  name     = "example"
  location = "westeurope"
}
'''
        result = validate_terraform_syntax(hcl)
        assert result["valid"] is True
    
    def test_unbalanced_braces(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name = "example"
'''
        result = validate_terraform_syntax(hcl)
        assert result["valid"] is False
        assert any("brace" in e.lower() for e in result["errors"])
    
    def test_double_equals(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name == "example"
}
'''
        result = validate_terraform_syntax(hcl)
        assert result["valid"] is False
    
    def test_missing_terraform_block_warning(self):
        hcl = '''
resource "azurerm_resource_group" "main" {
  name     = "example"
  location = "westeurope"
}
'''
        result = validate_terraform_syntax(hcl)
        assert any("terraform" in w.lower() for w in result["warnings"])


class TestPlanRendering:
    """Tests for plan preview rendering."""
    
    def test_render_basic_plan(self):
        result = TerraformPlanResult(
            success=True,
            plan_id="plan-123",
            resources=[
                ResourceChange("rg.main", "azurerm_resource_group", "main", ResourceAction.CREATE),
            ],
        )
        
        markdown = render_plan_preview(result)
        
        assert "# Terraform Plan Preview" in markdown
        assert "plan-123" in markdown
        assert "Create" in markdown
    
    def test_render_with_errors(self):
        result = TerraformPlanResult(
            success=False,
            plan_id="plan-456",
            errors=["Syntax error on line 10"],
        )
        
        markdown = render_plan_preview(result)
        
        assert "Failed" in markdown
        assert "Syntax error" in markdown
    
    def test_render_with_warnings(self):
        result = TerraformPlanResult(
            success=True,
            plan_id="plan-789",
            warnings=["No tags defined"],
        )
        
        markdown = render_plan_preview(result)
        
        assert "Warnings" in markdown
        assert "No tags" in markdown
