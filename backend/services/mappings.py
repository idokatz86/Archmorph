"""
Cross-Cloud Service Mappings — AWS ↔ Azure ↔ GCP equivalents with confidence scores.
Each mapping: { aws, azure, gcp, category, confidence, notes }
"""

CROSS_CLOUD_MAPPINGS = [
    # ═══════════════════════════════════════════════════════════
    # COMPUTE
    # ═══════════════════════════════════════════════════════════
    {"aws": "EC2", "azure": "Virtual Machines", "gcp": "Compute Engine", "category": "Compute", "confidence": 0.95, "notes": "Direct equivalent — IaaS virtual machines"},
    {"aws": "Lambda", "azure": "Azure Functions", "gcp": "Cloud Functions", "category": "Compute", "confidence": 0.95, "notes": "Event-driven serverless compute"},
    {"aws": "ECS", "azure": "Container Instances", "gcp": "Cloud Run", "category": "Compute", "confidence": 0.85, "notes": "Container orchestration — different abstractions"},
    {"aws": "EKS", "azure": "AKS", "gcp": "GKE", "category": "Compute", "confidence": 0.95, "notes": "Managed Kubernetes — all based on upstream K8s"},
    {"aws": "Fargate", "azure": "Container Apps", "gcp": "Cloud Run", "category": "Compute", "confidence": 0.90, "notes": "Serverless container execution"},
    {"aws": "Lightsail", "azure": "App Service", "gcp": "App Engine", "category": "Compute", "confidence": 0.80, "notes": "Simplified PaaS — different feature sets"},
    {"aws": "Batch", "azure": "Azure Batch", "gcp": "Batch", "category": "Compute", "confidence": 0.95, "notes": "Managed batch computing"},
    {"aws": "Elastic Beanstalk", "azure": "App Service", "gcp": "App Engine", "category": "Compute", "confidence": 0.90, "notes": "PaaS for web applications"},
    {"aws": "Outposts", "azure": "Azure Stack", "gcp": "Anthos", "category": "Compute", "confidence": 0.85, "notes": "Hybrid/on-premises cloud extension"},
    {"aws": "App Runner", "azure": "Container Apps", "gcp": "Cloud Run", "category": "Compute", "confidence": 0.90, "notes": "Simple containerized app deployment"},
    {"aws": "EC2 Auto Scaling", "azure": "VM Scale Sets", "gcp": "Managed Instance Groups", "category": "Compute", "confidence": 0.95, "notes": "Auto-scaling VM groups"},
    {"aws": "EC2 Image Builder", "azure": "Image Builder", "gcp": "Compute Engine (custom images)", "category": "Compute", "confidence": 0.85, "notes": "VM image creation pipelines"},

    # ═══════════════════════════════════════════════════════════
    # STORAGE
    # ═══════════════════════════════════════════════════════════
    {"aws": "S3", "azure": "Blob Storage", "gcp": "Cloud Storage", "category": "Storage", "confidence": 0.95, "notes": "Object storage — near-identical capabilities"},
    {"aws": "EBS", "azure": "Managed Disks", "gcp": "Persistent Disk", "category": "Storage", "confidence": 0.95, "notes": "Block storage for VMs"},
    {"aws": "EFS", "azure": "Azure Files", "gcp": "Filestore", "category": "Storage", "confidence": 0.90, "notes": "Managed NFS file storage"},
    {"aws": "FSx", "azure": "NetApp Files", "gcp": "NetApp Volumes", "category": "Storage", "confidence": 0.85, "notes": "Enterprise file systems (Windows/Lustre/NetApp)"},
    {"aws": "S3 Glacier", "azure": "Archive Storage", "gcp": "Archive Storage", "category": "Storage", "confidence": 0.95, "notes": "Cold/archive data storage"},
    {"aws": "Storage Gateway", "azure": "StorSimple", "gcp": "Storage Transfer Service", "category": "Storage", "confidence": 0.80, "notes": "Hybrid storage — different approaches"},
    {"aws": "Snow Family", "azure": "Data Box", "gcp": "Transfer Appliance", "category": "Storage", "confidence": 0.90, "notes": "Physical data transfer devices"},
    {"aws": "Backup", "azure": "Azure Backup", "gcp": "Backup and DR", "category": "Storage", "confidence": 0.90, "notes": "Centralized backup service"},
    {"aws": "DataSync", "azure": "File Sync", "gcp": "Storage Transfer Service", "category": "Storage", "confidence": 0.85, "notes": "Data transfer and synchronization"},

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════
    {"aws": "RDS", "azure": "SQL Database", "gcp": "Cloud SQL", "category": "Database", "confidence": 0.90, "notes": "Managed relational database (multi-engine)"},
    # #590 — Aurora is PostgreSQL- or MySQL-compatible; SQL Database is Microsoft
    # SQL Server. The previous "SQL Database (Hyperscale)" mapping silently moves
    # the customer to a different engine + a SQL Server licence cost surprise.
    # Split into two engine-correct rows; both reference Azure's flexible-server
    # offering (current Azure GA recommendation as of 2026-05-01).
    {"aws": "Aurora PostgreSQL", "azure": "Azure Database for PostgreSQL Flexible Server", "gcp": "AlloyDB", "category": "Database", "confidence": 0.90, "notes": "Engine-correct PostgreSQL mapping. Aurora PG → Azure DB for PostgreSQL Flexible Server. (Pre-#590 mapped to SQL Server — wrong engine.)", "last_reviewed": "2026-05-01"},
    {"aws": "Aurora MySQL", "azure": "Azure Database for MySQL Flexible Server", "gcp": "Cloud SQL for MySQL", "category": "Database", "confidence": 0.90, "notes": "Engine-correct MySQL mapping. Aurora MySQL → Azure DB for MySQL Flexible Server.", "last_reviewed": "2026-05-01"},
    {"aws": "DynamoDB", "azure": "Cosmos DB", "gcp": "Firestore / Bigtable", "category": "Database", "confidence": 0.85, "notes": "Managed NoSQL — Cosmos DB is multi-model"},
    {"aws": "ElastiCache", "azure": "Cache for Redis", "gcp": "Memorystore", "category": "Database", "confidence": 0.95, "notes": "Managed Redis/Memcached"},
    {"aws": "Redshift", "azure": "Synapse Analytics", "gcp": "BigQuery", "category": "Database", "confidence": 0.90, "notes": "Data warehouse — different architectures"},
    {"aws": "Neptune", "azure": "Cosmos DB (Gremlin)", "gcp": "Vertex AI (graph features)", "category": "Database", "confidence": 0.80, "notes": "Graph database — Azure uses Cosmos Gremlin API"},
    {"aws": "DocumentDB", "azure": "Cosmos DB (MongoDB API)", "gcp": "Firestore", "category": "Database", "confidence": 0.85, "notes": "Document database"},
    {"aws": "Keyspaces", "azure": "Cosmos DB (Cassandra)", "gcp": "Bigtable", "category": "Database", "confidence": 0.80, "notes": "Wide-column NoSQL database"},
    {"aws": "Timestream", "azure": "Time Series Insights / Data Explorer", "gcp": "BigQuery (time series)", "category": "Database", "confidence": 0.80, "notes": "Time series database"},
    {"aws": "QLDB", "azure": "Confidential Ledger", "gcp": "Cloud Spanner (immutable)", "category": "Database", "confidence": 0.75, "notes": "Ledger/immutable database — limited equivalents"},
    {"aws": "MemoryDB", "azure": "Cache for Redis (Enterprise)", "gcp": "Memorystore (Redis Cluster)", "category": "Database", "confidence": 0.85, "notes": "In-memory database"},
    {"aws": "DMS", "azure": "Database Migration Service", "gcp": "Database Migration Service", "category": "Database", "confidence": 0.90, "notes": "Database migration tooling"},

    # ═══════════════════════════════════════════════════════════
    # NETWORKING
    # ═══════════════════════════════════════════════════════════
    {"aws": "VPC", "azure": "Virtual Network", "gcp": "VPC", "category": "Networking", "confidence": 0.95, "notes": "Virtual private cloud networking"},
    # #590 — Azure CDN Standard is retiring; modern equivalent is Azure Front
    # Door (Standard/Premium with built-in CDN).
    {"aws": "CloudFront", "azure": "Front Door", "gcp": "Cloud CDN", "category": "Networking", "confidence": 0.90, "notes": "Content delivery + global routing. Azure CDN Standard is retiring — use Front Door Standard/Premium.", "last_reviewed": "2026-05-01"},
    {"aws": "Route 53", "azure": "Azure DNS / Traffic Manager", "gcp": "Cloud DNS", "category": "Networking", "confidence": 0.90, "notes": "DNS service — Route 53 includes health checks"},
    {"aws": "API Gateway", "azure": "API Management", "gcp": "Apigee", "category": "Networking", "confidence": 0.85, "notes": "API management — different feature depth"},
    {"aws": "ELB", "azure": "Load Balancer / Application Gateway", "gcp": "Cloud Load Balancing", "category": "Networking", "confidence": 0.90, "notes": "Load balancing (L4/L7)"},
    {"aws": "Direct Connect", "azure": "ExpressRoute", "gcp": "Cloud Interconnect", "category": "Networking", "confidence": 0.95, "notes": "Dedicated private network connection"},
    {"aws": "Global Accelerator", "azure": "Front Door", "gcp": "Cloud Load Balancing (Premium)", "category": "Networking", "confidence": 0.85, "notes": "Global traffic acceleration"},
    {"aws": "Transit Gateway", "azure": "Virtual WAN", "gcp": "Network Connectivity Center", "category": "Networking", "confidence": 0.85, "notes": "Hub-and-spoke network topology"},
    {"aws": "PrivateLink", "azure": "Private Link", "gcp": "Private Service Connect", "category": "Networking", "confidence": 0.95, "notes": "Private endpoint connectivity"},
    {"aws": "App Mesh", "azure": "Open Service Mesh", "gcp": "Traffic Director", "category": "Networking", "confidence": 0.80, "notes": "Service mesh — different maturity levels"},
    {"aws": "Cloud Map", "azure": "Azure DNS (private zones)", "gcp": "Service Directory", "category": "Networking", "confidence": 0.80, "notes": "Service discovery"},
    {"aws": "VPN", "azure": "VPN Gateway", "gcp": "Cloud VPN", "category": "Networking", "confidence": 0.95, "notes": "Site-to-site VPN connectivity"},
    {"aws": "Network Firewall", "azure": "Azure Firewall", "gcp": "Cloud Firewall", "category": "Networking", "confidence": 0.90, "notes": "Managed network firewall"},

    # ═══════════════════════════════════════════════════════════
    # SECURITY
    # ═══════════════════════════════════════════════════════════
    {"aws": "IAM", "azure": "Entra ID / RBAC", "gcp": "Cloud IAM", "category": "Security", "confidence": 0.90, "notes": "Identity and access management"},
    # #590 — Microsoft retired the "B2C" sub-brand in late 2024; the product is
    # now "Entra External ID". Drop the parenthetical to avoid stale branding.
    {"aws": "Cognito", "azure": "Entra External ID", "gcp": "Identity Platform", "category": "Security", "confidence": 0.90, "notes": "Customer identity management. (Pre-#590 said ‘Entra External ID (B2C)’ — the B2C name was retired late 2024.)", "last_reviewed": "2026-05-01"},
    # #590 — GuardDuty (detection) maps to Defender for Cloud + Microsoft
    # Sentinel (SIEM) together; either alone loses architectural intent.
    {"aws": "GuardDuty", "azure": "Defender for Cloud + Microsoft Sentinel", "gcp": "Security Command Center", "category": "Security", "confidence": 0.85, "notes": "Threat detection + SIEM. Defender for Cloud detects; Sentinel is the SIEM/SOAR pair. Pre-#590 only listed Defender (lossy).", "last_reviewed": "2026-05-01"},
    {"aws": "Inspector", "azure": "Defender for Cloud", "gcp": "Web Security Scanner", "category": "Security", "confidence": 0.80, "notes": "Vulnerability assessment"},
    {"aws": "Macie", "azure": "Information Protection", "gcp": "Cloud DLP", "category": "Security", "confidence": 0.85, "notes": "Sensitive data discovery and protection"},
    {"aws": "KMS", "azure": "Key Vault", "gcp": "Cloud KMS", "category": "Security", "confidence": 0.95, "notes": "Encryption key management (software-protected)", "last_reviewed": "2026-05-01"},
    # #590 — Add the FIPS 140-3 / Dedicated-HSM tier explicitly. KMS Custom Key
    # Stores backed by CloudHSM map to Azure Managed HSM, not generic Key Vault.
    {"aws": "KMS (FIPS 140-3)", "azure": "Managed HSM", "gcp": "Cloud HSM", "category": "Security", "confidence": 0.90, "notes": "FIPS 140-3 / dedicated-HSM-backed key management. Use when KMS is configured with a CloudHSM Custom Key Store.", "last_reviewed": "2026-05-01"},
    {"aws": "Secrets Manager", "azure": "Key Vault (Secrets)", "gcp": "Secret Manager", "category": "Security", "confidence": 0.95, "notes": "Secrets management — Azure vaults combine keys+secrets"},
    {"aws": "WAF", "azure": "Web Application Firewall", "gcp": "Cloud Armor", "category": "Security", "confidence": 0.90, "notes": "Web application firewall"},
    {"aws": "Shield", "azure": "DDoS Protection", "gcp": "Cloud Armor (DDoS)", "category": "Security", "confidence": 0.90, "notes": "DDoS mitigation"},
    {"aws": "Certificate Manager", "azure": "Key Vault (Certificates)", "gcp": "Certificate Manager", "category": "Security", "confidence": 0.90, "notes": "TLS/SSL certificate management"},
    {"aws": "IAM Identity Center", "azure": "Entra ID (SSO)", "gcp": "BeyondCorp Enterprise", "category": "Security", "confidence": 0.85, "notes": "Single sign-on"},
    {"aws": "Directory Service", "azure": "Entra Domain Services", "gcp": "Managed AD (via Anthos)", "category": "Security", "confidence": 0.80, "notes": "Managed Active Directory"},
    {"aws": "Security Hub", "azure": "Microsoft Sentinel", "gcp": "Chronicle", "category": "Security", "confidence": 0.85, "notes": "Centralized security management / SIEM"},
    {"aws": "CloudHSM", "azure": "Dedicated HSM", "gcp": "Cloud HSM", "category": "Security", "confidence": 0.95, "notes": "Hardware security modules"},

    # ═══════════════════════════════════════════════════════════
    # AI / ML
    # ═══════════════════════════════════════════════════════════
    {"aws": "SageMaker", "azure": "Azure Machine Learning", "gcp": "Vertex AI", "category": "AI/ML", "confidence": 0.90, "notes": "End-to-end ML platform"},
    {"aws": "Bedrock", "azure": "Azure OpenAI Service", "gcp": "Gemini on Vertex AI", "category": "AI/ML", "confidence": 0.85, "notes": "Foundation model access — different model families"},
    {"aws": "Rekognition", "azure": "AI Vision", "gcp": "Vision AI", "category": "AI/ML", "confidence": 0.90, "notes": "Image/video analysis"},
    {"aws": "Comprehend", "azure": "AI Language", "gcp": "Natural Language AI", "category": "AI/ML", "confidence": 0.90, "notes": "Natural language processing"},
    {"aws": "Polly", "azure": "AI Speech (TTS)", "gcp": "Text-to-Speech", "category": "AI/ML", "confidence": 0.95, "notes": "Text-to-speech synthesis"},
    {"aws": "Transcribe", "azure": "AI Speech (STT)", "gcp": "Speech-to-Text", "category": "AI/ML", "confidence": 0.95, "notes": "Speech-to-text transcription"},
    {"aws": "Translate", "azure": "AI Translator", "gcp": "Translation AI", "category": "AI/ML", "confidence": 0.95, "notes": "Machine translation"},
    {"aws": "Lex", "azure": "Bot Service", "gcp": "Dialogflow", "category": "AI/ML", "confidence": 0.90, "notes": "Conversational AI / chatbot"},
    {"aws": "Textract", "azure": "AI Document Intelligence", "gcp": "Document AI", "category": "AI/ML", "confidence": 0.90, "notes": "Document data extraction (OCR+)"},
    {"aws": "Personalize", "azure": "Personalizer", "gcp": "Recommendations AI", "category": "AI/ML", "confidence": 0.85, "notes": "Personalization and recommendations"},
    {"aws": "Kendra", "azure": "AI Search", "gcp": "Vertex AI Search", "category": "AI/ML", "confidence": 0.85, "notes": "Enterprise AI-powered search"},
    {"aws": "HealthLake", "azure": "Health Insights", "gcp": "Healthcare API", "category": "AI/ML", "confidence": 0.80, "notes": "Healthcare data analysis"},
    {"aws": "CodeWhisperer", "azure": "Copilot Studio", "gcp": "Gemini Code Assist", "category": "AI/ML", "confidence": 0.85, "notes": "AI code assistant"},

    # ═══════════════════════════════════════════════════════════
    # ANALYTICS
    # ═══════════════════════════════════════════════════════════
    {"aws": "Athena", "azure": "Synapse Analytics (Serverless SQL)", "gcp": "BigQuery", "category": "Analytics", "confidence": 0.85, "notes": "Serverless SQL query on data lake"},
    {"aws": "EMR", "azure": "HDInsight / Databricks", "gcp": "Dataproc", "category": "Analytics", "confidence": 0.85, "notes": "Managed Spark/Hadoop"},
    {"aws": "Kinesis", "azure": "Event Hubs / Stream Analytics", "gcp": "Dataflow / Pub/Sub", "category": "Analytics", "confidence": 0.85, "notes": "Real-time data streaming"},
    {"aws": "QuickSight", "azure": "Power BI", "gcp": "Looker", "category": "Analytics", "confidence": 0.90, "notes": "Business intelligence and visualization"},
    {"aws": "Glue", "azure": "Data Factory", "gcp": "Data Fusion / Dataflow", "category": "Analytics", "confidence": 0.85, "notes": "Data integration and ETL"},
    {"aws": "Lake Formation", "azure": "Microsoft Purview", "gcp": "Dataplex", "category": "Analytics", "confidence": 0.80, "notes": "Data lake governance and management"},
    {"aws": "MSK", "azure": "Event Hubs (Kafka)", "gcp": "Pub/Sub", "category": "Analytics", "confidence": 0.85, "notes": "Managed messaging/streaming — Kafka on Azure Event Hubs"},
    {"aws": "OpenSearch", "azure": "Data Explorer / AI Search", "gcp": "Elasticsearch on GKE", "category": "Analytics", "confidence": 0.80, "notes": "Search and analytics engine"},
    {"aws": "MWAA", "azure": "Data Factory (orchestration)", "gcp": "Cloud Composer", "category": "Analytics", "confidence": 0.85, "notes": "Managed Apache Airflow"},
    {"aws": "Data Exchange", "azure": "Data Share", "gcp": "Analytics Hub", "category": "Analytics", "confidence": 0.80, "notes": "Data sharing/exchange marketplace"},

    # ═══════════════════════════════════════════════════════════
    # APPLICATION INTEGRATION
    # ═══════════════════════════════════════════════════════════
    {"aws": "SQS", "azure": "Service Bus (Queues)", "gcp": "Cloud Tasks / Pub/Sub", "category": "Integration", "confidence": 0.90, "notes": "Message queuing"},
    {"aws": "SNS", "azure": "Event Grid / Notification Hubs", "gcp": "Pub/Sub / Firebase Cloud Messaging", "category": "Integration", "confidence": 0.85, "notes": "Pub/sub and notifications"},
    {"aws": "EventBridge", "azure": "Event Grid", "gcp": "Eventarc", "category": "Integration", "confidence": 0.90, "notes": "Serverless event bus"},
    {"aws": "Step Functions", "azure": "Logic Apps", "gcp": "Workflows", "category": "Integration", "confidence": 0.85, "notes": "Workflow orchestration"},
    {"aws": "Amazon MQ", "azure": "Service Bus (Premium)", "gcp": "Pub/Sub", "category": "Integration", "confidence": 0.80, "notes": "Managed message broker"},
    {"aws": "AppSync", "azure": "API Apps (with GraphQL)", "gcp": "Apigee (GraphQL)", "category": "Integration", "confidence": 0.75, "notes": "GraphQL APIs — different maturity levels"},

    # ═══════════════════════════════════════════════════════════
    # DEVELOPER TOOLS
    # ═══════════════════════════════════════════════════════════
    {"aws": "CodeCommit", "azure": "Azure DevOps Repos", "gcp": "Cloud Source Repositories", "category": "DevTools", "confidence": 0.90, "notes": "Git repository hosting"},
    {"aws": "CodeBuild", "azure": "Azure Pipelines (Build)", "gcp": "Cloud Build", "category": "DevTools", "confidence": 0.90, "notes": "CI build service"},
    {"aws": "CodeDeploy", "azure": "Azure Pipelines (Deploy)", "gcp": "Cloud Deploy", "category": "DevTools", "confidence": 0.85, "notes": "Continuous deployment"},
    {"aws": "CodePipeline", "azure": "Azure Pipelines", "gcp": "Cloud Build triggers", "category": "DevTools", "confidence": 0.90, "notes": "CI/CD pipeline orchestration"},
    {"aws": "CloudFormation", "azure": "ARM Templates / Bicep", "gcp": "Deployment Manager", "category": "DevTools", "confidence": 0.90, "notes": "Infrastructure as code"},
    {"aws": "X-Ray", "azure": "Application Insights", "gcp": "Cloud Trace", "category": "DevTools", "confidence": 0.90, "notes": "Distributed tracing"},
    {"aws": "CodeArtifact", "azure": "Azure Artifacts", "gcp": "Artifact Registry", "category": "DevTools", "confidence": 0.90, "notes": "Package/artifact repository"},
    {"aws": "ECR", "azure": "Container Registry", "gcp": "Artifact Registry / Container Registry", "category": "DevTools", "confidence": 0.95, "notes": "Container image registry"},
    {"aws": "FIS", "azure": "Chaos Studio", "gcp": "Litmus (OSS on GKE)", "category": "DevTools", "confidence": 0.80, "notes": "Chaos engineering"},

    # ═══════════════════════════════════════════════════════════
    # MANAGEMENT & GOVERNANCE
    # ═══════════════════════════════════════════════════════════
    {"aws": "CloudWatch", "azure": "Azure Monitor / Log Analytics", "gcp": "Cloud Monitoring", "category": "Management", "confidence": 0.90, "notes": "Monitoring and observability"},
    {"aws": "CloudTrail", "azure": "Azure Monitor (Activity Logs)", "gcp": "Cloud Audit Logs", "category": "Management", "confidence": 0.90, "notes": "API activity auditing"},
    {"aws": "Config", "azure": "Azure Policy", "gcp": "Organization Policy", "category": "Management", "confidence": 0.85, "notes": "Resource configuration compliance"},
    {"aws": "Systems Manager", "azure": "Azure Automation", "gcp": "OS Config (via VM Manager)", "category": "Management", "confidence": 0.80, "notes": "Operations management — different scope"},
    {"aws": "Organizations", "azure": "Management Groups", "gcp": "Resource Manager", "category": "Management", "confidence": 0.90, "notes": "Multi-account/subscription governance"},
    {"aws": "Control Tower", "azure": "Azure Blueprints / Landing Zones", "gcp": "Assured Workloads", "category": "Management", "confidence": 0.80, "notes": "Multi-account best practice setup"},
    {"aws": "Trusted Advisor", "azure": "Azure Advisor", "gcp": "Recommender", "category": "Management", "confidence": 0.90, "notes": "Best practice recommendations"},
    {"aws": "Cost Explorer", "azure": "Cost Management", "gcp": "Cloud Billing", "category": "Management", "confidence": 0.90, "notes": "Cost analysis and optimization"},
    {"aws": "Health Dashboard", "azure": "Service Health", "gcp": "Service Health", "category": "Management", "confidence": 0.95, "notes": "Service status dashboard"},

    # ═══════════════════════════════════════════════════════════
    # IOT
    # ═══════════════════════════════════════════════════════════
    {"aws": "IoT Core", "azure": "IoT Hub", "gcp": "Cloud IoT Core", "category": "IoT", "confidence": 0.90, "notes": "IoT device connectivity and management"},
    {"aws": "IoT Greengrass", "azure": "IoT Edge", "gcp": "Anthos (edge)", "category": "IoT", "confidence": 0.85, "notes": "Edge computing for IoT"},
    {"aws": "IoT Analytics", "azure": "Time Series Insights / Stream Analytics", "gcp": "BigQuery (IoT data)", "category": "IoT", "confidence": 0.80, "notes": "IoT data analytics"},
    {"aws": "IoT SiteWise", "azure": "IoT Hub + Digital Twins", "gcp": "Cloud IoT + Dataflow", "category": "IoT", "confidence": 0.75, "notes": "Industrial IoT"},
    {"aws": "IoT TwinMaker", "azure": "Digital Twins", "gcp": "Supply Chain Twin (limited)", "category": "IoT", "confidence": 0.80, "notes": "Digital twin modeling"},
    {"aws": "IoT FleetWise", "azure": "IoT Hub + Stream Analytics", "gcp": "Cloud IoT + Pub/Sub", "category": "IoT", "confidence": 0.70, "notes": "Vehicle data — AWS-specific, limited equivalents"},

    # ═══════════════════════════════════════════════════════════
    # MEDIA
    # ═══════════════════════════════════════════════════════════
    {"aws": "MediaConvert", "azure": "Media Services (encoding)", "gcp": "Transcoder API", "category": "Media", "confidence": 0.90, "notes": "Video transcoding"},
    {"aws": "MediaLive", "azure": "Media Services (live)", "gcp": "Live Stream API", "category": "Media", "confidence": 0.85, "notes": "Live video processing"},
    {"aws": "IVS", "azure": "Communication Services", "gcp": "Live Stream API", "category": "Media", "confidence": 0.75, "notes": "Interactive live streaming"},

    # ═══════════════════════════════════════════════════════════
    # MIGRATION
    # ═══════════════════════════════════════════════════════════
    {"aws": "Migration Hub", "azure": "Azure Migrate", "gcp": "Migrate to VMs", "category": "Migration", "confidence": 0.85, "notes": "Migration tracking and assessment"},
    {"aws": "Application Migration Service", "azure": "Site Recovery", "gcp": "Migrate to VMs", "category": "Migration", "confidence": 0.85, "notes": "Server migration (lift and shift)"},

    # ═══════════════════════════════════════════════════════════
    # BUSINESS APPLICATIONS
    # ═══════════════════════════════════════════════════════════
    {"aws": "SES", "azure": "Email Communication", "gcp": "Google Workspace (Gmail API)", "category": "Business", "confidence": 0.80, "notes": "Email sending service"},
    {"aws": "Connect", "azure": "Dynamics 365 Contact Center", "gcp": "Contact Center AI", "category": "Business", "confidence": 0.80, "notes": "Cloud contact center"},
    {"aws": "WorkSpaces", "azure": "Virtual Desktop", "gcp": "Chrome Remote Desktop / VDI on GCE", "category": "Business", "confidence": 0.85, "notes": "Virtual desktop infrastructure"},
    {"aws": "Pinpoint", "azure": "Notification Hubs", "gcp": "Firebase Cloud Messaging", "category": "Business", "confidence": 0.75, "notes": "Multi-channel marketing/notifications"},

    # ═══════════════════════════════════════════════════════════
    # HYBRID & MULTI-CLOUD  (#60 — Azure Arc & Hybrid Management)
    # ═══════════════════════════════════════════════════════════
    {"aws": "EKS Anywhere", "azure": "Azure Arc-enabled Kubernetes", "gcp": "Anthos (multi-cloud)", "category": "Hybrid", "confidence": 0.85, "notes": "Managed Kubernetes across on-prem and multi-cloud — Arc projects Azure control plane anywhere"},
    {"aws": "SSM (hybrid nodes)", "azure": "Azure Arc-enabled Servers", "gcp": "Anthos for VMs", "category": "Hybrid", "confidence": 0.80, "notes": "Manage on-prem/multi-cloud servers from the cloud control plane"},
    {"aws": "RDS on Outposts", "azure": "Azure Arc-enabled SQL", "gcp": "AlloyDB Omni", "category": "Hybrid", "confidence": 0.75, "notes": "Run managed database engine outside the cloud provider's region"},
    {"aws": "Control Tower (multi-account)", "azure": "Azure Lighthouse", "gcp": "Cloud Foundation Toolkit", "category": "Hybrid", "confidence": 0.80, "notes": "Multi-tenant / multi-subscription governance and delegation"},
    {"aws": "Outposts (rack)", "azure": "Azure Stack HCI", "gcp": "Google Distributed Cloud (GDC)", "category": "Hybrid", "confidence": 0.85, "notes": "Full cloud stack running on-premises on customer-owned hardware"},

    # ═══════════════════════════════════════════════════════════
    # GENERATIVE AI & AI AGENTS  (#61)
    # ═══════════════════════════════════════════════════════════
    {"aws": "Bedrock Agents", "azure": "Azure AI Agent Service", "gcp": "Vertex AI Agents", "category": "AI/ML", "confidence": 0.80, "notes": "Autonomous AI agents with tool-use — rapidly evolving across all providers"},
    {"aws": "Bedrock Knowledge Bases", "azure": "Azure AI Search (RAG)", "gcp": "Vertex AI Search", "category": "AI/ML", "confidence": 0.80, "notes": "Retrieval-Augmented Generation with managed vector stores"},
    {"aws": "Q Business", "azure": "Microsoft 365 Copilot / AI Foundry", "gcp": "Gemini for Workspace", "category": "AI/ML", "confidence": 0.75, "notes": "Enterprise AI assistant grounded in organizational data"},
    {"aws": "SageMaker Canvas", "azure": "Azure ML AutoML", "gcp": "Vertex AI AutoML", "category": "AI/ML", "confidence": 0.85, "notes": "No-code / low-code ML model building"},
    {"aws": "Bedrock Guardrails", "azure": "Azure AI Content Safety", "gcp": "Vertex AI Safety Filters", "category": "AI/ML", "confidence": 0.80, "notes": "Content filtering and responsible AI guardrails for LLM applications"},
    {"aws": "PartyRock", "azure": "Azure AI Foundry (low-code)", "gcp": "Vertex AI Studio", "category": "AI/ML", "confidence": 0.75, "notes": "Low-code generative AI app builder"},
    {"aws": "CodeGuru", "azure": "GitHub Advanced Security", "gcp": "Gemini Code Assist", "category": "AI/ML", "confidence": 0.75, "notes": "AI-powered code review and security analysis"},

    # ═══════════════════════════════════════════════════════════
    # EDGE COMPUTING & DISTRIBUTED CLOUD  (#62)
    # ═══════════════════════════════════════════════════════════
    {"aws": "Wavelength", "azure": "Azure Edge Zones", "gcp": "Distributed Cloud Edge", "category": "Edge", "confidence": 0.80, "notes": "Ultra-low-latency compute at 5G / telco edge"},
    {"aws": "Local Zones", "azure": "Azure Extended Zones", "gcp": "Distributed Cloud Edge", "category": "Edge", "confidence": 0.80, "notes": "Cloud infrastructure closer to metro areas for latency-sensitive apps"},
    {"aws": "Lambda@Edge", "azure": "Azure Front Door Rules Engine", "gcp": "Cloud CDN (edge functions)", "category": "Edge", "confidence": 0.80, "notes": "Serverless logic at CDN edge locations"},
    {"aws": "CloudFront Functions", "azure": "Azure CDN Rules Engine", "gcp": "Cloud CDN Policies", "category": "Edge", "confidence": 0.80, "notes": "Lightweight edge compute for request/response manipulation"},
    {"aws": "Elastic Disaster Recovery", "azure": "Azure Site Recovery", "gcp": "Backup and DR (Actifio)", "category": "Edge", "confidence": 0.85, "notes": "Cloud-native disaster recovery with continuous replication"},

    # ═══════════════════════════════════════════════════════════
    # MANAGED OBSERVABILITY  (#63)
    # ═══════════════════════════════════════════════════════════
    {"aws": "Managed Grafana", "azure": "Azure Managed Grafana", "gcp": "Grafana (marketplace)", "category": "Observability", "confidence": 0.90, "notes": "Fully managed Grafana dashboards — first-party on AWS/Azure, marketplace on GCP"},
    {"aws": "Managed Prometheus", "azure": "Azure Monitor (Prometheus)", "gcp": "Managed Service for Prometheus", "category": "Observability", "confidence": 0.90, "notes": "Managed Prometheus-compatible metrics collection"},
    {"aws": "Distro for OpenTelemetry", "azure": "Azure Monitor (OpenTelemetry)", "gcp": "Cloud Trace (OpenTelemetry)", "category": "Observability", "confidence": 0.85, "notes": "OpenTelemetry distribution for vendor-neutral telemetry collection"},
    {"aws": "CloudWatch Container Insights", "azure": "Container Insights (Azure Monitor)", "gcp": "GKE Monitoring", "category": "Observability", "confidence": 0.85, "notes": "Container and Kubernetes-specific monitoring and logging"},

    # ═══════════════════════════════════════════════════════════
    # DATA GOVERNANCE & DATA MESH  (#64)
    # ═══════════════════════════════════════════════════════════
    {"aws": "DataZone", "azure": "Microsoft Purview (Data Governance)", "gcp": "Dataplex", "category": "Data Governance", "confidence": 0.85, "notes": "Data catalog, governance, and domain-based data mesh management"},
    {"aws": "Clean Rooms", "azure": "Azure Confidential Clean Rooms", "gcp": "BigQuery Clean Rooms", "category": "Data Governance", "confidence": 0.80, "notes": "Privacy-safe collaborative analytics across organizations"},
    {"aws": "AppFlow", "azure": "Azure Logic Apps (SaaS connectors)", "gcp": "Application Integration", "category": "Data Governance", "confidence": 0.80, "notes": "No-code SaaS data integration (Salesforce, SAP, etc.)"},
    {"aws": "Audit Manager", "azure": "Microsoft Purview Compliance Manager", "gcp": "Assured Workloads", "category": "Data Governance", "confidence": 0.80, "notes": "Continuous audit and compliance evidence collection"},
    {"aws": "Glue DataBrew", "azure": "Azure Data Factory (data wrangling)", "gcp": "Dataprep by Trifacta", "category": "Data Governance", "confidence": 0.85, "notes": "Visual data preparation and cleansing tool"},

    # ═══════════════════════════════════════════════════════════
    # ZERO TRUST & SASE SECURITY  (#67)
    # ═══════════════════════════════════════════════════════════
    {"aws": "Verified Access", "azure": "Entra Private Access", "gcp": "BeyondCorp Enterprise", "category": "Zero Trust", "confidence": 0.85, "notes": "Zero-trust network access — identity-based app access without VPN"},
    {"aws": "Security Lake", "azure": "Microsoft Sentinel (data lake)", "gcp": "Chronicle SIEM", "category": "Zero Trust", "confidence": 0.80, "notes": "Centralized security data lake with OCSF / normalized schema"},
    {"aws": "Detective", "azure": "Microsoft Sentinel (investigation)", "gcp": "Chronicle Investigation", "category": "Zero Trust", "confidence": 0.85, "notes": "Security investigation and root-cause analysis"},
    {"aws": "Firewall Manager", "azure": "Azure Firewall Manager", "gcp": "Cloud Firewall Policies", "category": "Zero Trust", "confidence": 0.90, "notes": "Centralized firewall policy management across accounts/subscriptions"},
    {"aws": "Network Firewall (IDPS)", "azure": "Azure Firewall Premium (IDPS)", "gcp": "Cloud IDS", "category": "Zero Trust", "confidence": 0.85, "notes": "Intrusion detection and prevention integrated with network firewall"},
    {"aws": "VPC Lattice", "azure": "Azure Private Link (service networking)", "gcp": "Private Service Connect", "category": "Zero Trust", "confidence": 0.80, "notes": "Application-layer service-to-service networking with built-in auth"},
]
