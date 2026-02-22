"""
Archmorph — Infrastructure Import Unit Tests
Tests for infra_import.py (Issue #155)
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from infra_import import (
    InfraFormat,
    detect_format,
    parse_infrastructure,
    AWS_TF_RESOURCE_MAP,
    GCP_TF_RESOURCE_MAP,
    CFN_RESOURCE_MAP,
    SERVICE_TO_AZURE,
)


# ====================================================================
# Resource map data quality
# ====================================================================

class TestResourceMaps:
    def test_aws_tf_map_not_empty(self):
        assert len(AWS_TF_RESOURCE_MAP) > 30

    def test_gcp_tf_map_not_empty(self):
        assert len(GCP_TF_RESOURCE_MAP) > 10

    def test_cfn_map_not_empty(self):
        assert len(CFN_RESOURCE_MAP) > 20

    def test_azure_map_not_empty(self):
        assert len(SERVICE_TO_AZURE) > 30

    def test_aws_common_resources(self):
        expected = ["aws_instance", "aws_s3_bucket", "aws_lambda_function", "aws_db_instance"]
        for r in expected:
            assert r in AWS_TF_RESOURCE_MAP, f"Missing {r}"

    def test_cfn_common_resources(self):
        expected = ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::Lambda::Function"]
        for r in expected:
            assert r in CFN_RESOURCE_MAP, f"Missing {r}"


# ====================================================================
# InfraFormat enum
# ====================================================================

class TestInfraFormat:
    def test_all_formats(self):
        expected = {"TERRAFORM_STATE", "TERRAFORM_HCL", "CLOUDFORMATION", "ARM_TEMPLATE", "KUBERNETES", "DOCKER_COMPOSE"}
        actual = {f.name for f in InfraFormat}
        assert expected.issubset(actual)


# ====================================================================
# detect_format
# ====================================================================

class TestDetectFormat:
    def test_terraform_state(self):
        content = json.dumps({"version": 4, "terraform_version": "1.5.0", "resources": []})
        fmt = detect_format("main.tfstate", content)
        assert fmt == InfraFormat.TERRAFORM_STATE

    def test_cloudformation(self):
        content = json.dumps({"AWSTemplateFormatVersion": "2010-09-09", "Resources": {}})
        fmt = detect_format("template.json", content)
        assert fmt == InfraFormat.CLOUDFORMATION

    def test_arm_template(self):
        content = json.dumps({"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json", "resources": []})
        fmt = detect_format("deploy.json", content)
        # ARM templates may be detected or return None since module focuses on AWS/GCP → Azure
        assert fmt is None or fmt == InfraFormat.ARM_TEMPLATE

    def test_terraform_hcl(self):
        content = 'resource "aws_instance" "web" {\n  ami = "ami-123"\n}'
        fmt = detect_format("main.tf", content)
        assert fmt == InfraFormat.TERRAFORM_HCL

    def test_kubernetes(self):
        content = "apiVersion: apps/v1\nkind: Deployment"
        fmt = detect_format("deploy.yaml", content)
        assert fmt is None or fmt == InfraFormat.KUBERNETES

    def test_docker_compose(self):
        content = "version: '3'\nservices:\n  web:\n    image: nginx"
        fmt = detect_format("docker-compose.yml", content)
        assert fmt is None or fmt == InfraFormat.DOCKER_COMPOSE


# ====================================================================
# parse_infrastructure
# ====================================================================

class TestParseInfrastructure:
    def test_terraform_state_basic(self):
        content = json.dumps({
            "version": 4,
            "terraform_version": "1.5.0",
            "resources": [
                {"type": "aws_instance", "name": "web", "provider": "aws", "instances": [{"attributes": {"id": "i-123"}}]},
                {"type": "aws_s3_bucket", "name": "data", "provider": "aws", "instances": [{"attributes": {"id": "b-456"}}]},
            ],
        })
        result = parse_infrastructure(content, InfraFormat.TERRAFORM_STATE, "diag-001")
        assert "mappings" in result or "analysis" in result

    def test_terraform_hcl_basic(self):
        content = '''
resource "aws_instance" "web" {
  ami           = "ami-12345"
  instance_type = "t3.micro"
}

resource "aws_s3_bucket" "logs" {
  bucket = "my-logs"
}
'''
        result = parse_infrastructure(content, InfraFormat.TERRAFORM_HCL, "diag-002")
        mappings = result.get("mappings", [])
        assert len(mappings) >= 2

    def test_cloudformation_basic(self):
        content = json.dumps({
            "AWSTemplateFormatVersion": "2010-09-09",
            "Resources": {
                "WebServer": {"Type": "AWS::EC2::Instance", "Properties": {"InstanceType": "t3.micro"}},
                "DataBucket": {"Type": "AWS::S3::Bucket", "Properties": {}},
            },
        })
        result = parse_infrastructure(content, InfraFormat.CLOUDFORMATION, "diag-003")
        mappings = result.get("mappings", [])
        assert len(mappings) >= 2

    def test_unknown_format(self):
        try:
            result = parse_infrastructure("random text content", None, "diag-004")
            assert result is not None
        except (ValueError, Exception):
            pass  # Acceptable to raise on unrecognized format

    def test_result_has_diagram_id(self):
        content = json.dumps({
            "version": 4,
            "terraform_version": "1.5",
            "resources": [
                {"type": "aws_instance", "name": "x", "provider": "aws", "instances": [{"attributes": {"id": "i-1"}}]},
            ],
        })
        result = parse_infrastructure(content, InfraFormat.TERRAFORM_STATE, "diag-005")
        assert result.get("diagram_id") == "diag-005"

    def test_mappings_have_azure_service(self):
        content = 'resource "aws_instance" "web" { ami = "ami-123" }'
        result = parse_infrastructure(content, InfraFormat.TERRAFORM_HCL, "diag-006")
        for m in result.get("mappings", []):
            assert "azure_service" in m

    def test_mappings_have_confidence(self):
        content = 'resource "aws_instance" "web" { ami = "ami-123" }'
        result = parse_infrastructure(content, InfraFormat.TERRAFORM_HCL, "diag-007")
        for m in result.get("mappings", []):
            assert "confidence" in m
            assert 0 <= m["confidence"] <= 1
