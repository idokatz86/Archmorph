"""
Terraform / CloudFormation / ARM State Import Service (#497).

Parses infrastructure state files and transforms discovered resources
into the Archmorph analysis schema (zones → services) so they can be
visualized, translated, and cost-estimated like hand-drawn diagrams.
"""

import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Resource-type → category mapping tables
# ─────────────────────────────────────────────────────────────

AWS_CATEGORY_MAP: Dict[str, str] = {
    # Compute
    "aws_instance": "Compute",
    "aws_launch_template": "Compute",
    "aws_autoscaling_group": "Compute",
    "aws_ecs_cluster": "Compute",
    "aws_ecs_service": "Compute",
    "aws_ecs_task_definition": "Compute",
    "aws_eks_cluster": "Compute",
    "aws_lambda_function": "Compute",
    "aws_lightsail_instance": "Compute",
    "aws_batch_job_definition": "Compute",
    # Storage
    "aws_s3_bucket": "Storage",
    "aws_s3_bucket_policy": "Storage",
    "aws_ebs_volume": "Storage",
    "aws_efs_file_system": "Storage",
    "aws_glacier_vault": "Storage",
    # Database
    "aws_db_instance": "Database",
    "aws_rds_cluster": "Database",
    "aws_dynamodb_table": "Database",
    "aws_elasticache_cluster": "Database",
    "aws_elasticache_replication_group": "Database",
    "aws_redshift_cluster": "Database",
    "aws_docdb_cluster": "Database",
    # Networking
    "aws_vpc": "Networking",
    "aws_subnet": "Networking",
    "aws_security_group": "Networking",
    "aws_route_table": "Networking",
    "aws_internet_gateway": "Networking",
    "aws_nat_gateway": "Networking",
    "aws_lb": "Networking",
    "aws_alb": "Networking",
    "aws_elb": "Networking",
    "aws_route53_zone": "Networking",
    "aws_route53_record": "Networking",
    "aws_cloudfront_distribution": "Networking",
    "aws_api_gateway_rest_api": "Networking",
    "aws_apigatewayv2_api": "Networking",
    # Messaging
    "aws_sqs_queue": "Messaging",
    "aws_sns_topic": "Messaging",
    "aws_kinesis_stream": "Messaging",
    "aws_mq_broker": "Messaging",
    # Security
    "aws_iam_role": "Security",
    "aws_iam_policy": "Security",
    "aws_iam_user": "Security",
    "aws_kms_key": "Security",
    "aws_secretsmanager_secret": "Security",
    "aws_acm_certificate": "Security",
    "aws_waf_web_acl": "Security",
    "aws_wafv2_web_acl": "Security",
    # Monitoring
    "aws_cloudwatch_log_group": "Monitoring",
    "aws_cloudwatch_metric_alarm": "Monitoring",
    "aws_cloudtrail": "Monitoring",
    # AI/ML
    "aws_sagemaker_endpoint": "AI/ML",
    "aws_sagemaker_notebook_instance": "AI/ML",
}

AZURE_CATEGORY_MAP: Dict[str, str] = {
    # Compute
    "azurerm_virtual_machine": "Compute",
    "azurerm_linux_virtual_machine": "Compute",
    "azurerm_windows_virtual_machine": "Compute",
    "azurerm_virtual_machine_scale_set": "Compute",
    "azurerm_container_group": "Compute",
    "azurerm_container_app": "Compute",
    "azurerm_kubernetes_cluster": "Compute",
    "azurerm_function_app": "Compute",
    "azurerm_linux_function_app": "Compute",
    "azurerm_windows_function_app": "Compute",
    "azurerm_app_service": "Compute",
    "azurerm_linux_web_app": "Compute",
    "azurerm_windows_web_app": "Compute",
    "azurerm_service_plan": "Compute",
    # Storage
    "azurerm_storage_account": "Storage",
    "azurerm_storage_container": "Storage",
    "azurerm_storage_blob": "Storage",
    "azurerm_managed_disk": "Storage",
    "azurerm_storage_share": "Storage",
    # Database
    "azurerm_mssql_server": "Database",
    "azurerm_mssql_database": "Database",
    "azurerm_postgresql_server": "Database",
    "azurerm_postgresql_flexible_server": "Database",
    "azurerm_mysql_server": "Database",
    "azurerm_mysql_flexible_server": "Database",
    "azurerm_cosmosdb_account": "Database",
    "azurerm_redis_cache": "Database",
    # Networking
    "azurerm_virtual_network": "Networking",
    "azurerm_subnet": "Networking",
    "azurerm_network_security_group": "Networking",
    "azurerm_public_ip": "Networking",
    "azurerm_lb": "Networking",
    "azurerm_application_gateway": "Networking",
    "azurerm_frontdoor": "Networking",
    "azurerm_cdn_profile": "Networking",
    "azurerm_dns_zone": "Networking",
    "azurerm_private_dns_zone": "Networking",
    "azurerm_api_management": "Networking",
    "azurerm_traffic_manager_profile": "Networking",
    # Messaging
    "azurerm_servicebus_namespace": "Messaging",
    "azurerm_servicebus_queue": "Messaging",
    "azurerm_servicebus_topic": "Messaging",
    "azurerm_eventhub_namespace": "Messaging",
    "azurerm_eventhub": "Messaging",
    "azurerm_eventgrid_topic": "Messaging",
    # Security
    "azurerm_key_vault": "Security",
    "azurerm_key_vault_secret": "Security",
    "azurerm_role_assignment": "Security",
    "azurerm_user_assigned_identity": "Security",
    # Monitoring
    "azurerm_monitor_action_group": "Monitoring",
    "azurerm_application_insights": "Monitoring",
    "azurerm_log_analytics_workspace": "Monitoring",
    # AI/ML
    "azurerm_cognitive_account": "AI/ML",
    "azurerm_machine_learning_workspace": "AI/ML",
    # ARM resource types (Microsoft.*)
    "Microsoft.Compute/virtualMachines": "Compute",
    "Microsoft.ContainerService/managedClusters": "Compute",
    "Microsoft.Web/sites": "Compute",
    "Microsoft.Web/serverFarms": "Compute",
    "Microsoft.App/containerApps": "Compute",
    "Microsoft.Storage/storageAccounts": "Storage",
    "Microsoft.Sql/servers": "Database",
    "Microsoft.Sql/servers/databases": "Database",
    "Microsoft.DBforPostgreSQL/flexibleServers": "Database",
    "Microsoft.DocumentDB/databaseAccounts": "Database",
    "Microsoft.Cache/redis": "Database",
    "Microsoft.Network/virtualNetworks": "Networking",
    "Microsoft.Network/networkSecurityGroups": "Networking",
    "Microsoft.Network/publicIPAddresses": "Networking",
    "Microsoft.Network/loadBalancers": "Networking",
    "Microsoft.Network/applicationGateways": "Networking",
    "Microsoft.Cdn/profiles": "Networking",
    "Microsoft.ServiceBus/namespaces": "Messaging",
    "Microsoft.EventHub/namespaces": "Messaging",
    "Microsoft.KeyVault/vaults": "Security",
    "Microsoft.ManagedIdentity/userAssignedIdentities": "Security",
    "Microsoft.Insights/components": "Monitoring",
    "Microsoft.OperationalInsights/workspaces": "Monitoring",
    "Microsoft.CognitiveServices/accounts": "AI/ML",
}

GCP_CATEGORY_MAP: Dict[str, str] = {
    # Compute
    "google_compute_instance": "Compute",
    "google_compute_instance_template": "Compute",
    "google_compute_instance_group_manager": "Compute",
    "google_container_cluster": "Compute",
    "google_container_node_pool": "Compute",
    "google_cloud_run_service": "Compute",
    "google_cloudfunctions_function": "Compute",
    "google_cloudfunctions2_function": "Compute",
    "google_app_engine_application": "Compute",
    # Storage
    "google_storage_bucket": "Storage",
    "google_compute_disk": "Storage",
    "google_filestore_instance": "Storage",
    # Database
    "google_sql_database_instance": "Database",
    "google_spanner_instance": "Database",
    "google_bigtable_instance": "Database",
    "google_redis_instance": "Database",
    "google_firestore_database": "Database",
    # Networking
    "google_compute_network": "Networking",
    "google_compute_subnetwork": "Networking",
    "google_compute_firewall": "Networking",
    "google_compute_global_address": "Networking",
    "google_compute_url_map": "Networking",
    "google_compute_target_https_proxy": "Networking",
    "google_compute_forwarding_rule": "Networking",
    "google_dns_managed_zone": "Networking",
    "google_compute_router": "Networking",
    "google_compute_router_nat": "Networking",
    # Messaging
    "google_pubsub_topic": "Messaging",
    "google_pubsub_subscription": "Messaging",
    # Security
    "google_kms_key_ring": "Security",
    "google_kms_crypto_key": "Security",
    "google_secret_manager_secret": "Security",
    "google_service_account": "Security",
    "google_project_iam_member": "Security",
    # Monitoring
    "google_monitoring_alert_policy": "Monitoring",
    "google_logging_metric": "Monitoring",
    # AI/ML
    "google_vertex_ai_endpoint": "AI/ML",
    "google_ml_engine_model": "AI/ML",
}


def _categorize_resource(resource_type: str) -> str:
    """Resolve the category for a resource type across all cloud providers."""
    if resource_type in AWS_CATEGORY_MAP:
        return AWS_CATEGORY_MAP[resource_type]
    if resource_type in AZURE_CATEGORY_MAP:
        return AZURE_CATEGORY_MAP[resource_type]
    if resource_type in GCP_CATEGORY_MAP:
        return GCP_CATEGORY_MAP[resource_type]

    # Heuristic fallback based on prefix keywords
    rt_lower = resource_type.lower()
    for keyword, cat in [
        ("compute", "Compute"), ("vm", "Compute"), ("instance", "Compute"),
        ("function", "Compute"), ("lambda", "Compute"), ("container", "Compute"),
        ("storage", "Storage"), ("bucket", "Storage"), ("blob", "Storage"), ("disk", "Storage"),
        ("db", "Database"), ("sql", "Database"), ("redis", "Database"), ("cache", "Database"),
        ("cosmos", "Database"), ("dynamo", "Database"),
        ("network", "Networking"), ("vpc", "Networking"), ("subnet", "Networking"),
        ("dns", "Networking"), ("lb", "Networking"), ("gateway", "Networking"),
        ("queue", "Messaging"), ("topic", "Messaging"), ("event", "Messaging"),
        ("pubsub", "Messaging"), ("sqs", "Messaging"), ("sns", "Messaging"),
        ("iam", "Security"), ("key", "Security"), ("secret", "Security"),
        ("monitor", "Monitoring"), ("log", "Monitoring"), ("insight", "Monitoring"),
    ]:
        if keyword in rt_lower:
            return cat

    return "Other"


def _detect_provider(resource_type: str) -> str:
    """Detect the cloud provider from a resource type string."""
    if resource_type.startswith("aws_"):
        return "AWS"
    if resource_type.startswith("azurerm_") or resource_type.startswith("Microsoft."):
        return "Azure"
    if resource_type.startswith("google_"):
        return "GCP"
    return "Unknown"


# ─────────────────────────────────────────────────────────────
# Terraform tfstate parser
# ─────────────────────────────────────────────────────────────

def _extract_tf_v4_resources(state: dict) -> List[Dict[str, Any]]:
    """Extract resources from Terraform state format v4."""
    results: List[Dict[str, Any]] = []
    for resource in state.get("resources", []):
        r_type = resource.get("type", "")
        r_name = resource.get("name", "")
        r_mode = resource.get("mode", "managed")
        if r_mode != "managed":
            continue

        for inst in resource.get("instances", []):
            attrs = inst.get("attributes", {})
            deps = inst.get("dependencies", [])
            results.append({
                "type": r_type,
                "name": r_name,
                "provider": _detect_provider(r_type),
                "category": _categorize_resource(r_type),
                "attributes": attrs,
                "dependencies": deps,
            })
    return results


def _extract_tf_v3_resources(state: dict) -> List[Dict[str, Any]]:
    """Extract resources from Terraform state format v3."""
    results: List[Dict[str, Any]] = []
    for module in state.get("modules", []):
        for r_key, r_val in module.get("resources", {}).items():
            r_type = r_val.get("type", "")
            primary = r_val.get("primary", {})
            attrs = primary.get("attributes", {})
            deps = r_val.get("depends_on", [])
            results.append({
                "type": r_type,
                "name": r_key,
                "provider": _detect_provider(r_type),
                "category": _categorize_resource(r_type),
                "attributes": attrs,
                "dependencies": deps,
            })
    return results


def parse_terraform_state(content: str) -> Dict[str, Any]:
    """Parse a terraform.tfstate JSON file and return Archmorph analysis schema."""
    state = json.loads(content)
    version = state.get("version", 4)

    if version >= 4:
        resources = _extract_tf_v4_resources(state)
    elif version >= 3:
        resources = _extract_tf_v3_resources(state)
    else:
        raise ValueError(f"Unsupported Terraform state version: {version}")

    return _build_analysis_schema(resources, source="terraform")


# ─────────────────────────────────────────────────────────────
# CloudFormation parser
# ─────────────────────────────────────────────────────────────

_CF_TYPE_MAP: Dict[str, Tuple[str, str]] = {
    "AWS::EC2::Instance": ("aws_instance", "Compute"),
    "AWS::Lambda::Function": ("aws_lambda_function", "Compute"),
    "AWS::ECS::Cluster": ("aws_ecs_cluster", "Compute"),
    "AWS::ECS::Service": ("aws_ecs_service", "Compute"),
    "AWS::EKS::Cluster": ("aws_eks_cluster", "Compute"),
    "AWS::AutoScaling::AutoScalingGroup": ("aws_autoscaling_group", "Compute"),
    "AWS::S3::Bucket": ("aws_s3_bucket", "Storage"),
    "AWS::EFS::FileSystem": ("aws_efs_file_system", "Storage"),
    "AWS::RDS::DBInstance": ("aws_db_instance", "Database"),
    "AWS::RDS::DBCluster": ("aws_rds_cluster", "Database"),
    "AWS::DynamoDB::Table": ("aws_dynamodb_table", "Database"),
    "AWS::ElastiCache::CacheCluster": ("aws_elasticache_cluster", "Database"),
    "AWS::Redshift::Cluster": ("aws_redshift_cluster", "Database"),
    "AWS::EC2::VPC": ("aws_vpc", "Networking"),
    "AWS::EC2::Subnet": ("aws_subnet", "Networking"),
    "AWS::EC2::SecurityGroup": ("aws_security_group", "Networking"),
    "AWS::EC2::InternetGateway": ("aws_internet_gateway", "Networking"),
    "AWS::EC2::NatGateway": ("aws_nat_gateway", "Networking"),
    "AWS::ElasticLoadBalancingV2::LoadBalancer": ("aws_lb", "Networking"),
    "AWS::Route53::HostedZone": ("aws_route53_zone", "Networking"),
    "AWS::CloudFront::Distribution": ("aws_cloudfront_distribution", "Networking"),
    "AWS::ApiGateway::RestApi": ("aws_api_gateway_rest_api", "Networking"),
    "AWS::SQS::Queue": ("aws_sqs_queue", "Messaging"),
    "AWS::SNS::Topic": ("aws_sns_topic", "Messaging"),
    "AWS::Kinesis::Stream": ("aws_kinesis_stream", "Messaging"),
    "AWS::IAM::Role": ("aws_iam_role", "Security"),
    "AWS::IAM::Policy": ("aws_iam_policy", "Security"),
    "AWS::KMS::Key": ("aws_kms_key", "Security"),
    "AWS::SecretsManager::Secret": ("aws_secretsmanager_secret", "Security"),
    "AWS::Logs::LogGroup": ("aws_cloudwatch_log_group", "Monitoring"),
    "AWS::CloudWatch::Alarm": ("aws_cloudwatch_metric_alarm", "Monitoring"),
}


def parse_cloudformation(content: str) -> Dict[str, Any]:
    """Parse a CloudFormation template and return Archmorph analysis schema."""
    template = json.loads(content)
    cf_resources = template.get("Resources", {})

    resources: List[Dict[str, Any]] = []
    for logical_id, r_def in cf_resources.items():
        cf_type = r_def.get("Type", "")
        properties = r_def.get("Properties", {})
        depends_on = r_def.get("DependsOn", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]

        mapped = _CF_TYPE_MAP.get(cf_type)
        if mapped:
            tf_type, category = mapped
        else:
            tf_type = cf_type
            category = _categorize_resource(cf_type)

        resources.append({
            "type": tf_type,
            "name": logical_id,
            "provider": "AWS",
            "category": category,
            "attributes": properties,
            "dependencies": depends_on,
        })

    return _build_analysis_schema(resources, source="cloudformation")


# ─────────────────────────────────────────────────────────────
# ARM template parser
# ─────────────────────────────────────────────────────────────

def parse_arm_template(content: str) -> Dict[str, Any]:
    """Parse an ARM deployment template and return Archmorph analysis schema."""
    template = json.loads(content)
    arm_resources = template.get("resources", [])

    resources: List[Dict[str, Any]] = []
    for r_def in arm_resources:
        arm_type = r_def.get("type", "")
        name = r_def.get("name", "")
        properties = r_def.get("properties", {})
        depends_on = r_def.get("dependsOn", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]

        category = AZURE_CATEGORY_MAP.get(arm_type, _categorize_resource(arm_type))
        resources.append({
            "type": arm_type,
            "name": name,
            "provider": "Azure",
            "category": category,
            "attributes": properties,
            "dependencies": depends_on,
        })

    return _build_analysis_schema(resources, source="arm")


# ─────────────────────────────────────────────────────────────
# Analysis schema builder
# ─────────────────────────────────────────────────────────────

def _build_analysis_schema(
    resources: List[Dict[str, Any]],
    source: str,
) -> Dict[str, Any]:
    """Transform a flat resource list into the Archmorph zones/services schema."""
    # Group by category → zone
    zones: Dict[str, List[Dict[str, Any]]] = {}
    for r in resources:
        cat = r["category"]
        if cat not in zones:
            zones[cat] = []
        zones[cat].append({
            "name": r["name"],
            "type": r["type"],
            "provider": r["provider"],
            "config": _sanitize_attributes(r.get("attributes", {})),
            "dependencies": r.get("dependencies", []),
        })

    zone_list = []
    for zone_name, services in zones.items():
        zone_list.append({
            "name": zone_name,
            "services": services,
        })

    providers = list({r["provider"] for r in resources})

    return {
        "source": source,
        "total_resources": len(resources),
        "providers": providers,
        "zones": zone_list,
    }


def _sanitize_attributes(attrs: Dict[str, Any], max_depth: int = 3) -> Dict[str, Any]:
    """Trim large/sensitive attributes to keep payloads manageable."""
    if max_depth <= 0:
        return {"_truncated": True}

    sanitized: Dict[str, Any] = {}
    sensitive_keys = {"password", "secret", "access_key", "private_key", "certificate", "token"}

    for k, v in attrs.items():
        if any(s in k.lower() for s in sensitive_keys):
            sanitized[k] = "***REDACTED***"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_attributes(v, max_depth - 1)
        elif isinstance(v, list) and len(v) > 20:
            sanitized[k] = v[:20] + [f"...({len(v) - 20} more)"]
        else:
            sanitized[k] = v

    return sanitized


# ─────────────────────────────────────────────────────────────
# Supported formats metadata
# ─────────────────────────────────────────────────────────────

SUPPORTED_FORMATS = [
    {
        "id": "terraform",
        "name": "Terraform State",
        "description": "Terraform tfstate file (v3 and v4 formats)",
        "file_extensions": [".tfstate", ".json"],
        "content_type": "application/json",
    },
    {
        "id": "cloudformation",
        "name": "AWS CloudFormation",
        "description": "CloudFormation stack template (JSON)",
        "file_extensions": [".json", ".template"],
        "content_type": "application/json",
    },
    {
        "id": "arm",
        "name": "Azure ARM Template",
        "description": "ARM deployment template (JSON)",
        "file_extensions": [".json"],
        "content_type": "application/json",
    },
]
