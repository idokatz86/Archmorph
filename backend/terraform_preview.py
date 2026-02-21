"""
Archmorph Terraform Plan Preview
Generate and preview Terraform plans with estimated changes
"""

import logging
import subprocess
import tempfile
import shutil
import json
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ResourceAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    NO_OP = "no-op"
    REPLACE = "replace"


@dataclass
class ResourceChange:
    """A planned change to a resource."""
    address: str
    resource_type: str
    name: str
    action: ResourceAction
    reason: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "address": self.address,
            "resource_type": self.resource_type,
            "name": self.name,
            "action": self.action.value,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class TerraformPlanResult:
    """Result of a Terraform plan operation."""
    success: bool
    plan_id: str
    resources: List[ResourceChange] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_output: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "plan_id": self.plan_id,
            "summary": self.get_summary(),
            "resources": [r.to_dict() for r in self.resources],
            "outputs": self.outputs,
            "errors": self.errors,
            "warnings": self.warnings,
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of planned changes."""
        action_counts = {action.value: 0 for action in ResourceAction}
        for resource in self.resources:
            action_counts[resource.action.value] += 1
        
        return {
            "total_resources": len(self.resources),
            "to_create": action_counts["create"],
            "to_update": action_counts["update"],
            "to_delete": action_counts["delete"],
            "to_replace": action_counts["replace"],
            "no_changes": action_counts["no-op"],
        }


def _parse_terraform_plan_json(plan_json: Dict[str, Any]) -> List[ResourceChange]:
    """Parse Terraform plan JSON output into ResourceChange objects."""
    changes = []
    
    resource_changes = plan_json.get("resource_changes", [])
    
    for rc in resource_changes:
        # Skip data sources for preview
        if rc.get("type", "").startswith("data."):
            continue
        
        change = rc.get("change", {})
        actions = change.get("actions", ["no-op"])
        
        # Map Terraform actions to our enum
        if actions == ["create"]:
            action = ResourceAction.CREATE
        elif actions == ["delete"]:
            action = ResourceAction.DELETE
        elif actions == ["update"]:
            action = ResourceAction.UPDATE
        elif actions == ["delete", "create"]:
            action = ResourceAction.REPLACE
        elif actions == ["create", "delete"]:
            action = ResourceAction.REPLACE
        elif actions == ["no-op"]:
            action = ResourceAction.NO_OP
        elif actions == ["read"]:
            action = ResourceAction.READ
        else:
            action = ResourceAction.UPDATE
        
        resource_change = ResourceChange(
            address=rc.get("address", ""),
            resource_type=rc.get("type", ""),
            name=rc.get("name", ""),
            action=action,
            reason=rc.get("action_reason"),
            before=change.get("before"),
            after=change.get("after"),
        )
        changes.append(resource_change)
    
    return changes


def _simulate_plan_from_hcl(hcl_content: str) -> List[ResourceChange]:
    """Simulate a Terraform plan from HCL content without running Terraform."""
    changes = []
    
    # Parse resource blocks from HCL
    # Pattern: resource "type" "name" {
    resource_pattern = re.compile(
        r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{',
        re.MULTILINE
    )
    
    for match in resource_pattern.finditer(hcl_content):
        resource_type = match.group(1)
        name = match.group(2)
        
        changes.append(ResourceChange(
            address=f"{resource_type}.{name}",
            resource_type=resource_type,
            name=name,
            action=ResourceAction.CREATE,
            reason="New resource defined in generated IaC",
        ))
    
    return changes


def preview_terraform_plan(
    hcl_content: str,
    diagram_id: str,
    use_simulation: bool = True,
) -> TerraformPlanResult:
    """
    Preview what Terraform would create/change.
    
    By default uses simulation mode which parses HCL to estimate changes
    without requiring actual Terraform installation or credentials.
    """
    import uuid
    plan_id = f"plan-{uuid.uuid4().hex[:8]}"
    
    if use_simulation:
        # Simulate plan by parsing HCL
        try:
            resources = _simulate_plan_from_hcl(hcl_content)
            
            # Generate warnings for common issues
            warnings = []
            
            # Check for hardcoded values
            if "password" in hcl_content.lower() and "random_password" not in hcl_content.lower():
                warnings.append("Consider using random_password instead of hardcoded passwords")
            
            if re.search(r'location\s*=\s*"[^"]*"', hcl_content):
                warnings.append("Hardcoded region detected - consider using variables")
            
            # Check for missing tags
            if "tags" not in hcl_content.lower():
                warnings.append("No tags defined - consider adding tags for resource management")
            
            return TerraformPlanResult(
                success=True,
                plan_id=plan_id,
                resources=resources,
                warnings=warnings,
            )
        
        except Exception as e:
            logger.error("Plan simulation failed: %s", e)
            return TerraformPlanResult(
                success=False,
                plan_id=plan_id,
                errors=[f"Plan simulation failed: {str(e)}"],
            )
    
    # Actual Terraform plan (requires Terraform CLI)
    # This is disabled by default but can be enabled for advanced use
    return _run_actual_terraform_plan(hcl_content, plan_id)


def _run_actual_terraform_plan(hcl_content: str, plan_id: str) -> TerraformPlanResult:
    """Run actual Terraform plan command."""
    
    # Check if Terraform is available
    terraform_cmd = shutil.which("terraform")
    if not terraform_cmd:
        return TerraformPlanResult(
            success=False,
            plan_id=plan_id,
            errors=["Terraform CLI not found. Install Terraform to use actual plan preview."],
        )
    
    try:
        # Create temp directory for plan
        with tempfile.TemporaryDirectory(prefix="archmorph_plan_") as temp_dir:
            temp_path = Path(temp_dir)
            
            # Write HCL to file
            main_tf = temp_path / "main.tf"
            main_tf.write_text(hcl_content)
            
            # Initialize Terraform (skip backend)
            init_result = subprocess.run(
                [terraform_cmd, "init", "-backend=false", "-no-color"],
                cwd=temp_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if init_result.returncode != 0:
                return TerraformPlanResult(
                    success=False,
                    plan_id=plan_id,
                    errors=[f"Terraform init failed: {init_result.stderr}"],
                )
            
            # Run plan with JSON output
            plan_result = subprocess.run(
                [
                    terraform_cmd, "plan",
                    "-out=plan.out",
                    "-no-color",
                ],
                cwd=temp_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            # Convert plan to JSON
            show_result = subprocess.run(
                [terraform_cmd, "show", "-json", "plan.out"],
                cwd=temp_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            if show_result.returncode == 0:
                plan_json = json.loads(show_result.stdout)
                resources = _parse_terraform_plan_json(plan_json)
                
                return TerraformPlanResult(
                    success=True,
                    plan_id=plan_id,
                    resources=resources,
                    raw_output=plan_result.stdout,
                )
            else:
                # Parse text output as fallback
                resources = _simulate_plan_from_hcl(hcl_content)
                
                return TerraformPlanResult(
                    success=True,
                    plan_id=plan_id,
                    resources=resources,
                    raw_output=plan_result.stdout,
                    warnings=["Plan JSON unavailable, using simulation"],
                )
    
    except subprocess.TimeoutExpired:
        return TerraformPlanResult(
            success=False,
            plan_id=plan_id,
            errors=["Terraform plan timed out"],
        )
    except Exception as e:
        logger.error("Terraform plan failed: %s", e)
        return TerraformPlanResult(
            success=False,
            plan_id=plan_id,
            errors=[f"Terraform plan failed: {str(e)}"],
        )


def render_plan_preview(plan_result: TerraformPlanResult) -> str:
    """Render a human-readable plan preview."""
    lines = [
        "# Terraform Plan Preview",
        "",
        f"**Plan ID:** {plan_result.plan_id}",
        f"**Status:** {'✅ Success' if plan_result.success else '❌ Failed'}",
        "",
    ]
    
    summary = plan_result.get_summary()
    lines.extend([
        "## Summary",
        "",
        f"- **Total Resources:** {summary['total_resources']}",
        f"- **To Create:** {summary['to_create']} 🟢",
        f"- **To Update:** {summary['to_update']} 🟡",
        f"- **To Delete:** {summary['to_delete']} 🔴",
        f"- **To Replace:** {summary['to_replace']} 🟠",
        "",
    ])
    
    if plan_result.errors:
        lines.append("## Errors")
        lines.append("")
        for error in plan_result.errors:
            lines.append(f"- ❌ {error}")
        lines.append("")
    
    if plan_result.warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in plan_result.warnings:
            lines.append(f"- ⚠️ {warning}")
        lines.append("")
    
    if plan_result.resources:
        lines.append("## Resource Changes")
        lines.append("")
        
        # Group by action
        action_icons = {
            ResourceAction.CREATE: "🟢 Create",
            ResourceAction.UPDATE: "🟡 Update",
            ResourceAction.DELETE: "🔴 Delete",
            ResourceAction.REPLACE: "🟠 Replace",
            ResourceAction.NO_OP: "⚪ No Change",
            ResourceAction.READ: "📖 Read",
        }
        
        current_action = None
        for resource in sorted(plan_result.resources, key=lambda r: r.action.value):
            if resource.action != current_action:
                current_action = resource.action
                lines.append(f"### {action_icons[current_action]}")
                lines.append("")
            
            lines.append(f"- `{resource.address}`")
            if resource.reason:
                lines.append(f"  - Reason: {resource.reason}")
    
    return "\n".join(lines)


def validate_terraform_syntax(hcl_content: str) -> Dict[str, Any]:
    """Validate Terraform HCL syntax without running plan."""
    errors = []
    warnings = []
    
    # Basic syntax checks
    brace_count = hcl_content.count("{") - hcl_content.count("}")
    if brace_count != 0:
        errors.append(f"Unbalanced braces: {abs(brace_count)} {'extra opening' if brace_count > 0 else 'extra closing'}")
    
    # Check for common issues
    if re.search(r'=\s*=', hcl_content):
        errors.append("Double equals sign found - use single = for assignment")
    
    # Check for required blocks
    if "terraform {" not in hcl_content:
        warnings.append("Missing terraform {} block with required_providers")
    
    if "provider" not in hcl_content:
        warnings.append("No provider block found")
    
    # Resource naming
    invalid_names = re.findall(r'resource\s+"[^"]+"\s+"([^"]+)"', hcl_content)
    for name in invalid_names:
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', name):
            errors.append(f"Invalid resource name: {name} - must start with letter and contain only alphanumeric and underscores")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
