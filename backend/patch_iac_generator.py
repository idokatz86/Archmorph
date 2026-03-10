import re

with open('/Users/idokatz/VSCode/Archmorph/backend/iac_generator.py', 'r') as f:
    content = f.read()

# Add templates for pulumi and aws-cdk
template_map_replacement = """        template_map = {
            "terraform": "terraform_base.tf",
            "bicep": "bicep_base.bicep",
            "cloudformation": "cloudformation_base.yaml",
            "pulumi": "pulumi_base.ts",
            "aws-cdk": "aws-cdk_base.ts",
        }"""
content = re.sub(
    r'        template_map = \{\n            "terraform": "terraform_base\.tf",\n            "bicep": "bicep_base\.bicep",\n            "cloudformation": "cloudformation_base\.yaml",\n        \}', 
    template_map_replacement, 
    content
)

# Also update the function signature
content = re.sub(
    r'def generate_iac_code\(analysis: Optional\[dict\], iac_format: str = "terraform", params: Optional\[dict\] = None\) -> str:\n    """\n    Generate IaC code from analysis results using GPT-4o.\n    \n    If no analysis is available, returns a base template.\n    \n    Args:\n        analysis: The diagram analysis result \(mappings, services_detected, etc\.\)\n        iac_format: "terraform", "bicep", or "cloudformation"',
    'def generate_iac_code(analysis: Optional[dict], iac_format: str = "terraform", params: Optional[dict] = None) -> str:\n    """\n    Generate IaC code from analysis results using GPT-4o.\n    \n    If no analysis is available, returns a base template.\n    \n    Args:\n        analysis: The diagram analysis result (mappings, services_detected, etc.)\n        iac_format: "terraform", "bicep", "cloudformation", "pulumi", or "aws-cdk"',
    content
)

# Update build prompt mapping
prompt_map_replacement = """    # Build prompt and call GPT-4o
    if iac_format == "terraform":
        prompt = _build_terraform_prompt(analysis or {}, params)
    elif iac_format == "cloudformation":
        prompt = _build_cloudformation_prompt(analysis or {}, params)
    elif iac_format == "pulumi":
        prompt = _build_pulumi_prompt(analysis or {}, params)
    elif iac_format == "aws-cdk":
        prompt = _build_aws_cdk_prompt(analysis or {}, params)
    else:
        prompt = _build_bicep_prompt(analysis or {}, params)"""
        
content = re.sub(
    r'    # Build prompt and call GPT-4o\n    if iac_format == "terraform":\n        prompt = _build_terraform_prompt\(analysis or \{\}, params\)\n    elif iac_format == "cloudformation":\n        prompt = _build_cloudformation_prompt\(analysis or \{\}, params\)\n    else:\n        prompt = _build_bicep_prompt\(analysis or \{\}, params\)',
    prompt_map_replacement,
    content
)

# Update truncation warnings
trunc_warning_replacement = """            truncation_warning = {
                "terraform": "\\n\\n# ⚠️ WARNING: This output was truncated by the AI model.\\n# Some resources may be incomplete. Please review and regenerate if needed.\\n",
                "bicep": "\\n\\n// ⚠️ WARNING: This output was truncated by the AI model.\\n// Some resources may be incomplete. Please review and regenerate if needed.\\n",
                "cloudformation": "\\n\\n# ⚠️ WARNING: This output was truncated by the AI model.\\n# Some resources may be incomplete. Please review and regenerate if needed.\\n",
                "pulumi": "\\n\\n// ⚠️ WARNING: This output was truncated by the AI model.\\n// Some resources may be incomplete. Please review and regenerate if needed.\\n",
                "aws-cdk": "\\n\\n// ⚠️ WARNING: This output was truncated by the AI model.\\n// Some resources may be incomplete. Please review and regenerate if needed.\\n",
            }"""
content = re.sub(
    r'            truncation_warning = \{\n                "terraform": "\\n\\n# ⚠️ WARNING: This output was truncated by the AI model\.\\n# Some resources may be incomplete\. Please review and regenerate if needed\.\\n",\n                "bicep": "\\n\\n// ⚠️ WARNING: This output was truncated by the AI model\.\\n// Some resources may be incomplete\. Please review and regenerate if needed\.\\n",\n                "cloudformation": "\\n\\n# ⚠️ WARNING: This output was truncated by the AI model\.\\n# Some resources may be incomplete\. Please review and regenerate if needed\.\\n",\n            \}',
    trunc_warning_replacement,
    content
)

with open('/Users/idokatz/VSCode/Archmorph/backend/iac_generator.py', 'w') as f:
    f.write(content)
