"""Deterministic backend responses for CI full-spine smoke tests."""

from __future__ import annotations

import os
from copy import deepcopy


def enabled() -> bool:
    return os.getenv("ARCHMORPH_CI_SMOKE_MODE", "").lower() in {"1", "true", "yes"}


def classification() -> dict:
    return {
        "is_architecture_diagram": True,
        "confidence": 0.99,
        "image_type": "architecture_diagram",
        "reason": "CI smoke mode",
    }


def analysis(diagram_id: str) -> dict:
    payload = {
        "diagram_type": "AWS Architecture",
        "title": "CLI Full-Spine Smoke",
        "source_provider": "aws",
        "target_provider": "azure",
        "architecture_patterns": ["multi-AZ", "web-tier"],
        "services_detected": 3,
        "zones": [
            {
                "id": 1,
                "name": "Application",
                "number": 1,
                "services": [
                    {"aws": "EC2", "azure": "Azure Virtual Machines", "confidence": 0.92},
                    {"aws": "S3", "azure": "Azure Blob Storage", "confidence": 0.95},
                    {"aws": "CloudWatch", "azure": "Azure Monitor", "confidence": 0.9},
                ],
            }
        ],
        "mappings": [
            {
                "source_service": "EC2",
                "source_provider": "aws",
                "azure_service": "Azure Virtual Machines",
                "category": "Compute",
                "confidence": 0.92,
            },
            {
                "source_service": "S3",
                "source_provider": "aws",
                "azure_service": "Azure Blob Storage",
                "category": "Storage",
                "confidence": 0.95,
            },
            {
                "source_service": "CloudWatch",
                "source_provider": "aws",
                "azure_service": "Azure Monitor",
                "category": "Monitoring",
                "confidence": 0.9,
            },
        ],
        "service_connections": [
            {"from": "EC2", "to": "S3", "protocol": "HTTPS", "type": "storage"},
            {"from": "CloudWatch", "to": "EC2", "protocol": "HTTPS", "type": "metrics"},
        ],
        "warnings": [],
        "confidence_summary": {"high": 3, "medium": 0, "low": 0, "average": 0.92},
    }
    payload["diagram_id"] = diagram_id
    payload["image_classification"] = classification()
    return payload


def iac_code(iac_format: str, project_name: str = "cli-smoke", region: str = "westeurope") -> str:
    if iac_format == "bicep":
        return f"""targetScope = 'subscription'

param location string = '{region}'

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {{
  name: 'rg-{project_name}'
  location: location
}}

output resourceGroupName string = rg.name
"""
    if iac_format == "terraform":
        return f"""terraform {{
  required_version = ">= 1.5"
}}

resource "terraform_data" "main" {{
  input = {{
    project = "{project_name}"
    region  = "{region}"
  }}
}}

output "project_name" {{
  value = terraform_data.main.input.project
}}
"""
    return f"# Unsupported CI smoke IaC format: {iac_format}\n"


def clone_analysis(diagram_id: str) -> dict:
    return deepcopy(analysis(diagram_id))
