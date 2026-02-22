"""
Infrastructure Import — Issue #155

Parse Terraform State, Terraform HCL, and CloudFormation templates to
reverse-engineer an architecture analysis. Removes the biggest adoption
friction — 80% of enterprises don't have a clean architecture diagram.

Supported Formats (Phase 1):
    - Terraform State (.tfstate) — JSON state file
    - Terraform HCL (.tf) — HCL configuration files
    - CloudFormation (.yaml/.json) — AWS CFN templates

Usage:
    from infra_import import parse_infrastructure, InfraFormat

    result = parse_infrastructure(content, InfraFormat.TERRAFORM_STATE)
    # → analysis-compatible dict with mappings, zones, connections
"""

from __future__ import annotations

import json
import logging
import re
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB for tfstate
MAX_TEMPLATE_SIZE = 10 * 1024 * 1024  # 10MB for templates

# Sensitive keys to strip from tfstate
SENSITIVE_KEYS = {
    "password", "secret", "access_key", "secret_key", "private_key",
    "token", "api_key", "connection_string", "sas_token", "account_key",
    "master_password", "admin_password", "db_password", "credentials",
    "client_secret", "certificate", "private_key_pem",
}


class InfraFormat(str, Enum):
    """Supported infrastructure file formats."""
    TERRAFORM_STATE = "terraform_state"
    TERRAFORM_HCL = "terraform_hcl"
    CLOUDFORMATION = "cloudformation"
    ARM_TEMPLATE = "arm_template"
    KUBERNETES = "kubernetes"
    DOCKER_COMPOSE = "docker_compose"


# ─────────────────────────────────────────────────────────────
# Provider → Service Mapping
# ─────────────────────────────────────────────────────────────

# Terraform AWS provider resource → service name mapping
AWS_TF_RESOURCE_MAP: Dict[str, Dict[str, str]] = {
    # Compute
    "aws_instance": {"service": "EC2", "category": "Compute"},
    "aws_launch_template": {"service": "EC2", "category": "Compute"},
    "aws_autoscaling_group": {"service": "EC2", "category": "Compute"},
    "aws_lambda_function": {"service": "Lambda", "category": "Compute"},
    "aws_lambda_layer_version": {"service": "Lambda", "category": "Compute"},
    "aws_ecs_cluster": {"service": "ECS", "category": "Compute"},
    "aws_ecs_service": {"service": "ECS", "category": "Compute"},
    "aws_ecs_task_definition": {"service": "ECS", "category": "Compute"},
    "aws_eks_cluster": {"service": "EKS", "category": "Compute"},
    "aws_eks_node_group": {"service": "EKS", "category": "Compute"},
    "aws_elastic_beanstalk_environment": {"service": "Elastic Beanstalk", "category": "Compute"},
    "aws_batch_job_definition": {"service": "Batch", "category": "Compute"},
    "aws_batch_compute_environment": {"service": "Batch", "category": "Compute"},
    "aws_apprunner_service": {"service": "App Runner", "category": "Compute"},
    # Storage
    "aws_s3_bucket": {"service": "S3", "category": "Storage"},
    "aws_s3_bucket_policy": {"service": "S3", "category": "Storage"},
    "aws_efs_file_system": {"service": "EFS", "category": "Storage"},
    "aws_fsx_lustre_file_system": {"service": "FSx", "category": "Storage"},
    "aws_fsx_windows_file_system": {"service": "FSx", "category": "Storage"},
    "aws_glacier_vault": {"service": "Glacier", "category": "Storage"},
    # Database
    "aws_db_instance": {"service": "RDS", "category": "Database"},
    "aws_db_cluster": {"service": "Aurora", "category": "Database"},
    "aws_rds_cluster": {"service": "Aurora", "category": "Database"},
    "aws_dynamodb_table": {"service": "DynamoDB", "category": "Database"},
    "aws_elasticache_cluster": {"service": "ElastiCache", "category": "Database"},
    "aws_elasticache_replication_group": {"service": "ElastiCache", "category": "Database"},
    "aws_neptune_cluster": {"service": "Neptune", "category": "Database"},
    "aws_docdb_cluster": {"service": "DocumentDB", "category": "Database"},
    "aws_redshift_cluster": {"service": "Redshift", "category": "Analytics"},
    "aws_opensearch_domain": {"service": "OpenSearch", "category": "Analytics"},
    "aws_elasticsearch_domain": {"service": "OpenSearch", "category": "Analytics"},
    # Networking
    "aws_vpc": {"service": "VPC", "category": "Networking"},
    "aws_subnet": {"service": "VPC", "category": "Networking"},
    "aws_security_group": {"service": "VPC", "category": "Networking"},
    "aws_lb": {"service": "ELB", "category": "Networking"},
    "aws_alb": {"service": "ALB", "category": "Networking"},
    "aws_lb_target_group": {"service": "ELB", "category": "Networking"},
    "aws_route53_zone": {"service": "Route 53", "category": "Networking"},
    "aws_route53_record": {"service": "Route 53", "category": "Networking"},
    "aws_cloudfront_distribution": {"service": "CloudFront", "category": "Networking"},
    "aws_api_gateway_rest_api": {"service": "API Gateway", "category": "Networking"},
    "aws_apigatewayv2_api": {"service": "API Gateway", "category": "Networking"},
    "aws_nat_gateway": {"service": "VPC", "category": "Networking"},
    "aws_internet_gateway": {"service": "VPC", "category": "Networking"},
    "aws_vpn_gateway": {"service": "VPN", "category": "Networking"},
    "aws_transit_gateway": {"service": "Transit Gateway", "category": "Networking"},
    "aws_dx_connection": {"service": "Direct Connect", "category": "Networking"},
    # Security
    "aws_iam_role": {"service": "IAM", "category": "Security"},
    "aws_iam_policy": {"service": "IAM", "category": "Security"},
    "aws_iam_user": {"service": "IAM", "category": "Security"},
    "aws_kms_key": {"service": "KMS", "category": "Security"},
    "aws_secretsmanager_secret": {"service": "Secrets Manager", "category": "Security"},
    "aws_acm_certificate": {"service": "Certificate Manager", "category": "Security"},
    "aws_cognito_user_pool": {"service": "Cognito", "category": "Security"},
    "aws_waf_web_acl": {"service": "WAF", "category": "Security"},
    "aws_wafv2_web_acl": {"service": "WAF", "category": "Security"},
    "aws_guardduty_detector": {"service": "GuardDuty", "category": "Security"},
    "aws_shield_protection": {"service": "Shield", "category": "Security"},
    # Integration
    "aws_sqs_queue": {"service": "SQS", "category": "Integration"},
    "aws_sns_topic": {"service": "SNS", "category": "Integration"},
    "aws_sfn_state_machine": {"service": "Step Functions", "category": "Integration"},
    "aws_mq_broker": {"service": "MQ", "category": "Integration"},
    "aws_msk_cluster": {"service": "MSK", "category": "Integration"},
    "aws_kinesis_stream": {"service": "Kinesis", "category": "Integration"},
    "aws_kinesis_firehose_delivery_stream": {"service": "Kinesis", "category": "Integration"},
    "aws_eventbridge_rule": {"service": "EventBridge", "category": "Integration"},
    # AI/ML
    "aws_sagemaker_notebook_instance": {"service": "SageMaker", "category": "AI/ML"},
    "aws_sagemaker_endpoint": {"service": "SageMaker", "category": "AI/ML"},
    "aws_bedrock_model_invocation_logging_configuration": {"service": "Bedrock", "category": "AI/ML"},
    # Analytics
    "aws_athena_workgroup": {"service": "Athena", "category": "Analytics"},
    "aws_glue_job": {"service": "Glue", "category": "Analytics"},
    "aws_glue_catalog_database": {"service": "Glue", "category": "Analytics"},
    "aws_emr_cluster": {"service": "EMR", "category": "Analytics"},
    "aws_lakeformation_resource": {"service": "Lake Formation", "category": "Analytics"},
    # Management
    "aws_cloudwatch_log_group": {"service": "CloudWatch", "category": "Management"},
    "aws_cloudwatch_metric_alarm": {"service": "CloudWatch", "category": "Management"},
    "aws_cloudtrail": {"service": "CloudTrail", "category": "Management"},
    "aws_config_configuration_recorder": {"service": "Config", "category": "Management"},
    "aws_ssm_parameter": {"service": "Systems Manager", "category": "Management"},
    # IoT
    "aws_iot_thing": {"service": "IoT Core", "category": "IoT"},
    "aws_iot_topic_rule": {"service": "IoT Core", "category": "IoT"},
}

# GCP Terraform resource mapping
GCP_TF_RESOURCE_MAP: Dict[str, Dict[str, str]] = {
    "google_compute_instance": {"service": "Compute Engine", "category": "Compute"},
    "google_compute_instance_group": {"service": "Compute Engine", "category": "Compute"},
    "google_cloud_run_service": {"service": "Cloud Run", "category": "Compute"},
    "google_cloud_run_v2_service": {"service": "Cloud Run", "category": "Compute"},
    "google_cloudfunctions_function": {"service": "Cloud Functions", "category": "Compute"},
    "google_cloudfunctions2_function": {"service": "Cloud Functions", "category": "Compute"},
    "google_container_cluster": {"service": "GKE", "category": "Compute"},
    "google_container_node_pool": {"service": "GKE", "category": "Compute"},
    "google_app_engine_application": {"service": "App Engine", "category": "Compute"},
    "google_storage_bucket": {"service": "Cloud Storage", "category": "Storage"},
    "google_sql_database_instance": {"service": "Cloud SQL", "category": "Database"},
    "google_spanner_instance": {"service": "Cloud Spanner", "category": "Database"},
    "google_firestore_database": {"service": "Firestore", "category": "Database"},
    "google_bigtable_instance": {"service": "Bigtable", "category": "Database"},
    "google_redis_instance": {"service": "Memorystore", "category": "Database"},
    "google_alloydb_cluster": {"service": "AlloyDB", "category": "Database"},
    "google_bigquery_dataset": {"service": "BigQuery", "category": "Analytics"},
    "google_bigquery_table": {"service": "BigQuery", "category": "Analytics"},
    "google_dataflow_job": {"service": "Dataflow", "category": "Analytics"},
    "google_dataproc_cluster": {"service": "Dataproc", "category": "Analytics"},
    "google_pubsub_topic": {"service": "Cloud Pub/Sub", "category": "Integration"},
    "google_pubsub_subscription": {"service": "Cloud Pub/Sub", "category": "Integration"},
    "google_compute_network": {"service": "VPC", "category": "Networking"},
    "google_compute_subnetwork": {"service": "VPC", "category": "Networking"},
    "google_compute_firewall": {"service": "VPC", "category": "Networking"},
    "google_compute_forwarding_rule": {"service": "Cloud Load Balancing", "category": "Networking"},
    "google_compute_url_map": {"service": "Cloud Load Balancing", "category": "Networking"},
    "google_dns_managed_zone": {"service": "Cloud DNS", "category": "Networking"},
    "google_compute_router": {"service": "Cloud Router", "category": "Networking"},
    "google_kms_key_ring": {"service": "Cloud KMS", "category": "Security"},
    "google_kms_crypto_key": {"service": "Cloud KMS", "category": "Security"},
    "google_secret_manager_secret": {"service": "Secret Manager", "category": "Security"},
    "google_service_account": {"service": "Cloud IAM", "category": "Security"},
    "google_project_iam_member": {"service": "Cloud IAM", "category": "Security"},
    "google_monitoring_alert_policy": {"service": "Cloud Monitoring", "category": "Management"},
    "google_logging_metric": {"service": "Cloud Logging", "category": "Management"},
    "google_artifact_registry_repository": {"service": "Artifact Registry", "category": "DevTools"},
}

# CloudFormation resource → service mapping
CFN_RESOURCE_MAP: Dict[str, Dict[str, str]] = {
    "AWS::EC2::Instance": {"service": "EC2", "category": "Compute"},
    "AWS::EC2::LaunchTemplate": {"service": "EC2", "category": "Compute"},
    "AWS::AutoScaling::AutoScalingGroup": {"service": "EC2", "category": "Compute"},
    "AWS::Lambda::Function": {"service": "Lambda", "category": "Compute"},
    "AWS::ECS::Cluster": {"service": "ECS", "category": "Compute"},
    "AWS::ECS::Service": {"service": "ECS", "category": "Compute"},
    "AWS::ECS::TaskDefinition": {"service": "ECS", "category": "Compute"},
    "AWS::EKS::Cluster": {"service": "EKS", "category": "Compute"},
    "AWS::ElasticBeanstalk::Environment": {"service": "Elastic Beanstalk", "category": "Compute"},
    "AWS::Batch::JobDefinition": {"service": "Batch", "category": "Compute"},
    "AWS::S3::Bucket": {"service": "S3", "category": "Storage"},
    "AWS::EFS::FileSystem": {"service": "EFS", "category": "Storage"},
    "AWS::RDS::DBInstance": {"service": "RDS", "category": "Database"},
    "AWS::RDS::DBCluster": {"service": "Aurora", "category": "Database"},
    "AWS::DynamoDB::Table": {"service": "DynamoDB", "category": "Database"},
    "AWS::ElastiCache::CacheCluster": {"service": "ElastiCache", "category": "Database"},
    "AWS::ElastiCache::ReplicationGroup": {"service": "ElastiCache", "category": "Database"},
    "AWS::Neptune::DBCluster": {"service": "Neptune", "category": "Database"},
    "AWS::DocDB::DBCluster": {"service": "DocumentDB", "category": "Database"},
    "AWS::Redshift::Cluster": {"service": "Redshift", "category": "Analytics"},
    "AWS::OpenSearchService::Domain": {"service": "OpenSearch", "category": "Analytics"},
    "AWS::EC2::VPC": {"service": "VPC", "category": "Networking"},
    "AWS::EC2::Subnet": {"service": "VPC", "category": "Networking"},
    "AWS::EC2::SecurityGroup": {"service": "VPC", "category": "Networking"},
    "AWS::ElasticLoadBalancingV2::LoadBalancer": {"service": "ALB", "category": "Networking"},
    "AWS::ElasticLoadBalancing::LoadBalancer": {"service": "ELB", "category": "Networking"},
    "AWS::Route53::HostedZone": {"service": "Route 53", "category": "Networking"},
    "AWS::CloudFront::Distribution": {"service": "CloudFront", "category": "Networking"},
    "AWS::ApiGateway::RestApi": {"service": "API Gateway", "category": "Networking"},
    "AWS::ApiGatewayV2::Api": {"service": "API Gateway", "category": "Networking"},
    "AWS::EC2::NatGateway": {"service": "VPC", "category": "Networking"},
    "AWS::EC2::InternetGateway": {"service": "VPC", "category": "Networking"},
    "AWS::EC2::TransitGateway": {"service": "Transit Gateway", "category": "Networking"},
    "AWS::IAM::Role": {"service": "IAM", "category": "Security"},
    "AWS::IAM::Policy": {"service": "IAM", "category": "Security"},
    "AWS::IAM::User": {"service": "IAM", "category": "Security"},
    "AWS::KMS::Key": {"service": "KMS", "category": "Security"},
    "AWS::SecretsManager::Secret": {"service": "Secrets Manager", "category": "Security"},
    "AWS::CertificateManager::Certificate": {"service": "Certificate Manager", "category": "Security"},
    "AWS::Cognito::UserPool": {"service": "Cognito", "category": "Security"},
    "AWS::WAFv2::WebACL": {"service": "WAF", "category": "Security"},
    "AWS::SQS::Queue": {"service": "SQS", "category": "Integration"},
    "AWS::SNS::Topic": {"service": "SNS", "category": "Integration"},
    "AWS::StepFunctions::StateMachine": {"service": "Step Functions", "category": "Integration"},
    "AWS::Kinesis::Stream": {"service": "Kinesis", "category": "Integration"},
    "AWS::Events::Rule": {"service": "EventBridge", "category": "Integration"},
    "AWS::SageMaker::NotebookInstance": {"service": "SageMaker", "category": "AI/ML"},
    "AWS::SageMaker::Endpoint": {"service": "SageMaker", "category": "AI/ML"},
    "AWS::Athena::WorkGroup": {"service": "Athena", "category": "Analytics"},
    "AWS::Glue::Job": {"service": "Glue", "category": "Analytics"},
    "AWS::EMR::Cluster": {"service": "EMR", "category": "Analytics"},
    "AWS::CloudWatch::Alarm": {"service": "CloudWatch", "category": "Management"},
    "AWS::Logs::LogGroup": {"service": "CloudWatch", "category": "Management"},
    "AWS::CloudTrail::Trail": {"service": "CloudTrail", "category": "Management"},
    "AWS::IoT::Thing": {"service": "IoT Core", "category": "IoT"},
}

# Cross-cloud Azure mapping (subset — full mapping lives in services/mappings.py)
SERVICE_TO_AZURE: Dict[str, Tuple[str, float]] = {
    # (azure_service, confidence)
    "EC2": ("Azure Virtual Machines", 0.95),
    "Lambda": ("Azure Functions", 0.90),
    "ECS": ("Azure Container Apps", 0.85),
    "EKS": ("Azure Kubernetes Service", 0.95),
    "Fargate": ("Azure Container Apps", 0.85),
    "App Runner": ("Azure Container Apps", 0.90),
    "Elastic Beanstalk": ("Azure App Service", 0.90),
    "Batch": ("Azure Batch", 0.90),
    "S3": ("Azure Blob Storage", 0.95),
    "EFS": ("Azure Files", 0.90),
    "FSx": ("Azure NetApp Files", 0.85),
    "Glacier": ("Azure Archive Storage", 0.95),
    "RDS": ("Azure SQL Database", 0.90),
    "Aurora": ("Azure Database for PostgreSQL", 0.85),
    "DynamoDB": ("Azure Cosmos DB", 0.90),
    "ElastiCache": ("Azure Cache for Redis", 0.90),
    "Neptune": ("Azure Cosmos DB (Gremlin)", 0.80),
    "DocumentDB": ("Azure Cosmos DB", 0.90),
    "Redshift": ("Azure Synapse Analytics", 0.85),
    "OpenSearch": ("Azure AI Search", 0.80),
    "VPC": ("Azure Virtual Network", 0.95),
    "ELB": ("Azure Load Balancer", 0.95),
    "ALB": ("Azure Application Gateway", 0.90),
    "NLB": ("Azure Load Balancer", 0.95),
    "Route 53": ("Azure DNS", 0.95),
    "CloudFront": ("Azure Front Door", 0.90),
    "API Gateway": ("Azure API Management", 0.85),
    "Transit Gateway": ("Azure Virtual WAN", 0.80),
    "Direct Connect": ("Azure ExpressRoute", 0.90),
    "VPN": ("Azure VPN Gateway", 0.95),
    "IAM": ("Microsoft Entra ID", 0.85),
    "KMS": ("Azure Key Vault", 0.95),
    "Secrets Manager": ("Azure Key Vault", 0.95),
    "Certificate Manager": ("Azure Key Vault", 0.90),
    "Cognito": ("Azure AD B2C", 0.80),
    "WAF": ("Azure WAF", 0.95),
    "GuardDuty": ("Microsoft Defender for Cloud", 0.85),
    "Shield": ("Azure DDoS Protection", 0.90),
    "SQS": ("Azure Queue Storage", 0.90),
    "SNS": ("Azure Event Grid", 0.85),
    "Step Functions": ("Azure Logic Apps", 0.80),
    "MQ": ("Azure Service Bus", 0.85),
    "MSK": ("Azure Event Hubs (Kafka)", 0.85),
    "Kinesis": ("Azure Event Hubs", 0.85),
    "EventBridge": ("Azure Event Grid", 0.85),
    "SageMaker": ("Azure Machine Learning", 0.85),
    "Bedrock": ("Azure OpenAI Service", 0.80),
    "Athena": ("Azure Synapse Serverless SQL", 0.80),
    "Glue": ("Azure Data Factory", 0.85),
    "EMR": ("Azure HDInsight", 0.80),
    "Lake Formation": ("Microsoft Purview", 0.75),
    "CloudWatch": ("Azure Monitor", 0.90),
    "CloudTrail": ("Azure Activity Log", 0.85),
    "Config": ("Azure Policy", 0.80),
    "Systems Manager": ("Azure Automation", 0.80),
    "IoT Core": ("Azure IoT Hub", 0.90),
    # GCP
    "Compute Engine": ("Azure Virtual Machines", 0.95),
    "Cloud Run": ("Azure Container Apps", 0.90),
    "Cloud Functions": ("Azure Functions", 0.90),
    "GKE": ("Azure Kubernetes Service", 0.95),
    "App Engine": ("Azure App Service", 0.85),
    "Cloud Storage": ("Azure Blob Storage", 0.95),
    "Cloud SQL": ("Azure Database for PostgreSQL", 0.90),
    "Cloud Spanner": ("Azure Cosmos DB", 0.80),
    "Firestore": ("Azure Cosmos DB", 0.90),
    "Bigtable": ("Azure Cosmos DB", 0.80),
    "Memorystore": ("Azure Cache for Redis", 0.90),
    "AlloyDB": ("Azure Database for PostgreSQL", 0.85),
    "BigQuery": ("Azure Synapse Analytics", 0.85),
    "Dataflow": ("Azure Stream Analytics", 0.80),
    "Dataproc": ("Azure HDInsight", 0.80),
    "Cloud Pub/Sub": ("Azure Service Bus", 0.85),
    "Cloud Load Balancing": ("Azure Load Balancer", 0.90),
    "Cloud DNS": ("Azure DNS", 0.95),
    "Cloud Router": ("Azure Virtual WAN", 0.80),
    "Cloud KMS": ("Azure Key Vault", 0.95),
    "Secret Manager": ("Azure Key Vault", 0.95),
    "Cloud IAM": ("Microsoft Entra ID", 0.85),
    "Cloud Monitoring": ("Azure Monitor", 0.90),
    "Cloud Logging": ("Azure Monitor Logs", 0.85),
    "Artifact Registry": ("Azure Container Registry", 0.90),
}


# ─────────────────────────────────────────────────────────────
# Security: Strip sensitive values
# ─────────────────────────────────────────────────────────────

def _strip_sensitive(obj: Any) -> Any:
    """Recursively strip sensitive values from parsed data."""
    if isinstance(obj, dict):
        return {
            k: ("***REDACTED***" if _is_sensitive_key(k) else _strip_sensitive(v))
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [_strip_sensitive(item) for item in obj]
    return obj


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    key_lower = key.lower()
    return any(s in key_lower for s in SENSITIVE_KEYS)


# ─────────────────────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────────────────────

def _detect_provider(resources: List[Dict[str, Any]]) -> str:
    """Auto-detect cloud provider from resource types."""
    aws_count = sum(1 for r in resources if r.get("provider", "").startswith("aws"))
    gcp_count = sum(1 for r in resources if r.get("provider", "").startswith("gcp"))
    if gcp_count > aws_count:
        return "gcp"
    return "aws"


def _parse_terraform_state(content: str) -> Dict[str, Any]:
    """Parse Terraform .tfstate JSON file."""
    try:
        state = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in Terraform state file: {e}")

    version = state.get("version", 0)
    if version < 3:
        raise ValueError(f"Terraform state version {version} is not supported (need v3+)")

    resources_raw = state.get("resources", [])
    if not resources_raw:
        raise ValueError("No resources found in Terraform state file")

    parsed_resources: List[Dict[str, Any]] = []

    for resource in resources_raw:
        rtype = resource.get("type", "")
        mode = resource.get("mode", "managed")
        if mode != "managed":
            continue

        provider = resource.get("provider", "")
        instances = resource.get("instances", [])

        # Determine provider
        if "aws" in provider.lower() or rtype.startswith("aws_"):
            cloud = "aws"
            mapping = AWS_TF_RESOURCE_MAP.get(rtype)
        elif "google" in provider.lower() or rtype.startswith("google_"):
            cloud = "gcp"
            mapping = GCP_TF_RESOURCE_MAP.get(rtype)
        else:
            continue  # Skip non-cloud resources (local, null, etc.)

        if not mapping:
            # Unknown resource type — skip
            logger.debug("Skipping unknown resource type: %s", rtype)
            continue

        for instance in instances:
            attrs = instance.get("attributes", {})
            name = (
                resource.get("name", "")
                or attrs.get("name", "")
                or attrs.get("tags", {}).get("Name", "")
                or rtype
            )

            parsed_resources.append({
                "resource_type": rtype,
                "name": name,
                "provider": cloud,
                "service": mapping["service"],
                "category": mapping["category"],
                "attributes": _strip_sensitive(attrs),
            })

    return _build_analysis(parsed_resources, "terraform_state")


def _parse_terraform_hcl(content: str) -> Dict[str, Any]:
    """
    Parse Terraform HCL files. Since we can't install hcl2 parser in all
    environments, we use regex-based extraction for resource blocks.
    """
    # Match resource "type" "name" { ... }
    resource_pattern = re.compile(
        r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{',
        re.MULTILINE,
    )

    parsed_resources: List[Dict[str, Any]] = []
    matches = resource_pattern.findall(content)

    if not matches:
        raise ValueError("No resource blocks found in Terraform HCL file")

    for rtype, name in matches:
        if rtype.startswith("aws_"):
            cloud = "aws"
            mapping = AWS_TF_RESOURCE_MAP.get(rtype)
        elif rtype.startswith("google_"):
            cloud = "gcp"
            mapping = GCP_TF_RESOURCE_MAP.get(rtype)
        else:
            continue

        if not mapping:
            logger.debug("Skipping unknown HCL resource type: %s", rtype)
            continue

        parsed_resources.append({
            "resource_type": rtype,
            "name": name,
            "provider": cloud,
            "service": mapping["service"],
            "category": mapping["category"],
            "attributes": {},
        })

    return _build_analysis(parsed_resources, "terraform_hcl")


def _parse_cloudformation(content: str) -> Dict[str, Any]:
    """Parse AWS CloudFormation template (JSON or YAML)."""
    # Try JSON first
    template = None
    try:
        template = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try YAML
    if template is None:
        try:
            import yaml
            template = yaml.safe_load(content)
        except Exception:
            pass

    if template is None:
        raise ValueError("Could not parse CloudFormation template as JSON or YAML")

    # Validate it's a CFN template
    if not isinstance(template, dict):
        raise ValueError("CloudFormation template must be a JSON/YAML object")

    resources = template.get("Resources", template.get("resources", {}))
    if not resources:
        raise ValueError("No Resources section found in CloudFormation template")

    parsed_resources: List[Dict[str, Any]] = []

    for logical_id, resource_def in resources.items():
        if not isinstance(resource_def, dict):
            continue

        rtype = resource_def.get("Type", "")
        properties = resource_def.get("Properties", {})

        mapping = CFN_RESOURCE_MAP.get(rtype)
        if not mapping:
            logger.debug("Skipping unknown CFN resource type: %s", rtype)
            continue

        name = (
            properties.get("Name", "")
            or properties.get("FunctionName", "")
            or properties.get("ClusterName", "")
            or properties.get("BucketName", "")
            or properties.get("TableName", "")
            or properties.get("DomainName", "")
            or logical_id
        )

        parsed_resources.append({
            "resource_type": rtype,
            "name": str(name),
            "provider": "aws",
            "service": mapping["service"],
            "category": mapping["category"],
            "attributes": _strip_sensitive(properties),
        })

    return _build_analysis(parsed_resources, "cloudformation")


# ─────────────────────────────────────────────────────────────
# Analysis Builder
# ─────────────────────────────────────────────────────────────

def _build_analysis(
    resources: List[Dict[str, Any]],
    source_format: str,
) -> Dict[str, Any]:
    """Build an analysis-compatible result from parsed resources."""
    if not resources:
        raise ValueError("No supported cloud resources found in the file")

    provider = _detect_provider(resources)

    # Deduplicate services
    seen_services: Dict[str, Dict[str, Any]] = {}
    for r in resources:
        svc = r["service"]
        if svc not in seen_services:
            seen_services[svc] = {
                "service": svc,
                "category": r["category"],
                "provider": r["provider"],
                "instance_count": 0,
                "resource_types": set(),
            }
        seen_services[svc]["instance_count"] += 1
        seen_services[svc]["resource_types"].add(r["resource_type"])

    # Build mappings (compatible with analysis["mappings"])
    mappings: List[Dict[str, Any]] = []
    for svc_name, svc_info in seen_services.items():
        azure_info = SERVICE_TO_AZURE.get(svc_name, ("Manual mapping required", 0.5))
        azure_service, confidence = azure_info

        mappings.append({
            "source_service": svc_name,
            "source_provider": svc_info["provider"],
            "azure_service": azure_service,
            "confidence": confidence,
            "category": svc_info["category"],
            "notes": f"Imported from {source_format}: {svc_info['instance_count']} instance(s)",
        })

    # Build zones (group by category)
    categories: Dict[str, List[Dict[str, Any]]] = {}
    for m in mappings:
        cat = m["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            "source": m["source_service"],
            "azure": m["azure_service"],
            "confidence": m["confidence"],
        })

    zones = []
    for idx, (cat_name, services) in enumerate(sorted(categories.items()), 1):
        zones.append({
            "id": idx,
            "name": cat_name,
            "number": idx,
            "services": services,
        })

    # Infer connections from resource references
    connections = _infer_connections(resources)

    # Confidence summary
    confidences = [m["confidence"] for m in mappings]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    return {
        "diagram_id": None,  # Will be set by the router
        "diagram_type": f"imported_{source_format}",
        "source_provider": provider,
        "target_provider": "azure",
        "architecture_patterns": _detect_patterns(seen_services),
        "services_detected": len(seen_services),
        "zones": zones,
        "mappings": mappings,
        "warnings": [],
        "service_connections": connections,
        "confidence_summary": {
            "high": sum(1 for c in confidences if c >= 0.90),
            "medium": sum(1 for c in confidences if 0.75 <= c < 0.90),
            "low": sum(1 for c in confidences if c < 0.75),
            "average": round(avg_conf, 3),
        },
        "import_metadata": {
            "source_format": source_format,
            "total_resources": len(resources),
            "unique_services": len(seen_services),
            "provider": provider,
        },
    }


def _detect_patterns(services: Dict[str, Dict[str, Any]]) -> List[str]:
    """Detect architecture patterns from services."""
    patterns = []
    svc_names = set(services.keys())

    if svc_names & {"EKS", "ECS", "GKE", "Fargate"}:
        patterns.append("containerized")
    if svc_names & {"Lambda", "Cloud Functions"}:
        patterns.append("serverless")
    if svc_names & {"API Gateway"}:
        patterns.append("api-driven")
    if svc_names & {"SQS", "SNS", "Kinesis", "EventBridge", "Cloud Pub/Sub", "MSK"}:
        patterns.append("event-driven")
    if svc_names & {"CloudFront", "Route 53", "Cloud CDN"}:
        patterns.append("cdn-distributed")
    if svc_names & {"RDS", "Aurora", "DynamoDB", "Cloud SQL", "Cloud Spanner"}:
        patterns.append("database-backed")
    if svc_names & {"SageMaker", "Bedrock"}:
        patterns.append("ml-powered")
    if svc_names & {"VPC"}:
        patterns.append("vpc-isolated")
    if svc_names & {"ElastiCache", "Memorystore"}:
        patterns.append("cached")

    return patterns if patterns else ["standard"]


def _infer_connections(resources: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Infer service connections from common patterns."""
    connections = []
    svc_names = set(r["service"] for r in resources)

    # Common connection patterns
    conn_patterns = [
        ("ALB", "ECS", "HTTPS"), ("ALB", "EC2", "HTTPS"),
        ("ALB", "EKS", "HTTPS"), ("ELB", "EC2", "TCP"),
        ("CloudFront", "S3", "HTTPS"), ("CloudFront", "ALB", "HTTPS"),
        ("API Gateway", "Lambda", "HTTPS"),
        ("Lambda", "DynamoDB", "AWS SDK"), ("Lambda", "S3", "AWS SDK"),
        ("Lambda", "SQS", "AWS SDK"),
        ("ECS", "RDS", "TCP/5432"), ("ECS", "ElastiCache", "TCP/6379"),
        ("ECS", "S3", "AWS SDK"),
        ("EKS", "RDS", "TCP/5432"), ("EKS", "ElastiCache", "TCP/6379"),
        ("EC2", "RDS", "TCP/5432"), ("EC2", "S3", "AWS SDK"),
        ("SQS", "Lambda", "Event"), ("SNS", "SQS", "Event"),
        ("SNS", "Lambda", "Event"), ("EventBridge", "Lambda", "Event"),
        ("Kinesis", "Lambda", "Event"),
        ("Route 53", "CloudFront", "DNS"), ("Route 53", "ALB", "DNS"),
        # GCP
        ("Cloud Load Balancing", "Cloud Run", "HTTPS"),
        ("Cloud Load Balancing", "GKE", "HTTPS"),
        ("Cloud Run", "Cloud SQL", "TCP"), ("Cloud Run", "Firestore", "gRPC"),
        ("Cloud Functions", "Cloud Storage", "Event"),
        ("Cloud Functions", "Cloud Pub/Sub", "Event"),
        ("Cloud Pub/Sub", "Cloud Functions", "Event"),
        ("GKE", "Cloud SQL", "TCP"), ("GKE", "Memorystore", "TCP/6379"),
    ]

    for src, dst, protocol in conn_patterns:
        if src in svc_names and dst in svc_names:
            connections.append({
                "from": src,
                "to": dst,
                "protocol": protocol,
            })

    return connections


# ─────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────

PARSERS = {
    InfraFormat.TERRAFORM_STATE: _parse_terraform_state,
    InfraFormat.TERRAFORM_HCL: _parse_terraform_hcl,
    InfraFormat.CLOUDFORMATION: _parse_cloudformation,
}


def parse_infrastructure(
    content: str,
    format: InfraFormat,
    diagram_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parse infrastructure-as-code file into an analysis-compatible result.

    Args:
        content: File content as string.
        format: InfraFormat enum specifying the file type.
        diagram_id: Optional diagram ID to assign to the result.

    Returns:
        Analysis-compatible dict with mappings, zones, connections.

    Raises:
        ValueError: If the file cannot be parsed or contains no resources.
    """
    start_time = time.time()

    # Size checks
    size = len(content.encode("utf-8"))
    if format == InfraFormat.TERRAFORM_STATE and size > MAX_FILE_SIZE:
        raise ValueError(f"Terraform state file exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit")
    elif size > MAX_TEMPLATE_SIZE:
        raise ValueError(f"Template file exceeds {MAX_TEMPLATE_SIZE // (1024*1024)}MB limit")

    parser = PARSERS.get(format)
    if not parser:
        raise ValueError(f"Unsupported format: {format.value}. Supported: {[f.value for f in PARSERS]}")

    result = parser(content)

    if diagram_id:
        result["diagram_id"] = diagram_id

    elapsed = round((time.time() - start_time) * 1000, 1)
    result["import_metadata"]["parse_time_ms"] = elapsed

    logger.info(
        "Parsed %s: %d services from %d resources in %.1fms",
        format.value,
        result["services_detected"],
        result["import_metadata"]["total_resources"],
        elapsed,
    )

    return result


def detect_format(filename: str, content: str) -> Optional[InfraFormat]:
    """Auto-detect infrastructure file format from filename and content."""
    lower = filename.lower()

    if lower.endswith(".tfstate"):
        return InfraFormat.TERRAFORM_STATE
    if lower.endswith(".tf"):
        return InfraFormat.TERRAFORM_HCL

    # Try to detect from content
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            # Terraform state
            if "terraform_version" in data and "resources" in data:
                return InfraFormat.TERRAFORM_STATE
            # CloudFormation
            if "AWSTemplateFormatVersion" in data or "Resources" in data:
                return InfraFormat.CLOUDFORMATION
    except (json.JSONDecodeError, ValueError):
        pass

    # YAML CloudFormation
    if "AWSTemplateFormatVersion" in content or "AWS::CloudFormation" in content:
        return InfraFormat.CLOUDFORMATION

    # HCL detection
    if re.search(r'resource\s+"(aws_|google_)', content):
        return InfraFormat.TERRAFORM_HCL

    return None
