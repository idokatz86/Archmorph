"""
Confidence Provenance Engine — structured evidence for service mapping confidence.

Replaces generic AI prose with decomposed scores, feature parity checklists,
Azure documentation links, and migration guidance.  All data is hardcoded
for the top 30 most commonly mapped service pairs.

Thread-safe, zero external dependencies beyond stdlib.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────
# 1. Feature Parity Database  (top 30 AWS → Azure pairs)
# ─────────────────────────────────────────────────────────────
# Each entry: tuple of (matched_features: list, missing_features: list)

_FEATURE_PARITY: Dict[tuple, tuple] = {
    # COMPUTE
    ("EC2", "Virtual Machines"): (
        ["Auto-scaling", "Spot/Preemptible instances", "Dedicated hosts", "GPU instances",
         "Custom images (AMI / Managed Image)", "Placement groups", "Elastic network interfaces",
         "Instance metadata service", "Hibernation", "Nitro Enclaves → Confidential VMs",
         "User data / cloud-init", "Multiple instance families", "Burstable instances",
         "Accelerated networking"],
        ["Bare Metal instances (limited Azure SKUs)", "Mac instances"],
    ),
    ("Lambda", "Azure Functions"): (
        ["Auto-scaling", "Event triggers", "Custom runtime", "VNet integration",
         "Environment variables", "Layers → Dependency deployment", "Dead-letter queues",
         "Concurrency controls", "HTTP triggers", "Timer triggers",
         "Managed identity / IAM role"],
        ["Provisioned Concurrency (requires Premium plan)", "Lambda@Edge (use Front Door Rules Engine)"],
    ),
    ("S3", "Blob Storage"): (
        ["Object storage", "Versioning", "Lifecycle policies", "Server-side encryption",
         "Access policies / SAS tokens", "Event notifications", "Static website hosting",
         "Cross-region replication", "Storage tiers (Hot/Cool/Archive)",
         "Multipart upload", "Object lock / immutability"],
        ["S3 Select (limited via Azure Data Lake query)"],
    ),
    ("RDS", "SQL Database"): (
        ["Multi-AZ HA", "Automated backups", "Point-in-time restore", "Read replicas",
         "Encryption at rest", "VNet integration", "Performance Insights → Query Performance Insight",
         "Automated patching", "Scaling (vertical)", "Monitoring integration",
         "Multiple engine support (via Flexible Server)", "Connection pooling",
         "Geo-replication", "Serverless tier", "Long-term backup retention"],
        [],
    ),
    ("EKS", "AKS"): (
        ["Managed control plane", "Node auto-scaling", "Helm support", "RBAC integration",
         "VNet integration", "Ingress controllers", "Pod identity", "GPU node pools",
         "Spot/Preemptible nodes", "Multi-AZ clusters", "Container Insights monitoring",
         "Cluster auto-upgrade", "Network policies", "Service mesh integration",
         "Windows node pools", "Confidential containers"],
        [],
    ),
    ("ECS", "Container Instances"): (
        ["Docker container execution", "VNet integration", "GPU support",
         "Container groups / task definitions", "Logging integration",
         "Managed identity / IAM roles", "Private registry support"],
        ["Service discovery (built-in in ECS)", "Capacity providers", "ECS Exec"],
    ),
    ("Fargate", "Container Apps"): (
        ["Serverless containers", "Auto-scaling", "VNet integration",
         "Managed identity", "Ingress", "Dapr integration",
         "Revision management", "Health probes", "Secrets management"],
        ["Fargate Spot (use Container Apps spot pools)"],
    ),
    ("Elastic Beanstalk", "App Service"): (
        ["PaaS deployment", "Auto-scaling", "Load balancing", "Deployment slots",
         "Custom domains / TLS", "Managed runtime updates", "VNet integration",
         "Logging and diagnostics", "CI/CD integration"],
        ["Worker environments (use WebJobs or Functions)"],
    ),
    # STORAGE
    ("EBS", "Managed Disks"): (
        ["SSD / HDD tiers", "Snapshots", "Encryption at rest", "Disk resizing",
         "Throughput-optimized options", "Ultra disk / io2", "Shared disks",
         "Burst capability"],
        ["Multi-attach (limited Azure support)"],
    ),
    ("EFS", "Azure Files"): (
        ["NFS protocol", "SMB protocol (Azure only)", "Auto-scaling throughput",
         "Encryption at rest", "Backup integration", "VNet integration",
         "Lifecycle management"],
        ["EFS Intelligent-Tiering (Azure has hot/cool tiers)"],
    ),
    # DATABASE
    ("DynamoDB", "Cosmos DB"): (
        ["Key-value & document model", "Global distribution", "Auto-scaling",
         "TTL", "Change feed / streams", "Encryption at rest",
         "Point-in-time restore", "Serverless capacity", "Reserved capacity"],
        ["DynamoDB Accelerator / DAX (Cosmos has integrated cache)",
         "PartiQL (Cosmos uses SQL API)"],
    ),
    # #590 — Aurora is PostgreSQL/MySQL-compatible; previous SQL Hyperscale
    # mapping was a wrong-engine defect.
    ("Aurora", "Azure Database for PostgreSQL Flexible Server"): (
        ["High-performance relational DB", "Auto-scaling storage", "Read replicas",
         "Multi-AZ HA", "Automated backups", "Point-in-time restore",
         "Serverless option", "Global database"],
        ["Aurora Multi-Master (Azure uses zone-redundant HA + read replicas)",
         "Aurora Backtrack (Azure uses point-in-time restore + flashback)"],
    ),
    ("ElastiCache", "Cache for Redis"): (
        ["Managed Redis", "Cluster mode", "Replication", "Encryption in transit",
         "VNet integration", "Backup and restore", "Auto-scaling",
         "Data persistence"],
        ["Memcached engine (Azure Redis only)"],
    ),
    ("Redshift", "Synapse Analytics"): (
        ["Columnar storage", "Massively parallel processing", "SQL interface",
         "Data lake integration", "Materialized views", "Concurrency scaling",
         "Workload management", "Serverless option"],
        ["Redshift Spectrum (Synapse uses external tables)", "AQUA acceleration"],
    ),
    # NETWORKING
    ("VPC", "Virtual Network"): (
        ["Subnets", "Route tables", "Network ACLs / NSGs", "Internet gateway",
         "NAT gateway", "VPN connectivity", "Peering", "Flow logs",
         "Private endpoints", "DNS integration"],
        ["VPC Lattice (use Azure Private Link services)"],
    ),
    ("CloudFront", "CDN / Front Door"): (
        ["Global edge caching", "HTTPS / custom SSL", "Cache invalidation",
         "Origin groups / failover", "WAF integration", "Custom error pages",
         "Geo-restriction", "Real-time logs"],
        ["Lambda@Edge (use Front Door Rules Engine)"],
    ),
    ("Route 53", "Azure DNS / Traffic Manager"): (
        ["DNS hosting", "Health checks", "Routing policies (weighted/geo/latency)",
         "Domain registration (Azure: external registrar)", "DNSSEC",
         "Private DNS zones", "Alias records / CNAME flattening"],
        ["Route 53 Resolver (use Azure DNS Private Resolver)"],
    ),
    ("API Gateway", "API Management"): (
        ["REST API hosting", "Rate limiting / throttling", "API keys",
         "Request/response transformation", "OAuth integration",
         "Usage plans / subscriptions", "WebSocket support",
         "OpenAPI import", "Developer portal"],
        ["HTTP API (lightweight) — APIM Consumption tier is closest"],
    ),
    ("ELB", "Load Balancer / Application Gateway"): (
        ["L4 load balancing", "L7 load balancing", "Health checks",
         "SSL termination", "Sticky sessions", "Cross-zone load balancing",
         "WebSocket support", "Path-based routing"],
        ["Gateway Load Balancer (use Azure Gateway LB)"],
    ),
    # SECURITY
    ("IAM", "Entra ID / RBAC"): (
        ["Users & groups", "Roles & policies", "MFA", "Service accounts / managed identity",
         "Federation (SAML/OIDC)", "Temporary credentials / tokens",
         "Conditional access", "Audit logging"],
        ["IAM Access Analyzer (use Entra Permissions Management)"],
    ),
    ("KMS", "Key Vault"): (
        ["Symmetric key encryption", "Asymmetric key encryption", "Key rotation",
         "Audit logging", "Access policies", "Envelope encryption",
         "HSM-backed keys", "Cross-region replication"],
        ["Custom key store (Azure has Managed HSM)"],
    ),
    ("Cognito", "Entra External ID (B2C)"): (
        ["User sign-up/sign-in", "Social identity providers", "MFA",
         "Token-based auth (JWT)", "User pools / directories",
         "Custom auth flows", "Hosted UI"],
        ["Cognito Sync (use App Service offline sync or Graph API)"],
    ),
    # INTEGRATION
    ("SQS", "Service Bus (Queues)"): (
        ["Message queuing", "Dead-letter queues", "Visibility timeout",
         "FIFO ordering", "Batched operations", "Server-side encryption",
         "VNet integration", "Long polling / message sessions"],
        ["SQS delay queues (Service Bus has scheduled messages)"],
    ),
    ("SNS", "Event Grid / Notification Hubs"): (
        ["Pub/sub messaging", "Topic subscriptions", "Message filtering",
         "Push notifications", "Fanout pattern", "Dead-letter support"],
        ["SMS/email delivery (use Communication Services)"],
    ),
    ("Step Functions", "Logic Apps"): (
        ["Visual workflow designer", "State machine orchestration",
         "Error handling & retry", "Parallel execution",
         "Wait states / delays", "250+ connectors (Logic Apps)",
         "Nested workflows"],
        ["Express Workflows (use Durable Functions for high-throughput)"],
    ),
    # AI/ML
    ("SageMaker", "Azure Machine Learning"): (
        ["Notebook instances", "Training jobs", "Model hosting",
         "AutoML", "MLOps / pipelines", "Experiment tracking",
         "Data labeling", "Feature store",
         "Model registry", "Real-time inference"],
        ["SageMaker Canvas (use Azure ML AutoML UI)",
         "SageMaker Ground Truth (use Azure ML Data Labeling)"],
    ),
    ("Bedrock", "Azure OpenAI Service"): (
        ["Foundation model access", "Fine-tuning", "RAG integration",
         "Content filtering", "Embeddings", "Batch inference",
         "Managed endpoints"],
        ["Multi-provider models (Azure focuses on OpenAI family)",
         "Bedrock Agents (use Azure AI Agent Service)"],
    ),
    # DEVTOOLS
    ("CloudFormation", "ARM Templates / Bicep"): (
        ["Infrastructure as code", "Template syntax", "Parameterization",
         "Nested stacks / modules", "Drift detection", "Change sets / what-if",
         "Stack policies", "Cross-resource dependencies"],
        ["CloudFormation StackSets (use Deployment Stacks or Template Specs)"],
    ),
    # ANALYTICS
    ("Kinesis", "Event Hubs / Stream Analytics"): (
        ["Real-time data streaming", "Partitioned consumption",
         "Data retention", "Consumer groups", "Scaling (throughput units / shards)",
         "Kafka-compatible interface", "Schema registry"],
        ["Kinesis Data Firehose (use Event Hubs Capture + Stream Analytics)"],
    ),
    # MANAGEMENT
    ("CloudWatch", "Azure Monitor / Log Analytics"): (
        ["Metrics collection", "Log aggregation", "Dashboards",
         "Alarms / alerts", "Log queries (KQL vs Insights)",
         "Custom metrics", "Application-level tracing",
         "Cross-service correlation"],
        ["CloudWatch Synthetics (use Application Insights availability tests)"],
    ),
}


# ─────────────────────────────────────────────────────────────
# 2. Azure Documentation Links
# ─────────────────────────────────────────────────────────────

_AZURE_DOCS: Dict[str, List[Dict[str, str]]] = {
    "Virtual Machines": [
        {"title": "Azure Virtual Machines documentation", "url": "https://learn.microsoft.com/azure/virtual-machines/overview"},
        {"title": "AWS to Azure services comparison — Compute", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#compute"},
    ],
    "Azure Functions": [
        {"title": "Azure Functions documentation", "url": "https://learn.microsoft.com/azure/azure-functions/functions-overview"},
        {"title": "Compare Azure Functions and AWS Lambda", "url": "https://learn.microsoft.com/azure/azure-functions/functions-compare-logic-apps-ms-flow-webjobs"},
    ],
    "Blob Storage": [
        {"title": "Azure Blob Storage documentation", "url": "https://learn.microsoft.com/azure/storage/blobs/storage-blobs-overview"},
        {"title": "AWS to Azure services comparison — Storage", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#storage"},
    ],
    "SQL Database": [
        {"title": "Azure SQL Database documentation", "url": "https://learn.microsoft.com/azure/azure-sql/database/sql-database-paas-overview"},
        {"title": "AWS to Azure services comparison — Database", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#database"},
    ],
    "AKS": [
        {"title": "Azure Kubernetes Service documentation", "url": "https://learn.microsoft.com/azure/aks/intro-kubernetes"},
        {"title": "AWS to Azure services comparison — Containers", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#containers"},
    ],
    "Container Instances": [
        {"title": "Azure Container Instances documentation", "url": "https://learn.microsoft.com/azure/container-instances/container-instances-overview"},
    ],
    "Container Apps": [
        {"title": "Azure Container Apps documentation", "url": "https://learn.microsoft.com/azure/container-apps/overview"},
    ],
    "App Service": [
        {"title": "Azure App Service documentation", "url": "https://learn.microsoft.com/azure/app-service/overview"},
        {"title": "AWS to Azure services comparison — Compute", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#compute"},
    ],
    "Managed Disks": [
        {"title": "Azure Managed Disks documentation", "url": "https://learn.microsoft.com/azure/virtual-machines/managed-disks-overview"},
    ],
    "Azure Files": [
        {"title": "Azure Files documentation", "url": "https://learn.microsoft.com/azure/storage/files/storage-files-introduction"},
    ],
    "Cosmos DB": [
        {"title": "Azure Cosmos DB documentation", "url": "https://learn.microsoft.com/azure/cosmos-db/introduction"},
        {"title": "AWS to Azure services comparison — Database", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#database"},
    ],
    "SQL Database (Hyperscale)": [
        {"title": "Azure SQL Hyperscale documentation", "url": "https://learn.microsoft.com/azure/azure-sql/database/service-tier-hyperscale"},
    ],
    "Cache for Redis": [
        {"title": "Azure Cache for Redis documentation", "url": "https://learn.microsoft.com/azure/azure-cache-for-redis/cache-overview"},
    ],
    "Synapse Analytics": [
        {"title": "Azure Synapse Analytics documentation", "url": "https://learn.microsoft.com/azure/synapse-analytics/overview-what-is"},
    ],
    "Virtual Network": [
        {"title": "Azure Virtual Network documentation", "url": "https://learn.microsoft.com/azure/virtual-network/virtual-networks-overview"},
        {"title": "AWS to Azure services comparison — Networking", "url": "https://learn.microsoft.com/azure/architecture/aws-professional/services#networking"},
    ],
    "CDN / Front Door": [
        {"title": "Azure Front Door documentation", "url": "https://learn.microsoft.com/azure/frontdoor/front-door-overview"},
    ],
    "Azure DNS / Traffic Manager": [
        {"title": "Azure DNS documentation", "url": "https://learn.microsoft.com/azure/dns/dns-overview"},
        {"title": "Azure Traffic Manager documentation", "url": "https://learn.microsoft.com/azure/traffic-manager/traffic-manager-overview"},
    ],
    "API Management": [
        {"title": "Azure API Management documentation", "url": "https://learn.microsoft.com/azure/api-management/api-management-key-concepts"},
    ],
    "Load Balancer / Application Gateway": [
        {"title": "Azure Load Balancer documentation", "url": "https://learn.microsoft.com/azure/load-balancer/load-balancer-overview"},
        {"title": "Azure Application Gateway documentation", "url": "https://learn.microsoft.com/azure/application-gateway/overview"},
    ],
    "Entra ID / RBAC": [
        {"title": "Microsoft Entra ID documentation", "url": "https://learn.microsoft.com/entra/identity/"},
        {"title": "Azure RBAC documentation", "url": "https://learn.microsoft.com/azure/role-based-access-control/overview"},
    ],
    "Key Vault": [
        {"title": "Azure Key Vault documentation", "url": "https://learn.microsoft.com/azure/key-vault/general/overview"},
    ],
    "Entra External ID (B2C)": [
        {"title": "Azure AD B2C documentation", "url": "https://learn.microsoft.com/azure/active-directory-b2c/overview"},
    ],
    "Service Bus (Queues)": [
        {"title": "Azure Service Bus documentation", "url": "https://learn.microsoft.com/azure/service-bus-messaging/service-bus-messaging-overview"},
    ],
    "Event Grid / Notification Hubs": [
        {"title": "Azure Event Grid documentation", "url": "https://learn.microsoft.com/azure/event-grid/overview"},
    ],
    "Logic Apps": [
        {"title": "Azure Logic Apps documentation", "url": "https://learn.microsoft.com/azure/logic-apps/logic-apps-overview"},
    ],
    "Azure Machine Learning": [
        {"title": "Azure Machine Learning documentation", "url": "https://learn.microsoft.com/azure/machine-learning/overview-what-is-azure-machine-learning"},
    ],
    "Azure OpenAI Service": [
        {"title": "Azure OpenAI Service documentation", "url": "https://learn.microsoft.com/azure/ai-services/openai/overview"},
    ],
    "ARM Templates / Bicep": [
        {"title": "Azure Bicep documentation", "url": "https://learn.microsoft.com/azure/azure-resource-manager/bicep/overview"},
        {"title": "Azure ARM Templates documentation", "url": "https://learn.microsoft.com/azure/azure-resource-manager/templates/overview"},
    ],
    "Event Hubs / Stream Analytics": [
        {"title": "Azure Event Hubs documentation", "url": "https://learn.microsoft.com/azure/event-hubs/event-hubs-about"},
        {"title": "Azure Stream Analytics documentation", "url": "https://learn.microsoft.com/azure/stream-analytics/stream-analytics-introduction"},
    ],
    "Azure Monitor / Log Analytics": [
        {"title": "Azure Monitor documentation", "url": "https://learn.microsoft.com/azure/azure-monitor/overview"},
        {"title": "Azure Log Analytics documentation", "url": "https://learn.microsoft.com/azure/azure-monitor/logs/log-analytics-overview"},
    ],
    # Fallback for services without specific docs
    "VM Scale Sets": [
        {"title": "Azure VM Scale Sets documentation", "url": "https://learn.microsoft.com/azure/virtual-machine-scale-sets/overview"},
    ],
    "Defender for Cloud": [
        {"title": "Microsoft Defender for Cloud documentation", "url": "https://learn.microsoft.com/azure/defender-for-cloud/defender-for-cloud-introduction"},
    ],
    "Web Application Firewall": [
        {"title": "Azure WAF documentation", "url": "https://learn.microsoft.com/azure/web-application-firewall/overview"},
    ],
    "DDoS Protection": [
        {"title": "Azure DDoS Protection documentation", "url": "https://learn.microsoft.com/azure/ddos-protection/ddos-protection-overview"},
    ],
    "ExpressRoute": [
        {"title": "Azure ExpressRoute documentation", "url": "https://learn.microsoft.com/azure/expressroute/expressroute-introduction"},
    ],
    "VPN Gateway": [
        {"title": "Azure VPN Gateway documentation", "url": "https://learn.microsoft.com/azure/vpn-gateway/vpn-gateway-about-vpngateways"},
    ],
    "Azure Firewall": [
        {"title": "Azure Firewall documentation", "url": "https://learn.microsoft.com/azure/firewall/overview"},
    ],
    "IoT Hub": [
        {"title": "Azure IoT Hub documentation", "url": "https://learn.microsoft.com/azure/iot-hub/iot-concepts-and-iot-hub"},
    ],
    "Data Factory": [
        {"title": "Azure Data Factory documentation", "url": "https://learn.microsoft.com/azure/data-factory/introduction"},
    ],
    "Container Registry": [
        {"title": "Azure Container Registry documentation", "url": "https://learn.microsoft.com/azure/container-registry/container-registry-intro"},
    ],
    "Azure Pipelines": [
        {"title": "Azure Pipelines documentation", "url": "https://learn.microsoft.com/azure/devops/pipelines/get-started/what-is-azure-pipelines"},
    ],
    "Azure Batch": [
        {"title": "Azure Batch documentation", "url": "https://learn.microsoft.com/azure/batch/batch-technical-overview"},
    ],
    "Private Link": [
        {"title": "Azure Private Link documentation", "url": "https://learn.microsoft.com/azure/private-link/private-link-overview"},
    ],
    "Azure Backup": [
        {"title": "Azure Backup documentation", "url": "https://learn.microsoft.com/azure/backup/backup-overview"},
    ],
    "Power BI": [
        {"title": "Power BI documentation", "url": "https://learn.microsoft.com/power-bi/fundamentals/power-bi-overview"},
    ],
    "Microsoft Sentinel": [
        {"title": "Microsoft Sentinel documentation", "url": "https://learn.microsoft.com/azure/sentinel/overview"},
    ],
    "Application Insights": [
        {"title": "Application Insights documentation", "url": "https://learn.microsoft.com/azure/azure-monitor/app/app-insights-overview"},
    ],
    "Azure Migrate": [
        {"title": "Azure Migrate documentation", "url": "https://learn.microsoft.com/azure/migrate/migrate-services-overview"},
    ],
}

# Well-Architected link appended to every provenance result
_WELL_ARCHITECTED_URL = "https://learn.microsoft.com/azure/well-architected/"
_AWS_COMPARISON_URL = "https://learn.microsoft.com/azure/architecture/aws-professional/services"


# ─────────────────────────────────────────────────────────────
# 3. Migration Guidance
# ─────────────────────────────────────────────────────────────

_MIGRATION_GUIDANCE: Dict[tuple, Dict[str, Any]] = {
    ("EC2", "Virtual Machines"): {
        "migration_notes": "EC2 instances map directly to Azure VMs. AMIs translate to Managed Images or Azure Compute Gallery. Security groups → NSGs. User data scripts are compatible via cloud-init.",
        "estimated_effort": "low",
        "breaking_changes": ["Bare Metal instances have limited Azure SKU equivalents", "Mac instances not available on Azure"],
    },
    ("Lambda", "Azure Functions"): {
        "migration_notes": "Lambda functions map to Azure Functions with minor runtime differences. Python/Node.js functions port directly. Use Premium plan for VNet and pre-warmed instances. Provisioned Concurrency requires Premium plan.",
        "estimated_effort": "low",
        "breaking_changes": ["Lambda@Edge has no direct equivalent — use Azure Front Door Rules Engine", "Provisioned Concurrency requires Premium plan with minimum instances"],
    },
    ("S3", "Blob Storage"): {
        "migration_notes": "S3 buckets map to Blob Storage containers. IAM policies → Azure RBAC + SAS tokens. Event notifications → Event Grid. S3 Select has limited support — use Data Lake Analytics for complex queries.",
        "estimated_effort": "low",
        "breaking_changes": ["S3 Select requires rearchitecting to Data Lake query or Synapse Serverless SQL"],
    },
    ("RDS", "SQL Database"): {
        "migration_notes": "RDS maps to Azure SQL Database (SQL Server), Azure Database for MySQL/PostgreSQL (Flexible Server). Use Database Migration Service for schema + data migration. Performance Insights → Query Performance Insight.",
        "estimated_effort": "medium",
        "breaking_changes": ["Engine-specific parameter groups need translation to Azure server parameters"],
    },
    ("EKS", "AKS"): {
        "migration_notes": "EKS clusters map directly to AKS. Kubernetes manifests are portable. IAM Roles for Service Accounts → Workload Identity. ALB Ingress → AGIC or NGINX ingress. VPC CNI → Azure CNI.",
        "estimated_effort": "medium",
        "breaking_changes": ["AWS-specific annotations (ALB controller, EBS CSI) must be replaced with Azure equivalents"],
    },
    ("ECS", "Container Instances"): {
        "migration_notes": "ECS task definitions translate to Container Groups. For full orchestration, consider AKS or Container Apps instead of ACI. Fargate tasks map more naturally to Container Apps.",
        "estimated_effort": "medium",
        "breaking_changes": ["ECS Service Discovery requires manual DNS or Azure DNS private zones", "ECS Exec requires Azure Container Instances exec command"],
    },
    ("Fargate", "Container Apps"): {
        "migration_notes": "Fargate tasks map to Container Apps revisions. Environment variables, secrets, and scaling rules translate directly. Dapr sidecar available for microservices patterns.",
        "estimated_effort": "low",
        "breaking_changes": ["Fargate Spot pricing model differs from Container Apps consumption pricing"],
    },
    ("Elastic Beanstalk", "App Service"): {
        "migration_notes": "Beanstalk environments map to App Service plans. Platform-specific config (Procfile, .ebextensions) must be translated to App Service configuration. Deployment slots provide blue/green capability.",
        "estimated_effort": "low",
        "breaking_changes": ["Worker environments should be migrated to Azure Functions or WebJobs"],
    },
    ("DynamoDB", "Cosmos DB"): {
        "migration_notes": "DynamoDB tables map to Cosmos DB containers. Use the Cosmos DB Table API for closest compatibility, or the SQL API for richer querying. Partition key design principles are similar. DAX caching → Cosmos DB integrated cache.",
        "estimated_effort": "medium",
        "breaking_changes": ["PartiQL queries must be rewritten to Cosmos DB SQL API", "DAX caching requires Cosmos DB integrated cache or Azure Cache for Redis"],
    },
    # #590 — wrong-engine narrative replaced. Aurora is PostgreSQL/MySQL.
    ("Aurora", "Azure Database for PostgreSQL Flexible Server"): {
        "migration_notes": "Aurora PostgreSQL maps engine-correctly to Azure Database for PostgreSQL Flexible Server. Aurora MySQL → Azure Database for MySQL Flexible Server (separate row). Aurora Serverless v2 → Flexible Server's burstable tier; provisioned → General Purpose / Memory Optimized. Multi-master → zone-redundant HA + read replicas (active-active is not 1:1).",
        "estimated_effort": "medium",
        "breaking_changes": [
            "Aurora Multi-Master requires re-architecture for HA + read-replica pattern",
            "Aurora Backtrack → Azure point-in-time restore (different RTO/RPO semantics)",
            "Pre-#590 callers that used the old SQL-Server-target mapping must update to PostgreSQL Flex — the engine has changed",
        ],
    },
    ("ElastiCache", "Cache for Redis"): {
        "migration_notes": "ElastiCache Redis maps directly to Azure Cache for Redis. Cluster mode, persistence, and replication settings translate. Memcached workloads must migrate to Redis protocol.",
        "estimated_effort": "low",
        "breaking_changes": ["Memcached engine not available — must migrate to Redis protocol"],
    },
    ("Redshift", "Synapse Analytics"): {
        "migration_notes": "Redshift clusters map to Synapse dedicated SQL pools. Redshift Spectrum → Synapse external tables over Data Lake. RA3 instances → Synapse serverless SQL for cost optimization.",
        "estimated_effort": "high",
        "breaking_changes": ["Redshift Spectrum queries need rewriting for Synapse external tables", "AQUA acceleration has no direct equivalent"],
    },
    ("VPC", "Virtual Network"): {
        "migration_notes": "VPCs map to Azure Virtual Networks. Subnets, route tables, and security groups (→ NSGs) translate directly. Internet/NAT gateways have direct equivalents. VPC Endpoints → Private Endpoints.",
        "estimated_effort": "low",
        "breaking_changes": ["VPC Lattice requires redesign using Private Link services"],
    },
    ("CloudFront", "CDN / Front Door"): {
        "migration_notes": "CloudFront distributions map to Front Door profiles. Origin groups, caching rules, and WAF integration translate. Lambda@Edge functions must be reimplemented as Front Door Rules Engine rules.",
        "estimated_effort": "medium",
        "breaking_changes": ["Lambda@Edge → Front Door Rules Engine (different programming model)"],
    },
    ("Route 53", "Azure DNS / Traffic Manager"): {
        "migration_notes": "Route 53 hosted zones → Azure DNS zones. Routing policies → Traffic Manager profiles. Health checks → Traffic Manager endpoints. Domain registration must use external registrar.",
        "estimated_effort": "low",
        "breaking_changes": ["Route 53 Resolver → Azure DNS Private Resolver (different configuration)"],
    },
    ("API Gateway", "API Management"): {
        "migration_notes": "API Gateway REST APIs map to APIM APIs. Usage plans → APIM subscriptions. Lambda integrations → Azure Functions backend. HTTP APIs (lightweight) → APIM Consumption tier.",
        "estimated_effort": "medium",
        "breaking_changes": ["HTTP API (v2) lightweight mode → APIM Consumption tier has different limits"],
    },
    ("ELB", "Load Balancer / Application Gateway"): {
        "migration_notes": "ALB maps to Application Gateway (L7). NLB maps to Azure Load Balancer (L4). Target groups → backend pools. Health checks translate directly.",
        "estimated_effort": "low",
        "breaking_changes": ["Gateway Load Balancer patterns differ between AWS and Azure"],
    },
    ("IAM", "Entra ID / RBAC"): {
        "migration_notes": "AWS IAM policies map to Azure RBAC role assignments. IAM roles → Managed Identities. IAM users → Entra ID users. Policy conditions → Azure Policy + Conditional Access.",
        "estimated_effort": "high",
        "breaking_changes": ["IAM Access Analyzer → Entra Permissions Management (separate product)"],
    },
    ("KMS", "Key Vault"): {
        "migration_notes": "KMS keys map to Key Vault keys. Envelope encryption patterns are identical. Custom key stores → Managed HSM. Key policies → Key Vault access policies or RBAC.",
        "estimated_effort": "low",
        "breaking_changes": ["Custom key store → Azure Managed HSM (different provisioning model)"],
    },
    ("Cognito", "Entra External ID (B2C)"): {
        "migration_notes": "Cognito User Pools → Entra External ID (B2C) user flows. Identity pools → Entra ID app registrations with federated credentials. Custom auth challenges → B2C custom policies.",
        "estimated_effort": "high",
        "breaking_changes": ["Cognito Sync has no direct equivalent — use Graph API or app-level sync"],
    },
    ("SQS", "Service Bus (Queues)"): {
        "migration_notes": "SQS standard queues → Service Bus queues. FIFO queues → Service Bus sessions. Dead-letter queues translate directly. Visibility timeout → lock duration.",
        "estimated_effort": "low",
        "breaking_changes": ["SQS delay queues → Service Bus scheduled messages (slightly different API)"],
    },
    ("SNS", "Event Grid / Notification Hubs"): {
        "migration_notes": "SNS topics → Event Grid topics for event-driven patterns. SNS → Notification Hubs for push notifications. SMS/email delivery → Communication Services.",
        "estimated_effort": "medium",
        "breaking_changes": ["SNS SMS/email delivery requires Azure Communication Services"],
    },
    ("Step Functions", "Logic Apps"): {
        "migration_notes": "Step Functions state machines → Logic Apps workflows. ASL → Logic Apps workflow definition. Express Workflows → Durable Functions for high-throughput orchestration.",
        "estimated_effort": "medium",
        "breaking_changes": ["Express Workflows → Durable Functions (different programming model)"],
    },
    ("SageMaker", "Azure Machine Learning"): {
        "migration_notes": "SageMaker notebooks → Azure ML compute instances. Training jobs → Azure ML training pipelines. Model hosting → Azure ML managed endpoints. MLflow integration available on both.",
        "estimated_effort": "high",
        "breaking_changes": ["SageMaker Canvas → Azure ML AutoML UI (different UX)", "SageMaker Ground Truth → Azure ML Data Labeling (different workflow)"],
    },
    ("Bedrock", "Azure OpenAI Service"): {
        "migration_notes": "Bedrock model access → Azure OpenAI deployments. Fine-tuning available for select models. RAG → Azure AI Search + Azure OpenAI. Content filtering is built-in on Azure.",
        "estimated_effort": "medium",
        "breaking_changes": ["Multi-provider model access (Anthropic, Meta) not available on Azure OpenAI — use Azure AI model catalog", "Bedrock Agents → Azure AI Agent Service"],
    },
    ("CloudFormation", "ARM Templates / Bicep"): {
        "migration_notes": "CloudFormation templates → Bicep files (preferred) or ARM templates. Stacks → resource groups. StackSets → Deployment Stacks. Change sets → what-if deployments.",
        "estimated_effort": "high",
        "breaking_changes": ["CloudFormation StackSets → Deployment Stacks or Template Specs (different management model)"],
    },
    ("Kinesis", "Event Hubs / Stream Analytics"): {
        "migration_notes": "Kinesis Data Streams → Event Hubs. Kinesis Data Firehose → Event Hubs Capture + Stream Analytics. Kinesis Analytics → Stream Analytics. Kafka-compatible consumers work with Event Hubs.",
        "estimated_effort": "medium",
        "breaking_changes": ["Kinesis Data Firehose → Event Hubs Capture + Stream Analytics pipeline (two services instead of one)"],
    },
    ("CloudWatch", "Azure Monitor / Log Analytics"): {
        "migration_notes": "CloudWatch Metrics → Azure Monitor Metrics. CloudWatch Logs → Log Analytics workspace. CloudWatch Alarms → Azure Monitor Alerts. Dashboards → Azure Monitor Workbooks or Grafana.",
        "estimated_effort": "medium",
        "breaking_changes": ["CloudWatch Synthetics → Application Insights availability tests (different test authoring)"],
    },
    ("EBS", "Managed Disks"): {
        "migration_notes": "EBS volumes map to Azure Managed Disks. gp3/io2 → Premium SSD v2. st1/sc1 → Standard HDD. Snapshots → Managed Disk snapshots.",
        "estimated_effort": "low",
        "breaking_changes": ["Multi-attach has limited Azure support (shared disks for specific scenarios)"],
    },
    ("EFS", "Azure Files"): {
        "migration_notes": "EFS file systems → Azure Files with NFS protocol. SMB protocol also available on Azure. Performance tiers translate to Premium/Standard tiers.",
        "estimated_effort": "low",
        "breaking_changes": ["EFS Intelligent-Tiering → Azure Files hot/cool tiers (manual or lifecycle-based)"],
    },
}


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

# Default blending weights — must match the confidence methodology
# used in vision_analyzer.py system prompt
CATALOG_WEIGHT = 0.7
GPT_WEIGHT = 0.3


def build_provenance(mapping: Dict[str, Any], catalog_confidence: Optional[float] = None) -> Dict[str, Any]:
    """Build a structured confidence provenance record for a single mapping.

    Parameters
    ----------
    mapping : dict
        A service mapping dict from the analysis result.  Expected keys:
        ``source_service`` (str), ``azure_service`` (str), ``confidence`` (float),
        ``category`` (str), ``description`` / ``notes`` (str).
    catalog_confidence : float | None
        Confidence from the static catalog lookup.  If *None*, the engine
        will attempt to look it up from ``services/mappings.py``.

    Returns a dict with ``score_decomposition``, ``feature_parity``,
    ``azure_docs``, and ``migration_guidance`` sub-objects.
    """
    source = _norm(mapping.get("source_service", ""))
    azure = _norm(mapping.get("azure_service", mapping.get("target_service", "")))
    overall = mapping.get("confidence", 0)
    # Normalise to 0-100 scale
    if isinstance(overall, (int, float)) and overall <= 1.0:
        overall_pct = round(overall * 100)
    else:
        overall_pct = int(overall)

    # --- 1. Score decomposition ---
    cat_conf = catalog_confidence
    if cat_conf is None:
        cat_conf = _lookup_catalog_confidence(source, azure)

    if cat_conf is not None:
        cat_pct = round(cat_conf * 100) if cat_conf <= 1.0 else int(cat_conf)
        # Derive GPT contribution as the residual
        cat_contribution = round(cat_pct * CATALOG_WEIGHT, 1)
        gpt_pct = round((overall_pct - cat_contribution) / GPT_WEIGHT) if GPT_WEIGHT else overall_pct
        gpt_pct = max(0, min(100, gpt_pct))
        gpt_contribution = round(gpt_pct * GPT_WEIGHT, 1)
    else:
        # No catalog match — full GPT
        cat_pct = 0
        gpt_pct = overall_pct
        cat_contribution = 0.0
        gpt_contribution = round(gpt_pct * GPT_WEIGHT, 1)

    decomposition = {
        "overall_confidence": overall_pct,
        "components": {
            "catalog_match": {
                "score": cat_pct,
                "weight": CATALOG_WEIGHT,
                "contribution": cat_contribution,
                "source": "services/mappings.py static catalog",
            },
            "gpt_detection": {
                "score": gpt_pct,
                "weight": GPT_WEIGHT,
                "contribution": gpt_contribution,
                "source": "GPT-4o multimodal diagram analysis",
            },
        },
        "total_weighted": round(cat_contribution + gpt_contribution, 1),
    }

    # --- 2. Feature parity ---
    parity = _build_feature_parity(source, azure)

    # --- 3. Azure docs ---
    docs = _get_azure_docs(azure)

    # --- 4. Migration guidance ---
    guidance = _get_migration_guidance(source, azure)

    return {
        "source_service": source,
        "azure_service": azure,
        "score_decomposition": decomposition,
        "feature_parity": parity,
        "azure_docs": docs,
        "migration_guidance": guidance,
    }


def build_provenance_summary(mappings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build provenance for all mappings in an analysis result.

    Returns a dict keyed by source service name, plus summary statistics.
    """
    per_service: Dict[str, Dict[str, Any]] = {}
    parity_scores: list = []

    for m in mappings:
        source = _norm(m.get("source_service", ""))
        if not source:
            continue
        prov = build_provenance(m)
        per_service[source] = prov

        # Collect parity ratio for summary
        fp = prov.get("feature_parity")
        if fp and fp.get("total_features", 0) > 0:
            parity_scores.append(fp["matched_count"] / fp["total_features"])

    avg_parity = round(sum(parity_scores) / len(parity_scores) * 100) if parity_scores else None

    return {
        "services": per_service,
        "summary": {
            "total_mappings": len(per_service),
            "mappings_with_parity_data": sum(
                1 for p in per_service.values() if p["feature_parity"]["total_features"] > 0
            ),
            "average_parity_percent": avg_parity,
        },
    }


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _norm(value: Any) -> str:
    """Normalise a service name (may be dict from GPT output)."""
    if isinstance(value, dict):
        return str(value.get("name", value.get("short_name", "")))
    return str(value).strip()


def _lookup_catalog_confidence(source: str, azure: str) -> Optional[float]:
    """Look up static catalog confidence for a source→azure pair."""
    from services.mappings import CROSS_CLOUD_MAPPINGS

    src_lower = source.lower()
    az_lower = azure.lower()
    for entry in CROSS_CLOUD_MAPPINGS:
        if entry["aws"].lower() == src_lower and entry["azure"].lower() == az_lower:
            return entry["confidence"]
    return None


def _build_feature_parity(source: str, azure: str) -> Dict[str, Any]:
    """Build feature parity checklist for a source→azure pair."""
    key = _find_parity_key(source, azure)
    if key is None:
        return {
            "matched_features": [],
            "missing_features": [],
            "matched_count": 0,
            "total_features": 0,
            "parity_score": "N/A — parity data not available for this pair",
        }

    matched, missing = _FEATURE_PARITY[key]
    total = len(matched) + len(missing)
    return {
        "matched_features": list(matched),
        "missing_features": list(missing),
        "matched_count": len(matched),
        "total_features": total,
        "parity_score": f"{len(matched)}/{total} ({round(len(matched) / total * 100)}%)" if total else "N/A",
    }


def _find_parity_key(source: str, azure: str) -> Optional[tuple]:
    """Fuzzy-match against feature parity keys."""
    src_lower = source.lower()
    az_lower = azure.lower()
    for key in _FEATURE_PARITY:
        if key[0].lower() == src_lower and key[1].lower() == az_lower:
            return key
    # Fallback: partial match on source only
    for key in _FEATURE_PARITY:
        if key[0].lower() == src_lower:
            return key
    return None


def _get_azure_docs(azure_service: str) -> List[Dict[str, str]]:
    """Return Azure documentation links for a service."""
    docs = list(_AZURE_DOCS.get(azure_service, []))

    # Always include comparison and Well-Architected reference
    docs.append({
        "title": "AWS to Azure services comparison",
        "url": _AWS_COMPARISON_URL,
    })
    docs.append({
        "title": "Azure Well-Architected Framework",
        "url": _WELL_ARCHITECTED_URL,
    })
    return docs


def _get_migration_guidance(source: str, azure: str) -> Dict[str, Any]:
    """Return migration guidance for a source→azure pair."""
    key = _find_guidance_key(source, azure)
    if key is None:
        return {
            "migration_notes": "No specific migration guidance available for this pair. Refer to the Azure migration documentation.",
            "estimated_effort": "unknown",
            "breaking_changes": [],
        }
    return dict(_MIGRATION_GUIDANCE[key])


def _find_guidance_key(source: str, azure: str) -> Optional[tuple]:
    """Fuzzy-match against migration guidance keys."""
    src_lower = source.lower()
    az_lower = azure.lower()
    for key in _MIGRATION_GUIDANCE:
        if key[0].lower() == src_lower and key[1].lower() == az_lower:
            return key
    for key in _MIGRATION_GUIDANCE:
        if key[0].lower() == src_lower:
            return key
    return None
