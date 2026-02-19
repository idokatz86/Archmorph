"""
GCP Services Catalog — Comprehensive list of Google Cloud Platform services.
"""

GCP_SERVICES = [
    # ═══════════════════════════════════════════════════════════
    # COMPUTE
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-compute-engine", "name": "Compute Engine", "fullName": "Google Compute Engine", "category": "Compute", "description": "Virtual machines on Google infrastructure", "icon": "server"},
    {"id": "gcp-cloud-functions", "name": "Cloud Functions", "fullName": "Google Cloud Functions", "category": "Compute", "description": "Event-driven serverless functions", "icon": "function"},
    {"id": "gcp-cloud-run", "name": "Cloud Run", "fullName": "Google Cloud Run", "category": "Compute", "description": "Serverless containers on managed infrastructure", "icon": "container"},
    {"id": "gcp-gke", "name": "GKE", "fullName": "Google Kubernetes Engine", "category": "Compute", "description": "Managed Kubernetes service", "icon": "kubernetes"},
    {"id": "gcp-app-engine", "name": "App Engine", "fullName": "Google App Engine", "category": "Compute", "description": "Fully managed serverless application platform", "icon": "webapp"},
    {"id": "gcp-anthos", "name": "Anthos", "fullName": "Google Anthos", "category": "Compute", "description": "Modern hybrid and multi-cloud app platform", "icon": "hybrid"},
    {"id": "gcp-batch", "name": "Batch", "fullName": "Google Cloud Batch", "category": "Compute", "description": "Fully managed batch processing at scale", "icon": "batch"},
    {"id": "gcp-sole-tenant", "name": "Sole-Tenant Nodes", "fullName": "Sole-Tenant Nodes", "category": "Compute", "description": "Dedicated physical servers for your VMs", "icon": "server"},
    {"id": "gcp-preemptible-vms", "name": "Spot VMs", "fullName": "Spot VMs (Preemptible)", "category": "Compute", "description": "Discounted short-lived VM instances", "icon": "server"},
    {"id": "gcp-vmware-engine", "name": "VMware Engine", "fullName": "Google Cloud VMware Engine", "category": "Compute", "description": "Migrate and run VMware workloads natively", "icon": "hybrid"},
    {"id": "gcp-bare-metal", "name": "Bare Metal Solution", "fullName": "Bare Metal Solution", "category": "Compute", "description": "Run specialized workloads on bare metal servers", "icon": "server"},
    {"id": "gcp-managed-instance-groups", "name": "Managed Instance Groups", "fullName": "Managed Instance Groups", "category": "Compute", "description": "Auto-scaling groups of identical VMs", "icon": "autoscale"},

    # ═══════════════════════════════════════════════════════════
    # STORAGE
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-cloud-storage", "name": "Cloud Storage", "fullName": "Google Cloud Storage", "category": "Storage", "description": "Object storage for any amount of data", "icon": "storage"},
    {"id": "gcp-persistent-disk", "name": "Persistent Disk", "fullName": "Google Persistent Disk", "category": "Storage", "description": "Block storage for VM instances", "icon": "disk"},
    {"id": "gcp-filestore", "name": "Filestore", "fullName": "Google Cloud Filestore", "category": "Storage", "description": "Managed file storage (NFS)", "icon": "file"},
    {"id": "gcp-storage-transfer", "name": "Storage Transfer Service", "fullName": "Storage Transfer Service", "category": "Storage", "description": "Transfer data to Cloud Storage", "icon": "transfer"},
    {"id": "gcp-archive-storage", "name": "Archive Storage", "fullName": "Cloud Storage Archive", "category": "Storage", "description": "Ultra-low cost cold data storage", "icon": "archive"},
    {"id": "gcp-transfer-appliance", "name": "Transfer Appliance", "fullName": "Transfer Appliance", "category": "Storage", "description": "Physical device for large data transfers", "icon": "device"},
    {"id": "gcp-backup-dr", "name": "Backup and DR", "fullName": "Backup and DR Service", "category": "Storage", "description": "Managed backup and disaster recovery", "icon": "backup"},
    {"id": "gcp-netapp-volumes", "name": "NetApp Volumes", "fullName": "Google Cloud NetApp Volumes", "category": "Storage", "description": "Fully managed file storage powered by NetApp", "icon": "file"},
    {"id": "gcp-parallelstore", "name": "Parallelstore", "fullName": "Google Cloud Parallelstore", "category": "Storage", "description": "High-performance parallel file system", "icon": "file"},

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-cloud-sql", "name": "Cloud SQL", "fullName": "Google Cloud SQL", "category": "Database", "description": "Managed MySQL, PostgreSQL, SQL Server", "icon": "database"},
    {"id": "gcp-alloydb", "name": "AlloyDB", "fullName": "AlloyDB for PostgreSQL", "category": "Database", "description": "PostgreSQL-compatible database for demanding workloads", "icon": "database"},
    {"id": "gcp-cloud-spanner", "name": "Cloud Spanner", "fullName": "Google Cloud Spanner", "category": "Database", "description": "Globally distributed, strongly consistent database", "icon": "database"},
    {"id": "gcp-firestore", "name": "Firestore", "fullName": "Google Cloud Firestore", "category": "Database", "description": "NoSQL document database", "icon": "nosql"},
    {"id": "gcp-bigtable", "name": "Bigtable", "fullName": "Google Cloud Bigtable", "category": "Database", "description": "Petabyte-scale NoSQL wide-column database", "icon": "nosql"},
    {"id": "gcp-memorystore", "name": "Memorystore", "fullName": "Google Cloud Memorystore", "category": "Database", "description": "In-memory data store (Redis, Memcached)", "icon": "cache"},
    {"id": "gcp-bigquery", "name": "BigQuery", "fullName": "Google BigQuery", "category": "Database", "description": "Serverless enterprise data warehouse", "icon": "warehouse"},
    {"id": "gcp-datastore", "name": "Datastore", "fullName": "Google Cloud Datastore", "category": "Database", "description": "NoSQL database for web and mobile apps", "icon": "nosql"},
    {"id": "gcp-firebase-realtime", "name": "Firebase Realtime DB", "fullName": "Firebase Realtime Database", "category": "Database", "description": "Realtime NoSQL cloud database", "icon": "nosql"},
    {"id": "gcp-database-migration", "name": "Database Migration Service", "fullName": "Database Migration Service", "category": "Database", "description": "Migrate databases to Google Cloud", "icon": "migration"},

    # ═══════════════════════════════════════════════════════════
    # NETWORKING
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-vpc", "name": "VPC", "fullName": "Google Virtual Private Cloud", "category": "Networking", "description": "Virtual network for Google Cloud resources", "icon": "network"},
    {"id": "gcp-cloud-cdn", "name": "Cloud CDN", "fullName": "Google Cloud CDN", "category": "Networking", "description": "Content delivery network", "icon": "cdn"},
    {"id": "gcp-cloud-dns", "name": "Cloud DNS", "fullName": "Google Cloud DNS", "category": "Networking", "description": "Scalable, reliable DNS service", "icon": "dns"},
    {"id": "gcp-apigee", "name": "Apigee", "fullName": "Apigee API Management", "category": "Networking", "description": "Full-lifecycle API management", "icon": "api"},
    {"id": "gcp-cloud-load-balancing", "name": "Cloud Load Balancing", "fullName": "Google Cloud Load Balancing", "category": "Networking", "description": "High-performance, global load balancing", "icon": "loadbalancer"},
    {"id": "gcp-cloud-interconnect", "name": "Cloud Interconnect", "fullName": "Google Cloud Interconnect", "category": "Networking", "description": "Dedicated/partner connections to Google Cloud", "icon": "connection"},
    {"id": "gcp-cloud-vpn", "name": "Cloud VPN", "fullName": "Google Cloud VPN", "category": "Networking", "description": "Connect on-premises to GCP via VPN", "icon": "vpn"},
    {"id": "gcp-cloud-nat", "name": "Cloud NAT", "fullName": "Google Cloud NAT", "category": "Networking", "description": "Network address translation service", "icon": "nat"},
    {"id": "gcp-cloud-armor", "name": "Cloud Armor", "fullName": "Google Cloud Armor", "category": "Networking", "description": "DDoS and application protection", "icon": "shield"},
    {"id": "gcp-traffic-director", "name": "Traffic Director", "fullName": "Traffic Director", "category": "Networking", "description": "Managed service mesh control plane", "icon": "mesh"},
    {"id": "gcp-private-service-connect", "name": "Private Service Connect", "fullName": "Private Service Connect", "category": "Networking", "description": "Private access to Google and third-party services", "icon": "privatelink"},
    {"id": "gcp-network-connectivity-center", "name": "Network Connectivity Center", "fullName": "Network Connectivity Center", "category": "Networking", "description": "Hub-and-spoke network architecture", "icon": "gateway"},
    {"id": "gcp-cloud-firewall", "name": "Cloud Firewall", "fullName": "Google Cloud Firewall", "category": "Networking", "description": "Cloud-native network firewall", "icon": "firewall"},
    {"id": "gcp-service-directory", "name": "Service Directory", "fullName": "Service Directory", "category": "Networking", "description": "Managed service discovery", "icon": "discovery"},

    # ═══════════════════════════════════════════════════════════
    # SECURITY, IDENTITY & COMPLIANCE
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-iam", "name": "Cloud IAM", "fullName": "Google Cloud IAM", "category": "Security", "description": "Fine-grained access control and visibility", "icon": "identity"},
    {"id": "gcp-identity-platform", "name": "Identity Platform", "fullName": "Identity Platform", "category": "Security", "description": "Customer identity and access management", "icon": "auth"},
    {"id": "gcp-security-command-center", "name": "Security Command Center", "fullName": "Security Command Center", "category": "Security", "description": "Security and risk management platform", "icon": "shield"},
    {"id": "gcp-cloud-kms", "name": "Cloud KMS", "fullName": "Google Cloud KMS", "category": "Security", "description": "Manage encryption keys", "icon": "key"},
    {"id": "gcp-secret-manager", "name": "Secret Manager", "fullName": "Google Secret Manager", "category": "Security", "description": "Store API keys, passwords, certificates", "icon": "secret"},
    {"id": "gcp-dlp", "name": "Cloud DLP", "fullName": "Cloud Data Loss Prevention", "category": "Security", "description": "Discover and protect sensitive data", "icon": "data-protection"},
    {"id": "gcp-cloud-hsm", "name": "Cloud HSM", "fullName": "Google Cloud HSM", "category": "Security", "description": "Hardware security modules in the cloud", "icon": "hsm"},
    {"id": "gcp-binary-authorization", "name": "Binary Authorization", "fullName": "Binary Authorization", "category": "Security", "description": "Deploy only trusted containers", "icon": "policy"},
    {"id": "gcp-certificate-manager", "name": "Certificate Manager", "fullName": "Certificate Manager", "category": "Security", "description": "Manage TLS certificates", "icon": "certificate"},
    {"id": "gcp-web-security-scanner", "name": "Web Security Scanner", "fullName": "Web Security Scanner", "category": "Security", "description": "Scan web apps for vulnerabilities", "icon": "inspect"},
    {"id": "gcp-assured-workloads", "name": "Assured Workloads", "fullName": "Assured Workloads", "category": "Security", "description": "Compliance and sovereignty controls", "icon": "compliance"},
    {"id": "gcp-chronicle", "name": "Chronicle", "fullName": "Google Chronicle", "category": "Security", "description": "Cloud-native SIEM for threat detection", "icon": "siem"},
    {"id": "gcp-beyondcorp", "name": "BeyondCorp Enterprise", "fullName": "BeyondCorp Enterprise", "category": "Security", "description": "Zero-trust access for apps and resources", "icon": "sso"},
    {"id": "gcp-access-context-manager", "name": "Access Context Manager", "fullName": "Access Context Manager", "category": "Security", "description": "Attribute-based access control policies", "icon": "policy"},

    # ═══════════════════════════════════════════════════════════
    # AI / ML
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-vertex-ai", "name": "Vertex AI", "fullName": "Google Vertex AI", "category": "AI/ML", "description": "Unified ML platform to build, deploy, and scale models", "icon": "ml"},
    {"id": "gcp-gemini", "name": "Gemini", "fullName": "Gemini on Vertex AI", "category": "AI/ML", "description": "Google's multimodal foundation model", "icon": "ai"},
    {"id": "gcp-vision-ai", "name": "Vision AI", "fullName": "Google Cloud Vision AI", "category": "AI/ML", "description": "Image analysis and labeling", "icon": "vision"},
    {"id": "gcp-natural-language-ai", "name": "Natural Language AI", "fullName": "Google Cloud Natural Language AI", "category": "AI/ML", "description": "NLP: sentiment, entity, syntax analysis", "icon": "nlp"},
    {"id": "gcp-speech-to-text", "name": "Speech-to-Text", "fullName": "Google Cloud Speech-to-Text", "category": "AI/ML", "description": "Automatic speech recognition", "icon": "speech"},
    {"id": "gcp-text-to-speech", "name": "Text-to-Speech", "fullName": "Google Cloud Text-to-Speech", "category": "AI/ML", "description": "Convert text to natural-sounding speech", "icon": "speech"},
    {"id": "gcp-translation", "name": "Translation AI", "fullName": "Google Cloud Translation", "category": "AI/ML", "description": "Translate between languages dynamically", "icon": "translate"},
    {"id": "gcp-dialogflow", "name": "Dialogflow", "fullName": "Google Dialogflow", "category": "AI/ML", "description": "Build conversational agents (chatbots)", "icon": "chatbot"},
    {"id": "gcp-document-ai", "name": "Document AI", "fullName": "Google Document AI", "category": "AI/ML", "description": "Extract structured data from documents", "icon": "ocr"},
    {"id": "gcp-recommendations-ai", "name": "Recommendations AI", "fullName": "Recommendations AI", "category": "AI/ML", "description": "Real-time personalized recommendations", "icon": "recommend"},
    {"id": "gcp-automl", "name": "AutoML", "fullName": "Google Cloud AutoML", "category": "AI/ML", "description": "Train custom ML models with minimal effort", "icon": "ml"},
    {"id": "gcp-healthcare-api", "name": "Healthcare API", "fullName": "Google Cloud Healthcare API", "category": "AI/ML", "description": "Manage and analyze healthcare data", "icon": "health"},
    {"id": "gcp-contact-center-ai", "name": "Contact Center AI", "fullName": "Contact Center AI", "category": "AI/ML", "description": "AI for customer service", "icon": "contact"},
    {"id": "gcp-duet-ai", "name": "Gemini Code Assist", "fullName": "Gemini Code Assist", "category": "AI/ML", "description": "AI-powered code completion and assistance", "icon": "code"},

    # ═══════════════════════════════════════════════════════════
    # ANALYTICS / DATA
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-dataflow", "name": "Dataflow", "fullName": "Google Cloud Dataflow", "category": "Analytics", "description": "Managed Apache Beam stream/batch processing", "icon": "stream"},
    {"id": "gcp-dataproc", "name": "Dataproc", "fullName": "Google Cloud Dataproc", "category": "Analytics", "description": "Managed Spark and Hadoop service", "icon": "spark"},
    {"id": "gcp-pub-sub", "name": "Pub/Sub", "fullName": "Google Cloud Pub/Sub", "category": "Analytics", "description": "Messaging and event ingestion at scale", "icon": "kafka"},
    {"id": "gcp-looker", "name": "Looker", "fullName": "Google Looker", "category": "Analytics", "description": "Business intelligence and data analytics", "icon": "bi"},
    {"id": "gcp-data-fusion", "name": "Data Fusion", "fullName": "Google Cloud Data Fusion", "category": "Analytics", "description": "Code-free data integration (ETL/ELT)", "icon": "etl"},
    {"id": "gcp-dataplex", "name": "Dataplex", "fullName": "Google Cloud Dataplex", "category": "Analytics", "description": "Intelligent data fabric for data lakes", "icon": "datalake"},
    {"id": "gcp-data-catalog", "name": "Data Catalog", "fullName": "Google Cloud Data Catalog", "category": "Analytics", "description": "Metadata management and data discovery", "icon": "catalog"},
    {"id": "gcp-composer", "name": "Cloud Composer", "fullName": "Google Cloud Composer", "category": "Analytics", "description": "Managed Apache Airflow orchestration", "icon": "orchestration"},
    {"id": "gcp-analytics-hub", "name": "Analytics Hub", "fullName": "Analytics Hub", "category": "Analytics", "description": "Data exchange and sharing", "icon": "exchange"},
    {"id": "gcp-looker-studio", "name": "Looker Studio", "fullName": "Looker Studio (Data Studio)", "category": "Analytics", "description": "Interactive data visualization and dashboards", "icon": "bi"},

    # ═══════════════════════════════════════════════════════════
    # APPLICATION INTEGRATION
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-cloud-tasks", "name": "Cloud Tasks", "fullName": "Google Cloud Tasks", "category": "Integration", "description": "Asynchronous task execution", "icon": "queue"},
    {"id": "gcp-eventarc", "name": "Eventarc", "fullName": "Google Eventarc", "category": "Integration", "description": "Build event-driven architectures", "icon": "event"},
    {"id": "gcp-workflows", "name": "Workflows", "fullName": "Google Cloud Workflows", "category": "Integration", "description": "Orchestrate HTTP-based API services", "icon": "workflow"},
    {"id": "gcp-cloud-scheduler", "name": "Cloud Scheduler", "fullName": "Google Cloud Scheduler", "category": "Integration", "description": "Managed cron job service", "icon": "scheduler"},
    {"id": "gcp-apigee-integration", "name": "Application Integration", "fullName": "Application Integration", "category": "Integration", "description": "Integration Platform as a Service (iPaaS)", "icon": "integration"},
    {"id": "gcp-firebase-cloud-messaging", "name": "Firebase Cloud Messaging", "fullName": "Firebase Cloud Messaging", "category": "Integration", "description": "Cross-platform push notifications", "icon": "notification"},

    # ═══════════════════════════════════════════════════════════
    # DEVELOPER TOOLS
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-cloud-source-repos", "name": "Cloud Source Repositories", "fullName": "Cloud Source Repositories", "category": "DevTools", "description": "Private Git repositories", "icon": "git"},
    {"id": "gcp-cloud-build", "name": "Cloud Build", "fullName": "Google Cloud Build", "category": "DevTools", "description": "CI/CD platform", "icon": "build"},
    {"id": "gcp-cloud-deploy", "name": "Cloud Deploy", "fullName": "Google Cloud Deploy", "category": "DevTools", "description": "Managed continuous delivery to GKE/Cloud Run", "icon": "deploy"},
    {"id": "gcp-artifact-registry", "name": "Artifact Registry", "fullName": "Google Artifact Registry", "category": "DevTools", "description": "Store and manage build artifacts and dependencies", "icon": "artifact"},
    {"id": "gcp-container-registry", "name": "Container Registry", "fullName": "Google Container Registry", "category": "DevTools", "description": "Store and manage Docker images", "icon": "registry"},
    {"id": "gcp-cloud-trace", "name": "Cloud Trace", "fullName": "Google Cloud Trace", "category": "DevTools", "description": "Distributed tracing for applications", "icon": "trace"},
    {"id": "gcp-cloud-profiler", "name": "Cloud Profiler", "fullName": "Google Cloud Profiler", "category": "DevTools", "description": "Low-overhead production profiling", "icon": "monitor"},
    {"id": "gcp-error-reporting", "name": "Error Reporting", "fullName": "Google Cloud Error Reporting", "category": "DevTools", "description": "Real-time error tracking", "icon": "error"},
    {"id": "gcp-deployment-manager", "name": "Deployment Manager", "fullName": "Google Cloud Deployment Manager", "category": "DevTools", "description": "Infrastructure as code for GCP", "icon": "iac"},
    {"id": "gcp-cloud-shell", "name": "Cloud Shell", "fullName": "Google Cloud Shell", "category": "DevTools", "description": "Browser-based development environment", "icon": "ide"},

    # ═══════════════════════════════════════════════════════════
    # MANAGEMENT & GOVERNANCE
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-cloud-monitoring", "name": "Cloud Monitoring", "fullName": "Google Cloud Monitoring", "category": "Management", "description": "Infrastructure and application monitoring", "icon": "monitor"},
    {"id": "gcp-cloud-logging", "name": "Cloud Logging", "fullName": "Google Cloud Logging", "category": "Management", "description": "Real-time log management and analysis", "icon": "audit"},
    {"id": "gcp-cloud-audit-logs", "name": "Cloud Audit Logs", "fullName": "Cloud Audit Logs", "category": "Management", "description": "Track who did what, when, where", "icon": "audit"},
    {"id": "gcp-resource-manager", "name": "Resource Manager", "fullName": "Google Cloud Resource Manager", "category": "Management", "description": "Manage resources hierarchically", "icon": "org"},
    {"id": "gcp-org-policy", "name": "Organization Policy", "fullName": "Organization Policy Service", "category": "Management", "description": "Centralized policy management", "icon": "governance"},
    {"id": "gcp-recommender", "name": "Recommender", "fullName": "Google Cloud Recommender", "category": "Management", "description": "Cost and performance recommendations", "icon": "advisor"},
    {"id": "gcp-billing", "name": "Cloud Billing", "fullName": "Google Cloud Billing", "category": "Management", "description": "Track and manage cloud costs", "icon": "cost"},
    {"id": "gcp-service-health", "name": "Service Health", "fullName": "Service Health Dashboard", "category": "Management", "description": "Real-time GCP service status", "icon": "health"},
    {"id": "gcp-active-assist", "name": "Active Assist", "fullName": "Active Assist", "category": "Management", "description": "AI-powered cloud management insights", "icon": "advisor"},

    # ═══════════════════════════════════════════════════════════
    # IOT
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-iot-core", "name": "Cloud IoT Core", "fullName": "Google Cloud IoT Core", "category": "IoT", "description": "Device management and data ingestion", "icon": "iot"},

    # ═══════════════════════════════════════════════════════════
    # MEDIA
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-transcoder", "name": "Transcoder API", "fullName": "Google Transcoder API", "category": "Media", "description": "Convert video files to optimized formats", "icon": "video"},
    {"id": "gcp-live-stream", "name": "Live Stream API", "fullName": "Google Live Stream API", "category": "Media", "description": "Transcode live video streams", "icon": "live"},
    {"id": "gcp-video-stitcher", "name": "Video Stitcher API", "fullName": "Video Stitcher API", "category": "Media", "description": "Ad insertion for video on demand and live", "icon": "video"},

    # ═══════════════════════════════════════════════════════════
    # MIGRATION
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-migrate-vms", "name": "Migrate to VMs", "fullName": "Migrate to Virtual Machines", "category": "Migration", "description": "Migrate VMs to Compute Engine", "icon": "migration"},
    {"id": "gcp-migrate-containers", "name": "Migrate to Containers", "fullName": "Migrate to Containers", "category": "Migration", "description": "Migrate VMs to GKE containers", "icon": "migration"},

    # ═══════════════════════════════════════════════════════════
    # BUSINESS APPLICATIONS
    # ═══════════════════════════════════════════════════════════
    {"id": "gcp-workspace", "name": "Google Workspace", "fullName": "Google Workspace", "category": "Business", "description": "Collaboration and productivity apps", "icon": "productivity"},
    {"id": "gcp-maps-platform", "name": "Maps Platform", "fullName": "Google Maps Platform", "category": "Business", "description": "Location APIs and mapping services", "icon": "maps"},
    {"id": "gcp-firebase", "name": "Firebase", "fullName": "Google Firebase", "category": "Business", "description": "App development platform for web and mobile", "icon": "mobile"},
]
