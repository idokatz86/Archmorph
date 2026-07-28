"""
Core diagram routes — upload, analyze, session restore, async analysis.

Other diagram-related routes have been split into focused modules (#284):
  - routers/analysis.py     — questions, answers, add-services, export-diagram
  - routers/iac_routes.py   — IaC generation, IaC chat
  - routers/hld_routes.py   — HLD generation, export
  - routers/insights.py     — best practices, cost, risk, compliance
  - routers/sharing.py      — share links
  - routers/infra.py        — infrastructure import
  - routers/suggestions.py  — AI mapping suggestions
"""

from fastapi import APIRouter, UploadFile, File, Request, Depends
from strict_models import StrictBaseModel
from typing import Dict, Any, Optional
import asyncio
import base64
import copy
import hashlib
import json
import logging
from functools import partial
from starlette.concurrency import run_in_threadpool

from database import get_db, SessionLocal
from routers.shared import (
    SESSION_STORE, IMAGE_STORE,
    limiter, verify_api_key, verify_api_key_or_user_session, MAX_UPLOAD_SIZE, generate_session_id,
    get_api_key_service_principal, get_request_durable_principal,
    require_diagram_access,
)
import ci_smoke
from job_queue import job_manager, AdmissionRejected, AdmissionStoreError, JobStoreError
from usage_metrics import record_event, record_funnel_step
from export_capabilities import (
    _principal_marker,
    attach_export_capability,
    decode_restore_capability,
    issue_restore_capability,
)
from data_lifecycle import attach_trust_receipt, build_trust_receipt
from image_classifier import classify_image
from vision_analyzer import analyze_image, VISION_PROMPT_HASH
from openai_client import AZURE_OPENAI_DEPLOYMENT, OpenAIServiceError, handle_openai_error
from hld_generator import generate_hld, generate_hld_markdown  # noqa: F401 — re-exported for test monkeypatching
from auth import get_user_from_request_headers
from error_envelope import ArchmorphException
from upload_validator import validate_upload, UploadValidationError
from sku_translator import get_sku_translator
from confidence_provenance import build_provenance
from architecture_rules import evaluate as evaluate_architecture_rules
from architecture_review import build_audit_pipeline_issue, classify_regulated_workload
from source_provider import normalize_source_provider
from project_store import (
    acquire_project,
    get_project,
    register_diagram,
    get_project_id_for_diagram,
)
from analysis_payload_bounds import (
    AnalysisPayloadTooLarge,
    MAX_RESTORE_BODY_BYTES,
    validate_analysis_payload_bounds,
    validate_restore_payload_shape,
)
from workspace_store import (
    AnalysisCacheWriteError,
    DurableAnalysisPersistenceError,
    persist_analysis_state,
)

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
VISIO_EXTENSION = ".vsdx"


def _enrich_with_sku(result: dict) -> dict:
    """Enrich analysis mappings with SKU-level instance type translations.

    For each mapping whose source category is Compute, Database, or Storage,
    attempt to detect instance types from the service names/roles and attach
    SKU translation details with parity scores.
    """
    engine = get_sku_translator()
    provider = normalize_source_provider(result.get("source_provider"))

    for m in result.get("mappings", []):
        source_name = m.get("source_service", "")
        if isinstance(source_name, dict):
            source_name = source_name.get("name", "")
        role = m.get("role", m.get("description", ""))
        search_text = f"{source_name} {role}"

        category = m.get("category", "").lower()
        if category in ("compute", ""):
            translation = engine.best_fit(search_text, provider)
            if translation is not None:
                m["sku_translation"] = {
                    "source_sku": translation.source.sku,
                    "azure_sku": translation.target.sku,
                    "parity_score": translation.parity.overall,
                    "parity_details": translation.parity.details,
                    "vcpus": translation.target.vcpus,
                    "ram_gb": translation.target.ram_gb,
                }

    return result


def _enrich_with_provenance(result: dict) -> dict:
    """Attach structured confidence provenance to each mapping."""
    for m in result.get("mappings", []):
        try:
            m["confidence_provenance"] = build_provenance(m)
        except Exception:
            logger.debug("Provenance enrichment skipped for mapping: %s", m.get("source_service"))
    return result


def _enrich_with_architecture_issues(result: dict) -> dict:
    """Run the architecture-limitations engine against the analysis (Issue #610).

    Adds two top-level keys to the result:
      - architecture_issues: list of issue dicts (rule_id, severity, message, ...)
      - architecture_issues_summary: { blocker, warning, info, total }

    Failures are swallowed and logged: a broken rule must never break analysis.
    """
    try:
        issues = evaluate_architecture_rules(result)
        classification = classify_regulated_workload(result)
        result["regulated_workload"] = classification.to_dict()
        audit_issue = build_audit_pipeline_issue(result, classification)
        if audit_issue is not None:
            issues.append(audit_issue)
        issue_dicts = [i.to_dict() for i in issues]
        summary = {"blocker": 0, "warning": 0, "info": 0, "total": len(issue_dicts)}
        for d in issue_dicts:
            sev = d.get("severity")
            if sev in summary:
                summary[sev] += 1
        result["architecture_issues"] = issue_dicts
        result["architecture_issues_summary"] = summary
    except Exception as exc:
        logger.warning(
            "architecture_rules evaluation failed: %s",
            str(exc).replace("\n", " ").replace("\r", " "),
        )
        result.setdefault("architecture_issues", [])
        result.setdefault(
            "architecture_issues_summary",
            {"blocker": 0, "warning": 0, "info": 0, "total": 0, "engine_error": True},
        )
    return result


def _normalize_analysis(result: dict) -> dict:
    """Normalize GPT vision output so downstream code always sees consistent fields.

    - source_service: always a string (GPT-4.1 sometimes returns a dict)
    - azure_service: always present (GPT-4.1 sometimes uses target_service instead)
    - sku_translation: enriched when instance types are detected in service text
    """
    for m in result.get("mappings", []):
        if isinstance(m.get("source_service"), dict):
            m["source_service"] = m["source_service"].get("name", str(m["source_service"]))
        if "azure_service" not in m and "target_service" in m:
            m["azure_service"] = m.pop("target_service")

    result = _enrich_with_sku(result)
    result = _enrich_with_provenance(result)
    result = _enrich_with_architecture_issues(result)
    return result


# ─────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────
class RestoreSessionRequest(StrictBaseModel):
    """Request body for restoring a cached analysis session."""
    analysis: Dict[str, Any]
    hld: Optional[Dict[str, Any]] = None
    hld_markdown: Optional[str] = None
    iac_code: Optional[str] = None
    iac_format: Optional[str] = None
    image_base64: Optional[str] = None
    image_content_type: Optional[str] = None
    restore_capability: Optional[str] = None


def _diagram_project_metadata(
    diagram_id: str,
    *,
    principal: Optional[dict] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    if principal is None or not principal.get("tenant_id"):
        return None, {}
    db = SessionLocal()
    try:
        project_id = get_project_id_for_diagram(
            db,
            diagram_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
        )
        if not project_id:
            return None, {}
        project = get_project(
            db,
            project_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
        ) or {}
        diagram = next(
            (
                item
                for item in project.get("diagrams", [])
                if item.get("diagram_id") == diagram_id
            ),
            {},
        )
        return project_id, diagram
    finally:
        db.close()


def _attach_lifecycle_receipt(
    payload: Dict[str, Any],
    diagram_id: str,
    *,
    image_present: Optional[bool] = None,
    session_present: Optional[bool] = None,
    principal: Optional[dict] = None,
) -> Dict[str, Any]:
    project_id, diagram_meta = _diagram_project_metadata(
        diagram_id,
        principal=principal,
    )
    return attach_trust_receipt(
        payload,
        diagram_id,
        project_id=project_id,
        uploaded_at=diagram_meta.get("created_at"),
        image_present=(diagram_id in IMAGE_STORE) if image_present is None else image_present,
        session_present=(diagram_id in SESSION_STORE) if session_present is None else session_present,
        export_capability_expires_in=payload.get("export_capability_expires_in"),
    )


def _persist_authenticated_analysis(
    db,
    *,
    user_id: str,
    tenant_id: Optional[str],
    diagram_id: str,
    session: Dict[str, Any],
    owner_api_key_id: Optional[str] = None,
    cache_required: bool = False,
    require_project_membership: bool = False,
    precommit_hook=None,
) -> Any:
    try:
        if tenant_id and owner_api_key_id is None:
            from project_store import PROJECT_EDIT_ROLES, resolve_diagram_principal

            project_principal = resolve_diagram_principal(
                db,
                diagram_id,
                caller_user_id=user_id,
                tenant_id=tenant_id,
                allowed_roles=PROJECT_EDIT_ROLES,
            )
            if project_principal is None:
                raise ValueError("Durable project edit permission not found")
            user_id = project_principal["owner_user_id"]
        from workspace_store import get_analysis_by_diagram

        workspace_id = get_project_id_for_diagram(
            db,
            diagram_id,
            owner_user_id=user_id,
            tenant_id=tenant_id,
        ) if tenant_id else None
        if workspace_id is None and require_project_membership:
            raise ValueError("Durable project membership not found")
        durable_analysis = get_analysis_by_diagram(
            db,
            diagram_id=diagram_id,
            owner_user_id=user_id,
            tenant_id=tenant_id,
        ) if tenant_id else None
        expected_version = (
            int(durable_analysis.current_version or 0)
            if durable_analysis is not None and int(durable_analysis.current_version or 0) > 0
            else None
        )
        operation = "analysis-result"
        request_snapshot = copy.deepcopy(session)
        request_snapshot.pop("_analysis_version", None)
        request_hash = hashlib.sha256(json.dumps(
            {
                "diagram_id": diagram_id,
                "operation": operation,
                "snapshot": request_snapshot,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest()
        result = persist_analysis_state(
            db,
            owner_user_id=user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            snapshot=session,
            workspace_id=workspace_id,
            session_store=SESSION_STORE,
            cache_owner_api_key_id=owner_api_key_id,
            cache_required=cache_required,
            allow_unowned_upload_claim=True,
            expected_version=expected_version,
            operation=operation,
            request_hash=request_hash,
            require_snapshot_version=False,
            precommit_hook=precommit_hook,
        )
        session["_analysis_version"] = result.version.version_number
        return result
    except ValueError as exc:
        if not tenant_id:
            raise ArchmorphException(
                401,
                "Authenticated tenant context is required for durable analysis state.",
                details={"error": "tenant_context_required"},
            ) from exc
        raise ArchmorphException(
            503,
            "Analysis persistence is temporarily unavailable. Please retry shortly.",
            details={"error": "analysis_persistence_unavailable"},
            headers={"Retry-After": "30"},
        ) from exc
    except DurableAnalysisPersistenceError as exc:
        raise ArchmorphException(
            503,
            "Analysis persistence is temporarily unavailable. Please retry shortly.",
            details={"error": "analysis_persistence_unavailable"},
            headers={"Retry-After": "30"},
        ) from exc
    except AnalysisCacheWriteError as exc:
        raise ArchmorphException(
            503,
            "Analysis cache is temporarily unavailable. The durable record was saved; retry to continue.",
            details={"error": "analysis_cache_unavailable", "durable_saved": True},
            headers={"Retry-After": "5"},
        ) from exc


def _persist_authenticated_analysis_in_worker(**kwargs):
    db = SessionLocal()
    try:
        return _persist_authenticated_analysis(db, **kwargs)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────
# Diagrams — Upload
# ─────────────────────────────────────────────────────────────
def _new_project_upload() -> None:
    return None


def _persist_project_upload(
    *,
    request: Request,
    requested_project_id: Optional[str],
    caller_owner_user_id: str,
    tenant_id: str,
    diagram_id: str,
    filename: Optional[str],
    content_type: Optional[str],
    file_size_bytes: int,
    content_hash: str,
) -> tuple[str, str, str]:
    from project_store import PROJECT_EDIT_ROLES, require_project_access

    db = SessionLocal()
    try:
        canonical_owner_user_id = caller_owner_user_id
        authorized_project_id = None
        if requested_project_id:
            resolved = require_project_access(
                db,
                project_id=requested_project_id,
                caller_user_id=caller_owner_user_id,
                tenant_id=tenant_id,
                allowed_roles=PROJECT_EDIT_ROLES,
            )
            if resolved is not None:
                project, _role = resolved
                authorized_project_id = project.id
                canonical_owner_user_id = project.owner_user_id
        project = acquire_project(
            db,
            owner_user_id=canonical_owner_user_id,
            tenant_id=tenant_id,
            project_id=authorized_project_id,
        )
        register_diagram(
            db,
            project_id=project.id,
            diagram_id=diagram_id,
            owner_user_id=project.owner_user_id,
            tenant_id=tenant_id,
            filename=filename,
            content_type=content_type,
            file_size_bytes=file_size_bytes,
            content_hash=content_hash,
        )
        restore_capability = issue_restore_capability(
            request,
            diagram_id,
            db=db,
            owner_user_id=project.owner_user_id,
            tenant_id=tenant_id,
        )
        return project.id, project.owner_user_id, restore_capability
    finally:
        db.close()


@router.post("/api/projects/diagrams")
@limiter.limit("10/minute")
async def upload_diagram(
    request: Request,
    file: UploadFile = File(...),
    _auth=Depends(verify_api_key_or_user_session),
    requested_project_id: Optional[str] = Depends(_new_project_upload),
):
    """Upload an architecture diagram image for analysis.

    Accepts PNG, JPEG, SVG, PDF, and Visio (.vsdx) files up to the
    configured MAX_UPLOAD_SIZE limit.
    """
    # Validate file type
    allowed_types = [
        "image/png", "image/jpeg", "image/svg+xml", "application/pdf",
        "application/vnd.ms-visio.drawing.main+xml",  # .vsdx
        "application/vnd.visio",  # legacy alias
        "application/xml", "text/xml",  # .drawio files
        "application/octet-stream",  # browsers may send .vsdx/.drawio as octet-stream
    ]
    is_visio = file.filename and file.filename.lower().endswith(VISIO_EXTENSION)
    is_drawio = file.filename and file.filename.lower().endswith(".drawio")
    if file.content_type not in allowed_types and not is_visio and not is_drawio:
        raise ArchmorphException(400, f"File type {file.content_type} not supported. Accepted: PNG, JPG, JPEG, SVG, PDF, Draw.io, Visio.")

    diagram_id = generate_session_id("diag")
    # Read file in chunks with early size limit enforcement
    chunks = []
    total_size = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE_BYTES)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE:
            raise ArchmorphException(
                413,
                f"File too large. Maximum allowed: {MAX_UPLOAD_SIZE // (1024*1024)} MB."
            )
        chunks.append(chunk)
    image_bytes = b"".join(chunks)

    # Content-level validation (magic bytes, active PDF/SVG/ZIP content, etc.)
    original_filename = file.filename or "upload"
    filename_suffix = (
        original_filename.rsplit(".", 1)[-1].lower()[:16]
        if "." in original_filename
        else "bin"
    )
    retained_filename = (
        "sha256:"
        f"{hashlib.sha256(original_filename.encode('utf-8')).hexdigest()}:"
        f"{filename_suffix}"
    )
    try:
        validate_upload(image_bytes, file.content_type or "", file.filename)
    except UploadValidationError as exc:
        raise ArchmorphException(exc.status_code, exc.message)

    # Base64-encode for Redis/FileStore compatibility
    IMAGE_STORE[diagram_id] = (base64.b64encode(image_bytes).decode("ascii"), file.content_type)
    headers = dict(request.headers)
    upload_user = get_user_from_request_headers(headers)
    upload_principal = get_request_durable_principal(request)
    upload_api_key_id = get_api_key_service_principal(headers)
    if upload_principal is None and upload_api_key_id:
        upload_principal = {
            "owner_user_id": upload_api_key_id,
            "tenant_id": f"service:{upload_api_key_id.split(':', 1)[-1]}",
            "owner_api_key_id": upload_api_key_id,
            "legacy_owner_user_ids": [],
        }
    if upload_principal is None or not upload_principal.get("tenant_id"):
        IMAGE_STORE.delete(diagram_id)
        raise ArchmorphException(401, "Authenticated tenant context is required")
    try:
        project_id, canonical_owner_user_id, restore_capability = await run_in_threadpool(partial(
            _persist_project_upload,
            request=request,
            requested_project_id=requested_project_id,
            caller_owner_user_id=upload_principal["owner_user_id"],
            tenant_id=upload_principal["tenant_id"],
            diagram_id=diagram_id,
            filename=retained_filename,
            content_type=file.content_type,
            file_size_bytes=len(image_bytes),
            content_hash=hashlib.sha256(image_bytes).hexdigest(),
        ))
        upload_principal = {
            **upload_principal,
            "owner_user_id": canonical_owner_user_id,
        }
    except Exception as exc:
        IMAGE_STORE.delete(diagram_id)
        raise ArchmorphException(503, "Project persistence is temporarily unavailable") from exc
    namespace_claim = {"diagram_id": diagram_id, "status": "uploaded"}
    if upload_user:
        namespace_claim["_owner_user_id"] = upload_principal["owner_user_id"]
        namespace_claim["_tenant_id"] = upload_user.tenant_id
    elif upload_api_key_id:
        namespace_claim["_owner_api_key_id"] = upload_api_key_id
        namespace_claim["_tenant_id"] = f"service:{upload_api_key_id.split(':', 1)[-1]}"
    SESSION_STORE.set(diagram_id, namespace_claim)
    logger.info("Stored image for %s (%s bytes, %s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(len(image_bytes)).replace('\n', '').replace('\r', ''), str(file.content_type).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    # Proactive capacity warning (#177)
    img_usage = len(IMAGE_STORE) / IMAGE_STORE.maxsize
    if img_usage >= 0.8:
        logger.warning(
            "IMAGE_STORE at %.0f%% capacity (%d/%d) — oldest entries will be evicted",
            str(img_usage * 100).replace('\n', '').replace('\r', ''), str(len(IMAGE_STORE)).replace('\n', '').replace('\r', ''), str(IMAGE_STORE.maxsize).replace('\n', '').replace('\r', ''),
        )

    record_event(
        "diagrams_uploaded",
        {
            "filename_sha256": hashlib.sha256(
                original_filename.encode("utf-8")
            ).hexdigest(),
            "extension": filename_suffix,
        },
    )
    record_funnel_step(diagram_id, "upload")
    principal_marker = _principal_marker(request)
    return _attach_lifecycle_receipt(attach_export_capability({
        "diagram_id": diagram_id,
        "project_id": project_id,
        "filename": file.filename,
        "size": len(image_bytes),
        "status": "uploaded",
        "restore_capability": restore_capability,
    }, diagram_id, principal_marker=principal_marker), diagram_id, image_present=True, session_present=False, principal=upload_principal)


@router.post(
    "/api/projects/{project_id}/diagrams",
    include_in_schema=False,
)
@limiter.limit("10/minute")
async def upload_diagram_to_project(
    request: Request,
    project_id: str,
    file: UploadFile = File(...),
    _auth=Depends(verify_api_key_or_user_session),
):
    """Compatibility path; the supplied ID is only an authorized reacquisition hint."""
    return await upload_diagram(
        request=request,
        file=file,
        _auth=_auth,
        requested_project_id=project_id,
    )


# ─────────────────────────────────────────────────────────────
# Session Restore
# ─────────────────────────────────────────────────────────────
@router.post("/api/diagrams/{diagram_id}/restore-session")
@limiter.limit("10/minute")
async def restore_session(
    request: Request,
    diagram_id: str,
    body: RestoreSessionRequest,
    _auth=Depends(verify_api_key_or_user_session),
    db=Depends(get_db),
):
    """Re-inject a cached analysis result into the session store.

    The frontend caches analysis data in sessionStorage.  When the backend
    restarts and the in-memory store is wiped, the frontend can push its
    cached copy here to transparently restore the session.
    """
    content_length = request.headers.get("content-length")
    try:
        declared_length = int(content_length) if content_length is not None else 0
    except ValueError:
        raise ArchmorphException(400, "Invalid Content-Length")
    if declared_length > MAX_RESTORE_BODY_BYTES:
        raise ArchmorphException(413, "Restore request body is too large")
    try:
        validate_restore_payload_shape(body.model_dump())
    except AnalysisPayloadTooLarge as exc:
        raise ArchmorphException(
            413,
            detail={
                "error": "restore_payload_too_large",
                "message": str(exc),
                **exc.details,
            },
        )
    analysis = copy.deepcopy(body.analysis)
    if not analysis or not isinstance(analysis, dict):
        raise ArchmorphException(400, "Invalid analysis payload")
    principal = get_request_durable_principal(request)
    if principal is None or not principal["tenant_id"]:
        raise ArchmorphException(401, "Authentication required")
    owner_user_id = principal["owner_user_id"]
    tenant_id = principal["tenant_id"]
    owner_api_key_id = principal["owner_api_key_id"]

    from workspace_store import consume_restore_grant, load_analysis_state, snapshot_payload_hash

    durable = load_analysis_state(
        db,
        diagram_id=diagram_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
    )
    if durable is not None:
        analysis = durable
        decoded_image: Optional[bytes] = None
        restored_content_type: Optional[str] = None
    else:
        try:
            validate_analysis_payload_bounds(analysis)
        except AnalysisPayloadTooLarge as exc:
            raise ArchmorphException(
                413,
                detail={
                    "error": "analysis_payload_too_large",
                    "message": str(exc),
                    **exc.details,
                },
            )
        decoded_image = None
        restored_content_type = None
        if body.image_base64:
            try:
                decoded_image = base64.b64decode(body.image_base64, validate=True)
            except Exception as exc:
                raise ArchmorphException(400, f"Invalid image_base64 payload: {str(exc)}")
            if len(decoded_image) > MAX_UPLOAD_SIZE:
                raise ArchmorphException(
                    413,
                    f"image_base64 too large. Maximum allowed: {MAX_UPLOAD_SIZE // (1024*1024)} MB.",
                )
            restored_content_type = body.image_content_type or "image/png"
            try:
                validate_upload(decoded_image, restored_content_type, None)
            except UploadValidationError as exc:
                raise ArchmorphException(exc.status_code, exc.message)
        claims = decode_restore_capability(
            request,
            diagram_id,
            body.restore_capability,
        )
        payload_hash = snapshot_payload_hash(analysis)
        if claims is None:
            raise ArchmorphException(404, "Diagram not found")
        grant_kwargs = {
            "nonce": str(claims.get("nonce") or ""),
            "owner_user_id": owner_user_id,
            "tenant_id": tenant_id,
            "diagram_id": diagram_id,
            "generation": int(claims.get("generation", -1)),
            "expected_version": int(claims.get("expected_version", -1)),
            "payload_hash": payload_hash,
        }

    analysis["diagram_id"] = diagram_id
    analysis["_tenant_id"] = tenant_id
    if owner_api_key_id:
        analysis["_owner_api_key_id"] = owner_api_key_id
        analysis.pop("_owner_user_id", None)
    else:
        analysis["_owner_user_id"] = owner_user_id
        analysis.pop("_owner_api_key_id", None)

    if durable is None:
        if body.hld:
            analysis["hld"] = body.hld
        if body.hld_markdown:
            analysis["hld_markdown"] = body.hld_markdown
        if body.iac_code:
            analysis["_cached_iac_code"] = body.iac_code
        if body.iac_format:
            analysis["_cached_iac_format"] = body.iac_format

    if durable is not None:
        from workspace_store import _write_session_cache

        _write_session_cache(
            SESSION_STORE,
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            snapshot=analysis,
            version_number=int(analysis["_analysis_version"]),
            owner_api_key_id=owner_api_key_id,
        )
    else:
        _persist_authenticated_analysis(
            db,
            user_id=owner_user_id,
            tenant_id=tenant_id,
            diagram_id=diagram_id,
            session=analysis,
            owner_api_key_id=owner_api_key_id,
            cache_required=True,
            precommit_hook=lambda transaction: (
                consume_restore_grant(transaction, **grant_kwargs, commit=False)
                or (_ for _ in ()).throw(ValueError("Restore grant unavailable"))
            ),
        )
    restored_parts = ["analysis"]
    if durable is None and body.hld:
        restored_parts.append("hld")
    if durable is None and body.iac_code:
        restored_parts.append("iac")
    if durable is None and body.image_base64:
        assert decoded_image is not None
        assert restored_content_type is not None
        IMAGE_STORE[diagram_id] = (
            body.image_base64,
            restored_content_type,
        )
        restored_parts.append("image")
    logger.info("Session restored for %s via client cache (%s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(", ".join(restored_parts)).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
    record_event("sessions_restored", {"diagram_id": diagram_id, "parts": restored_parts})
    next_restore_capability = issue_restore_capability(
        request,
        diagram_id,
        db=db,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        payload_hash=snapshot_payload_hash(analysis),
    )
    return _attach_lifecycle_receipt(attach_export_capability(
        {
            "status": "restored",
            "diagram_id": diagram_id,
            "restored": restored_parts,
            "analysis": analysis,
            "restore_capability": next_restore_capability,
        },
        diagram_id,
        principal_marker=_principal_marker(request),
    ), diagram_id, image_present=diagram_id in IMAGE_STORE, session_present=True)


@router.delete(
    "/api/diagrams/{diagram_id}/purge",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("20/minute")
async def purge_diagram_session(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key),
):
    """Purge uploaded content and derived artifacts for a diagram.

    Retention baseline: upload/session/project/export capability stores use a
    2-hour TTL by default. Browser sessionStorage cache may also hold analysis
    state until tab/session close unless the client clears it.

    This endpoint provides immediate deletion of server-side data for API/UI
    callers, including uploaded bytes, analysis session payloads, project
    indexes, share links, export capabilities, and queued async jobs/events.
    Uploaded data is processed by model services for analysis and is not used
    by Archmorph for model training.
    """
    principal = get_request_durable_principal(request)
    if principal is None or not principal.get("tenant_id"):
        raise ArchmorphException(404, "Diagram not found")
    project_id, diagram_meta = _diagram_project_metadata(
        diagram_id,
        principal=principal,
    )
    from purge_service import PurgeIncompleteError, purge_diagram

    try:
        result = purge_diagram(
            diagram_id=diagram_id,
            owner_user_id=principal["owner_user_id"],
            tenant_id=principal["tenant_id"],
        )
    except PurgeIncompleteError as exc:
        raise ArchmorphException(
            503,
            "Analysis purge is incomplete and can be retried.",
            details={
                "error": "analysis_purge_unavailable",
                "operation_id": exc.operation_id,
                "pending_stage": exc.stage,
            },
            headers={"Retry-After": "5"},
        ) from exc

    record_event("diagram_data_purged", {
        "diagram_id": diagram_id,
        "project_id": project_id,
        "operation_id": result.operation_id,
        "status": result.status,
    })
    purge_confirmation = {
        "status": "purged",
        "operation_id": result.operation_id,
        "server_content_deleted": True,
        "client_cache_action": "clear_session_storage_after_successful_purge",
        "audit_security_logs_retained": True,
    }
    artifact_status = {
        "uploaded_content": "purged",
        "analysis_session": "purged",
        "project_index": "purged",
        "share_links": "confirmed_absent",
        "share_store": "confirmed_absent",
        "export_capabilities": "confirmed_absent",
        "async_jobs": "physically_deleted",
        "iac_chat": "confirmed_absent",
        "durable_analysis": "confirmed_absent",
    }
    trust_receipt = build_trust_receipt(
        diagram_id,
        project_id=project_id,
        uploaded_at=diagram_meta.get("created_at"),
        image_present=False,
        session_present=False,
        artifact_status=artifact_status,
        purge=purge_confirmation,
    )
    return {
        "status": "purged",
        "diagram_id": diagram_id,
        "project_id": project_id,
        "operation_id": result.operation_id,
        "trust_receipt": trust_receipt,
        "purged": result.deleted,
    }


# ─────────────────────────────────────────────────────────────
# Diagrams — Analyze (sync)
# ─────────────────────────────────────────────────────────────

def _retry_after_seconds(exc: Exception, default: int = 30) -> int:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        retry_after = int(value) if value is not None else default
    except (TypeError, ValueError):
        retry_after = default
    return max(1, min(retry_after, 300))


def _raise_analysis_service_failure(exc: Exception) -> None:
    service_error = exc if isinstance(exc, OpenAIServiceError) else handle_openai_error(exc, "Vision analysis")
    if service_error.status_code == 429:
        retry_after = _retry_after_seconds(exc)
        raise ArchmorphException(
            429,
            "Analysis service is busy. Please wait a moment and try again.",
            details={"error": "analysis_retryable", "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    if service_error.retryable:
        raise ArchmorphException(
            503,
            service_error.args[0] if service_error.args else "Analysis service is temporarily unavailable.",
            details={"error": "analysis_retryable", "retry_after_seconds": 30},
            headers={"Retry-After": "30"},
        )
    raise ArchmorphException(service_error.status_code, service_error.args[0] if service_error.args else "Vision analysis failed.")


@router.post(
    "/api/diagrams/{diagram_id}/analyze",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("5/minute")
async def analyze_diagram(request: Request, diagram_id: str, _auth=Depends(verify_api_key_or_user_session)):
    """Analyze an uploaded architecture diagram using GPT-4o vision.

    Detects cloud services and maps them to Azure equivalents using the catalog.
    Includes an image classification pre-check to reject non-architecture images.
    """
    if diagram_id not in IMAGE_STORE:
        raise ArchmorphException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    image_b64, content_type = IMAGE_STORE[diagram_id]
    image_bytes = base64.b64decode(image_b64) if isinstance(image_b64, str) else image_b64
    logger.info("Analyzing diagram %s (%s bytes)", str(diagram_id).replace('\n', '').replace('\r', ''), str(len(image_bytes)).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    principal = get_request_durable_principal(request)
    api_key_principal_id = get_api_key_service_principal(headers)

    if ci_smoke.enabled():
        result = ci_smoke.clone_analysis(diagram_id)
        if user:
            result["_owner_user_id"] = principal["owner_user_id"]
            result["_tenant_id"] = user.tenant_id
        elif api_key_principal_id:
            result["_owner_api_key_id"] = api_key_principal_id
        if user:
            await run_in_threadpool(partial(
                _persist_authenticated_analysis_in_worker,
                    user_id=principal["owner_user_id"],
                    tenant_id=user.tenant_id,
                    diagram_id=diagram_id,
                    session=result,
                    cache_required=True,
                    require_project_membership=True,
            ))
        elif api_key_principal_id:
            await run_in_threadpool(partial(
                _persist_authenticated_analysis_in_worker,
                    user_id=api_key_principal_id,
                    tenant_id=f"service:{api_key_principal_id.split(':', 1)[-1]}",
                    diagram_id=diagram_id,
                    session=result,
                    owner_api_key_id=api_key_principal_id,
                    cache_required=True,
                    require_project_membership=True,
            ))
        else:
            SESSION_STORE[diagram_id] = result
        record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
        record_funnel_step(diagram_id, "analyze")
        return _attach_lifecycle_receipt(
            attach_export_capability(
                result,
                diagram_id,
                principal_marker=_principal_marker(request),
            ),
            diagram_id,
            image_present=True,
            session_present=True,
            principal=principal,
        )

    # No need to pre-compress, vision analyzer and classifier handle it internally
    compressed_bytes, compressed_type = image_bytes, content_type

    # Speculative parallel: classify + analyze concurrently (#299)
    async def _classify():
        try:
            return await asyncio.to_thread(classify_image, compressed_bytes, compressed_type)
        except Exception as exc:
            logger.warning(
                "Image classification failed diagram_id=%s error_type=%s; proceeding",
                str(diagram_id).replace('\n', '').replace('\r', ''),
                type(exc).__name__,
            )
            return {"is_architecture_diagram": True, "confidence": 0.5, "image_type": "unknown", "reason": "Classification unavailable"}

    async def _analyze():
        return await asyncio.to_thread(
            analyze_image,
            compressed_bytes,
            compressed_type,
            diagram_id=diagram_id,
            owner_user_id=(principal or {}).get("owner_user_id"),
            tenant_id=(principal or {}).get("tenant_id"),
        )

    classification, analysis_result_or_exc = await asyncio.gather(
        _classify(),
        _analyze(),
        return_exceptions=True,
    )

    if not classification["is_architecture_diagram"]:
        logger.info("Image rejected for %s: %s (confidence: %s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(classification["reason"]).replace('\n', '').replace('\r', ''), str(classification["confidence"]).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom
        record_event("images_rejected", {"diagram_id": diagram_id, "image_type": classification["image_type"], "reason": classification["reason"]})
        raise ArchmorphException(
            status_code=422,
            detail={
                "error": "not_architecture_diagram",
                "message": f"The uploaded image does not appear to be a cloud architecture diagram. Detected: {classification['image_type']}.",
                "classification": classification,
            },
        )

    logger.info("Image classified as architecture diagram for %s (confidence: %s)", str(diagram_id).replace('\n', '').replace('\r', ''), str(classification["confidence"]).replace('\n', '').replace('\r', ''))  # codeql[py/log-injection] Handled by custom

    if isinstance(analysis_result_or_exc, Exception):
        logger.error("Vision analysis failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(analysis_result_or_exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        _raise_analysis_service_failure(analysis_result_or_exc)

    result = await asyncio.to_thread(_normalize_analysis, analysis_result_or_exc)
    result["diagram_id"] = diagram_id
    result["image_classification"] = classification

    # Save to user history if authenticated (#245)
    if user:
        result["_owner_user_id"] = principal["owner_user_id"]
        result["_tenant_id"] = user.tenant_id
    elif api_key_principal_id:
        result["_owner_api_key_id"] = api_key_principal_id

    if len(SESSION_STORE) >= SESSION_STORE.maxsize:
        logger.warning("Session store at capacity (%d/%d) — oldest sessions will be evicted",
                       str(len(SESSION_STORE)).replace('\n', '').replace('\r', ''), str(SESSION_STORE.maxsize).replace('\n', '').replace('\r', ''))
    if user:
        await run_in_threadpool(partial(
            _persist_authenticated_analysis_in_worker,
                user_id=principal["owner_user_id"],
                tenant_id=user.tenant_id,
                diagram_id=diagram_id,
                session=result,
                cache_required=True,
                require_project_membership=True,
        ))
    elif api_key_principal_id:
        await run_in_threadpool(partial(
            _persist_authenticated_analysis_in_worker,
                user_id=api_key_principal_id,
                tenant_id=f"service:{api_key_principal_id.split(':', 1)[-1]}",
                diagram_id=diagram_id,
                session=result,
                owner_api_key_id=api_key_principal_id,
                cache_required=True,
                require_project_membership=True,
        ))
    else:
        SESSION_STORE[diagram_id] = result
    record_event("analyses_run", {"diagram_id": diagram_id, "services": result["services_detected"]})
    record_funnel_step(diagram_id, "analyze")

    return _attach_lifecycle_receipt(
        attach_export_capability(
            result,
            diagram_id,
            principal_marker=_principal_marker(request),
        ),
        diagram_id,
        image_present=True,
        session_present=True,
        principal=principal,
    )


# ─────────────────────────────────────────────────────────────
# Async Analysis (Issue #172)
# ─────────────────────────────────────────────────────────────
@router.post(
    "/api/diagrams/{diagram_id}/analyze-async",
    dependencies=[Depends(require_diagram_access)],
)
@limiter.limit("5/minute")
async def analyze_diagram_async(
    request: Request,
    diagram_id: str,
    _auth=Depends(verify_api_key_or_user_session),
):
    """Start an async analysis of an uploaded diagram.

    Returns ``202 Accepted`` with a ``job_id``. Use the SSE stream
    endpoint ``GET /api/jobs/{job_id}/stream`` to receive real-time
    progress events, or poll ``GET /api/jobs/{job_id}`` for status.
    """
    if diagram_id not in IMAGE_STORE:
        raise ArchmorphException(404, f"No uploaded image found for diagram {diagram_id}. Upload first.")

    headers = dict(request.headers)
    user = get_user_from_request_headers(headers)
    principal = get_request_durable_principal(request)
    api_key_principal_id = get_api_key_service_principal(headers)

    # Admission control: enforce per-user/per-tenant active-job limits.
    owner_user_id = principal["owner_user_id"] if user else None
    tenant_id = user.tenant_id if user else None
    owner_api_key_id = api_key_principal_id if not user else None
    image_b64, content_type = IMAGE_STORE[diagram_id]
    image_bytes = base64.b64decode(image_b64) if isinstance(image_b64, str) else image_b64
    execution_payload = {
        "diagram_id": diagram_id,
        "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
        "content_type": content_type,
        "model": AZURE_OPENAI_DEPLOYMENT,
        "vision_prompt_hash": VISION_PROMPT_HASH,
    }
    try:
        job = job_manager.submit(
            "analyze",
            diagram_id=diagram_id,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
            owner_api_key_id=owner_api_key_id,
            enforce_admission=True,
            execution_payload=execution_payload,
        )
    except AdmissionRejected as exc:
        raise ArchmorphException(
            429,
            str(exc),
            details={
                "error": "analysis_admission_rejected",
                "scope": exc.scope,
                "active_jobs": exc.active,
                "limit": exc.limit,
            },
            headers={"Retry-After": "30"},
        )
    except (AdmissionStoreError, JobStoreError):
        raise ArchmorphException(
            503,
            "Analysis admission is temporarily unavailable. Please retry shortly.",
            details={"error": "analysis_admission_unavailable"},
            headers={"Retry-After": "30"},
        )
    from starlette.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "diagram_id": diagram_id,
            "status": job.status.value,
            "stream_url": f"/api/jobs/{job.job_id}/stream",
            "status_url": f"/api/jobs/{job.job_id}",
        },
    )


async def _run_analysis_job(job_id: str, payload: Dict[str, Any]) -> None:
    """Background worker for diagram analysis with real progress updates."""
    diagram_id = str(payload["diagram_id"])
    try:
        image_b64, content_type = IMAGE_STORE[diagram_id]
        image_bytes = base64.b64decode(image_b64) if isinstance(image_b64, str) else image_b64
        if hashlib.sha256(image_bytes).hexdigest() != payload.get("image_sha256"):
            job_manager.fail(job_id, "Uploaded image changed after this analysis job was accepted")
            return
        job_manager.update_progress(job_id, 5, "Preprocessing image...", phase="preprocessing")

        if not job_manager.owns_current_lease(job_id):
            return

        # Forward raw bytes directly
        compressed_bytes, compressed_type = image_bytes, content_type

        job_manager.update_progress(job_id, 15, "Classifying image type...", phase="classifying")

        if not job_manager.owns_current_lease(job_id):
            return

        # Classify
        try:
            classification = await asyncio.to_thread(classify_image, compressed_bytes, compressed_type)
        except Exception as exc:
            logger.warning(
                "Classification failed diagram_id=%s error_type=%s",
                str(diagram_id).replace('\n', '').replace('\r', ''),
                type(exc).__name__,
            )
            classification = {"is_architecture_diagram": True, "confidence": 0.5, "image_type": "unknown"}

        if not classification.get("is_architecture_diagram", True):
            job_manager.fail(
                job_id,
                f"Not an architecture diagram. Detected: {classification.get('image_type', 'unknown')}",
            )
            return

        job_manager.update_progress(job_id, 30, "Waiting for model capacity...", phase="waiting_for_model")

        if not job_manager.owns_current_lease(job_id):
            return

        job_manager.update_progress(job_id, 40, "Analyzing cloud services and topology...", phase="analyzing")
        result = await asyncio.to_thread(
            analyze_image,
            compressed_bytes,
            compressed_type,
            diagram_id=diagram_id,
            owner_user_id=(
                getattr(job_manager.get(job_id), "owner_user_id", None)
                or getattr(job_manager.get(job_id), "owner_api_key_id", None)
            ),
            tenant_id=(
                getattr(job_manager.get(job_id), "tenant_id", None)
                or (
                    f"service:{getattr(job_manager.get(job_id), 'owner_api_key_id').split(':', 1)[-1]}"
                    if getattr(job_manager.get(job_id), "owner_api_key_id", None)
                    else None
                )
            ),
        )

        if not job_manager.owns_current_lease(job_id):
            return

        job_manager.update_progress(job_id, 65, "Validating analysis output...", phase="validating")

        result = _normalize_analysis(result)
        result["diagram_id"] = diagram_id
        result["image_classification"] = classification

        job_manager.update_progress(job_id, 70, "Mapping services to Azure equivalents...", phase="mapping")

        job_record = job_manager.get(job_id)
        job_user_id = getattr(job_record, "owner_user_id", None)
        job_tenant_id = getattr(job_record, "tenant_id", None)
        job_api_principal_id = getattr(job_record, "owner_api_key_id", None)
        if job_user_id and job_tenant_id:
            result["_owner_user_id"] = job_user_id
            result["_tenant_id"] = job_tenant_id
        elif job_api_principal_id:
            result["_owner_api_key_id"] = job_api_principal_id

        job_manager.update_progress(job_id, 80, "Saving analysis results...", phase="saving")
        if not job_manager.owns_current_lease(job_id):
            return
        latest_image_b64, _latest_content_type = IMAGE_STORE[diagram_id]
        latest_image_bytes = (
            base64.b64decode(latest_image_b64)
            if isinstance(latest_image_b64, str)
            else latest_image_b64
        )
        if hashlib.sha256(latest_image_bytes).hexdigest() != payload.get("image_sha256"):
            job_manager.fail(job_id, "Uploaded image changed while analysis was running")
            return
        if job_user_id:
            await run_in_threadpool(partial(
                _persist_authenticated_analysis_in_worker,
                    user_id=job_user_id,
                    tenant_id=job_tenant_id,
                    diagram_id=diagram_id,
                    session=result,
                    cache_required=True,
                    require_project_membership=True,
            ))
        elif job_api_principal_id:
            await run_in_threadpool(partial(
                _persist_authenticated_analysis_in_worker,
                    user_id=job_api_principal_id,
                    tenant_id=f"service:{job_api_principal_id.split(':', 1)[-1]}",
                    diagram_id=diagram_id,
                    session=result,
                    owner_api_key_id=job_api_principal_id,
                    cache_required=True,
                    require_project_membership=True,
            ))
        else:
            SESSION_STORE[diagram_id] = result
        job_manager.update_progress(job_id, 90, "Saving guided questions and evidence...", phase="saving")

        record_event("analyses_run", {"diagram_id": diagram_id, "services": result.get("services_detected", 0)})
        record_funnel_step(diagram_id, "analyze")

        if job_api_principal_id:
            logger.debug(
                "Skipping user history persistence for API principal-owned async analysis %s",
                str(diagram_id).replace('\n', '').replace('\r', ''),
            )

        job_manager.update_progress(job_id, 95, "Finalizing...", phase="saving")
        job_principal = {
            "owner_user_id": job_user_id or job_api_principal_id,
            "tenant_id": (
                job_tenant_id
                if job_user_id
                else f"service:{job_api_principal_id.split(':', 1)[-1]}"
                if job_api_principal_id
                else None
            ),
        }
        job_manager.complete(job_id, result=_attach_lifecycle_receipt(
            attach_export_capability(result, diagram_id),
            diagram_id,
            image_present=diagram_id in IMAGE_STORE,
            session_present=True,
            principal=job_principal,
        ))

    except Exception as exc:
        logger.error("Async analysis failed for %s: %s", str(diagram_id).replace('\n', '').replace('\r', ''), str(exc).replace('\n', '').replace('\r', ''), exc_info=True)  # codeql[py/log-injection] Handled by custom
        job_manager.fail(job_id, str(exc))
