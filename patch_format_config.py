import re

with open('/Users/idokatz/VSCode/Archmorph/backend/iac_generator.py', 'r') as f:
    content = f.read()

pulumi_config = """    "pulumi": {
        "expert_role": "Cloud infrastructure engineer",
        "code_type": "Pulumi TypeScript code",
        "target_field": "azure_service",
        "target_label": "Azure",
        "use_azure_region": True,
        "requirements": (
            "1. Use @pulumi/azure-native provider\\n"
            "2. Follow standard Pulumi naming conventions\\n"
            "3. Use constants/interfaces for configuration\\n"
            "4. Include a ResourceGroup as the foundation\\n"
            "5. Generate EVERY Azure resource from the mappings above\\n"
            "6. Group logically with clear comments\\n"
            "7. Export key outputs using pulumi.export\\n"
            "8. **CRITICAL:** Use secret management for all credentials\\n"
        ),
        "return_instruction": "Return ONLY the Pulumi TypeScript code, no markdown fences, no explanations.",
    },"""

aws_cdk_config = """    "aws-cdk": {
        "expert_role": "AWS infrastructure expert",
        "code_type": "AWS CDK TypeScript code",
        "target_field": "aws_service",
        "target_label": "AWS",
        "use_azure_region": False,
        "requirements": (
            "1. Use AWS CDK v2 (aws-cdk-lib)\\n"
            "2. Define standard AWS architectures logically within Stacks\\n"
            "3. Include the App, Stack, and required Constructs\\n"
            "4. Export stack outputs where relevant\\n"
            "5. Apply standard AWS security best practices\\n"
            "6. Generate EVERY AWS resource from the mappings above\\n"
            "7. **CRITICAL:** Do NOT hardcode credentials. Use Secrets Manager or SSM.\\n"
        ),
        "return_instruction": "Return ONLY the AWS CDK TypeScript code, no markdown fences, no explanations.",
    }"""

# Insert into dictionary
replacement = f"""{pulumi_config}\n{aws_cdk_config}\n}}"""
content = re.sub(
    r'        "return_instruction": "Return ONLY the CloudFormation YAML, no markdown \\nfences, no explanations\.",\s*\},\s*\}', 
    f'        "return_instruction": "Return ONLY the CloudFormation YAML, no markdown \\nfences, no explanations.",\n    }},\n{replacement}', 
    content,
    flags=re.DOTALL
)

# And if there's without newline
content = re.sub(
    r'        "return_instruction": "Return ONLY the CloudFormation YAML, no markdown fences, no explanations\.",\s*\}\s*\}', 
    f'        "return_instruction": "Return ONLY the CloudFormation YAML, no markdown fences, no explanations.",\n    }},\n{replacement}', 
    content,
    flags=re.DOTALL
)


# Add wrappers
wrapper_replacement = """def _build_cloudformation_prompt(analysis: dict, params: dict) -> str:
    return _build_iac_prompt("cloudformation", analysis, params)


def _build_pulumi_prompt(analysis: dict, params: dict) -> str:
    return _build_iac_prompt("pulumi", analysis, params)


def _build_aws_cdk_prompt(analysis: dict, params: dict) -> str:
    return _build_iac_prompt("aws-cdk", analysis, params)"""

content = re.sub(
    r'def _build_cloudformation_prompt\(analysis: dict, params: dict\) -> str:\n    return _build_iac_prompt\("cloudformation", analysis, params\)', 
    wrapper_replacement, 
    content
)

with open('/Users/idokatz/VSCode/Archmorph/backend/iac_generator.py', 'w') as f:
    f.write(content)
