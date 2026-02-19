"""
AWS Services Catalog — Comprehensive list of AWS services with categories, descriptions, and metadata.
"""

AWS_SERVICES = [
    # ═══════════════════════════════════════════════════════════
    # COMPUTE
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-ec2", "name": "EC2", "fullName": "Elastic Compute Cloud", "category": "Compute", "description": "Scalable virtual servers in the cloud", "icon": "server"},
    {"id": "aws-lambda", "name": "Lambda", "fullName": "AWS Lambda", "category": "Compute", "description": "Run code without provisioning servers", "icon": "function"},
    {"id": "aws-ecs", "name": "ECS", "fullName": "Elastic Container Service", "category": "Compute", "description": "Run and manage Docker containers", "icon": "container"},
    {"id": "aws-eks", "name": "EKS", "fullName": "Elastic Kubernetes Service", "category": "Compute", "description": "Managed Kubernetes service", "icon": "kubernetes"},
    {"id": "aws-fargate", "name": "Fargate", "fullName": "AWS Fargate", "category": "Compute", "description": "Serverless compute for containers", "icon": "container"},
    {"id": "aws-lightsail", "name": "Lightsail", "fullName": "Amazon Lightsail", "category": "Compute", "description": "Easy-to-use virtual private servers", "icon": "server"},
    {"id": "aws-batch", "name": "Batch", "fullName": "AWS Batch", "category": "Compute", "description": "Batch computing at any scale", "icon": "batch"},
    {"id": "aws-elastic-beanstalk", "name": "Elastic Beanstalk", "fullName": "AWS Elastic Beanstalk", "category": "Compute", "description": "Deploy and scale web apps", "icon": "webapp"},
    {"id": "aws-outposts", "name": "Outposts", "fullName": "AWS Outposts", "category": "Compute", "description": "Run AWS services on-premises", "icon": "hybrid"},
    {"id": "aws-wavelength", "name": "Wavelength", "fullName": "AWS Wavelength", "category": "Compute", "description": "Ultra-low latency at the 5G edge", "icon": "edge"},
    {"id": "aws-app-runner", "name": "App Runner", "fullName": "AWS App Runner", "category": "Compute", "description": "Build and run containerized web apps at scale", "icon": "webapp"},
    {"id": "aws-ec2-auto-scaling", "name": "EC2 Auto Scaling", "fullName": "Amazon EC2 Auto Scaling", "category": "Compute", "description": "Scale compute capacity to meet demand", "icon": "autoscale"},
    {"id": "aws-ec2-image-builder", "name": "EC2 Image Builder", "fullName": "EC2 Image Builder", "category": "Compute", "description": "Build and maintain secure images", "icon": "image"},
    {"id": "aws-serverless-repo", "name": "Serverless Application Repository", "fullName": "AWS Serverless Application Repository", "category": "Compute", "description": "Discover, deploy, and publish serverless applications", "icon": "function"},

    # ═══════════════════════════════════════════════════════════
    # STORAGE
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-s3", "name": "S3", "fullName": "Simple Storage Service", "category": "Storage", "description": "Scalable object storage in the cloud", "icon": "storage"},
    {"id": "aws-ebs", "name": "EBS", "fullName": "Elastic Block Store", "category": "Storage", "description": "Block-level storage for EC2 instances", "icon": "disk"},
    {"id": "aws-efs", "name": "EFS", "fullName": "Elastic File System", "category": "Storage", "description": "Fully managed file system for EC2", "icon": "file"},
    {"id": "aws-fsx", "name": "FSx", "fullName": "Amazon FSx", "category": "Storage", "description": "Fully managed third-party file systems", "icon": "file"},
    {"id": "aws-s3-glacier", "name": "S3 Glacier", "fullName": "Amazon S3 Glacier", "category": "Storage", "description": "Low-cost archive storage in the cloud", "icon": "archive"},
    {"id": "aws-storage-gateway", "name": "Storage Gateway", "fullName": "AWS Storage Gateway", "category": "Storage", "description": "Hybrid cloud storage integration", "icon": "hybrid"},
    {"id": "aws-snow-family", "name": "Snow Family", "fullName": "AWS Snow Family", "category": "Storage", "description": "Physical edge computing and storage devices", "icon": "device"},
    {"id": "aws-backup", "name": "Backup", "fullName": "AWS Backup", "category": "Storage", "description": "Centralized backup across AWS services", "icon": "backup"},
    {"id": "aws-datasync", "name": "DataSync", "fullName": "AWS DataSync", "category": "Storage", "description": "Automate data transfer", "icon": "transfer"},
    {"id": "aws-transfer-family", "name": "Transfer Family", "fullName": "AWS Transfer Family", "category": "Storage", "description": "Managed file transfers using SFTP, FTPS, FTP", "icon": "transfer"},

    # ═══════════════════════════════════════════════════════════
    # DATABASE
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-rds", "name": "RDS", "fullName": "Relational Database Service", "category": "Database", "description": "Managed relational databases (MySQL, PostgreSQL, etc.)", "icon": "database"},
    {"id": "aws-aurora", "name": "Aurora", "fullName": "Amazon Aurora", "category": "Database", "description": "MySQL and PostgreSQL-compatible relational database", "icon": "database"},
    {"id": "aws-dynamodb", "name": "DynamoDB", "fullName": "Amazon DynamoDB", "category": "Database", "description": "Managed NoSQL key-value and document database", "icon": "nosql"},
    {"id": "aws-elasticache", "name": "ElastiCache", "fullName": "Amazon ElastiCache", "category": "Database", "description": "In-memory caching (Redis, Memcached)", "icon": "cache"},
    {"id": "aws-redshift", "name": "Redshift", "fullName": "Amazon Redshift", "category": "Database", "description": "Cloud data warehouse", "icon": "warehouse"},
    {"id": "aws-neptune", "name": "Neptune", "fullName": "Amazon Neptune", "category": "Database", "description": "Managed graph database", "icon": "graph"},
    {"id": "aws-documentdb", "name": "DocumentDB", "fullName": "Amazon DocumentDB", "category": "Database", "description": "MongoDB-compatible document database", "icon": "document"},
    {"id": "aws-keyspaces", "name": "Keyspaces", "fullName": "Amazon Keyspaces", "category": "Database", "description": "Managed Apache Cassandra-compatible database", "icon": "nosql"},
    {"id": "aws-timestream", "name": "Timestream", "fullName": "Amazon Timestream", "category": "Database", "description": "Serverless time series database", "icon": "timeseries"},
    {"id": "aws-qldb", "name": "QLDB", "fullName": "Amazon QLDB", "category": "Database", "description": "Fully managed ledger database", "icon": "ledger"},
    {"id": "aws-memorydb", "name": "MemoryDB", "fullName": "Amazon MemoryDB for Redis", "category": "Database", "description": "Redis-compatible in-memory database", "icon": "cache"},
    {"id": "aws-dms", "name": "DMS", "fullName": "Database Migration Service", "category": "Database", "description": "Migrate databases to AWS", "icon": "migration"},

    # ═══════════════════════════════════════════════════════════
    # NETWORKING
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-vpc", "name": "VPC", "fullName": "Virtual Private Cloud", "category": "Networking", "description": "Isolated cloud resources in a virtual network", "icon": "network"},
    {"id": "aws-cloudfront", "name": "CloudFront", "fullName": "Amazon CloudFront", "category": "Networking", "description": "Content delivery network (CDN)", "icon": "cdn"},
    {"id": "aws-route53", "name": "Route 53", "fullName": "Amazon Route 53", "category": "Networking", "description": "Scalable DNS and domain management", "icon": "dns"},
    {"id": "aws-api-gateway", "name": "API Gateway", "fullName": "Amazon API Gateway", "category": "Networking", "description": "Create, manage, and secure APIs at any scale", "icon": "api"},
    {"id": "aws-elb", "name": "ELB", "fullName": "Elastic Load Balancing", "category": "Networking", "description": "Distribute incoming traffic across targets", "icon": "loadbalancer"},
    {"id": "aws-direct-connect", "name": "Direct Connect", "fullName": "AWS Direct Connect", "category": "Networking", "description": "Dedicated network connection to AWS", "icon": "connection"},
    {"id": "aws-global-accelerator", "name": "Global Accelerator", "fullName": "AWS Global Accelerator", "category": "Networking", "description": "Improve global application availability", "icon": "accelerator"},
    {"id": "aws-transit-gateway", "name": "Transit Gateway", "fullName": "AWS Transit Gateway", "category": "Networking", "description": "Connect VPCs and on-premises networks", "icon": "gateway"},
    {"id": "aws-privatelink", "name": "PrivateLink", "fullName": "AWS PrivateLink", "category": "Networking", "description": "Secure access to services hosted on AWS", "icon": "privatelink"},
    {"id": "aws-app-mesh", "name": "App Mesh", "fullName": "AWS App Mesh", "category": "Networking", "description": "Application-level networking service mesh", "icon": "mesh"},
    {"id": "aws-cloud-map", "name": "Cloud Map", "fullName": "AWS Cloud Map", "category": "Networking", "description": "Service discovery for cloud resources", "icon": "discovery"},
    {"id": "aws-vpn", "name": "VPN", "fullName": "AWS VPN", "category": "Networking", "description": "Securely connect on-premises to AWS", "icon": "vpn"},
    {"id": "aws-network-firewall", "name": "Network Firewall", "fullName": "AWS Network Firewall", "category": "Networking", "description": "Managed network firewall and IDS/IPS", "icon": "firewall"},

    # ═══════════════════════════════════════════════════════════
    # SECURITY, IDENTITY & COMPLIANCE
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-iam", "name": "IAM", "fullName": "Identity and Access Management", "category": "Security", "description": "Manage access to AWS services and resources", "icon": "identity"},
    {"id": "aws-cognito", "name": "Cognito", "fullName": "Amazon Cognito", "category": "Security", "description": "User sign-up, sign-in, and access control", "icon": "auth"},
    {"id": "aws-guardduty", "name": "GuardDuty", "fullName": "Amazon GuardDuty", "category": "Security", "description": "Intelligent threat detection", "icon": "shield"},
    {"id": "aws-inspector", "name": "Inspector", "fullName": "Amazon Inspector", "category": "Security", "description": "Automated security assessment", "icon": "inspect"},
    {"id": "aws-macie", "name": "Macie", "fullName": "Amazon Macie", "category": "Security", "description": "Discover and protect sensitive data", "icon": "data-protection"},
    {"id": "aws-kms", "name": "KMS", "fullName": "Key Management Service", "category": "Security", "description": "Create and manage encryption keys", "icon": "key"},
    {"id": "aws-secrets-manager", "name": "Secrets Manager", "fullName": "AWS Secrets Manager", "category": "Security", "description": "Rotate, manage, and retrieve secrets", "icon": "secret"},
    {"id": "aws-waf", "name": "WAF", "fullName": "AWS WAF", "category": "Security", "description": "Web application firewall", "icon": "waf"},
    {"id": "aws-shield", "name": "Shield", "fullName": "AWS Shield", "category": "Security", "description": "DDoS protection", "icon": "shield"},
    {"id": "aws-certificate-manager", "name": "Certificate Manager", "fullName": "AWS Certificate Manager", "category": "Security", "description": "Provision, manage, and deploy SSL/TLS certificates", "icon": "certificate"},
    {"id": "aws-sso", "name": "IAM Identity Center", "fullName": "AWS IAM Identity Center (SSO)", "category": "Security", "description": "Single sign-on for AWS accounts and apps", "icon": "sso"},
    {"id": "aws-directory-service", "name": "Directory Service", "fullName": "AWS Directory Service", "category": "Security", "description": "Managed Microsoft Active Directory", "icon": "directory"},
    {"id": "aws-security-hub", "name": "Security Hub", "fullName": "AWS Security Hub", "category": "Security", "description": "Centralized security and compliance center", "icon": "security-center"},
    {"id": "aws-firewall-manager", "name": "Firewall Manager", "fullName": "AWS Firewall Manager", "category": "Security", "description": "Central management of firewall rules", "icon": "firewall"},
    {"id": "aws-cloudhsm", "name": "CloudHSM", "fullName": "AWS CloudHSM", "category": "Security", "description": "Hardware-based key storage for regulatory compliance", "icon": "hsm"},
    {"id": "aws-detective", "name": "Detective", "fullName": "Amazon Detective", "category": "Security", "description": "Investigate security findings", "icon": "detective"},
    {"id": "aws-audit-manager", "name": "Audit Manager", "fullName": "AWS Audit Manager", "category": "Security", "description": "Continuously audit AWS usage", "icon": "audit"},

    # ═══════════════════════════════════════════════════════════
    # AI / ML
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-sagemaker", "name": "SageMaker", "fullName": "Amazon SageMaker", "category": "AI/ML", "description": "Build, train, and deploy ML models", "icon": "ml"},
    {"id": "aws-bedrock", "name": "Bedrock", "fullName": "Amazon Bedrock", "category": "AI/ML", "description": "Foundation models as a service", "icon": "ai"},
    {"id": "aws-rekognition", "name": "Rekognition", "fullName": "Amazon Rekognition", "category": "AI/ML", "description": "Image and video analysis", "icon": "vision"},
    {"id": "aws-comprehend", "name": "Comprehend", "fullName": "Amazon Comprehend", "category": "AI/ML", "description": "Natural language processing", "icon": "nlp"},
    {"id": "aws-polly", "name": "Polly", "fullName": "Amazon Polly", "category": "AI/ML", "description": "Turn text into lifelike speech", "icon": "speech"},
    {"id": "aws-transcribe", "name": "Transcribe", "fullName": "Amazon Transcribe", "category": "AI/ML", "description": "Automatic speech recognition", "icon": "speech"},
    {"id": "aws-translate", "name": "Translate", "fullName": "Amazon Translate", "category": "AI/ML", "description": "Neural machine translation", "icon": "translate"},
    {"id": "aws-lex", "name": "Lex", "fullName": "Amazon Lex", "category": "AI/ML", "description": "Build conversational interfaces (chatbots)", "icon": "chatbot"},
    {"id": "aws-textract", "name": "Textract", "fullName": "Amazon Textract", "category": "AI/ML", "description": "Extract text and data from documents", "icon": "ocr"},
    {"id": "aws-forecast", "name": "Forecast", "fullName": "Amazon Forecast", "category": "AI/ML", "description": "Time-series forecasting", "icon": "forecast"},
    {"id": "aws-personalize", "name": "Personalize", "fullName": "Amazon Personalize", "category": "AI/ML", "description": "Real-time personalization and recommendations", "icon": "recommend"},
    {"id": "aws-kendra", "name": "Kendra", "fullName": "Amazon Kendra", "category": "AI/ML", "description": "Intelligent enterprise search", "icon": "search"},
    {"id": "aws-lookout-vision", "name": "Lookout for Vision", "fullName": "Amazon Lookout for Vision", "category": "AI/ML", "description": "Spot product defects with computer vision", "icon": "vision"},
    {"id": "aws-healthlake", "name": "HealthLake", "fullName": "Amazon HealthLake", "category": "AI/ML", "description": "Store, transform, query health data", "icon": "health"},
    {"id": "aws-codewhisperer", "name": "CodeWhisperer", "fullName": "Amazon CodeWhisperer", "category": "AI/ML", "description": "AI-powered code suggestions", "icon": "code"},

    # ═══════════════════════════════════════════════════════════
    # ANALYTICS
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-athena", "name": "Athena", "fullName": "Amazon Athena", "category": "Analytics", "description": "Interactive query service for S3 data", "icon": "query"},
    {"id": "aws-emr", "name": "EMR", "fullName": "Elastic MapReduce", "category": "Analytics", "description": "Managed Hadoop/Spark framework", "icon": "spark"},
    {"id": "aws-kinesis", "name": "Kinesis", "fullName": "Amazon Kinesis", "category": "Analytics", "description": "Real-time data streaming", "icon": "stream"},
    {"id": "aws-quicksight", "name": "QuickSight", "fullName": "Amazon QuickSight", "category": "Analytics", "description": "Business intelligence and visualization", "icon": "bi"},
    {"id": "aws-glue", "name": "Glue", "fullName": "AWS Glue", "category": "Analytics", "description": "Serverless data integration and ETL", "icon": "etl"},
    {"id": "aws-lake-formation", "name": "Lake Formation", "fullName": "AWS Lake Formation", "category": "Analytics", "description": "Build, manage, and secure data lakes", "icon": "datalake"},
    {"id": "aws-msk", "name": "MSK", "fullName": "Amazon MSK", "category": "Analytics", "description": "Managed Streaming for Apache Kafka", "icon": "kafka"},
    {"id": "aws-opensearch", "name": "OpenSearch", "fullName": "Amazon OpenSearch Service", "category": "Analytics", "description": "Search, visualize, and analyze data", "icon": "search"},
    {"id": "aws-data-pipeline", "name": "Data Pipeline", "fullName": "AWS Data Pipeline", "category": "Analytics", "description": "Orchestrate and automate data workflows", "icon": "pipeline"},
    {"id": "aws-clean-rooms", "name": "Clean Rooms", "fullName": "AWS Clean Rooms", "category": "Analytics", "description": "Collaborate on data without sharing raw data", "icon": "cleanroom"},
    {"id": "aws-data-exchange", "name": "Data Exchange", "fullName": "AWS Data Exchange", "category": "Analytics", "description": "Find, subscribe to, and use third-party data", "icon": "exchange"},
    {"id": "aws-managed-airflow", "name": "MWAA", "fullName": "Managed Workflows for Apache Airflow", "category": "Analytics", "description": "Managed Apache Airflow orchestration", "icon": "orchestration"},

    # ═══════════════════════════════════════════════════════════
    # APPLICATION INTEGRATION
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-sqs", "name": "SQS", "fullName": "Simple Queue Service", "category": "Integration", "description": "Managed message queuing service", "icon": "queue"},
    {"id": "aws-sns", "name": "SNS", "fullName": "Simple Notification Service", "category": "Integration", "description": "Pub/sub messaging and mobile notifications", "icon": "notification"},
    {"id": "aws-eventbridge", "name": "EventBridge", "fullName": "Amazon EventBridge", "category": "Integration", "description": "Serverless event bus", "icon": "event"},
    {"id": "aws-step-functions", "name": "Step Functions", "fullName": "AWS Step Functions", "category": "Integration", "description": "Visual workflow orchestration", "icon": "workflow"},
    {"id": "aws-mq", "name": "Amazon MQ", "fullName": "Amazon MQ", "category": "Integration", "description": "Managed message broker (ActiveMQ, RabbitMQ)", "icon": "broker"},
    {"id": "aws-appsync", "name": "AppSync", "fullName": "AWS AppSync", "category": "Integration", "description": "Managed GraphQL APIs", "icon": "graphql"},
    {"id": "aws-swf", "name": "SWF", "fullName": "Simple Workflow Service", "category": "Integration", "description": "Build, run, and coordinate tasks", "icon": "workflow"},

    # ═══════════════════════════════════════════════════════════
    # DEVELOPER TOOLS
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-codecommit", "name": "CodeCommit", "fullName": "AWS CodeCommit", "category": "DevTools", "description": "Managed source control (Git)", "icon": "git"},
    {"id": "aws-codebuild", "name": "CodeBuild", "fullName": "AWS CodeBuild", "category": "DevTools", "description": "Build and test code", "icon": "build"},
    {"id": "aws-codedeploy", "name": "CodeDeploy", "fullName": "AWS CodeDeploy", "category": "DevTools", "description": "Automate code deployments", "icon": "deploy"},
    {"id": "aws-codepipeline", "name": "CodePipeline", "fullName": "AWS CodePipeline", "category": "DevTools", "description": "Continuous delivery pipeline", "icon": "pipeline"},
    {"id": "aws-cdk", "name": "CDK", "fullName": "AWS Cloud Development Kit", "category": "DevTools", "description": "Define cloud infrastructure in code", "icon": "iac"},
    {"id": "aws-cloudformation", "name": "CloudFormation", "fullName": "AWS CloudFormation", "category": "DevTools", "description": "Model and provision AWS resources with templates", "icon": "iac"},
    {"id": "aws-cloud9", "name": "Cloud9", "fullName": "AWS Cloud9", "category": "DevTools", "description": "Cloud-based IDE", "icon": "ide"},
    {"id": "aws-xray", "name": "X-Ray", "fullName": "AWS X-Ray", "category": "DevTools", "description": "Analyze and debug distributed applications", "icon": "trace"},
    {"id": "aws-codeartifact", "name": "CodeArtifact", "fullName": "AWS CodeArtifact", "category": "DevTools", "description": "Managed artifact repository", "icon": "artifact"},
    {"id": "aws-fault-injection", "name": "FIS", "fullName": "AWS Fault Injection Simulator", "category": "DevTools", "description": "Chaos engineering experiments", "icon": "chaos"},

    # ═══════════════════════════════════════════════════════════
    # MANAGEMENT & GOVERNANCE
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-cloudwatch", "name": "CloudWatch", "fullName": "Amazon CloudWatch", "category": "Management", "description": "Monitoring and observability", "icon": "monitor"},
    {"id": "aws-cloudtrail", "name": "CloudTrail", "fullName": "AWS CloudTrail", "category": "Management", "description": "Track user activity and API usage", "icon": "audit"},
    {"id": "aws-config", "name": "Config", "fullName": "AWS Config", "category": "Management", "description": "Assess, audit, and evaluate resource configurations", "icon": "config"},
    {"id": "aws-systems-manager", "name": "Systems Manager", "fullName": "AWS Systems Manager", "category": "Management", "description": "Operations hub for AWS resources", "icon": "ops"},
    {"id": "aws-organizations", "name": "Organizations", "fullName": "AWS Organizations", "category": "Management", "description": "Centrally manage multiple AWS accounts", "icon": "org"},
    {"id": "aws-control-tower", "name": "Control Tower", "fullName": "AWS Control Tower", "category": "Management", "description": "Set up and govern a secure multi-account environment", "icon": "governance"},
    {"id": "aws-service-catalog", "name": "Service Catalog", "fullName": "AWS Service Catalog", "category": "Management", "description": "Create and manage catalogs of IT services", "icon": "catalog"},
    {"id": "aws-trusted-advisor", "name": "Trusted Advisor", "fullName": "AWS Trusted Advisor", "category": "Management", "description": "Best practice recommendations", "icon": "advisor"},
    {"id": "aws-well-architected", "name": "Well-Architected Tool", "fullName": "AWS Well-Architected Tool", "category": "Management", "description": "Review workloads against best practices", "icon": "review"},
    {"id": "aws-cost-explorer", "name": "Cost Explorer", "fullName": "AWS Cost Explorer", "category": "Management", "description": "Analyze and manage AWS costs", "icon": "cost"},
    {"id": "aws-health", "name": "Health Dashboard", "fullName": "AWS Health Dashboard", "category": "Management", "description": "Personalized service health information", "icon": "health"},
    {"id": "aws-license-manager", "name": "License Manager", "fullName": "AWS License Manager", "category": "Management", "description": "Manage software licenses", "icon": "license"},
    {"id": "aws-resource-groups", "name": "Resource Groups", "fullName": "AWS Resource Groups", "category": "Management", "description": "Organize resources using tags", "icon": "group"},

    # ═══════════════════════════════════════════════════════════
    # CONTAINERS
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-ecr", "name": "ECR", "fullName": "Elastic Container Registry", "category": "Containers", "description": "Container image registry", "icon": "registry"},
    {"id": "aws-ecs-anywhere", "name": "ECS Anywhere", "fullName": "Amazon ECS Anywhere", "category": "Containers", "description": "Run containers on customer-managed infrastructure", "icon": "hybrid"},

    # ═══════════════════════════════════════════════════════════
    # IOT
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-iot-core", "name": "IoT Core", "fullName": "AWS IoT Core", "category": "IoT", "description": "Connect IoT devices to the cloud", "icon": "iot"},
    {"id": "aws-iot-greengrass", "name": "IoT Greengrass", "fullName": "AWS IoT Greengrass", "category": "IoT", "description": "Local compute and ML for IoT devices", "icon": "edge"},
    {"id": "aws-iot-analytics", "name": "IoT Analytics", "fullName": "AWS IoT Analytics", "category": "IoT", "description": "Analytics for IoT devices", "icon": "analytics"},
    {"id": "aws-iot-sitewise", "name": "IoT SiteWise", "fullName": "AWS IoT SiteWise", "category": "IoT", "description": "Collect and analyze industrial equipment data", "icon": "industrial"},
    {"id": "aws-iot-events", "name": "IoT Events", "fullName": "AWS IoT Events", "category": "IoT", "description": "Detect and respond to IoT events", "icon": "event"},
    {"id": "aws-iot-twinmaker", "name": "IoT TwinMaker", "fullName": "AWS IoT TwinMaker", "category": "IoT", "description": "Build digital twins of real-world systems", "icon": "twin"},
    {"id": "aws-iot-fleetwise", "name": "IoT FleetWise", "fullName": "AWS IoT FleetWise", "category": "IoT", "description": "Collect and transfer vehicle data", "icon": "vehicle"},

    # ═══════════════════════════════════════════════════════════
    # MEDIA SERVICES
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-mediaconvert", "name": "MediaConvert", "fullName": "AWS Elemental MediaConvert", "category": "Media", "description": "File-based video transcoding", "icon": "video"},
    {"id": "aws-medialive", "name": "MediaLive", "fullName": "AWS Elemental MediaLive", "category": "Media", "description": "Live video processing", "icon": "live"},
    {"id": "aws-mediapackage", "name": "MediaPackage", "fullName": "AWS Elemental MediaPackage", "category": "Media", "description": "Video origination and packaging", "icon": "package"},
    {"id": "aws-ivs", "name": "IVS", "fullName": "Amazon Interactive Video Service", "category": "Media", "description": "Managed live streaming", "icon": "streaming"},

    # ═══════════════════════════════════════════════════════════
    # MIGRATION & TRANSFER
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-migration-hub", "name": "Migration Hub", "fullName": "AWS Migration Hub", "category": "Migration", "description": "Track migrations across AWS", "icon": "migration"},
    {"id": "aws-application-migration", "name": "Application Migration Service", "fullName": "AWS Application Migration Service", "category": "Migration", "description": "Lift-and-shift migration service", "icon": "migration"},
    {"id": "aws-mainframe-modernization", "name": "Mainframe Modernization", "fullName": "AWS Mainframe Modernization", "category": "Migration", "description": "Migrate and modernize mainframe workloads", "icon": "mainframe"},

    # ═══════════════════════════════════════════════════════════
    # BUSINESS APPLICATIONS
    # ═══════════════════════════════════════════════════════════
    {"id": "aws-ses", "name": "SES", "fullName": "Simple Email Service", "category": "Business", "description": "Email sending and receiving", "icon": "email"},
    {"id": "aws-connect", "name": "Connect", "fullName": "Amazon Connect", "category": "Business", "description": "Cloud contact center", "icon": "contact"},
    {"id": "aws-chime", "name": "Chime", "fullName": "Amazon Chime", "category": "Business", "description": "Communications service", "icon": "comms"},
    {"id": "aws-pinpoint", "name": "Pinpoint", "fullName": "Amazon Pinpoint", "category": "Business", "description": "Multichannel marketing communications", "icon": "marketing"},
    {"id": "aws-workspaces", "name": "WorkSpaces", "fullName": "Amazon WorkSpaces", "category": "Business", "description": "Virtual desktops in the cloud", "icon": "desktop"},
    {"id": "aws-appstream", "name": "AppStream 2.0", "fullName": "Amazon AppStream 2.0", "category": "Business", "description": "Stream desktop applications", "icon": "streaming"},
]
