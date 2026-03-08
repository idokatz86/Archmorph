from error_envelope import ArchmorphException
"""
Cloud Services Catalog & Service Updater routes.
"""

from fastapi import APIRouter, HTTPException, Query, Response, Depends
from typing import Optional

from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import get_update_status, get_last_update, run_update_now
from routers.shared import verify_api_key

router = APIRouter()


@router.get("/api/services")
async def list_all_services(
    response: Response,
    provider: Optional[str] = Query(None, description="Filter by provider: aws, azure, gcp"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search services by name/description"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=1000, description="Items per page (max 1000)"),
):
    """List cloud services from all providers, with optional filters and pagination."""
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

    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    paginated = results[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "services": paginated,
    }


@router.get("/api/services/providers")
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


@router.get("/api/services/categories")
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


@router.get("/api/services/mappings")
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


@router.get("/api/services/{provider}/{service_id}")
async def get_service(provider: str, service_id: str):
    """Get a specific service by provider and ID."""
    catalog = {"aws": AWS_SERVICES, "azure": AZURE_SERVICES, "gcp": GCP_SERVICES}
    if provider not in catalog:
        raise ArchmorphException(400, f"Invalid provider: {provider}. Use aws, azure, or gcp.")

    service = next((s for s in catalog[provider] if s["id"] == service_id), None)
    if not service:
        raise ArchmorphException(404, f"Service '{service_id}' not found for provider '{provider}'")

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


@router.get("/api/services/stats")
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
# Service Updater
# ─────────────────────────────────────────────────────────────
@router.get("/api/service-updates/status")
async def service_update_status():
    """Return the service updater scheduler status."""
    return get_update_status()


@router.get("/api/service-updates/last")
async def service_update_last():
    """Return info about the most recent catalog check."""
    return get_last_update()


@router.post("/api/service-updates/run-now")
async def trigger_service_update(_auth=Depends(verify_api_key)):
    """Trigger an immediate service catalog update (requires API key)."""
    result = run_update_now()
    return result
