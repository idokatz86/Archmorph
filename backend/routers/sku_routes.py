"""
SKU Translation Routes — Instance-level cross-cloud SKU translation with parity scoring.
"""

from fastapi import APIRouter, Query, Response
from typing import List, Optional

from sku_translator import get_sku_translator, SKUTranslation
from error_envelope import ArchmorphException

router = APIRouter()


def _translation_to_dict(t: SKUTranslation) -> dict:
    """Serialize a SKUTranslation into a JSON-safe dict."""
    return {
        "source": {
            "sku": t.source.sku,
            "provider": t.source.provider,
            "family": t.source.family,
            "vcpus": t.source.vcpus,
            "ram_gb": t.source.ram_gb,
            "network_gbps": t.source.network_gbps,
            "storage_type": t.source.storage_type,
            "burstable": t.source.burstable,
            "gpu": t.source.gpu,
            "gpu_model": t.source.gpu_model,
        },
        "target": {
            "sku": t.target.sku,
            "provider": t.target.provider,
            "family": t.target.family,
            "vcpus": t.target.vcpus,
            "ram_gb": t.target.ram_gb,
            "network_gbps": t.target.network_gbps,
            "storage_type": t.target.storage_type,
            "burstable": t.target.burstable,
            "gpu": t.target.gpu,
            "gpu_model": t.target.gpu_model,
        },
        "parity": {
            "vcpu_score": t.parity.vcpu_score,
            "ram_score": t.parity.ram_score,
            "network_score": t.parity.network_score,
            "storage_score": t.parity.storage_score,
            "overall": t.parity.overall,
            "details": t.parity.details,
        },
        "alternatives": [
            {
                "sku": alt.sku,
                "family": alt.family,
                "vcpus": alt.vcpus,
                "ram_gb": alt.ram_gb,
                "parity_score": parity.overall,
            }
            for alt, parity in t.alternatives
        ],
    }


# ─────────────────────────────────────────────────────────────
# GET /api/sku/translate — Single SKU translation
# ─────────────────────────────────────────────────────────────
@router.get("/api/sku/translate")
async def translate_sku(
    response: Response,
    source: str = Query(..., description="Source instance type (e.g. m5.xlarge, n2-standard-4)"),
    provider: str = Query(..., description="Source cloud provider: aws or gcp"),
):
    """Translate a single compute instance SKU to its Azure equivalent with parity scoring."""
    response.headers["Cache-Control"] = "public, max-age=300"
    engine = get_sku_translator()

    # Try exact translation first, then best-fit
    result = engine.translate(source, provider)
    if result is None:
        result = engine.best_fit(source, provider)

    if result is None:
        raise ArchmorphException(
            404,
            f"No Azure equivalent found for '{source}' (provider={provider}). "
            f"Use GET /api/sku/families to see supported instance types.",
        )

    return _translation_to_dict(result)


# ─────────────────────────────────────────────────────────────
# POST /api/sku/translate/batch — Batch SKU translation
# ─────────────────────────────────────────────────────────────
from strict_models import StrictBaseModel


class BatchSKURequest(StrictBaseModel):
    """Batch translation request body."""
    skus: List[str]
    provider: str = "aws"


@router.post("/api/sku/translate/batch")
async def translate_sku_batch(body: BatchSKURequest, response: Response):
    """Translate multiple compute instance SKUs to Azure equivalents."""
    response.headers["Cache-Control"] = "public, max-age=300"
    engine = get_sku_translator()
    results = []

    for sku in body.skus:
        result = engine.translate(sku, body.provider)
        if result is None:
            result = engine.best_fit(sku, body.provider)

        if result is not None:
            results.append(_translation_to_dict(result))
        else:
            results.append({
                "source": {"sku": sku, "provider": body.provider},
                "target": None,
                "parity": None,
                "alternatives": [],
                "error": f"No Azure equivalent found for '{sku}'",
            })

    translated = sum(1 for r in results if r.get("target") is not None)
    return {
        "total": len(results),
        "translated": translated,
        "failed": len(results) - translated,
        "results": results,
    }


# ─────────────────────────────────────────────────────────────
# GET /api/sku/families — Instance family cross-cloud mapping
# ─────────────────────────────────────────────────────────────
@router.get("/api/sku/families")
async def list_families(response: Response):
    """List all compute instance families with cross-cloud series mapping."""
    response.headers["Cache-Control"] = "public, max-age=600"
    engine = get_sku_translator()
    return {"families": engine.list_families()}


# ─────────────────────────────────────────────────────────────
# GET /api/sku/storage — Storage tier mapping table
# ─────────────────────────────────────────────────────────────
@router.get("/api/sku/storage")
async def list_storage_mappings(
    response: Response,
    provider: Optional[str] = Query(None, description="Filter by provider: aws or gcp"),
    category: Optional[str] = Query(None, description="Filter by category: object or block"),
):
    """List all storage tier mappings (S3/GCS → Azure Blob, EBS/PD → Azure Disks)."""
    response.headers["Cache-Control"] = "public, max-age=600"
    engine = get_sku_translator()
    mappings = engine.list_storage_mappings()

    if provider:
        mappings = [m for m in mappings if m["source_provider"] == provider.lower()]
    if category:
        mappings = [m for m in mappings if m["category"] == category.lower()]

    return {"total": len(mappings), "mappings": mappings}


# ─────────────────────────────────────────────────────────────
# GET /api/sku/database — Database SKU mapping table
# ─────────────────────────────────────────────────────────────
@router.get("/api/sku/database")
async def list_database_mappings(
    response: Response,
    provider: Optional[str] = Query(None, description="Filter by provider: aws or gcp"),
):
    """List all database SKU mappings (RDS/Cloud SQL → Azure Flexible Server / SQL Hyperscale)."""
    response.headers["Cache-Control"] = "public, max-age=600"
    engine = get_sku_translator()
    mappings = engine.list_database_mappings()

    if provider:
        mappings = [m for m in mappings if m["source_provider"] == provider.lower()]

    return {"total": len(mappings), "mappings": mappings}
