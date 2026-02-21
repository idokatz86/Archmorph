"""
Archmorph Backend API
Cloud Architecture Translator to Azure — Full Services Catalog
"""

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Response, Request, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio
import os
import logging
import secrets
import uuid
from datetime import datetime, timezone

from cachetools import TTLCache

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ── Azure Monitor / Application Insights ──
APPLICATIONINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
if APPLICATIONINSIGHTS_CONNECTION_STRING:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=APPLICATIONINSIGHTS_CONNECTION_STRING)
        logging.getLogger(__name__).info("Application Insights telemetry enabled")
    except Exception as exc:
        logging.getLogger(__name__).warning("App Insights init failed: %s", exc)
else:
    logging.getLogger(__name__).info("APPLICATIONINSIGHTS_CONNECTION_STRING not set — telemetry disabled")

from services import AWS_SERVICES, AZURE_SERVICES, GCP_SERVICES, CROSS_CLOUD_MAPPINGS
from service_updater import start_scheduler, stop_scheduler, run_update_now, get_update_status, get_last_update
from guided_questions import generate_questions, apply_answers
from diagram_export import generate_diagram
from chatbot import process_chat_message, get_chat_history, clear_chat_session
from iac_chat import process_iac_chat, get_iac_chat_history, clear_iac_chat
from iac_generator import generate_iac_code
from hld_generator import generate_hld, generate_hld_markdown
from image_classifier import classify_image
from vision_analyzer import analyze_image
from usage_metrics import (
    record_event, get_metrics_summary, get_daily_metrics, get_recent_events,
    get_funnel_metrics, record_funnel_step, flush_metrics, ADMIN_SECRET,
)
from icons.routes import router as icon_router

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Rate Limiting
# ─────────────────────────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address,
    enabled=os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false",
)

# ─────────────────────────────────────────────────────────────
# API Key Authentication
# ─────────────────────────────────────────────────────────────
API_KEY = os.getenv("ARCHMORPH_API_KEY", "")  # Empty = auth disabled (dev mode)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Allowed frontend origins (production) — strictly enumerated, no wildcards
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://agreeable-ground-01012c003.2.azurestaticapps.net"
    ).split(",")
    if o.strip()
]
# Add local dev origins only when running locally
if os.getenv("ENVIRONMENT", "production") == "dev":
    ALLOWED_ORIGINS += ["http://localhost:5173", "http://localhost:3000"]

# Max upload file size (10 MB)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(10 * 1024 * 1024)))


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """Verify API key if authentication is enabled."""
    if not API_KEY:
        return  # Auth disabled — dev mode
    if not secrets.compare_digest(api_key or "", API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle manager."""
    logger.info("Starting Archmorph API v2.8.0 — production mode")
    start_scheduler()

    # Auto-load built-in icon packs from samples/
    try:
        from icons.registry import load_builtin_packs, _load_from_disk

        if not _load_from_disk():
            loaded = load_builtin_packs()
            logger.info("Auto-loaded %d built-in icon packs", loaded)
        else:
            logger.info("Icon registry restored from disk")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Icon auto-load skipped: %s", exc)

    yield
    logger.info("Shutting down Archmorph API")
    stop_scheduler()
    flush_metrics()


app = FastAPI(
    title="Archmorph API",
    description="AI-powered Cloud Architecture Translator to Azure",
    version="2.8.0",
    lifespan=lifespan,
)

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — strict origin list, minimal methods/headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "X-Admin-Key"],
    max_age=3600,  # Cache preflight for 1 hour
)


# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Icon Registry routes
app.include_router(icon_router)

# Environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# In-memory session store for analysis results (TTL: 2 hours, max 500 sessions)
SESSION_STORE: TTLCache = TTLCache(maxsize=500, ttl=7200)

# In-memory image store keyed by diagram_id → (image_bytes, content_type) (TTL: 1 hour, max 200)
IMAGE_STORE: TTLCache = TTLCache(maxsize=200, ttl=3600)


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

    # Deeper checks
    checks = {"openai": "unknown", "storage": "unknown"}

    # Check OpenAI client is reachable
    try:
        from openai_client import AZURE_OPENAI_ENDPOINT
        checks["openai"] = "configured" if AZURE_OPENAI_ENDPOINT else "not_configured"
    except Exception:
        checks["openai"] = "error"

    # Check blob storage if configured
    try:
        from usage_metrics import AZURE_STORAGE_CONNECTION_STRING
        checks["storage"] = "configured" if AZURE_STORAGE_CONNECTION_STRING else "local_only"
    except Exception:
        checks["storage"] = "error"

    return {
        "status": "healthy",
        "version": "2.8.0",
        "environment": ENVIRONMENT,
        "mode": "production",
        "checks": checks,
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
    raise HTTPException(501, "Project management is not yet implemented.")


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    raise HTTPException(501, "Project management is not yet implemented.")


# ─────────────────────────────────────────────────────────────
# Diagrams
# ─────────────────────────────────────────────────────────────
@app.post("/api/projects/{project_id}/diagrams")
@limiter.limit("10/minute")
async def upload_diagram(request: Request, project_id: str, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(400, f"File type {file.content_type} not supported")

    # Generate unique diagram ID and store image bytes
    diagram_id = f"diag-{uuid.uuid4().hex[:8]}"
    # Read file in chunks with early size limit enforcement
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(1024 * 1024)  # 1 MB chunks
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            raise HTTPException(
                413,
                f"File too large. Maximum allowed: {MAX_UPLOAD_SIZE // (1024*1024)} MB."
            )
        chunks.append(chunk)
    image_bytes = b"".join(chunks)

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
@limiter.limit("5/minute")
async def analyze_diagram(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """
    Analyze an uploaded architecture diagram using GPT-4o vision.
    Detects cloud services and maps them to Azure equivalents using the catalog.
    Includes an image classification pre-check to reject non-architecture images.
    """
    # Retrieve stored image
    if diagram_id not in IMAGE_STORE:
        raise HTTPException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    image_bytes, content_type = IMAGE_STORE[diagram_id]
    logger.info("Analyzing diagram %s (%d bytes)", diagram_id, len(image_bytes))

    # ── Image classification pre-check (async) ──
    try:
        classification = await asyncio.to_thread(classify_image, image_bytes, content_type)
    except Exception as exc:
        logger.warning("Image classification failed for %s: %s — proceeding with analysis", diagram_id, exc)
        classification = {"is_architecture_diagram": True, "confidence": 0.5, "image_type": "unknown", "reason": "Classification unavailable"}

    if not classification["is_architecture_diagram"]:
        logger.info("Image rejected for %s: %s (confidence: %.2f)", diagram_id, classification["reason"], classification["confidence"])
        record_event("images_rejected", {"diagram_id": diagram_id, "image_type": classification["image_type"], "reason": classification["reason"]})
        raise HTTPException(
            status_code=422,
            detail={
                "error": "not_architecture_diagram",
                "message": f"The uploaded image does not appear to be a cloud architecture diagram. Detected: {classification['image_type']}.",
                "classification": classification,
            },
        )

    logger.info("Image classified as architecture diagram for %s (confidence: %.2f)", diagram_id, classification["confidence"])

    try:
        result = await asyncio.to_thread(analyze_image, image_bytes, content_type)
    except Exception as exc:
        logger.error("Vision analysis failed for %s: %s", diagram_id, exc, exc_info=True)
        err_type = type(exc).__name__
        err_msg = str(exc)[:200]
        raise HTTPException(500, f"Vision analysis failed ({err_type}): {err_msg}")

    # Inject diagram_id and classification metadata into result
    result["diagram_id"] = diagram_id
    result["image_classification"] = classification

    # Store analysis result for guided questions and diagram export
    SESSION_STORE[diagram_id] = result
    record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
    record_funnel_step(diagram_id, "analyze")
    return result


@app.get("/api/diagrams/{diagram_id}/mappings")
async def get_mappings(diagram_id: str):
    raise HTTPException(501, "Mapping retrieval is not yet implemented.")


@app.patch("/api/diagrams/{diagram_id}/mappings/{service}")
async def update_mapping(diagram_id: str, service: str, azure_service: str):
    raise HTTPException(501, "Mapping override is not yet implemented.")


# ─────────────────────────────────────────────────────────────
# Guided Questions
# ─────────────────────────────────────────────────────────────
@app.post("/api/diagrams/{diagram_id}/questions")
async def get_guided_questions(diagram_id: str, smart_dedup: bool = True):
    """Generate guided questions based on detected AWS services.
    
    If smart_dedup=True, questions that have been implicitly answered
    by user context (e.g., natural language additions) are filtered out.
    """
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")

    detected = [m["source_service"] for m in analysis.get("mappings", [])]
    questions = generate_questions(detected)
    
    # Apply smart deduplication if enabled
    inferred_answers = {}
    if smart_dedup:
        from service_builder import deduplicate_questions, get_smart_defaults_from_analysis
        user_context = analysis.get("user_context", {})
        questions, inferred_answers = deduplicate_questions(questions, analysis, user_context)
        smart_defaults = get_smart_defaults_from_analysis(analysis)
        inferred_answers = {**smart_defaults, **inferred_answers}
    
    record_event("questions_generated", {"diagram_id": diagram_id, "count": len(questions)})
    record_funnel_step(diagram_id, "questions")
    return {
        "diagram_id": diagram_id,
        "questions": questions,
        "total": len(questions),
        "inferred_answers": inferred_answers,
        "questions_skipped": len(inferred_answers),
    }


# ─────────────────────────────────────────────────────────────
# Natural Language Service Builder
# ─────────────────────────────────────────────────────────────
class AddServicesRequest(BaseModel):
    text: str


@app.post("/api/diagrams/{diagram_id}/add-services")
@limiter.limit("10/minute")
async def add_services_natural_language(
    request: Request,
    diagram_id: str,
    body: AddServicesRequest,
    _auth=Depends(verify_api_key),
):
    """Add Azure services to an architecture using natural language.
    
    Example: "Add a Redis cache and API Gateway with WAF"
    
    The services are added to the existing analysis, and users can continue
    to the guided questions or IaC generation.
    """
    from service_builder import add_services_from_text
    
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, f"No analysis found for diagram {diagram_id}. Run /analyze first.")
    
    try:
        updated = await asyncio.to_thread(
            add_services_from_text,
            analysis=analysis,
            user_text=body.text,
        )
    except Exception as exc:
        logger.error("Failed to add services for %s: %s", diagram_id, exc)
        raise HTTPException(500, f"Failed to process request: {str(exc)}")
    
    # Store user context for smart question deduplication
    updated.setdefault("user_context", {})
    updated["user_context"].setdefault("natural_language_additions", [])
    updated["user_context"]["natural_language_additions"].append({
        "text": body.text,
        "services_added": updated.get("services_added", []),
    })
    
    SESSION_STORE[diagram_id] = updated
    
    record_event("services_added_nl", {
        "diagram_id": diagram_id,
        "services_count": len(updated.get("services_added", [])),
    })
    
    return {
        "diagram_id": diagram_id,
        "services_added": updated.get("services_added", []),
        "services_detected": updated.get("services_detected", 0),
        "inferred_requirements": updated.get("inferred_requirements", []),
        "message": f"Added {len(updated.get('services_added', []))} service(s) to your architecture.",
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
async def trigger_service_update(_auth=Depends(verify_api_key)):
    """Trigger an immediate service catalog update (requires API key)."""
    result = run_update_now()
    return result


# ─────────────────────────────────────────────────────────────
# IaC Generation
# ─────────────────────────────────────────────────────────────
@app.post("/api/diagrams/{diagram_id}/generate")
@limiter.limit("5/minute")
async def generate_iac(request: Request, diagram_id: str, format: str = "terraform", _auth=Depends(verify_api_key)):
    if format not in ["terraform", "bicep"]:
        raise HTTPException(400, "Format must be 'terraform' or 'bicep'")

    # Get analysis from session (may be None for base template)
    session = SESSION_STORE.get(diagram_id, {})
    iac_params = session.get("iac_parameters", {})

    # Generate IaC dynamically using GPT-4o
    try:
        code = await asyncio.to_thread(
            generate_iac_code,
            analysis=session if session else None,
            iac_format=format,
            params=iac_params,
        )
    except Exception as exc:
        logger.error("IaC generation failed for %s: %s", diagram_id, exc)
        raise HTTPException(500, "IaC generation failed. Please try again.")

    record_event(f"iac_generated_{format}", {"diagram_id": diagram_id})
    record_funnel_step(diagram_id, "iac_generate")
    return {"diagram_id": diagram_id, "format": format, "code": code}


@app.get("/api/diagrams/{diagram_id}/export")
async def export_iac(diagram_id: str, format: str = "terraform"):
    raise HTTPException(501, "File download export is not yet implemented.")


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
    from services.azure_pricing import estimate_services_cost

    if mappings:
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
# IaC Chat — GPT-4o powered Terraform/Bicep assistant
# ─────────────────────────────────────────────────────────────
class IaCChatMessage(BaseModel):
    message: str
    code: str
    format: str = "terraform"


@app.post("/api/diagrams/{diagram_id}/iac-chat")
@limiter.limit("10/minute")
async def iac_chat_endpoint(request: Request, diagram_id: str, msg: IaCChatMessage, _auth=Depends(verify_api_key)):
    """Chat with AI to modify generated Terraform/Bicep code."""
    record_event("iac_chat_messages", {"diagram_id": diagram_id})

    # Get analysis context from session
    session = SESSION_STORE.get(diagram_id, {})
    analysis_context = session.get("analysis") if session else None

    result = await asyncio.to_thread(
        process_iac_chat,
        diagram_id=diagram_id,
        message=msg.message,
        current_code=msg.code,
        iac_format=msg.format,
        analysis_context=analysis_context,
    )

    if result.get("services_added"):
        record_event("iac_services_added", {
            "diagram_id": diagram_id,
            "services": result["services_added"],
        })

    return result


@app.get("/api/diagrams/{diagram_id}/iac-chat/history")
async def iac_chat_history(diagram_id: str):
    """Get IaC chat history for a diagram."""
    return {
        "diagram_id": diagram_id,
        "messages": get_iac_chat_history(diagram_id),
    }


@app.delete("/api/diagrams/{diagram_id}/iac-chat")
async def iac_chat_clear(diagram_id: str):
    """Clear IaC chat session for a diagram."""
    cleared = clear_iac_chat(diagram_id)
    return {"cleared": cleared}


# ─────────────────────────────────────────────────────────────
# HLD Generation — AI-powered High-Level Design document
# ─────────────────────────────────────────────────────────────

@app.post("/api/diagrams/{diagram_id}/generate-hld")
@limiter.limit("3/minute")
async def generate_hld_endpoint(request: Request, diagram_id: str, _auth=Depends(verify_api_key)):
    """Generate a comprehensive High-Level Design document."""
    record_event("hld_generated", {"diagram_id": diagram_id})

    session = SESSION_STORE.get(diagram_id)
    if not session:
        raise HTTPException(404, "No analysis found. Analyze a diagram first.")

    analysis = session

    # Get cost estimate if available
    cost_estimate = None
    try:
        from services.azure_pricing import estimate_services_cost
        iac_params = session.get("iac_parameters", {})
        region = iac_params.get("region", "westeurope")
        strategy = iac_params.get("sku_strategy", "balanced")
        cost_estimate = estimate_services_cost(analysis.get("mappings", []), region=region, sku_strategy=strategy)
    except Exception:
        pass

    try:
        hld = await asyncio.to_thread(
            generate_hld,
            analysis=analysis,
            cost_estimate=cost_estimate,
            iac_params=session.get("iac_parameters"),
        )
        markdown = generate_hld_markdown(hld)
    except ValueError as e:
        raise HTTPException(500, str(e))

    # Store in session
    session["hld"] = hld
    session["hld_markdown"] = markdown

    return {
        "diagram_id": diagram_id,
        "hld": hld,
        "markdown": markdown,
    }


@app.get("/api/diagrams/{diagram_id}/hld")
async def get_hld(diagram_id: str):
    """Get previously generated HLD document."""
    session = SESSION_STORE.get(diagram_id)
    if not session or "hld" not in session:
        raise HTTPException(404, "No HLD found. Generate one first.")
    return {
        "diagram_id": diagram_id,
        "hld": session["hld"],
        "markdown": session.get("hld_markdown", ""),
    }


# ─────────────────────────────────────────────────────────────
# Chatbot — AI assistant with GitHub issue creation
# ─────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = "default"


@app.post("/api/chat")
@limiter.limit("15/minute")
async def chat(request: Request, msg: ChatMessage, _auth=Depends(verify_api_key)):
    """Process a chat message and return bot response. Can create GitHub issues."""
    record_event("chat_messages", {"session_id": msg.session_id})
    result = await asyncio.to_thread(process_chat_message, msg.session_id, msg.message)
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
ADMIN_KEY_HEADER = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def verify_admin_key(admin_key: Optional[str] = Security(ADMIN_KEY_HEADER)):
    """Verify admin key via X-Admin-Key header."""
    if not ADMIN_SECRET:
        raise HTTPException(503, "Admin API not configured")
    if not admin_key or not secrets.compare_digest(admin_key, ADMIN_SECRET):
        raise HTTPException(403, "Invalid or missing admin key")


@app.get("/api/admin/metrics")
async def admin_metrics_summary(_admin=Depends(verify_admin_key)):
    """Return aggregate usage metrics (admin only)."""
    return get_metrics_summary()


@app.get("/api/admin/metrics/funnel")
async def admin_funnel(_admin=Depends(verify_admin_key)):
    """Return conversion funnel data (admin only)."""
    return get_funnel_metrics()


@app.get("/api/admin/metrics/daily")
async def admin_metrics_daily(days: int = Query(30, ge=1, le=365), _admin=Depends(verify_admin_key)):
    """Return daily metrics for the last N days (admin only)."""
    return {"days": days, "data": get_daily_metrics(days)}


@app.get("/api/admin/metrics/recent")
async def admin_metrics_recent(limit: int = Query(50, ge=1, le=200), _admin=Depends(verify_admin_key)):
    """Return the most recent usage events (admin only)."""
    return {"events": get_recent_events(limit)}


@app.get("/api/admin/costs")
async def admin_cost_dashboard(_admin=Depends(verify_admin_key)):
    """
    Return estimated monthly Azure costs for the Archmorph platform itself.
    Based on actual deployed resource SKUs (not user diagrams).
    """
    # Estimated costs per resource (USD/month, pay-as-you-go North Europe)
    resources = [
        {"name": "Container Apps (0.5 vCPU, 1Gi)", "category": "Compute", "monthly_usd": 36.50, "notes": "Always-on single instance"},
        {"name": "Azure OpenAI (GPT-4o)", "category": "AI", "monthly_usd": 0.0, "notes": "Pay-per-token: ~$2.50/1K images analyzed"},
        {"name": "Static Web Apps (Free)", "category": "Frontend", "monthly_usd": 0.0, "notes": "Free tier"},
        {"name": "Container Registry (Basic)", "category": "Containers", "monthly_usd": 5.0, "notes": "Basic SKU"},
        {"name": "Log Analytics (PerGB2018)", "category": "Monitoring", "monthly_usd": 2.76, "notes": "~1 GB/month ingest"},
        {"name": "Storage Account (LRS)", "category": "Storage", "monthly_usd": 0.50, "notes": "Blob storage for metrics"},
        {"name": "PostgreSQL Flex (B1ms)", "category": "Database", "monthly_usd": 12.90, "notes": "Burstable B1ms, 32GB storage"},
        {"name": "Key Vault (Standard)", "category": "Security", "monthly_usd": 0.03, "notes": "3 secrets"},
    ]

    # Compute per-token OpenAI cost estimate from actual usage
    metrics = get_metrics_summary()
    analyses = metrics["totals"].get("analyses_run", 0)
    iac_generated = metrics["totals"].get("iac_generated_terraform", 0) + metrics["totals"].get("iac_generated_bicep", 0)
    hld_count = metrics["totals"].get("hld_generated", 0)
    chat_msgs = metrics["totals"].get("iac_chat_messages", 0) + metrics["totals"].get("chat_messages", 0)

    # Rough token estimates: vision ~1500 tokens in + 4000 out, IaC ~2000 in + 8000 out
    input_tokens = analyses * 2000 + iac_generated * 2000 + hld_count * 2000 + chat_msgs * 500
    output_tokens = analyses * 4000 + iac_generated * 8000 + hld_count * 8000 + chat_msgs * 1000
    # GPT-4o pricing: $2.50/1M input, $10/1M output
    openai_cost = round(input_tokens * 2.50 / 1_000_000 + output_tokens * 10.0 / 1_000_000, 2)
    resources[1]["monthly_usd"] = openai_cost
    resources[1]["notes"] = f"~{input_tokens:,} in + {output_tokens:,} out tokens used"

    total = round(sum(r["monthly_usd"] for r in resources), 2)

    return {
        "total_monthly_usd": total,
        "currency": "USD",
        "region": "North Europe",
        "resources": resources,
        "usage_based": {
            "analyses_run": analyses,
            "iac_generated": iac_generated,
            "hld_generated": hld_count,
            "chat_messages": chat_msgs,
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "openai_cost_usd": openai_cost,
        },
    }


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


# ─────────────────────────────────────────────────────────────
# Sample Diagrams
# ─────────────────────────────────────────────────────────────
SAMPLE_DIAGRAMS = [
    {
        "id": "aws-3tier",
        "name": "AWS 3-Tier Web App",
        "description": "Classic 3-tier architecture with ALB, EC2, and RDS",
        "provider": "aws",
        "services": ["ALB", "EC2", "RDS", "S3", "CloudFront"],
        "complexity": "medium"
    },
    {
        "id": "aws-serverless",
        "name": "AWS Serverless API",
        "description": "API Gateway + Lambda + DynamoDB architecture",
        "provider": "aws",
        "services": ["API Gateway", "Lambda", "DynamoDB", "Cognito"],
        "complexity": "simple"
    },
    {
        "id": "gcp-microservices",
        "name": "GCP Microservices",
        "description": "GKE-based microservices with Cloud SQL and Pub/Sub",
        "provider": "gcp",
        "services": ["GKE", "Cloud SQL", "Pub/Sub", "Cloud Run"],
        "complexity": "complex"
    },
    {
        "id": "aws-data-lake",
        "name": "AWS Data Lake",
        "description": "S3 data lake with Glue, Athena, and Redshift",
        "provider": "aws",
        "services": ["S3", "Glue", "Athena", "Redshift", "Lake Formation"],
        "complexity": "complex"
    }
]

@app.get("/api/samples")
async def list_sample_diagrams():
    """List available sample diagrams for onboarding."""
    return {"samples": SAMPLE_DIAGRAMS}


@app.post("/api/samples/{sample_id}/analyze")
@limiter.limit("5/minute")
async def analyze_sample_diagram(request: Request, sample_id: str):
    """Generate a mock analysis for a sample diagram."""
    sample = next((s for s in SAMPLE_DIAGRAMS if s["id"] == sample_id), None)
    if not sample:
        raise HTTPException(404, f"Sample '{sample_id}' not found")
    
    # Generate mock analysis based on sample metadata
    diagram_id = f"sample-{sample_id}-{uuid.uuid4().hex[:6]}"
    
    # Create mock zones and mappings
    from services import CROSS_CLOUD_MAPPINGS
    
    zones = []
    mappings = []
    
    # Group services by category
    for i, svc_name in enumerate(sample["services"]):
        # Find mapping
        mapping = next(
            (m for m in CROSS_CLOUD_MAPPINGS 
             if svc_name.lower() in m.get("aws", "").lower() 
             or svc_name.lower() in m.get("gcp", "").lower()),
            None
        )
        azure_svc = mapping["azure"] if mapping else f"Azure {svc_name}"
        confidence = mapping.get("confidence", 85) / 100 if mapping else 0.8
        
        mappings.append({
            "source": svc_name,
            "azure": azure_svc,
            "confidence": confidence,
            "notes": mapping.get("notes", "Direct mapping") if mapping else "Suggested equivalent"
        })
    
    zones.append({
        "number": 1,
        "name": "Application Tier",
        "services": mappings
    })
    
    analysis = {
        "diagram_id": diagram_id,
        "diagram_type": sample["name"],
        "source_provider": sample["provider"],
        "services_detected": len(sample["services"]),
        "zones": zones,
        "confidence_summary": {
            "high": sum(1 for m in mappings if m["confidence"] >= 0.9),
            "medium": sum(1 for m in mappings if 0.7 <= m["confidence"] < 0.9),
            "low": sum(1 for m in mappings if m["confidence"] < 0.7),
            "average": sum(m["confidence"] for m in mappings) / len(mappings)
        },
        "is_sample": True
    }
    
    SESSION_STORE[diagram_id] = analysis
    record_funnel_step(diagram_id, "analyze")
    
    return analysis


# ─────────────────────────────────────────────────────────────
# Best Practices & WAF Analysis
# ─────────────────────────────────────────────────────────────
@app.get("/api/diagrams/{diagram_id}/best-practices")
async def get_best_practices(diagram_id: str):
    """Analyze architecture against Azure Well-Architected Framework."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    from best_practices import analyze_architecture, get_quick_wins
    
    # Get user answers if available
    answers = analysis.get("applied_answers", {})
    
    result = analyze_architecture(analysis, answers)
    result["quick_wins"] = get_quick_wins(result["recommendations"])
    
    return result


# ─────────────────────────────────────────────────────────────
# Cost Optimization
# ─────────────────────────────────────────────────────────────
@app.get("/api/diagrams/{diagram_id}/cost-optimization")
async def get_cost_optimization(diagram_id: str):
    """Get cost optimization recommendations for the architecture."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    from cost_optimizer import analyze_cost_optimizations
    
    answers = analysis.get("applied_answers", {})
    
    # Try to get cost estimate if available
    cost_estimate = analysis.get("cost_estimate")
    
    return analyze_cost_optimizations(analysis, answers, cost_estimate)


# ─────────────────────────────────────────────────────────────
# Feedback & NPS
# ─────────────────────────────────────────────────────────────
class NPSRequest(BaseModel):
    score: int
    follow_up: Optional[str] = None
    session_id: Optional[str] = None
    feature_context: Optional[str] = None


class FeatureFeedbackRequest(BaseModel):
    feature: str
    helpful: bool
    comment: Optional[str] = None
    session_id: Optional[str] = None


class BugReportRequest(BaseModel):
    description: str
    context: Optional[Dict[str, Any]] = None
    severity: str = "medium"
    session_id: Optional[str] = None


@app.post("/api/feedback/nps")
@limiter.limit("10/minute")
async def submit_nps_feedback(request: Request, data: NPSRequest):
    """Submit NPS score (0-10) with optional follow-up."""
    from feedback import submit_nps
    return submit_nps(
        score=data.score,
        follow_up=data.follow_up,
        session_id=data.session_id,
        feature_context=data.feature_context
    )


@app.post("/api/feedback/feature")
@limiter.limit("20/minute")
async def submit_feature_feedback_endpoint(request: Request, data: FeatureFeedbackRequest):
    """Submit feature feedback (thumbs up/down)."""
    from feedback import submit_feature_feedback
    return submit_feature_feedback(
        feature=data.feature,
        helpful=data.helpful,
        comment=data.comment,
        session_id=data.session_id
    )


@app.post("/api/feedback/bug")
@limiter.limit("5/minute")
async def submit_bug_report_endpoint(request: Request, data: BugReportRequest):
    """Submit bug report with context."""
    from feedback import submit_bug_report
    return submit_bug_report(
        description=data.description,
        context=data.context,
        severity=data.severity,
        session_id=data.session_id
    )


@app.get("/api/admin/feedback")
async def get_feedback_summary_endpoint(admin_key: str = Query(...)):
    """Get feedback summary (admin only)."""
    if not ADMIN_SECRET or not secrets.compare_digest(admin_key, ADMIN_SECRET):
        raise HTTPException(401, "Invalid admin key")
    
    from feedback import get_feedback_summary, get_nps_trend
    
    summary = get_feedback_summary()
    summary["nps_trend"] = get_nps_trend(30)
    return summary


# ─────────────────────────────────────────────────────────────
# Share Links
# ─────────────────────────────────────────────────────────────
SHARE_STORE: TTLCache = TTLCache(maxsize=100, ttl=86400)  # 24 hour TTL


@app.post("/api/diagrams/{diagram_id}/share")
async def create_share_link(diagram_id: str):
    """Create a shareable read-only link for analysis results."""
    analysis = SESSION_STORE.get(diagram_id)
    if not analysis:
        raise HTTPException(404, "Analysis not found")
    
    share_id = f"share-{uuid.uuid4().hex[:10]}"
    
    # Store a read-only snapshot
    SHARE_STORE[share_id] = {
        "analysis": analysis,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_in": "24 hours"
    }
    
    return {
        "share_id": share_id,
        "share_url": f"/shared/{share_id}",
        "expires_in": "24 hours"
    }


@app.get("/api/shared/{share_id}")
async def get_shared_analysis(share_id: str):
    """Get shared analysis by share ID (public, read-only)."""
    shared = SHARE_STORE.get(share_id)
    if not shared:
        raise HTTPException(404, "Share link expired or invalid")
    
    return {
        "analysis": shared["analysis"],
        "shared_at": shared["created_at"],
        "read_only": True
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
