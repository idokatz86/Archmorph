from error_envelope import ArchmorphException
"""
Infrastructure import routes.

Split from diagrams.py for maintainability (#284).
"""

from fastapi import APIRouter, Request, Depends
from pydantic import Field
from strict_models import StrictBaseModel
import asyncio
import json
import logging

from routers.shared import (
    generate_session_id,
    limiter,
    persist_diagram_mutation_async,
    verify_api_key,
)
from usage_metrics import record_event, record_funnel_step
from infra_import import parse_infrastructure, detect_format, InfraFormat

logger = logging.getLogger(__name__)

router = APIRouter(tags=["infra"])

_MAX_IMPORT_CONTENT_CHARS = 10 * 1024 * 1024


class InfraImportRequest(StrictBaseModel):
    """Request body for infrastructure file import."""
    content: str = Field(..., min_length=10, max_length=_MAX_IMPORT_CONTENT_CHARS)
    format: str = Field(default="auto", pattern="^(auto|terraform_state|terraform_hcl|cloudformation)$")
    filename: str = Field(default="unknown")


@router.post("/api/import/infrastructure")
@limiter.limit("5/minute")
async def import_infrastructure(request: Request, body: InfraImportRequest, _auth=Depends(verify_api_key)):
    """Import infrastructure-as-code files to create an architecture analysis.

    Supports Terraform State (.tfstate), Terraform HCL (.tf), and
    CloudFormation templates (JSON/YAML). Auto-detects format when
    format='auto'.
    """
    # Auto-detect format
    if body.format == "auto":
        fmt = detect_format(body.filename, body.content)
        if fmt is None:
            raise ArchmorphException(400, "Could not auto-detect file format. "
                              "Specify format as terraform_state, terraform_hcl, or cloudformation.")
    else:
        try:
            fmt = InfraFormat(body.format)
        except ValueError:
            raise ArchmorphException(400, f"Unsupported format: {body.format}")

    diagram_id = generate_session_id("import")

    try:
        analysis = await asyncio.to_thread(
            parse_infrastructure, body.content, fmt, diagram_id
        )
    except ValueError as e:
        raise ArchmorphException(400, str(e))
    except Exception as e:
        logger.error("Infrastructure import failed: %s", e, exc_info=True)
        raise ArchmorphException(500, "Failed to parse infrastructure file")

    await persist_diagram_mutation_async(
        request,
        diagram_id,
        analysis,
        artifact_type="infrastructure_import",
        artifact_format="json",
        artifact_content=json.dumps(
            {
                "diagram_id": diagram_id,
                "source_format": fmt.value,
                "source_provider": analysis.get("source_provider"),
                "services_detected": analysis.get("services_detected", 0),
                "mappings": analysis.get("mappings", []),
                "import_metadata": analysis.get("import_metadata", {}),
            },
            sort_keys=True,
            default=str,
        ),
        label=f"infrastructure-import-{fmt.value}",
    )
    record_event("infra_imported", {
        "diagram_id": diagram_id,
        "format": fmt.value,
        "services": analysis["services_detected"],
    })
    record_funnel_step(diagram_id, "import")

    return {
        "diagram_id": diagram_id,
        "source_format": fmt.value,
        "services_detected": analysis["services_detected"],
        "source_provider": analysis["source_provider"],
        "mappings": analysis["mappings"],
        "zones": analysis["zones"],
        "service_connections": analysis["service_connections"],
        "confidence_summary": analysis["confidence_summary"],
        "architecture_patterns": analysis["architecture_patterns"],
        "import_metadata": analysis.get("import_metadata", {}),
    }
