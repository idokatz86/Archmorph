"""
Cloud Scanner execution routes.
Leverages the credentials store and the specific cloud scanners 
(AWSScanner, AzureScanner, GCPScanner).
"""
from __future__ import annotations

import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends
from error_envelope import ArchmorphException
from auth import get_user_from_session
from services.credential_manager import get_credentials
from routers.credentials import validate_session
from scanners.aws_scanner import AWSScanner
from scanners.azure_scanner import AzureScanner
from scanners.gcp_scanner import GCPScanner
from cost_optimizer import analyze_live_finops
from compliance_mapper import analyze_live_compliance
from feature_flags import feature_flag_dependency

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post(
    "/api/scanner/run/{provider}",
    response_model=Dict[str, Any],
    dependencies=[Depends(feature_flag_dependency("live_cloud_scanner"))],
)
async def run_cloud_scan(
    provider: str,
    session_token: str = Depends(validate_session),
    user: dict = Depends(get_user_from_session)
):
    """
    Initiate a live scan of cloud architecture using stored credentials.
    """
    try:
        creds = get_credentials(session_token, expected_provider=provider)
    except ArchmorphException as e:
        raise e
    except Exception:
        raise ArchmorphException(401, "Please connect your cloud account before scanning.")

    if provider.lower() == "aws":
        scanner = AWSScanner(credentials=creds)
        report = scanner.perform_full_scan()
        finops = analyze_live_finops(report)
        compliance = analyze_live_compliance(report)
        return {
            "status": "success",
            "provider": "aws",
            "data": report,
            "finops": finops,
            "compliance": compliance
        }
    elif provider.lower() == "azure":
        try:
            scanner = AzureScanner(credentials=creds)
            report = scanner.perform_full_scan()
            finops = analyze_live_finops(report)
            compliance = analyze_live_compliance(report)
            return {
                "status": "success",
                "provider": "azure",
                "data": report,
                "finops": finops,
                "compliance": compliance
            }
        except Exception as e:
            logger.error(f"Error during Azure scan: {e}")
            raise ArchmorphException(500, f"Azure scan failed: {str(e)}")
    elif provider.lower() == "gcp":
        try:
            scanner = GCPScanner(credentials=creds)
            report = scanner.perform_full_scan()
            finops = analyze_live_finops(report)
            compliance = analyze_live_compliance(report)
            return {
                "status": "success",
                "provider": "gcp",
                "data": report,
                "finops": finops,
                "compliance": compliance
            }
        except Exception as e:
            logger.error(f"Error during GCP scan: {e}")
            raise ArchmorphException(500, f"GCP scan failed: {str(e)}")
    else:
        raise ArchmorphException(400, "Unsupported provider")
