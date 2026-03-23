/**
 * Cloud services palette for the Canvas Editor.
 * ~30 services per provider, grouped by category.
 */

const SERVICES = [
  // ── AWS ─────────────────────────────────────────────
  // Compute
  { id: 'aws-ec2',            name: 'EC2',                provider: 'AWS', category: 'Compute',  icon_letter: 'E', color: '#FF9900' },
  { id: 'aws-lambda',         name: 'Lambda',             provider: 'AWS', category: 'Compute',  icon_letter: 'λ', color: '#FF9900' },
  { id: 'aws-ecs',            name: 'ECS',                provider: 'AWS', category: 'Compute',  icon_letter: 'C', color: '#FF9900' },
  { id: 'aws-eks',            name: 'EKS',                provider: 'AWS', category: 'Compute',  icon_letter: 'K', color: '#FF9900' },
  { id: 'aws-fargate',        name: 'Fargate',            provider: 'AWS', category: 'Compute',  icon_letter: 'F', color: '#FF9900' },
  { id: 'aws-beanstalk',      name: 'Elastic Beanstalk',  provider: 'AWS', category: 'Compute',  icon_letter: 'B', color: '#FF9900' },
  // Storage
  { id: 'aws-s3',             name: 'S3',                 provider: 'AWS', category: 'Storage',  icon_letter: 'S', color: '#3F8624' },
  { id: 'aws-ebs',            name: 'EBS',                provider: 'AWS', category: 'Storage',  icon_letter: 'E', color: '#3F8624' },
  { id: 'aws-efs',            name: 'EFS',                provider: 'AWS', category: 'Storage',  icon_letter: 'F', color: '#3F8624' },
  // Database
  { id: 'aws-rds',            name: 'RDS',                provider: 'AWS', category: 'Database', icon_letter: 'R', color: '#3B48CC' },
  { id: 'aws-dynamodb',       name: 'DynamoDB',           provider: 'AWS', category: 'Database', icon_letter: 'D', color: '#3B48CC' },
  { id: 'aws-aurora',         name: 'Aurora',             provider: 'AWS', category: 'Database', icon_letter: 'A', color: '#3B48CC' },
  { id: 'aws-elasticache',    name: 'ElastiCache',        provider: 'AWS', category: 'Database', icon_letter: 'C', color: '#3B48CC' },
  { id: 'aws-redshift',       name: 'Redshift',           provider: 'AWS', category: 'Database', icon_letter: 'R', color: '#3B48CC' },
  // Network
  { id: 'aws-vpc',            name: 'VPC',                provider: 'AWS', category: 'Network',  icon_letter: 'V', color: '#8C4FFF' },
  { id: 'aws-elb',            name: 'ELB',                provider: 'AWS', category: 'Network',  icon_letter: 'L', color: '#8C4FFF' },
  { id: 'aws-cloudfront',     name: 'CloudFront',         provider: 'AWS', category: 'Network',  icon_letter: 'C', color: '#8C4FFF' },
  { id: 'aws-route53',        name: 'Route 53',           provider: 'AWS', category: 'Network',  icon_letter: '5', color: '#8C4FFF' },
  { id: 'aws-apigateway',     name: 'API Gateway',        provider: 'AWS', category: 'Network',  icon_letter: 'A', color: '#8C4FFF' },
  // Security
  { id: 'aws-iam',            name: 'IAM',                provider: 'AWS', category: 'Security', icon_letter: 'I', color: '#DD344C' },
  { id: 'aws-cognito',        name: 'Cognito',            provider: 'AWS', category: 'Security', icon_letter: 'C', color: '#DD344C' },
  { id: 'aws-kms',            name: 'KMS',                provider: 'AWS', category: 'Security', icon_letter: 'K', color: '#DD344C' },
  { id: 'aws-waf',            name: 'WAF',                provider: 'AWS', category: 'Security', icon_letter: 'W', color: '#DD344C' },
  { id: 'aws-secretsmanager', name: 'Secrets Manager',    provider: 'AWS', category: 'Security', icon_letter: 'S', color: '#DD344C' },
  // AI/ML
  { id: 'aws-sagemaker',      name: 'SageMaker',          provider: 'AWS', category: 'AI/ML',    icon_letter: 'S', color: '#01A88D' },
  { id: 'aws-bedrock',        name: 'Bedrock',            provider: 'AWS', category: 'AI/ML',    icon_letter: 'B', color: '#01A88D' },
  { id: 'aws-rekognition',    name: 'Rekognition',        provider: 'AWS', category: 'AI/ML',    icon_letter: 'R', color: '#01A88D' },
  { id: 'aws-sns',            name: 'SNS',                provider: 'AWS', category: 'Network',  icon_letter: 'N', color: '#8C4FFF' },
  { id: 'aws-sqs',            name: 'SQS',                provider: 'AWS', category: 'Network',  icon_letter: 'Q', color: '#8C4FFF' },
  { id: 'aws-cloudwatch',     name: 'CloudWatch',         provider: 'AWS', category: 'Compute',  icon_letter: 'W', color: '#FF9900' },

  // ── Azure ───────────────────────────────────────────
  // Compute
  { id: 'az-vm',              name: 'Virtual Machines',    provider: 'Azure', category: 'Compute',  icon_letter: 'V', color: '#0078D4' },
  { id: 'az-functions',       name: 'Functions',           provider: 'Azure', category: 'Compute',  icon_letter: 'F', color: '#0078D4' },
  { id: 'az-aks',             name: 'AKS',                provider: 'Azure', category: 'Compute',  icon_letter: 'K', color: '#0078D4' },
  { id: 'az-aci',             name: 'Container Instances', provider: 'Azure', category: 'Compute',  icon_letter: 'C', color: '#0078D4' },
  { id: 'az-appservice',      name: 'App Service',         provider: 'Azure', category: 'Compute',  icon_letter: 'A', color: '#0078D4' },
  { id: 'az-batch',           name: 'Batch',               provider: 'Azure', category: 'Compute',  icon_letter: 'B', color: '#0078D4' },
  // Storage
  { id: 'az-blob',            name: 'Blob Storage',        provider: 'Azure', category: 'Storage',  icon_letter: 'B', color: '#0078D4' },
  { id: 'az-files',           name: 'File Storage',        provider: 'Azure', category: 'Storage',  icon_letter: 'F', color: '#0078D4' },
  { id: 'az-disk',            name: 'Managed Disks',       provider: 'Azure', category: 'Storage',  icon_letter: 'D', color: '#0078D4' },
  // Database
  { id: 'az-sqldb',           name: 'SQL Database',        provider: 'Azure', category: 'Database', icon_letter: 'S', color: '#0078D4' },
  { id: 'az-cosmos',          name: 'Cosmos DB',           provider: 'Azure', category: 'Database', icon_letter: 'C', color: '#0078D4' },
  { id: 'az-redis',           name: 'Cache for Redis',     provider: 'Azure', category: 'Database', icon_letter: 'R', color: '#0078D4' },
  { id: 'az-postgres',        name: 'PostgreSQL',          provider: 'Azure', category: 'Database', icon_letter: 'P', color: '#0078D4' },
  { id: 'az-mysql',           name: 'MySQL',               provider: 'Azure', category: 'Database', icon_letter: 'M', color: '#0078D4' },
  // Network
  { id: 'az-vnet',            name: 'Virtual Network',     provider: 'Azure', category: 'Network',  icon_letter: 'V', color: '#0078D4' },
  { id: 'az-lb',              name: 'Load Balancer',       provider: 'Azure', category: 'Network',  icon_letter: 'L', color: '#0078D4' },
  { id: 'az-appgw',           name: 'App Gateway',         provider: 'Azure', category: 'Network',  icon_letter: 'G', color: '#0078D4' },
  { id: 'az-frontdoor',       name: 'Front Door',          provider: 'Azure', category: 'Network',  icon_letter: 'F', color: '#0078D4' },
  { id: 'az-dns',             name: 'DNS Zone',            provider: 'Azure', category: 'Network',  icon_letter: 'D', color: '#0078D4' },
  { id: 'az-apim',            name: 'API Management',      provider: 'Azure', category: 'Network',  icon_letter: 'A', color: '#0078D4' },
  // Security
  { id: 'az-keyvault',        name: 'Key Vault',           provider: 'Azure', category: 'Security', icon_letter: 'K', color: '#0078D4' },
  { id: 'az-entra',           name: 'Entra ID',            provider: 'Azure', category: 'Security', icon_letter: 'E', color: '#0078D4' },
  { id: 'az-firewall',        name: 'Firewall',            provider: 'Azure', category: 'Security', icon_letter: 'F', color: '#0078D4' },
  { id: 'az-sentinel',        name: 'Sentinel',            provider: 'Azure', category: 'Security', icon_letter: 'S', color: '#0078D4' },
  // AI/ML
  { id: 'az-openai',          name: 'OpenAI Service',      provider: 'Azure', category: 'AI/ML',    icon_letter: 'O', color: '#0078D4' },
  { id: 'az-ml',              name: 'Machine Learning',    provider: 'Azure', category: 'AI/ML',    icon_letter: 'M', color: '#0078D4' },
  { id: 'az-cognitive',       name: 'AI Services',         provider: 'Azure', category: 'AI/ML',    icon_letter: 'A', color: '#0078D4' },
  { id: 'az-servicebus',      name: 'Service Bus',         provider: 'Azure', category: 'Network',  icon_letter: 'B', color: '#0078D4' },
  { id: 'az-eventhubs',       name: 'Event Hubs',          provider: 'Azure', category: 'Network',  icon_letter: 'H', color: '#0078D4' },
  { id: 'az-monitor',         name: 'Monitor',             provider: 'Azure', category: 'Compute',  icon_letter: 'M', color: '#0078D4' },

  // ── GCP ─────────────────────────────────────────────
  // Compute
  { id: 'gcp-gce',            name: 'Compute Engine',       provider: 'GCP', category: 'Compute',  icon_letter: 'C', color: '#4285F4' },
  { id: 'gcp-functions',      name: 'Cloud Functions',      provider: 'GCP', category: 'Compute',  icon_letter: 'F', color: '#4285F4' },
  { id: 'gcp-run',            name: 'Cloud Run',            provider: 'GCP', category: 'Compute',  icon_letter: 'R', color: '#4285F4' },
  { id: 'gcp-gke',            name: 'GKE',                  provider: 'GCP', category: 'Compute',  icon_letter: 'K', color: '#4285F4' },
  { id: 'gcp-appengine',      name: 'App Engine',           provider: 'GCP', category: 'Compute',  icon_letter: 'A', color: '#4285F4' },
  // Storage
  { id: 'gcp-gcs',            name: 'Cloud Storage',        provider: 'GCP', category: 'Storage',  icon_letter: 'S', color: '#4285F4' },
  { id: 'gcp-filestore',      name: 'Filestore',            provider: 'GCP', category: 'Storage',  icon_letter: 'F', color: '#4285F4' },
  { id: 'gcp-persistentdisk', name: 'Persistent Disk',      provider: 'GCP', category: 'Storage',  icon_letter: 'P', color: '#4285F4' },
  // Database
  { id: 'gcp-cloudsql',       name: 'Cloud SQL',            provider: 'GCP', category: 'Database', icon_letter: 'S', color: '#4285F4' },
  { id: 'gcp-firestore',      name: 'Firestore',            provider: 'GCP', category: 'Database', icon_letter: 'F', color: '#4285F4' },
  { id: 'gcp-bigtable',       name: 'Bigtable',             provider: 'GCP', category: 'Database', icon_letter: 'B', color: '#4285F4' },
  { id: 'gcp-spanner',        name: 'Spanner',              provider: 'GCP', category: 'Database', icon_letter: 'S', color: '#4285F4' },
  { id: 'gcp-memorystore',    name: 'Memorystore',          provider: 'GCP', category: 'Database', icon_letter: 'M', color: '#4285F4' },
  { id: 'gcp-alloydb',        name: 'AlloyDB',              provider: 'GCP', category: 'Database', icon_letter: 'A', color: '#4285F4' },
  // Network
  { id: 'gcp-vpc',            name: 'VPC Network',          provider: 'GCP', category: 'Network',  icon_letter: 'V', color: '#4285F4' },
  { id: 'gcp-lb',             name: 'Cloud Load Balancing', provider: 'GCP', category: 'Network',  icon_letter: 'L', color: '#4285F4' },
  { id: 'gcp-cdn',            name: 'Cloud CDN',            provider: 'GCP', category: 'Network',  icon_letter: 'C', color: '#4285F4' },
  { id: 'gcp-dns',            name: 'Cloud DNS',            provider: 'GCP', category: 'Network',  icon_letter: 'D', color: '#4285F4' },
  { id: 'gcp-apigateway',     name: 'API Gateway',          provider: 'GCP', category: 'Network',  icon_letter: 'A', color: '#4285F4' },
  { id: 'gcp-pubsub',         name: 'Pub/Sub',              provider: 'GCP', category: 'Network',  icon_letter: 'P', color: '#4285F4' },
  // Security
  { id: 'gcp-iam',            name: 'IAM',                  provider: 'GCP', category: 'Security', icon_letter: 'I', color: '#4285F4' },
  { id: 'gcp-kms',            name: 'Cloud KMS',            provider: 'GCP', category: 'Security', icon_letter: 'K', color: '#4285F4' },
  { id: 'gcp-armor',          name: 'Cloud Armor',          provider: 'GCP', category: 'Security', icon_letter: 'A', color: '#4285F4' },
  { id: 'gcp-secretmanager',  name: 'Secret Manager',       provider: 'GCP', category: 'Security', icon_letter: 'S', color: '#4285F4' },
  // AI/ML
  { id: 'gcp-vertexai',       name: 'Vertex AI',            provider: 'GCP', category: 'AI/ML',    icon_letter: 'V', color: '#4285F4' },
  { id: 'gcp-automl',         name: 'AutoML',               provider: 'GCP', category: 'AI/ML',    icon_letter: 'A', color: '#4285F4' },
  { id: 'gcp-vision',         name: 'Vision AI',            provider: 'GCP', category: 'AI/ML',    icon_letter: 'V', color: '#4285F4' },
  { id: 'gcp-bigquery',       name: 'BigQuery',             provider: 'GCP', category: 'Database', icon_letter: 'Q', color: '#4285F4' },
  { id: 'gcp-monitoring',     name: 'Cloud Monitoring',     provider: 'GCP', category: 'Compute',  icon_letter: 'M', color: '#4285F4' },
];

export const CATEGORIES = ['Compute', 'Storage', 'Database', 'Network', 'Security', 'AI/ML'];
export const PROVIDERS = ['AWS', 'Azure', 'GCP'];

export default SERVICES;
