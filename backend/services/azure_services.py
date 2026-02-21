"""
Azure Services Catalog — Comprehensive list of Azure services with categories, descriptions, and metadata.
"""

AZURE_SERVICES = [
    # ═══════════════════════════════════════════════════════════
    # COMPUTE
    # ═══════════════════════════════════════════════════════════
    {"id": "az-virtual-machines", "name": "Virtual Machines", "fullName": "Azure Virtual Machines", "category": "Compute", "description": "On-demand, scalable virtual machines", "icon": "server"},
    {"id": "az-functions", "name": "Azure Functions", "fullName": "Azure Functions", "category": "Compute", "description": "Event-driven serverless compute", "icon": "function"},
    {"id": "az-container-instances", "name": "Container Instances", "fullName": "Azure Container Instances", "category": "Compute", "description": "Run containers without managing servers", "icon": "container"},
    {"id": "az-aks", "name": "AKS", "fullName": "Azure Kubernetes Service", "category": "Compute", "description": "Managed Kubernetes cluster", "icon": "kubernetes"},
    {"id": "az-container-apps", "name": "Container Apps", "fullName": "Azure Container Apps", "category": "Compute", "description": "Serverless containers with microservices features", "icon": "container"},
    {"id": "az-app-service", "name": "App Service", "fullName": "Azure App Service", "category": "Compute", "description": "Build, deploy, and scale web apps", "icon": "webapp"},
    {"id": "az-batch", "name": "Azure Batch", "fullName": "Azure Batch", "category": "Compute", "description": "Cloud-scale job scheduling and compute management", "icon": "batch"},
    {"id": "az-spring-apps", "name": "Spring Apps", "fullName": "Azure Spring Apps", "category": "Compute", "description": "Fully managed Spring Boot service", "icon": "spring"},
    {"id": "az-vmss", "name": "VM Scale Sets", "fullName": "Azure VM Scale Sets", "category": "Compute", "description": "Manage and scale sets of identical VMs", "icon": "autoscale"},
    {"id": "az-azure-stack", "name": "Azure Stack", "fullName": "Azure Stack", "category": "Compute", "description": "Build and run hybrid apps on-premises", "icon": "hybrid"},
    {"id": "az-azure-stack-hci", "name": "Azure Stack HCI", "fullName": "Azure Stack HCI", "category": "Compute", "description": "Hyperconverged infrastructure solution", "icon": "hybrid"},
    {"id": "az-azure-arc", "name": "Azure Arc", "fullName": "Azure Arc", "category": "Compute", "description": "Extend Azure management and services anywhere", "icon": "hybrid"},
    {"id": "az-dedicated-host", "name": "Dedicated Host", "fullName": "Azure Dedicated Host", "category": "Compute", "description": "Dedicated physical servers for your VMs", "icon": "server"},
    {"id": "az-image-builder", "name": "Image Builder", "fullName": "Azure Image Builder", "category": "Compute", "description": "Build and maintain VM images", "icon": "image"},
    {"id": "az-spot-vms", "name": "Spot VMs", "fullName": "Azure Spot Virtual Machines", "category": "Compute", "description": "Discounted VM capacity", "icon": "server"},

    # ═══════════════════════════════════════════════════════════
    # STORAGE
    # ═══════════════════════════════════════════════════════════
    {"id": "az-blob-storage", "name": "Blob Storage", "fullName": "Azure Blob Storage", "category": "Storage", "description": "Massively scalable object storage", "icon": "storage"},
    {"id": "az-managed-disks", "name": "Managed Disks", "fullName": "Azure Managed Disks", "category": "Storage", "description": "Persistent, high-performance block storage for VMs", "icon": "disk"},
    {"id": "az-files", "name": "Azure Files", "fullName": "Azure Files", "category": "Storage", "description": "Fully managed file shares in the cloud", "icon": "file"},
    {"id": "az-netapp-files", "name": "NetApp Files", "fullName": "Azure NetApp Files", "category": "Storage", "description": "Enterprise-grade file storage", "icon": "file"},
    {"id": "az-archive-storage", "name": "Archive Storage", "fullName": "Azure Archive Storage", "category": "Storage", "description": "Ultra-low-cost cold data storage", "icon": "archive"},
    {"id": "az-storage-gateway", "name": "StorSimple", "fullName": "Azure StorSimple", "category": "Storage", "description": "Hybrid cloud storage solution", "icon": "hybrid"},
    {"id": "az-data-box", "name": "Data Box", "fullName": "Azure Data Box", "category": "Storage", "description": "Appliance-based data transfer to Azure", "icon": "device"},
    {"id": "az-backup", "name": "Azure Backup", "fullName": "Azure Backup", "category": "Storage", "description": "Simplified backup as a service", "icon": "backup"},
    {"id": "az-adls", "name": "ADLS Gen2", "fullName": "Azure Data Lake Storage Gen2", "category": "Storage", "description": "Massively scalable data lake storage", "icon": "datalake"},
    {"id": "az-file-sync", "name": "File Sync", "fullName": "Azure File Sync", "category": "Storage", "description": "Centralize file shares in Azure Files", "icon": "sync"},
    {"id": "az-hpc-cache", "name": "HPC Cache", "fullName": "Azure HPC Cache", "category": "Storage", "description": "File caching for high-performance computing", "icon": "cache"},
    {"id": "az-elastic-san", "name": "Elastic SAN", "fullName": "Azure Elastic SAN", "category": "Storage", "description": "Cloud-native storage area network", "icon": "san"},

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════
    {"id": "az-sql-database", "name": "SQL Database", "fullName": "Azure SQL Database", "category": "Database", "description": "Managed relational SQL database (PaaS)", "icon": "database"},
    {"id": "az-sql-managed", "name": "SQL Managed Instance", "fullName": "Azure SQL Managed Instance", "category": "Database", "description": "Managed SQL Server with near-100% compatibility", "icon": "database"},
    {"id": "az-cosmos-db", "name": "Cosmos DB", "fullName": "Azure Cosmos DB", "category": "Database", "description": "Globally distributed, multi-model NoSQL database", "icon": "nosql"},
    {"id": "az-cache-redis", "name": "Cache for Redis", "fullName": "Azure Cache for Redis", "category": "Database", "description": "Fully managed in-memory cache", "icon": "cache"},
    {"id": "az-synapse", "name": "Synapse Analytics", "fullName": "Azure Synapse Analytics", "category": "Database", "description": "Limitless analytics service (data warehouse + big data)", "icon": "warehouse"},
    {"id": "az-db-postgresql", "name": "Database for PostgreSQL", "fullName": "Azure Database for PostgreSQL", "category": "Database", "description": "Managed PostgreSQL database service", "icon": "database"},
    {"id": "az-db-mysql", "name": "Database for MySQL", "fullName": "Azure Database for MySQL", "category": "Database", "description": "Managed MySQL database service", "icon": "database"},
    {"id": "az-db-mariadb", "name": "Database for MariaDB", "fullName": "Azure Database for MariaDB", "category": "Database", "description": "Managed MariaDB database service", "icon": "database"},
    {"id": "az-cosmos-db-gremlin", "name": "Cosmos DB (Gremlin)", "fullName": "Azure Cosmos DB Gremlin API", "category": "Database", "description": "Graph database with Gremlin API", "icon": "graph"},
    {"id": "az-cosmos-db-cassandra", "name": "Cosmos DB (Cassandra)", "fullName": "Azure Cosmos DB Cassandra API", "category": "Database", "description": "Cassandra-compatible NoSQL database", "icon": "nosql"},
    {"id": "az-time-series", "name": "Time Series Insights", "fullName": "Azure Time Series Insights", "category": "Database", "description": "Time series data analytics", "icon": "timeseries"},
    {"id": "az-managed-ledger", "name": "Confidential Ledger", "fullName": "Azure Confidential Ledger", "category": "Database", "description": "Tamper-proof, append-only ledger", "icon": "ledger"},
    {"id": "az-dms", "name": "Database Migration Service", "fullName": "Azure Database Migration Service", "category": "Database", "description": "Migrate databases to Azure", "icon": "migration"},
    {"id": "az-managed-instance-apache-cassandra", "name": "Managed Instance for Cassandra", "fullName": "Azure Managed Instance for Apache Cassandra", "category": "Database", "description": "Managed Cassandra service", "icon": "nosql"},

    # ═══════════════════════════════════════════════════════════
    # NETWORKING
    # ═══════════════════════════════════════════════════════════
    {"id": "az-vnet", "name": "Virtual Network", "fullName": "Azure Virtual Network", "category": "Networking", "description": "Provision private networks and connect to on-premises", "icon": "network"},
    {"id": "az-cdn", "name": "CDN", "fullName": "Azure CDN", "category": "Networking", "description": "Content delivery network", "icon": "cdn"},
    {"id": "az-dns", "name": "Azure DNS", "fullName": "Azure DNS", "category": "Networking", "description": "Host your DNS domain in Azure", "icon": "dns"},
    {"id": "az-apim", "name": "API Management", "fullName": "Azure API Management", "category": "Networking", "description": "Publish APIs securely at any scale", "icon": "api"},
    {"id": "az-load-balancer", "name": "Load Balancer", "fullName": "Azure Load Balancer", "category": "Networking", "description": "Layer 4 load balancing for VMs", "icon": "loadbalancer"},
    {"id": "az-app-gateway", "name": "Application Gateway", "fullName": "Azure Application Gateway", "category": "Networking", "description": "Layer 7 load balancer with WAF", "icon": "loadbalancer"},
    {"id": "az-expressroute", "name": "ExpressRoute", "fullName": "Azure ExpressRoute", "category": "Networking", "description": "Dedicated private connection to Azure", "icon": "connection"},
    {"id": "az-front-door", "name": "Front Door", "fullName": "Azure Front Door", "category": "Networking", "description": "Global, scalable entry-point with CDN and WAF", "icon": "accelerator"},
    {"id": "az-virtual-wan", "name": "Virtual WAN", "fullName": "Azure Virtual WAN", "category": "Networking", "description": "Optimize and automate branch-to-branch connectivity", "icon": "gateway"},
    {"id": "az-private-link", "name": "Private Link", "fullName": "Azure Private Link", "category": "Networking", "description": "Private access to Azure services", "icon": "privatelink"},
    {"id": "az-service-mesh", "name": "Open Service Mesh", "fullName": "Open Service Mesh on AKS", "category": "Networking", "description": "Lightweight service mesh for Kubernetes", "icon": "mesh"},
    {"id": "az-vpn-gateway", "name": "VPN Gateway", "fullName": "Azure VPN Gateway", "category": "Networking", "description": "Connect on-premises networks to Azure", "icon": "vpn"},
    {"id": "az-firewall", "name": "Azure Firewall", "fullName": "Azure Firewall", "category": "Networking", "description": "Cloud-native network firewall", "icon": "firewall"},
    {"id": "az-traffic-manager", "name": "Traffic Manager", "fullName": "Azure Traffic Manager", "category": "Networking", "description": "DNS-based traffic load balancer", "icon": "dns"},
    {"id": "az-bastion", "name": "Azure Bastion", "fullName": "Azure Bastion", "category": "Networking", "description": "Secure RDP/SSH access to VMs", "icon": "bastion"},
    {"id": "az-network-watcher", "name": "Network Watcher", "fullName": "Azure Network Watcher", "category": "Networking", "description": "Network monitoring and diagnostics", "icon": "monitor"},
    {"id": "az-ddos-protection", "name": "DDoS Protection", "fullName": "Azure DDoS Protection", "category": "Networking", "description": "DDoS attack mitigation", "icon": "shield"},

    # ═══════════════════════════════════════════════════════════
    # SECURITY, IDENTITY & COMPLIANCE
    # ═══════════════════════════════════════════════════════════
    {"id": "az-entra-id", "name": "Entra ID", "fullName": "Microsoft Entra ID (Azure AD)", "category": "Security", "description": "Cloud-based identity and access management", "icon": "identity"},
    {"id": "az-entra-b2c", "name": "Entra External ID", "fullName": "Microsoft Entra External ID (B2C)", "category": "Security", "description": "Customer identity and access management", "icon": "auth"},
    {"id": "az-defender-cloud", "name": "Defender for Cloud", "fullName": "Microsoft Defender for Cloud", "category": "Security", "description": "Unified security management and threat protection", "icon": "shield"},
    {"id": "az-key-vault", "name": "Key Vault", "fullName": "Azure Key Vault", "category": "Security", "description": "Safeguard encryption keys and secrets", "icon": "key"},
    {"id": "az-information-protection", "name": "Information Protection", "fullName": "Azure Information Protection", "category": "Security", "description": "Protect sensitive information", "icon": "data-protection"},
    {"id": "az-waf", "name": "Web Application Firewall", "fullName": "Azure Web Application Firewall", "category": "Security", "description": "Protect web apps from common exploits", "icon": "waf"},
    {"id": "az-sentinel", "name": "Microsoft Sentinel", "fullName": "Microsoft Sentinel", "category": "Security", "description": "Cloud-native SIEM and SOAR", "icon": "siem"},
    {"id": "az-dedicated-hsm", "name": "Dedicated HSM", "fullName": "Azure Dedicated HSM", "category": "Security", "description": "Hardware security module in the cloud", "icon": "hsm"},
    {"id": "az-policy", "name": "Azure Policy", "fullName": "Azure Policy", "category": "Security", "description": "Enforce organizational standards at scale", "icon": "policy"},
    {"id": "az-rbac", "name": "Azure RBAC", "fullName": "Azure Role-Based Access Control", "category": "Security", "description": "Fine-grained access control for Azure resources", "icon": "identity"},
    {"id": "az-managed-identity", "name": "Managed Identity", "fullName": "Azure Managed Identity", "category": "Security", "description": "Auto-managed identity for service authentication", "icon": "identity"},
    {"id": "az-confidential-computing", "name": "Confidential Computing", "fullName": "Azure Confidential Computing", "category": "Security", "description": "Protect data in use with TEEs", "icon": "lock"},
    {"id": "az-purview-compliance", "name": "Purview Compliance", "fullName": "Microsoft Purview Compliance", "category": "Security", "description": "Data governance and compliance management", "icon": "compliance"},

    # ═══════════════════════════════════════════════════════════
    # AI / ML
    # ═══════════════════════════════════════════════════════════
    {"id": "az-machine-learning", "name": "Azure Machine Learning", "fullName": "Azure Machine Learning", "category": "AI/ML", "description": "End-to-end ML lifecycle management", "icon": "ml"},
    {"id": "az-openai", "name": "Azure OpenAI Service", "fullName": "Azure OpenAI Service", "category": "AI/ML", "description": "Access OpenAI models (GPT-4, DALL-E, etc.)", "icon": "ai"},
    {"id": "az-ai-vision", "name": "AI Vision", "fullName": "Azure AI Vision", "category": "AI/ML", "description": "Image analysis and computer vision", "icon": "vision"},
    {"id": "az-ai-language", "name": "AI Language", "fullName": "Azure AI Language", "category": "AI/ML", "description": "NLP: sentiment, summarization, entity extraction", "icon": "nlp"},
    {"id": "az-ai-speech", "name": "AI Speech", "fullName": "Azure AI Speech", "category": "AI/ML", "description": "Speech to text, text to speech, translation", "icon": "speech"},
    {"id": "az-ai-translator", "name": "AI Translator", "fullName": "Azure AI Translator", "category": "AI/ML", "description": "Real-time text translation (100+ languages)", "icon": "translate"},
    {"id": "az-bot-service", "name": "Bot Service", "fullName": "Azure Bot Service", "category": "AI/ML", "description": "Build enterprise-grade conversational AI", "icon": "chatbot"},
    {"id": "az-ai-document", "name": "AI Document Intelligence", "fullName": "Azure AI Document Intelligence", "category": "AI/ML", "description": "Extract info from documents (OCR)", "icon": "ocr"},
    {"id": "az-ai-search", "name": "AI Search", "fullName": "Azure AI Search", "category": "AI/ML", "description": "AI-powered enterprise search", "icon": "search"},
    {"id": "az-personalizer", "name": "Personalizer", "fullName": "Azure AI Personalizer", "category": "AI/ML", "description": "Deliver personalized experiences", "icon": "recommend"},
    {"id": "az-ai-anomaly", "name": "Anomaly Detector", "fullName": "Azure AI Anomaly Detector", "category": "AI/ML", "description": "Detect anomalies in time series data", "icon": "forecast"},
    {"id": "az-ai-content-safety", "name": "AI Content Safety", "fullName": "Azure AI Content Safety", "category": "AI/ML", "description": "Detect harmful content", "icon": "shield"},
    {"id": "az-ai-health-insights", "name": "Health Insights", "fullName": "Azure AI Health Insights", "category": "AI/ML", "description": "AI models for healthcare", "icon": "health"},
    {"id": "az-copilot-studio", "name": "Copilot Studio", "fullName": "Microsoft Copilot Studio", "category": "AI/ML", "description": "Build and customize copilots and AI agents", "icon": "code"},

    # ═══════════════════════════════════════════════════════════
    # ANALYTICS
    # ═══════════════════════════════════════════════════════════
    {"id": "az-synapse-analytics", "name": "Synapse Analytics", "fullName": "Azure Synapse Analytics", "category": "Analytics", "description": "Unified analytics: data warehouse + big data + ETL", "icon": "query"},
    {"id": "az-hdinsight", "name": "HDInsight", "fullName": "Azure HDInsight", "category": "Analytics", "description": "Managed Hadoop, Spark, Kafka clusters", "icon": "spark"},
    {"id": "az-stream-analytics", "name": "Stream Analytics", "fullName": "Azure Stream Analytics", "category": "Analytics", "description": "Real-time analytics on data streams", "icon": "stream"},
    {"id": "az-power-bi", "name": "Power BI", "fullName": "Microsoft Power BI", "category": "Analytics", "description": "Business analytics and visualization", "icon": "bi"},
    {"id": "az-data-factory", "name": "Data Factory", "fullName": "Azure Data Factory", "category": "Analytics", "description": "Hybrid data integration and ETL/ELT", "icon": "etl"},
    {"id": "az-purview", "name": "Microsoft Purview", "fullName": "Microsoft Purview", "category": "Analytics", "description": "Unified data governance and cataloging", "icon": "datalake"},
    {"id": "az-event-hubs", "name": "Event Hubs", "fullName": "Azure Event Hubs", "category": "Analytics", "description": "Big data streaming platform (managed Kafka)", "icon": "kafka"},
    {"id": "az-databricks", "name": "Azure Databricks", "fullName": "Azure Databricks", "category": "Analytics", "description": "Apache Spark analytics platform", "icon": "spark"},
    {"id": "az-data-explorer", "name": "Data Explorer", "fullName": "Azure Data Explorer", "category": "Analytics", "description": "Fast and scalable data exploration", "icon": "search"},
    {"id": "az-analysis-services", "name": "Analysis Services", "fullName": "Azure Analysis Services", "category": "Analytics", "description": "Enterprise-grade analytics engine", "icon": "analytics"},
    {"id": "az-data-share", "name": "Data Share", "fullName": "Azure Data Share", "category": "Analytics", "description": "Share data with external organizations", "icon": "exchange"},
    {"id": "az-data-catalog", "name": "Data Catalog", "fullName": "Azure Data Catalog", "category": "Analytics", "description": "Register and discover data assets", "icon": "catalog"},

    # ═══════════════════════════════════════════════════════════
    # APPLICATION INTEGRATION
    # ═══════════════════════════════════════════════════════════
    {"id": "az-service-bus", "name": "Service Bus", "fullName": "Azure Service Bus", "category": "Integration", "description": "Enterprise message broker with queues and topics", "icon": "queue"},
    {"id": "az-event-grid", "name": "Event Grid", "fullName": "Azure Event Grid", "category": "Integration", "description": "Event routing service for event-driven architectures", "icon": "event"},
    {"id": "az-logic-apps", "name": "Logic Apps", "fullName": "Azure Logic Apps", "category": "Integration", "description": "Automate workflows and integrate apps/data", "icon": "workflow"},
    {"id": "az-notification-hubs", "name": "Notification Hubs", "fullName": "Azure Notification Hubs", "category": "Integration", "description": "Push notifications at scale", "icon": "notification"},
    {"id": "az-api-apps", "name": "API Apps", "fullName": "Azure API Apps", "category": "Integration", "description": "Build and consume APIs in the cloud", "icon": "api"},
    {"id": "az-signalr", "name": "SignalR Service", "fullName": "Azure SignalR Service", "category": "Integration", "description": "Real-time web functionality", "icon": "realtime"},
    {"id": "az-web-pubsub", "name": "Web PubSub", "fullName": "Azure Web PubSub", "category": "Integration", "description": "Real-time messaging using WebSockets", "icon": "realtime"},

    # ═══════════════════════════════════════════════════════════
    # DEVELOPER TOOLS
    # ═══════════════════════════════════════════════════════════
    {"id": "az-devops", "name": "Azure DevOps", "fullName": "Azure DevOps", "category": "DevTools", "description": "CI/CD, repos, boards, test plans, artifacts", "icon": "devops"},
    {"id": "az-devtest-labs", "name": "DevTest Labs", "fullName": "Azure DevTest Labs", "category": "DevTools", "description": "Quickly create environments for dev and test", "icon": "lab"},
    {"id": "az-pipelines", "name": "Azure Pipelines", "fullName": "Azure Pipelines", "category": "DevTools", "description": "CI/CD for any platform", "icon": "pipeline"},
    {"id": "az-arm-templates", "name": "ARM Templates", "fullName": "Azure Resource Manager Templates", "category": "DevTools", "description": "Infrastructure as code for Azure resources", "icon": "iac"},
    {"id": "az-bicep", "name": "Bicep", "fullName": "Azure Bicep", "category": "DevTools", "description": "Domain-specific language for deploying Azure resources", "icon": "iac"},
    {"id": "az-monitor", "name": "Azure Monitor", "fullName": "Azure Monitor", "category": "DevTools", "description": "Full-stack monitoring and diagnostics", "icon": "monitor"},
    {"id": "az-app-insights", "name": "Application Insights", "fullName": "Azure Application Insights", "category": "DevTools", "description": "APM for web applications", "icon": "trace"},
    {"id": "az-load-testing", "name": "Load Testing", "fullName": "Azure Load Testing", "category": "DevTools", "description": "Generate high-scale load tests", "icon": "test"},
    {"id": "az-chaos-studio", "name": "Chaos Studio", "fullName": "Azure Chaos Studio", "category": "DevTools", "description": "Chaos engineering experiments", "icon": "chaos"},
    {"id": "az-container-registry", "name": "Container Registry", "fullName": "Azure Container Registry", "category": "DevTools", "description": "Store and manage container images", "icon": "registry"},
    {"id": "az-artifacts", "name": "Azure Artifacts", "fullName": "Azure Artifacts", "category": "DevTools", "description": "Package management (npm, NuGet, Maven, pip)", "icon": "artifact"},
    {"id": "az-github-actions", "name": "GitHub Actions", "fullName": "GitHub Actions for Azure", "category": "DevTools", "description": "CI/CD with GitHub Actions", "icon": "pipeline"},

    # ═══════════════════════════════════════════════════════════
    # MANAGEMENT & GOVERNANCE
    # ═══════════════════════════════════════════════════════════
    {"id": "az-resource-manager", "name": "Resource Manager", "fullName": "Azure Resource Manager", "category": "Management", "description": "Deployment and management layer for Azure", "icon": "management"},
    {"id": "az-cost-management", "name": "Cost Management", "fullName": "Microsoft Cost Management", "category": "Management", "description": "Monitor, allocate, and optimize cloud costs", "icon": "cost"},
    {"id": "az-advisor", "name": "Azure Advisor", "fullName": "Azure Advisor", "category": "Management", "description": "Personalized best practice recommendations", "icon": "advisor"},
    {"id": "az-service-health", "name": "Service Health", "fullName": "Azure Service Health", "category": "Management", "description": "Personalized guidance when Azure service issues affect you", "icon": "health"},
    {"id": "az-management-groups", "name": "Management Groups", "fullName": "Azure Management Groups", "category": "Management", "description": "Organize subscriptions and apply governance", "icon": "org"},
    {"id": "az-blueprints", "name": "Azure Blueprints", "fullName": "Azure Blueprints", "category": "Management", "description": "Define repeatable sets of Azure resources", "icon": "governance"},
    {"id": "az-lighthouse", "name": "Azure Lighthouse", "fullName": "Azure Lighthouse", "category": "Management", "description": "Cross-tenant management at scale", "icon": "management"},
    {"id": "az-automation", "name": "Azure Automation", "fullName": "Azure Automation", "category": "Management", "description": "Process automation, config management, update management", "icon": "ops"},
    {"id": "az-log-analytics", "name": "Log Analytics", "fullName": "Azure Log Analytics", "category": "Management", "description": "Collect and analyze telemetry data", "icon": "monitor"},
    {"id": "az-resource-graph", "name": "Resource Graph", "fullName": "Azure Resource Graph", "category": "Management", "description": "Explore Azure resources at scale", "icon": "query"},

    # ═══════════════════════════════════════════════════════════
    # IOT
    # ═══════════════════════════════════════════════════════════
    {"id": "az-iot-hub", "name": "IoT Hub", "fullName": "Azure IoT Hub", "category": "IoT", "description": "Bi-directional communication with IoT devices", "icon": "iot"},
    {"id": "az-iot-edge", "name": "IoT Edge", "fullName": "Azure IoT Edge", "category": "IoT", "description": "Extend cloud intelligence to edge devices", "icon": "edge"},
    {"id": "az-iot-central", "name": "IoT Central", "fullName": "Azure IoT Central", "category": "IoT", "description": "SaaS for IoT solutions", "icon": "iot"},
    {"id": "az-digital-twins", "name": "Digital Twins", "fullName": "Azure Digital Twins", "category": "IoT", "description": "Build digital twin models of environments", "icon": "twin"},
    {"id": "az-sphere", "name": "Azure Sphere", "fullName": "Azure Sphere", "category": "IoT", "description": "Secure end-to-end IoT solution", "icon": "iot"},
    {"id": "az-rtos", "name": "Azure RTOS", "fullName": "Azure RTOS", "category": "IoT", "description": "Real-time OS for embedded IoT development", "icon": "embedded"},
    {"id": "az-defender-iot", "name": "Defender for IoT", "fullName": "Microsoft Defender for IoT", "category": "IoT", "description": "Security for IoT/OT environments", "icon": "shield"},

    # ═══════════════════════════════════════════════════════════
    # MEDIA SERVICES
    # ═══════════════════════════════════════════════════════════
    {"id": "az-media-services", "name": "Media Services", "fullName": "Azure Media Services", "category": "Media", "description": "Encode, store, and stream video/audio at scale", "icon": "video"},
    {"id": "az-video-indexer", "name": "Video Indexer", "fullName": "Azure Video Indexer", "category": "Media", "description": "Extract insights from videos using AI", "icon": "video"},
    {"id": "az-communication-services", "name": "Communication Services", "fullName": "Azure Communication Services", "category": "Media", "description": "Voice, video, chat, SMS, email APIs", "icon": "comms"},

    # ═══════════════════════════════════════════════════════════
    # MIGRATION
    # ═══════════════════════════════════════════════════════════
    {"id": "az-migrate", "name": "Azure Migrate", "fullName": "Azure Migrate", "category": "Migration", "description": "Unified migration platform", "icon": "migration"},
    {"id": "az-site-recovery", "name": "Site Recovery", "fullName": "Azure Site Recovery", "category": "Migration", "description": "Disaster recovery as a service", "icon": "recovery"},

    # ═══════════════════════════════════════════════════════════
    # BUSINESS APPLICATIONS
    # ═══════════════════════════════════════════════════════════
    {"id": "az-communication-email", "name": "Email Communication", "fullName": "Azure Communication Services Email", "category": "Business", "description": "Send emails at scale", "icon": "email"},
    {"id": "az-virtual-desktop", "name": "Virtual Desktop", "fullName": "Azure Virtual Desktop", "category": "Business", "description": "Desktop and app virtualization", "icon": "desktop"},
    {"id": "az-power-apps", "name": "Power Apps", "fullName": "Microsoft Power Apps", "category": "Business", "description": "Low-code application development", "icon": "lowcode"},
    {"id": "az-power-automate", "name": "Power Automate", "fullName": "Microsoft Power Automate", "category": "Business", "description": "Automate workflows across apps and services", "icon": "workflow"},
    {"id": "az-dynamics-365", "name": "Dynamics 365", "fullName": "Microsoft Dynamics 365", "category": "Business", "description": "CRM and ERP cloud applications", "icon": "crm"},

    # ═══════════════════════════════════════════════════════════
    # HYBRID & MULTI-CLOUD  (Issue #60)
    # ═══════════════════════════════════════════════════════════
    {"id": "az-arc-k8s", "name": "Arc-enabled Kubernetes", "fullName": "Azure Arc-enabled Kubernetes", "category": "Hybrid", "description": "Manage Kubernetes clusters anywhere with Azure Arc", "icon": "kubernetes"},
    {"id": "az-arc-servers", "name": "Arc-enabled Servers", "fullName": "Azure Arc-enabled Servers", "category": "Hybrid", "description": "Manage on-prem and multi-cloud servers from Azure", "icon": "hybrid"},
    {"id": "az-arc-sql", "name": "Arc-enabled SQL", "fullName": "Azure Arc-enabled SQL Managed Instance", "category": "Hybrid", "description": "Run Azure SQL managed instance anywhere via Arc", "icon": "database"},
    {"id": "az-lighthouse", "name": "Azure Lighthouse", "fullName": "Azure Lighthouse", "category": "Hybrid", "description": "Cross-tenant management at scale", "icon": "management"},

    # ═══════════════════════════════════════════════════════════
    # GENERATIVE AI  (Issue #61)
    # ═══════════════════════════════════════════════════════════
    {"id": "az-ai-agent-service", "name": "AI Agent Service", "fullName": "Azure AI Agent Service", "category": "AI/ML", "description": "Build and deploy autonomous AI agents with tool use", "icon": "bot"},
    {"id": "az-ai-foundry", "name": "AI Foundry", "fullName": "Azure AI Foundry", "category": "AI/ML", "description": "Unified platform for building generative AI applications", "icon": "ai"},
    {"id": "az-ai-content-safety", "name": "AI Content Safety", "fullName": "Azure AI Content Safety", "category": "AI/ML", "description": "Detect harmful content in text and images", "icon": "shield"},
    {"id": "az-ml-automl", "name": "Azure ML AutoML", "fullName": "Azure Machine Learning AutoML", "category": "AI/ML", "description": "Automated machine learning model training", "icon": "ai"},
    {"id": "az-github-advanced-security", "name": "GitHub Advanced Security", "fullName": "GitHub Advanced Security", "category": "AI/ML", "description": "AI-powered code scanning and security analysis", "icon": "shield"},

    # ═══════════════════════════════════════════════════════════
    # EDGE COMPUTING  (Issue #62)
    # ═══════════════════════════════════════════════════════════
    {"id": "az-edge-zones", "name": "Edge Zones", "fullName": "Azure Edge Zones", "category": "Edge", "description": "Azure services at carrier 5G edge locations", "icon": "edge"},
    {"id": "az-extended-zones", "name": "Extended Zones", "fullName": "Azure Extended Zones", "category": "Edge", "description": "Azure infrastructure in metro areas for low-latency apps", "icon": "edge"},
    {"id": "az-front-door-rules", "name": "Front Door Rules Engine", "fullName": "Azure Front Door Rules Engine", "category": "Edge", "description": "Edge compute rules for request/response manipulation", "icon": "cdn"},
    {"id": "az-cdn-rules", "name": "CDN Rules Engine", "fullName": "Azure CDN Rules Engine", "category": "Edge", "description": "Custom rules for CDN content delivery", "icon": "cdn"},

    # ═══════════════════════════════════════════════════════════
    # MANAGED OBSERVABILITY  (Issue #63)
    # ═══════════════════════════════════════════════════════════
    {"id": "az-managed-grafana", "name": "Managed Grafana", "fullName": "Azure Managed Grafana", "category": "Observability", "description": "Fully managed Grafana dashboards natively integrated with Azure", "icon": "dashboard"},
    {"id": "az-monitor-prometheus", "name": "Monitor (Prometheus)", "fullName": "Azure Monitor managed service for Prometheus", "category": "Observability", "description": "Prometheus-compatible metrics collection for containers", "icon": "metrics"},
    {"id": "az-monitor-otel", "name": "Monitor (OpenTelemetry)", "fullName": "Azure Monitor OpenTelemetry Distro", "category": "Observability", "description": "OpenTelemetry-based telemetry for Azure Monitor", "icon": "trace"},
    {"id": "az-container-insights", "name": "Container Insights", "fullName": "Azure Monitor Container Insights", "category": "Observability", "description": "Container and Kubernetes monitoring and logging", "icon": "container"},

    # ═══════════════════════════════════════════════════════════
    # DATA GOVERNANCE  (Issue #64)
    # ═══════════════════════════════════════════════════════════
    {"id": "az-purview-governance", "name": "Purview (Governance)", "fullName": "Microsoft Purview Data Governance", "category": "Data Governance", "description": "Unified data governance with catalog and lineage", "icon": "governance"},
    {"id": "az-clean-rooms", "name": "Confidential Clean Rooms", "fullName": "Azure Confidential Clean Rooms", "category": "Data Governance", "description": "Privacy-preserving multi-party data collaboration", "icon": "privacy"},
    {"id": "az-purview-compliance", "name": "Purview Compliance Manager", "fullName": "Microsoft Purview Compliance Manager", "category": "Data Governance", "description": "Automated compliance assessment and evidence collection", "icon": "compliance"},

    # ═══════════════════════════════════════════════════════════
    # ZERO TRUST & SASE  (Issue #67)
    # ═══════════════════════════════════════════════════════════
    {"id": "az-entra-private-access", "name": "Entra Private Access", "fullName": "Microsoft Entra Private Access", "category": "Zero Trust", "description": "Identity-centric ZTNA replacing legacy VPN", "icon": "shield"},
    {"id": "az-sentinel-datalake", "name": "Sentinel (Data Lake)", "fullName": "Microsoft Sentinel Security Data Lake", "category": "Zero Trust", "description": "Centralized security data lake with OCSF schema", "icon": "shield"},
    {"id": "az-sentinel-investigation", "name": "Sentinel (Investigation)", "fullName": "Microsoft Sentinel Investigation", "category": "Zero Trust", "description": "Security investigation and root-cause analysis", "icon": "shield"},
    {"id": "az-firewall-manager", "name": "Firewall Manager", "fullName": "Azure Firewall Manager", "category": "Zero Trust", "description": "Central firewall policy management across subscriptions", "icon": "firewall"},
    {"id": "az-firewall-premium", "name": "Firewall Premium (IDPS)", "fullName": "Azure Firewall Premium", "category": "Zero Trust", "description": "Firewall with intrusion detection and prevention", "icon": "firewall"},
]
