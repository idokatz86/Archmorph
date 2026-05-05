"""
Routes for securely managing cloud scanner credentials. 
Issue #413 - Secure Credential Management.
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Header, Depends
from pydantic import Field
from strict_models import StrictBaseModel

from services.credential_manager import store_credentials, get_credentials, clear_credentials
from error_envelope import ArchmorphException
from auth import get_user_from_session
from audit_logging import audit_logger
from routers.shared import limiter

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Pydantic Models for Input ---

class AWSCredentialsInput(StrictBaseModel):
    auth_method: str = Field(..., description="access_key, sso, instance_profile, assume_role")
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    session_token: Optional[str] = None
    role_arn: Optional[str] = None

class GCPCredentialsInput(StrictBaseModel):
    auth_method: str = Field(..., description="service_account_json, oauth2, workload_identity")
    service_account_json: Optional[Dict[str, Any]] = None

class AzureCredentialsInput(StrictBaseModel):
    auth_method: str = Field(..., description="service_principal, managed_identity, default")
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    subscription_id: Optional[str] = None


class CredentialResponse(StrictBaseModel):
    status: str = "ok"
    provider: str
    message: str


def validate_session(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise ArchmorphException(401, "Missing or invalid authorization header")
    return authorization.split(" ")[1]


@router.post("/api/credentials/aws", response_model=CredentialResponse)
@limiter.limit("5/minute")
async def store_aws_credentials(request: Request, 
    payload: AWSCredentialsInput,
    session_token: str = Depends(validate_session),
    user: dict = Depends(get_user_from_session)
):
    """Store AWS credentials in the secure transient store."""
    if payload.auth_method == "access_key" and not (payload.access_key_id and payload.secret_access_key):
        raise ArchmorphException(400, "Access Key ID and Secret Access Key are required for access_key auth.")
    
    # Audit log the credential event (never log the keys themselves!)
    audit_logger.log_event(
        event_type="CREDENTIALS_STORED",
        user_id=user["id"],
        details={"provider": "aws", "auth_method": payload.auth_method},
        ip_address="<hidden>"
    )

    creds = payload.model_dump(exclude_none=True)
    store_credentials(session_token, "aws", creds)
    
    return {"status": "ok", "provider": "aws", "message": "AWS credentials securely stored."}


@router.post("/api/credentials/azure", response_model=CredentialResponse)
@limiter.limit("5/minute")
async def store_azure_credentials(request: Request, 
    payload: AzureCredentialsInput,
    session_token: str = Depends(validate_session),
    user: dict = Depends(get_user_from_session)
):
    """Store Azure credentials in the secure transient store."""
    if payload.auth_method == "service_principal":
        if not all([payload.client_id, payload.client_secret, payload.tenant_id]):
            raise ArchmorphException(400, "Service principal requires client_id, client_secret, and tenant_id.")

    audit_logger.log_event(
        event_type="CREDENTIALS_STORED",
        user_id=user["id"],
        details={"provider": "azure", "auth_method": payload.auth_method},
        ip_address="<hidden>"
    )

    creds = payload.model_dump(exclude_none=True)
    store_credentials(session_token, "azure", creds)
    
    return {"status": "ok", "provider": "azure", "message": "Azure credentials securely stored."}


@router.delete("/api/credentials", response_model=Dict[str, str])
async def delete_credentials(
    session_token: str = Depends(validate_session),
    user: dict = Depends(get_user_from_session)
):
    """Immediately remove all credentials for the current session."""
    clear_credentials(session_token)
    audit_logger.log_event(
        event_type="CREDENTIALS_DELETED",
        user_id=user["id"],
        details={"reason": "user_logout_or_disconnect"},
        ip_address="<hidden>"
    )
    return {"status": "deleted", "message": "Credentials have been safely scrubbed."}


@router.post("/api/credentials/validate", response_model=Dict[str, Any])
@limiter.limit("3/minute")
async def validate_active_credentials(request: Request, 
    provider: str,
    session_token: str = Depends(validate_session),
    user: dict = Depends(get_user_from_session)
):
    """
    Test the currently stored credentials to ensure they work.
    (Mock implementation in this phase).
    """
    # Retrieve securely
    get_credentials(session_token, expected_provider=provider)
    
    # TODO: Connect to Boto3 / Azure SDK to validate identity.
    # For now, return mock success if we successfully decrypted them.
    audit_logger.log_event(
        event_type="CREDENTIALS_VALIDATED",
        user_id=user["id"],
        details={"provider": provider, "status": "success"},
        ip_address="<hidden>"
    )
    
    return {
        "status": "valid",
        "provider": provider,
        "permissions_status": "ok",
        "missing_permissions": []
    }
