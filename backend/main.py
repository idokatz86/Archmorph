"""
Archmorph Backend API
Cloud Architecture Translator to Azure — Full Services Catalog
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
import os
import logging
import uuid

from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import start_scheduler, stop_scheduler, run_update_now, get_update_status, get_last_update
from guided_questions import generate_questions, apply_answers
from diagram_export import generate_diagram
from chatbot import process_chat_message, get_chat_history, clear_chat_session
from vision_analyzer import analyze_image
from usage_metrics import (
    record_event, get_metrics_summary, get_daily_metrics, get_recent_events,
    get_funnel_metrics, record_funnel_step, flush_metrics, ADMIN_SECRET,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle manager."""
    logger.info("Starting Archmorph API v2.1.0 — production mode")
    start_scheduler()
    yield
    logger.info("Shutting down Archmorph API")
    stop_scheduler()
    flush_metrics()


app = FastAPI(
    title="Archmorph API",
    description="AI-powered Cloud Architecture Translator to Azure",
    version="2.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# In-memory session store for analysis results (production would use Redis/DB)
SESSION_STORE: Dict[str, Any] = {}

# In-memory image store keyed by diagram_id → (image_bytes, content_type)
IMAGE_STORE: Dict[str, tuple] = {}


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────
class Project(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None


class ServiceMapping(BaseModel):
    source_service: str
    source_provider: str
    azure_service: str
    confidence: float
    notes: Optional[str] = None


class AnalysisResult(BaseModel):
    diagram_id: str
    services_detected: int
    mappings: List[ServiceMapping]
    warnings: List[str] = []


# ─────────────────────────────────────────────────────────────
# Health Check
# ─────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    update_status = get_update_status()
    return {
        "status": "healthy",
        "version": "2.1.0",
        "environment": ENVIRONMENT,
        "mode": "production",
        "service_catalog": {
            "aws": len(AWS_SERVICES),
            "azure": len(AZURE_SERVICES),
            "gcp": len(GCP_SERVICES),
            "mappings": len(CROSS_CLOUD_MAPPINGS),
        },
        "last_service_update": update_status.get("last_check"),
        "scheduler_running": update_status.get("scheduler_running", False),
    }


# ─────────────────────────────────────────────────────────────
# Projects
# ─────────────────────────────────────────────────────────────
@app.post("/api/projects")
async def create_project(project: Project):
    # TODO: Implement with database
    return {"id": "proj-001", "name": project.name, "status": "created"}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    # TODO: Implement with database
    return {"id": project_id, "name": "Demo Project", "diagrams": []}


# ─────────────────────────────────────────────────────────────
# Diagrams
# ─────────────────────────────────────────────────────────────
@app.post("/api/projects/{project_id}/diagrams")
async def upload_diagram(project_id: str, file: UploadFile = File(...)):
    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(400, f"File type {file.content_type} not supported")

    # Generate unique diagram ID and store image bytes
    diagram_id = f"diag-{uuid.uuid4().hex[:8]}"
    image_bytes = await file.read()
    IMAGE_STORE[diagram_id] = (image_bytes, file.content_type)
    logger.info("Stored image for %s (%d bytes, %s)", diagram_id, len(image_bytes), file.content_type)

    record_event("diagrams_uploaded", {"filename": file.filename})
    record_funnel_step(diagram_id, "upload")
    return {
        "diagram_id": diagram_id,
        "filename": file.filename,
        "size": len(image_bytes),
        "status": "uploaded"
    }


@app.post("/api/diagrams/{diagram_id}/analyze")
async def analyze_diagram(diagram_id: str):
    """
    Analyze an uploaded architecture diagram using GPT-4o vision.
    Detects cloud services and maps them to Azure equivalents using the catalog.
    """
    # Retrieve stored image
    if diagram_id not in IMAGE_STORE:
        raise HTTPException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    image_bytes, content_type = IMAGE_STORE[diagram_id]
    logger.info("Analyzing diagram %s (%d bytes)", diagram_id, len(image_bytes))

    try:
        result = analyze_image(image_bytes, content_type)
    except Exception as exc:
        logger.error("Vision analysis failed for %s: %s", diagram_id, exc)
        raise HTTPException(500, f"Vision analysis failed: {exc}")

    # Inject diagram_id into result
    result["diagram_id"] = diagram_id

    # Store analysis result for guided questions and diagram export
    SESSION_STORE[diagram_id] = result
    record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
    record_funnel_step(diagram_id, "analyze")
    return result


@app.get("/api/diagrams/{diagram_id}/mappings")
async def get_mappings(diagram_id: str):
    # TODO: Implement with database
    return {"diagram_id": diagram_id, "mappings": []}


@app.patch("/api/diagrams/{diagram_id}/mappings/{service}")
async def update_mapping(diagram_id: str, service: str, azure_service: str):
    # TODO: Implement override
    return {"status": "updated", "service": service, "new_mapping": azure_service}


# ─────────────────────────────────────────────────────────────
# Guided Questions
# ─────────────────────────────────────────────────────────────
@app.post("/api/diagrams/{diagram_id}/questions")
async def get_guided_questions(diagram_id: str):
    """Generate guided questions based on detected AWS services."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    detected = [m["source_service"] for m in analysis.get("mappings", [])]
    questions = generate_questions(detected)
    record_event("questions_generated", {"diagram_id": diagram_id, "count": len(questions)})
    record_funnel_step(diagram_id, "questions")
    return {
        "diagram_id": diagram_id,
        "questions": questions,
        "total": len(questions),
    }


@app.post("/api/diagrams/{diagram_id}/apply-answers")
async def apply_guided_answers(diagram_id: str, answers: Dict[str, Any]):
    """Apply user answers to refine the Azure architecture analysis."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    refined = apply_answers(analysis, answers)
    SESSION_STORE[diagram_id] = refined
    record_event("answers_applied", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "answers")
    return refined


# ─────────────────────────────────────────────────────────────
# Diagram Export (Excalidraw / Draw.io / Visio)
# ─────────────────────────────────────────────────────────────
@app.post("/api/diagrams/{diagram_id}/export-diagram")
async def export_architecture_diagram(diagram_id: str, format: str = "excalidraw"):
    """Generate an architecture diagram in Excalidraw, Draw.io, or Visio format."""
    if format not in ("excalidraw", "drawio", "vsdx"):
        raise HTTPException(400, "Format must be 'excalidraw', 'drawio', or 'vsdx'")

    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    try:
        result = generate_diagram(analysis, format)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    record_event(f"exports_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "export")
    return result


# ─────────────────────────────────────────────────────────────
# Service Updater
# ─────────────────────────────────────────────────────────────
@app.get("/api/service-updates/status")
async def service_update_status():
    """Return the service updater scheduler status."""
    return get_update_status()


@app.get("/api/service-updates/last")
async def service_update_last():
    """Return info about the most recent catalog check."""
    return get_last_update()


@app.post("/api/service-updates/run-now")
async def trigger_service_update():
    """Trigger an immediate service catalog update."""
    result = run_update_now()
    return result


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@app.post("/api/diagrams/{diagram_id}/generate")
async def generate_iac(diagram_id: str, format: str = "terraform"):
    if format not in ["terraform", "bicep"]:
        raise HTTPException(400, "Format must be 'terraform' or 'bicep'")
    
    if format == "terraform":
        code = '''# ============================================================
# Archmorph – Azure Translation of AWS Automotive / IoT Pipeline
# Generated from diagram analysis (33 service mappings, 10 zones)
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.85"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  backend "azurerm" {
    resource_group_name  = "archmorph-tfstate-rg"
    storage_account_name = "archmorphtfstate"
    container_name       = "tfstate"
    key                  = "automotive-pipeline.tfstate"
  }
}

provider "azurerm" {
  features {}
}

# Generate a strong random password for SQL admin
resource "random_password" "sql_admin" {
  length           = 24
  special          = true
  override_special = "!@#$%&*"
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
}

locals {
  project  = "automotive-iot"
  env      = "dev"
  location = "westeurope"
  tags = {
    Project     = "Automotive-IoT-Pipeline"
    ManagedBy   = "Archmorph"
    Environment = local.env
    Source      = "AWS-Migration"
  }
}

# ── Resource Group ──────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = "rg-${local.project}-${local.env}"
  location = local.location
  tags     = local.tags
}

# ════════════════════════════════════════════════════════════
# ZONE 1 & 2: INGEST (Direct Connect → ExpressRoute,
#   Outposts → Stack Edge, IoT Greengrass → IoT Edge,
#   IoT Core → IoT Hub, Kinesis Firehose → Event Hubs)
# ════════════════════════════════════════════════════════════

# ExpressRoute Circuit (replaces AWS Direct Connect)
resource "azurerm_express_route_circuit" "ingest" {
  name                  = "erc-${local.project}-ingest"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  service_provider_name = "Equinix"
  peering_location      = "Amsterdam"
  bandwidth_in_mbps     = 1000
  sku {
    tier   = "Standard"
    family = "MeteredData"
  }
  tags = local.tags
}

# IoT Hub (replaces AWS IoT Core – Zone 2 OTA Ingest)
resource "azurerm_iothub" "main" {
  name                = "iot-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku {
    name     = "S1"
    capacity = 2
  }
  tags = local.tags
}

# Event Hubs Namespace (replaces Amazon Kinesis Data Firehose)
resource "azurerm_eventhub_namespace" "ingest" {
  name                = "evhns-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Standard"
  capacity            = 2
  tags                = local.tags
}

resource "azurerm_eventhub" "raw_telemetry" {
  name              = "raw-vehicle-telemetry"
  namespace_id      = azurerm_eventhub_namespace.ingest.id
  partition_count   = 8
  message_retention = 7
}

# ════════════════════════════════════════════════════════════
# ZONE 3: DATA STORAGE (S3 × 10 → Blob + ADLS Gen2)
# ════════════════════════════════════════════════════════════

# Storage Account – Raw / Images / Labeled data (Blob)
resource "azurerm_storage_account" "raw" {
  name                     = "st${local.project}raw${local.env}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  min_tls_version          = "TLS1_2"
  tags                     = local.tags
}

resource "azurerm_storage_container" "raw_drive" {
  name                 = "raw-drive-data"
  storage_account_id   = azurerm_storage_account.raw.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "high_quality" {
  name                 = "high-quality-data"
  storage_account_id   = azurerm_storage_account.raw.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "low_quality" {
  name                 = "low-quality-quarantine"
  storage_account_id   = azurerm_storage_account.raw.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "raw_images" {
  name                 = "raw-images"
  storage_account_id   = azurerm_storage_account.raw.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "anonymized_images" {
  name                 = "anonymized-images"
  storage_account_id   = azurerm_storage_account.raw.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "labeled_data" {
  name                 = "labeled-annotated"
  storage_account_id   = azurerm_storage_account.raw.id
  container_access_type = "private"
}

# ADLS Gen2 – Parquet / Analytics data (replaces S3 Parquet stores)
resource "azurerm_storage_account" "datalake" {
  name                     = "st${local.project}lake${local.env}"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  is_hns_enabled           = true  # Hierarchical namespace for ADLS Gen2
  min_tls_version          = "TLS1_2"
  tags                     = local.tags
}

resource "azurerm_storage_data_lake_gen2_filesystem" "parsed" {
  name               = "parsed-parquet"
  storage_account_id = azurerm_storage_account.datalake.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "enriched" {
  name               = "enriched-parquet"
  storage_account_id = azurerm_storage_account.datalake.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "synced" {
  name               = "synchronized-parquet"
  storage_account_id = azurerm_storage_account.datalake.id
}

resource "azurerm_storage_data_lake_gen2_filesystem" "scene_labels" {
  name               = "scene-labels-parquet"
  storage_account_id = azurerm_storage_account.datalake.id
}

# ════════════════════════════════════════════════════════════
# ZONE 4: ORCHESTRATION (MWAA → Azure Data Factory)
# ════════════════════════════════════════════════════════════

resource "azurerm_data_factory" "main" {
  name                = "adf-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

# ════════════════════════════════════════════════════════════
# ZONE 5 & 6: PROCESSING (EMR × 4 → Synapse Spark,
#   Fargate → ACI / Container Apps)
# ════════════════════════════════════════════════════════════

# Synapse Workspace (replaces Amazon EMR × 4 instances)
resource "azurerm_synapse_workspace" "main" {
  name                                 = "syn-${local.project}-${local.env}"
  resource_group_name                  = azurerm_resource_group.main.name
  location                             = azurerm_resource_group.main.location
  storage_data_lake_gen2_filesystem_id = azurerm_storage_data_lake_gen2_filesystem.parsed.id
  sql_administrator_login              = "sqladmin"
  sql_administrator_login_password     = random_password.sql_admin.result
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

resource "azurerm_synapse_spark_pool" "processing" {
  name                 = "sparkpool"
  synapse_workspace_id = azurerm_synapse_workspace.main.id
  node_size_family     = "MemoryOptimized"
  node_size            = "Small"
  node_count           = 3
  auto_pause {
    delay_in_minutes = 15
  }
  auto_scale {
    min_node_count = 3
    max_node_count = 10
  }
}

# Container App Environment (replaces Fargate for containers)
resource "azurerm_container_app_environment" "main" {
  name                = "cae-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

# ACI – Topic Extraction (Fargate zone 5)
resource "azurerm_container_group" "topic_extract" {
  name                = "aci-topic-extract"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  restart_policy      = "OnFailure"
  container {
    name   = "topic-extractor"
    image  = "automotive-pipeline/topic-extractor:latest"
    cpu    = 2
    memory = 4
    ports { port = 8080; protocol = "TCP" }
  }
  tags = local.tags
}

# ACI – Image Extraction (Fargate zone 8)
resource "azurerm_container_group" "image_extract" {
  name                = "aci-image-extract"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  restart_policy      = "OnFailure"
  container {
    name   = "image-extractor"
    image  = "automotive-pipeline/image-extractor:latest"
    cpu    = 4
    memory = 8
    ports { port = 8080; protocol = "TCP" }
  }
  tags = local.tags
}

# ════════════════════════════════════════════════════════════
# ZONE 7: DATA CATALOG (Glue → Purview, Neptune → Cosmos
#   Gremlin, DynamoDB → Cosmos NoSQL, ES → AI Search)
# ════════════════════════════════════════════════════════════

# Microsoft Purview (replaces AWS Glue Data Catalog)
resource "azurerm_purview_account" "main" {
  name                = "pv-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

# Cosmos DB – Gremlin API (replaces Amazon Neptune for lineage)
resource "azurerm_cosmosdb_account" "graph" {
  name                = "cosmos-graph-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  capabilities {
    name = "EnableGremlin"
  }
  consistency_policy {
    consistency_level = "Session"
  }
  geo_location {
    location          = azurerm_resource_group.main.location
    failover_priority = 0
  }
  tags = local.tags
}

# Cosmos DB – NoSQL API (replaces Amazon DynamoDB for metadata)
resource "azurerm_cosmosdb_account" "metadata" {
  name                = "cosmos-meta-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  consistency_policy {
    consistency_level = "Session"
  }
  geo_location {
    location          = azurerm_resource_group.main.location
    failover_priority = 0
  }
  tags = local.tags
}

resource "azurerm_cosmosdb_sql_database" "drive_metadata" {
  name                = "drive-metadata"
  resource_group_name = azurerm_cosmosdb_account.metadata.resource_group_name
  account_name        = azurerm_cosmosdb_account.metadata.name
  throughput          = 400
}

# Azure AI Search (replaces Amazon Elasticsearch / OpenSearch)
resource "azurerm_search_service" "main" {
  name                = "srch-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "standard"
  replica_count       = 1
  partition_count     = 1
  tags                = local.tags
}

# ════════════════════════════════════════════════════════════
# ZONE 8: ANONYMIZATION (Lambda → Functions, Rekognition →
#   AI Vision)
# ════════════════════════════════════════════════════════════

# Azure Functions (replaces AWS Lambda – blur faces/text)
resource "azurerm_service_plan" "functions" {
  name                = "asp-fn-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "Y1"
  tags                = local.tags
}

resource "azurerm_linux_function_app" "anonymizer" {
  name                       = "fn-anonymizer-${local.project}-${local.env}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  service_plan_id            = azurerm_service_plan.functions.id
  storage_account_name       = azurerm_storage_account.raw.name
  storage_account_access_key = azurerm_storage_account.raw.primary_access_key
  site_config {
    application_stack {
      python_version = "3.11"
    }
  }
  tags = local.tags
}

# Store SQL admin password in Key Vault
resource "azurerm_key_vault_secret" "sql_password" {
  name         = "synapse-sql-admin-password"
  value        = random_password.sql_admin.result
  key_vault_id = azurerm_key_vault.main.id
}

# Azure AI Services (replaces Amazon Rekognition)
resource "azurerm_cognitive_account" "vision" {
  name                = "cog-vision-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  kind                = "ComputerVision"
  sku_name            = "S1"
  tags                = local.tags
}

# ════════════════════════════════════════════════════════════
# ZONE 9: LABELING (SageMaker Ground Truth → AML Data Labeling)
# ════════════════════════════════════════════════════════════

resource "azurerm_machine_learning_workspace" "main" {
  name                    = "mlw-${local.project}-${local.env}"
  resource_group_name     = azurerm_resource_group.main.name
  location                = azurerm_resource_group.main.location
  application_insights_id = azurerm_application_insights.main.id
  key_vault_id            = azurerm_key_vault.main.id
  storage_account_id      = azurerm_storage_account.raw.id
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

resource "azurerm_key_vault" "main" {
  name                = "kv-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  application_type    = "web"
  tags                = local.tags
}

data "azurerm_client_config" "current" {}

# ════════════════════════════════════════════════════════════
# ZONE 10: ANALYTICS & VISUALIZATION (QuickSight → Power BI
#   Embedded, AppSync → APIM, Fargate Webviz → Container Apps)
# ════════════════════════════════════════════════════════════

# API Management (replaces AWS AppSync)
resource "azurerm_api_management" "main" {
  name                = "apim-${local.project}-${local.env}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  publisher_name      = "Automotive IoT Team"
  publisher_email     = "team@automotive-iot.dev"
  sku_name            = "Consumption_0"
  tags                = local.tags
}

# Container App – Webviz / RVIZ Visualization
resource "azurerm_container_app" "webviz" {
  name                         = "ca-webviz"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  template {
    container {
      name   = "webviz"
      image  = "automotive-pipeline/webviz:latest"
      cpu    = 1
      memory = "2Gi"
    }
  }
  ingress {
    external_enabled = true
    target_port      = 8080
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# ════════════════════════════════════════════════════════════
# OUTPUTS
# ════════════════════════════════════════════════════════════

output "iot_hub_hostname" {
  value = azurerm_iothub.main.hostname
}

output "synapse_workspace_url" {
  value = "https://web.azuresynapse.net?workspace=/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${azurerm_resource_group.main.name}/providers/Microsoft.Synapse/workspaces/${azurerm_synapse_workspace.main.name}"
}

output "datalake_endpoint" {
  value = azurerm_storage_account.datalake.primary_dfs_endpoint
}

output "purview_endpoint" {
  value = "https://${azurerm_purview_account.main.name}.purview.azure.com"
}

output "ai_search_endpoint" {
  value = "https://${azurerm_search_service.main.name}.search.windows.net"
}

output "webviz_url" {
  value = "https://${azurerm_container_app.webviz.ingress[0].fqdn}"
}
'''
    else:
        code = '''// ============================================================
// Archmorph – Azure Translation of AWS Automotive / IoT Pipeline
// Generated from diagram analysis (33 service mappings, 10 zones)
// ============================================================

targetScope = 'subscription'

@description('Environment name')
param env string = 'dev'

@description('Primary Azure region')
param location string = 'westeurope'

@secure()
@description('SQL Administrator password for Synapse workspace')
param sqlAdminPassword string

var project = 'automotive-iot'
var tags = {
  Project: 'Automotive-IoT-Pipeline'
  ManagedBy: 'Archmorph'
  Environment: env
  Source: 'AWS-Migration'
}

// ── Resource Group ─────────────────────────────────────────
resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: 'rg-${project}-${env}'
  location: location
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 1 & 2: INGEST
// ══════════════════════════════════════════════════════════

module ingest 'modules/ingest.bicep' = {
  name: 'ingest-deploy'
  scope: rg
  params: {
    location: location
    project: project
    env: env
    tags: tags
  }
}

// ── IoT Hub (replaces AWS IoT Core) ──
resource iotHub 'Microsoft.Devices/IotHubs@2023-06-30' = {
  name: 'iot-${project}-${env}'
  scope: rg
  location: location
  sku: {  name: 'S1'; capacity: 2 }
  tags: tags
}

// ── Event Hubs (replaces Kinesis Data Firehose) ──
resource evhns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: 'evhns-${project}-${env}'
  scope: rg
  location: location
  sku: { name: 'Standard'; tier: 'Standard'; capacity: 2 }
  tags: tags
}

resource evhRawTelemetry 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: evhns
  name: 'raw-vehicle-telemetry'
  properties: { partitionCount: 8; messageRetentionInDays: 7 }
}

// ══════════════════════════════════════════════════════════
// ZONE 3: STORAGE – Blob + ADLS Gen2
// ══════════════════════════════════════════════════════════

// Raw / Images / Labeled Data (Blob Storage)
resource stRaw 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${project}raw${env}'
  scope: rg
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: { minimumTlsVersion: 'TLS1_2' }
  tags: tags
}

// ADLS Gen2 for Parquet / Analytics workloads
resource stLake 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'st${project}lake${env}'
  scope: rg
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: {
    isHnsEnabled: true   // Hierarchical namespace
    minimumTlsVersion: 'TLS1_2'
  }
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 4: ORCHESTRATION – Azure Data Factory (replaces MWAA)
// ══════════════════════════════════════════════════════════

resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: 'adf-${project}-${env}'
  scope: rg
  location: location
  identity: { type: 'SystemAssigned' }
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 5 & 6: PROCESSING – Synapse Spark (replaces EMR × 4)
// ══════════════════════════════════════════════════════════

resource synapse 'Microsoft.Synapse/workspaces@2021-06-01' = {
  name: 'syn-${project}-${env}'
  scope: rg
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    defaultDataLakeStorage: {
      accountUrl: stLake.properties.primaryEndpoints.dfs
      filesystem: 'parsed-parquet'
    }
    sqlAdministratorLogin: 'sqladmin'
    sqlAdministratorLoginPassword: sqlAdminPassword
  }
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 7: DATA CATALOG – Purview, Cosmos DB, AI Search
// ══════════════════════════════════════════════════════════

// Purview (replaces Glue Data Catalog)
resource purview 'Microsoft.Purview/accounts@2021-12-01' = {
  name: 'pv-${project}-${env}'
  scope: rg
  location: location
  identity: { type: 'SystemAssigned' }
  tags: tags
}

// Cosmos DB Gremlin (replaces Neptune – data lineage)
resource cosmosGraph 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: 'cosmos-graph-${project}-${env}'
  scope: rg
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [{ name: 'EnableGremlin' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location; failoverPriority: 0 }]
  }
  tags: tags
}

// Cosmos DB NoSQL (replaces DynamoDB – drive metadata)
resource cosmosMeta 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: 'cosmos-meta-${project}-${env}'
  scope: rg
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location; failoverPriority: 0 }]
  }
  tags: tags
}

// Azure AI Search (replaces Elasticsearch / OpenSearch)
resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: 'srch-${project}-${env}'
  scope: rg
  location: location
  sku: { name: 'standard' }
  properties: { replicaCount: 1; partitionCount: 1 }
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 8: ANONYMIZATION – Functions + AI Vision
// ══════════════════════════════════════════════════════════

resource cogVision 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: 'cog-vision-${project}-${env}'
  scope: rg
  location: location
  kind: 'ComputerVision'
  sku: { name: 'S1' }
  properties: {}
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 9: LABELING – Azure ML Workspace
// ══════════════════════════════════════════════════════════

resource mlw 'Microsoft.MachineLearningServices/workspaces@2023-10-01' = {
  name: 'mlw-${project}-${env}'
  scope: rg
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    storageAccount: stRaw.id
    keyVault: kv.id
    applicationInsights: appInsights.id
  }
  tags: tags
}

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${project}-${env}'
  scope: rg
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A'; name: 'standard' }
    accessPolicies: []
  }
  tags: tags
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${project}-${env}'
  scope: rg
  location: location
  kind: 'web'
  properties: { Application_Type: 'web' }
  tags: tags
}

// ══════════════════════════════════════════════════════════
// ZONE 10: ANALYTICS & VISUALIZATION
// ══════════════════════════════════════════════════════════

resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: 'apim-${project}-${env}'
  scope: rg
  location: location
  sku: { name: 'Consumption'; capacity: 0 }
  properties: {
    publisherEmail: 'team@automotive-iot.dev'
    publisherName: 'Automotive IoT Team'
  }
  tags: tags
}

// ── Outputs ────────────────────────────────────────────────
output iotHubHostname string = iotHub.properties.hostName
output datalakeEndpoint string = stLake.properties.primaryEndpoints.dfs
output purviewEndpoint string = 'https://${purview.name}.purview.azure.com'
output searchEndpoint string = 'https://${search.name}.search.windows.net'
'''
    
    record_event(f"iac_generated_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "iac_generate")
    return {"diagram_id": diagram_id, "format": format, "code": code}


@app.get("/api/diagrams/{diagram_id}/export")
async def export_iac(diagram_id: str, format: str = "terraform"):
    # TODO: Return file download
    return {"diagram_id": diagram_id, "download_url": f"/downloads/{diagram_id}.tf"}


# ─────────────────────────────────────────────────────────────
# Cost Estimation
# ─────────────────────────────────────────────────────────────
@app.get("/api/diagrams/{diagram_id}/cost-estimate")
async def estimate_cost(diagram_id: str):
    record_event("cost_estimates", {"diagram_id": diagram_id})

    session = SESSION_STORE.get(diagram_id, {})
    # The analysis result is stored directly in SESSION_STORE (not nested under "analysis")
    mappings = session.get("mappings", [])
    iac_params = session.get("iac_parameters", {})

    # Get region from guided-question answers or iac_parameters
    region = iac_params.get("deploy_region", "westeurope")
    sku_strategy = iac_params.get("sku_strategy", "Balanced")

    # If we have real mappings, compute dynamic pricing
    if mappings:
        from services.azure_pricing import estimate_services_cost
        result = estimate_services_cost(mappings, region=region, sku_strategy=sku_strategy)
        result["diagram_id"] = diagram_id
        return result

    # Fallback: return structure-compatible empty estimate
    return {
        "diagram_id": diagram_id,
        "total_monthly_estimate": {
            "low": 0,
            "high": 0,
        },
        "currency": "USD",
        "region": "West Europe",
        "arm_region": region,
        "services": [],
        "service_count": 0,
        "pricing_source": "no analysis available",
    }


# ─────────────────────────────────────────────────────────────
# Cloud Services Catalog
# ─────────────────────────────────────────────────────────────
@app.get("/api/services")
async def list_all_services(
    response: Response,
    provider: Optional[str] = Query(None, description="Filter by provider: aws, azure, gcp"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search services by name/description"),
):
    """List cloud services from all providers, with optional filters."""
    response.headers["Cache-Control"] = "public, max-age=300"
    results = []
    
    if provider is None or provider == "aws":
        for s in AWS_SERVICES:
            results.append({**s, "provider": "aws"})
    if provider is None or provider == "azure":
        for s in AZURE_SERVICES:
            results.append({**s, "provider": "azure"})
    if provider is None or provider == "gcp":
        for s in GCP_SERVICES:
            results.append({**s, "provider": "gcp"})

    if category:
        cat_lower = category.lower()
        results = [s for s in results if s["category"].lower() == cat_lower]

    if search:
        q = search.lower()
        results = [
            s for s in results
            if q in s["name"].lower()
            or q in s.get("fullName", "").lower()
            or q in s.get("description", "").lower()
        ]

    return {
        "total": len(results),
        "services": results,
    }


@app.get("/api/services/providers")
async def list_providers(response: Response):
    """List available cloud providers and their service counts."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "providers": [
            {"id": "aws", "name": "Amazon Web Services", "serviceCount": len(AWS_SERVICES), "color": "#FF9900"},
            {"id": "azure", "name": "Microsoft Azure", "serviceCount": len(AZURE_SERVICES), "color": "#0078D4"},
            {"id": "gcp", "name": "Google Cloud Platform", "serviceCount": len(GCP_SERVICES), "color": "#4285F4"},
        ]
    }


@app.get("/api/services/categories")
async def list_categories(response: Response):
    """List all service categories with counts per provider."""
    response.headers["Cache-Control"] = "public, max-age=300"
    cats = {}
    for s in AWS_SERVICES:
        cats.setdefault(s["category"], {"aws": 0, "azure": 0, "gcp": 0})
        cats[s["category"]]["aws"] += 1
    for s in AZURE_SERVICES:
        cats.setdefault(s["category"], {"aws": 0, "azure": 0, "gcp": 0})
        cats[s["category"]]["azure"] += 1
    for s in GCP_SERVICES:
        cats.setdefault(s["category"], {"aws": 0, "azure": 0, "gcp": 0})
        cats[s["category"]]["gcp"] += 1

    return {
        "categories": [
            {"name": cat, "counts": counts}
            for cat, counts in sorted(cats.items())
        ]
    }


@app.get("/api/services/mappings")
async def list_mappings(
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search mappings"),
    min_confidence: Optional[float] = Query(None, description="Minimum confidence (0-1)"),
):
    """List cross-cloud service mappings (AWS ↔ Azure ↔ GCP)."""
    results = CROSS_CLOUD_MAPPINGS

    if category:
        cat_lower = category.lower()
        results = [m for m in results if m["category"].lower() == cat_lower]

    if min_confidence is not None:
        results = [m for m in results if m["confidence"] >= min_confidence]

    if search:
        q = search.lower()
        results = [
            m for m in results
            if q in m["aws"].lower()
            or q in m["azure"].lower()
            or q in m["gcp"].lower()
            or q in m.get("notes", "").lower()
        ]

    return {
        "total": len(results),
        "mappings": results,
    }


@app.get("/api/services/{provider}/{service_id}")
async def get_service(provider: str, service_id: str):
    """Get a specific service by provider and ID."""
    catalog = {"aws": AWS_SERVICES, "azure": AZURE_SERVICES, "gcp": GCP_SERVICES}
    if provider not in catalog:
        raise HTTPException(400, f"Invalid provider: {provider}. Use aws, azure, or gcp.")

    service = next((s for s in catalog[provider] if s["id"] == service_id), None)
    if not service:
        raise HTTPException(404, f"Service '{service_id}' not found for provider '{provider}'")

    # Find cross-cloud equivalents
    equivalents = []
    name = service["name"]
    for m in CROSS_CLOUD_MAPPINGS:
        matched = False
        if provider == "aws" and m["aws"] == name:
            matched = True
        elif provider == "azure" and m["azure"] == name:
            matched = True
        elif provider == "gcp" and m["gcp"] == name:
            matched = True
        if matched:
            equivalents.append(m)

    return {
        **service,
        "provider": provider,
        "equivalents": equivalents,
    }


@app.get("/api/services/stats")
async def get_stats(response: Response):
    """Get service catalog statistics."""
    response.headers["Cache-Control"] = "public, max-age=300"
    all_cats = set()
    for s in AWS_SERVICES + AZURE_SERVICES + GCP_SERVICES:
        all_cats.add(s["category"])

    return {
        "totalServices": len(AWS_SERVICES) + len(AZURE_SERVICES) + len(GCP_SERVICES),
        "totalMappings": len(CROSS_CLOUD_MAPPINGS),
        "providers": {
            "aws": len(AWS_SERVICES),
            "azure": len(AZURE_SERVICES),
            "gcp": len(GCP_SERVICES),
        },
        "categories": len(all_cats),
        "avgConfidence": round(
            sum(m["confidence"] for m in CROSS_CLOUD_MAPPINGS) / len(CROSS_CLOUD_MAPPINGS), 2
        ) if CROSS_CLOUD_MAPPINGS else 0,
    }


# ─────────────────────────────────────────────────────────────
# Chatbot — AI assistant with GitHub issue creation
# ─────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = "default"


@app.post("/api/chat")
async def chat(msg: ChatMessage):
    """Process a chat message and return bot response. Can create GitHub issues."""
    record_event("chat_messages", {"session_id": msg.session_id})
    result = process_chat_message(msg.session_id, msg.message)
    if result.get("action") == "issue_created":
        record_event("github_issues_created", result.get("data", {}))
    return result


@app.get("/api/chat/history/{session_id}")
async def chat_history(session_id: str):
    """Get chat history for a session."""
    return {"session_id": session_id, "messages": get_chat_history(session_id)}


@app.delete("/api/chat/{session_id}")
async def chat_clear(session_id: str):
    """Clear a chat session."""
    cleared = clear_chat_session(session_id)
    return {"cleared": cleared}


# ─────────────────────────────────────────────────────────────
# Admin Metrics (protected by secret key)
# ─────────────────────────────────────────────────────────────
def _check_admin(key: str):
    if key != ADMIN_SECRET:
        raise HTTPException(403, "Invalid admin key")


@app.get("/api/admin/metrics")
async def admin_metrics_summary(key: str = Query(...)):
    """Return aggregate usage metrics (admin only)."""
    _check_admin(key)
    return get_metrics_summary()


@app.get("/api/admin/metrics/funnel")
async def admin_funnel(key: str = Query(...)):
    """Return conversion funnel data (admin only)."""
    _check_admin(key)
    return get_funnel_metrics()


@app.get("/api/admin/metrics/daily")
async def admin_metrics_daily(key: str = Query(...), days: int = Query(30, ge=1, le=365)):
    """Return daily metrics for the last N days (admin only)."""
    _check_admin(key)
    return {"days": days, "data": get_daily_metrics(days)}


@app.get("/api/admin/metrics/recent")
async def admin_metrics_recent(key: str = Query(...), limit: int = Query(50, ge=1, le=200)):
    """Return the most recent usage events (admin only)."""
    _check_admin(key)
    return {"events": get_recent_events(limit)}


# ─────────────────────────────────────────────────────────────
# Contact
# ─────────────────────────────────────────────────────────────
@app.get("/api/contact")
async def contact_info():
    """Return contact information."""
    return {
        "email": "send2katz@gmail.com",
        "name": "Ido Katz",
        "project": "Archmorph",
        "github": "https://github.com/idokatz86/Archmorph",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
