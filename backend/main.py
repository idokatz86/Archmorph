"""
Archmorph Backend API
Cloud Architecture Translator to Azure — Full Services Catalog
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os

from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS

app = FastAPI(
    title="Archmorph API",
    description="AI-powered Cloud Architecture Translator to Azure",
    version="0.1.0"
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
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"


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
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": ENVIRONMENT,
        "demo_mode": DEMO_MODE
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
    
    # TODO: Save to Azure Blob Storage
    return {
        "diagram_id": "diag-001",
        "filename": file.filename,
        "size": 0,
        "status": "uploaded"
    }


@app.post("/api/diagrams/{diagram_id}/analyze")
async def analyze_diagram(diagram_id: str):
    # TODO: Implement with Azure OpenAI GPT-4 Vision
    # Demo response
    return AnalysisResult(
        diagram_id=diagram_id,
        services_detected=5,
        mappings=[
            ServiceMapping(
                source_service="EC2",
                source_provider="aws",
                azure_service="Virtual Machines",
                confidence=0.95,
                notes="Direct mapping"
            ),
            ServiceMapping(
                source_service="S3",
                source_provider="aws",
                azure_service="Blob Storage",
                confidence=0.95,
                notes="Direct mapping"
            ),
            ServiceMapping(
                source_service="Lambda",
                source_provider="aws",
                azure_service="Azure Functions",
                confidence=0.90,
                notes="Consumption model"
            ),
            ServiceMapping(
                source_service="RDS PostgreSQL",
                source_provider="aws",
                azure_service="Azure Database for PostgreSQL",
                confidence=0.90,
                notes="Flexible Server recommended"
            ),
            ServiceMapping(
                source_service="API Gateway",
                source_provider="aws",
                azure_service="API Management",
                confidence=0.85,
                notes="Feature parity may vary"
            ),
        ],
        warnings=["Demo mode - Analysis is simulated"]
    )


@app.get("/api/diagrams/{diagram_id}/mappings")
async def get_mappings(diagram_id: str):
    # TODO: Implement with database
    return {"diagram_id": diagram_id, "mappings": []}


@app.patch("/api/diagrams/{diagram_id}/mappings/{service}")
async def update_mapping(diagram_id: str, service: str, azure_service: str):
    # TODO: Implement override
    return {"status": "updated", "service": service, "new_mapping": azure_service}


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@app.post("/api/diagrams/{diagram_id}/generate")
async def generate_iac(diagram_id: str, format: str = "terraform"):
    if format not in ["terraform", "bicep"]:
        raise HTTPException(400, "Format must be 'terraform' or 'bicep'")
    
    # TODO: Implement IaC generation
    if format == "terraform":
        code = '''# Generated by Archmorph
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "main" {
  name     = "archmorph-generated-rg"
  location = "westeurope"
}

# TODO: Add translated resources
'''
    else:
        code = '''// Generated by Archmorph
targetScope = 'subscription'

resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: 'archmorph-generated-rg'
  location: 'westeurope'
}

// TODO: Add translated resources
'''
    
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
    # TODO: Implement with Azure Retail Prices API
    return {
        "diagram_id": diagram_id,
        "monthly_estimate": {
            "low": 180,
            "medium": 350,
            "high": 600
        },
        "currency": "USD",
        "services": [
            {"service": "Virtual Machines", "estimate": 120},
            {"service": "Blob Storage", "estimate": 25},
            {"service": "Azure Functions", "estimate": 50},
            {"service": "PostgreSQL Flexible", "estimate": 100},
            {"service": "API Management", "estimate": 55},
        ]
    }


# ─────────────────────────────────────────────────────────────
# Cloud Services Catalog
# ─────────────────────────────────────────────────────────────
@app.get("/api/services")
async def list_all_services(
    provider: Optional[str] = Query(None, description="Filter by provider: aws, azure, gcp"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search services by name/description"),
):
    """List cloud services from all providers, with optional filters."""
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
async def list_providers():
    """List available cloud providers and their service counts."""
    return {
        "providers": [
            {"id": "aws", "name": "Amazon Web Services", "serviceCount": len(AWS_SERVICES), "color": "#FF9900"},
            {"id": "azure", "name": "Microsoft Azure", "serviceCount": len(AZURE_SERVICES), "color": "#0078D4"},
            {"id": "gcp", "name": "Google Cloud Platform", "serviceCount": len(GCP_SERVICES), "color": "#4285F4"},
        ]
    }


@app.get("/api/services/categories")
async def list_categories():
    """List all service categories with counts per provider."""
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
async def get_stats():
    """Get service catalog statistics."""
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
