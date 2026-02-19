# AWS Automotive Data Pipeline → Azure Mapping

## Complete Service Mapping

This document maps the AWS automotive/IoT data pipeline architecture to Azure equivalents.

---

## Zone 1: Edge & Ingest Station

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 1.1 | AWS IoT Greengrass | Azure IoT Edge | 95% | Edge runtime with containerized modules |
| 1.2 | AWS IoT SDK | Azure IoT Device SDK | 95% | Direct SDK mapping |
| 1.3 | Data Logger (Removable Media) | Azure Data Box Edge | 85% | Edge storage and compute |
| 1.4 | AWS Direct Connect | Azure ExpressRoute | 95% | Dedicated private connection |
| 1.5 | AWS Outposts | Azure Stack HCI / Azure Arc | 85% | On-premises Azure extension |

---

## Zone 2: Cloud Ingestion

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 2.1 | AWS IoT Core | Azure IoT Hub | 95% | Managed IoT message broker |
| 2.2 | Amazon Kinesis Data Firehose | Azure Event Hubs + Stream Analytics | 90% | Real-time data streaming |
| 2.3 | Over-the-Air (OTA) Ingest | Azure IoT Hub Device Update | 90% | OTA firmware/data updates |

---

## Zone 3: Initial Data Quality & Storage

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 3.1 | Amazon S3 (Raw drive data - MDF4/Rosbag) | Azure Blob Storage (Hot tier) | 95% | Raw data landing zone |
| 3.2 | Amazon EMR (Data quality check) | Azure HDInsight / Synapse Spark | 85% | Distributed data processing |
| 3.3 | Amazon S3 (High quality data) | Azure Blob Storage | 95% | Quality-validated data |
| 3.4 | Amazon S3 (Low quality data) | Azure Blob Storage (Archive tier) | 95% | Quarantine for low-quality data |
| 3.5 | AWS Fargate (Extract topics) | Azure Container Apps | 90% | Serverless containers |

---

## Zone 4: Workflow Orchestration

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 4.1 | Amazon MWAA (Managed Airflow) | Azure Data Factory + Managed Airflow | 85% | Workflow orchestration |

---

## Zone 5: Data Enrichment & Synchronization

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 5.1 | Amazon S3 (Parsed Data - Parquet) | Azure Data Lake Storage Gen2 | 95% | Columnar data storage |
| 5.2 | Amazon EMR (Third-party enrichment) | Azure Synapse Spark Pools | 85% | Weather & map data enrichment |
| 5.3 | Amazon S3 (Enriched drive - Parquet) | Azure Data Lake Storage Gen2 | 95% | Enriched dataset |
| 5.4 | Amazon EMR (Synchronization) | Azure Synapse Spark Pools | 85% | Multi-sensor sync |
| 5.5 | Amazon S3 (Synchronized drive - Parquet) | Azure Data Lake Storage Gen2 | 95% | Time-aligned data |

---

## Zone 6: Scene Detection

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 6.1 | Amazon EMR (Scene detection) | Azure Synapse Spark + Azure ML | 80% | ML-based scene classification |
| 6.2 | Amazon S3 (Scene labels - Parquet) | Azure Data Lake Storage Gen2 | 95% | Scene metadata storage |

---

## Zone 7: Data Catalog

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 7.1 | AWS Glue Data Catalog | Azure Purview / Microsoft Purview | 90% | Data governance & catalog |
| 7.2 | Amazon Neptune (File & data lineage) | Azure Cosmos DB (Gremlin API) | 85% | Graph database for lineage |
| 7.3 | Amazon DynamoDB (Drive metadata) | Azure Cosmos DB (NoSQL API) | 90% | Key-value metadata store |
| 7.4 | Amazon Elasticsearch (OpenScenario search) | Azure AI Search (Cognitive Search) | 90% | Full-text search |

---

## Zone 8: Image Extraction & Anonymization

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 8.1 | AWS Fargate (Extract images from video) | Azure Container Apps | 90% | Video frame extraction |
| 8.2 | Amazon S3 (Raw images per drive) | Azure Blob Storage | 95% | Raw image store |
| 8.3 | AWS Lambda (Blur faces/text) | Azure Functions | 95% | Serverless image processing |
| 8.4 | Amazon Rekognition (Detect face/text) | Azure AI Vision (Face API) | 90% | PII detection in images |
| 8.5 | Amazon S3 (Anonymized images) | Azure Blob Storage | 95% | GDPR-compliant images |

---

## Zone 9: Labeling & Annotation

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 9.1 | Amazon SageMaker Ground Truth | Azure Machine Learning Data Labeling | 85% | Human-in-the-loop labeling |
| 9.2 | Amazon S3 (Labeled and annotated data) | Azure Data Lake Storage Gen2 | 95% | Training dataset storage |
| 9.3 | Labeling Teams / Partners | Azure ML Labeling (external workforce) | 85% | Partner labeling integration |

---

## Zone 10: Analytics & Visualization

| # | AWS Service | Azure Equivalent | Confidence | Notes |
|---|-------------|------------------|------------|-------|
| 10.1 | Amazon QuickSight | Power BI | 95% | KPI reporting & dashboards |
| 10.2 | AWS AppSync (Scene search interface) | Azure API Management + Cosmos DB | 80% | GraphQL API for search |
| 10.3 | AWS Fargate (Webviz/RVIZ visualization) | Azure Container Apps | 90% | 3D point cloud visualization |

---

## Summary Statistics

| Category | AWS Services | Azure Services | Avg Confidence |
|----------|--------------|----------------|----------------|
| Edge/IoT | 5 | 5 | 91% |
| Ingestion | 3 | 3 | 92% |
| Storage (S3) | 10 | 10 (Blob/ADLS) | 95% |
| Compute (Fargate/Lambda) | 4 | 4 (Container Apps/Functions) | 93% |
| Big Data (EMR) | 4 | 4 (Synapse Spark) | 84% |
| ML/AI | 3 | 3 | 87% |
| Database | 3 | 3 (Cosmos DB) | 88% |
| Analytics | 3 | 3 | 88% |
| **Total** | **35** | **35** | **90%** |

---

## Architecture Notes

### High-Confidence Mappings (≥90%)
- S3 → Azure Blob Storage / Data Lake Storage Gen2
- IoT Core → Azure IoT Hub
- Lambda → Azure Functions
- Fargate → Azure Container Apps
- QuickSight → Power BI
- Direct Connect → ExpressRoute

### Medium-Confidence Mappings (70-89%)
- EMR → Azure Synapse Spark (different cluster management model)
- Neptune → Cosmos DB Gremlin (different graph query syntax)
- SageMaker Ground Truth → Azure ML Data Labeling (fewer labeling task types)
- AppSync → API Management (no native GraphQL, requires custom resolver)
- MWAA → Azure Data Factory (different orchestration paradigm)

### Considerations
1. **MDF4/Rosbag files**: Use Azure Blob Storage with custom parsers; consider Databricks for specialized automotive formats
2. **Point Cloud Visualization**: Webviz/RVIZ can run on Azure Container Apps with GPU support
3. **Data Lineage**: Azure Purview provides integrated lineage; Neptune → Cosmos DB Gremlin requires query migration
4. **OpenScenario Search**: Elasticsearch → Azure AI Search requires index schema migration

---

## Terraform Resource Summary

```hcl
# Core Infrastructure
resource "azurerm_resource_group" "automotive" { ... }
resource "azurerm_storage_account" "datalake" { ... }  # ADLS Gen2

# IoT Layer
resource "azurerm_iothub" "main" { ... }
resource "azurerm_eventhub_namespace" "ingestion" { ... }

# Compute Layer
resource "azurerm_container_app_environment" "main" { ... }
resource "azurerm_container_app" "fargate_equivalent" { ... }  # Multiple apps
resource "azurerm_function_app" "lambda_equivalent" { ... }

# Big Data Layer
resource "azurerm_synapse_workspace" "analytics" { ... }
resource "azurerm_synapse_spark_pool" "processing" { ... }

# Database Layer
resource "azurerm_cosmosdb_account" "main" { ... }  # Multi-API

# AI/ML Layer
resource "azurerm_machine_learning_workspace" "labeling" { ... }
resource "azurerm_cognitive_account" "vision" { ... }

# Analytics Layer
# Power BI is SaaS - no Terraform resource
resource "azurerm_search_service" "opensearch" { ... }
resource "azurerm_api_management" "appsync_equivalent" { ... }
```

---

*Generated by Archmorph - Cloud Architecture Translator*
