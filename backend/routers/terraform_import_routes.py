"""
Terraform / CF / ARM import routes (#497).

Upload infrastructure state/template files and receive an Archmorph
analysis schema ready for visualization and cost estimation.
"""

import logging

from fastapi import APIRouter, Request, UploadFile, File, Depends

from error_envelope import ArchmorphException
from routers.shared import limiter, verify_api_key
from services.terraform_import import (
    parse_terraform_state,
    parse_cloudformation,
    parse_arm_template,
    SUPPORTED_FORMATS,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


async def _read_upload(file: UploadFile) -> str:
    """Read and validate an uploaded file."""
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise ArchmorphException(413, "File exceeds 10 MB limit")
    if not content:
        raise ArchmorphException(400, "Uploaded file is empty")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        raise ArchmorphException(400, "File must be UTF-8 encoded JSON")


@router.post("/api/import/terraform")
@limiter.limit("5/minute")
async def import_terraform(request: Request, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    """Upload a Terraform tfstate file and receive an Archmorph analysis schema."""
    text = await _read_upload(file)
    try:
        result = parse_terraform_state(text)
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))
    except Exception as exc:
        logger.exception("Terraform import failed")
        raise ArchmorphException(422, f"Failed to parse Terraform state: {exc}")

    logger.info("Terraform import: %d resources extracted", result["total_resources"])
    return result


@router.post("/api/import/cloudformation")
@limiter.limit("5/minute")
async def import_cloudformation(request: Request, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    """Upload a CloudFormation template and receive an Archmorph analysis schema."""
    text = await _read_upload(file)
    try:
        result = parse_cloudformation(text)
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))
    except Exception as exc:
        logger.exception("CloudFormation import failed")
        raise ArchmorphException(422, f"Failed to parse CloudFormation template: {exc}")

    logger.info("CloudFormation import: %d resources extracted", result["total_resources"])
    return result


@router.post("/api/import/arm")
@limiter.limit("5/minute")
async def import_arm(request: Request, file: UploadFile = File(...), _auth=Depends(verify_api_key)):
    """Upload an ARM deployment template and receive an Archmorph analysis schema."""
    text = await _read_upload(file)
    try:
        result = parse_arm_template(text)
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))
    except Exception as exc:
        logger.exception("ARM import failed")
        raise ArchmorphException(422, f"Failed to parse ARM template: {exc}")

    logger.info("ARM import: %d resources extracted", result["total_resources"])
    return result


@router.get("/api/import/supported-formats")
async def get_supported_formats(request: Request):
    """List supported infrastructure import formats."""
    return {"formats": SUPPORTED_FORMATS}
