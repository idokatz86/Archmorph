"""
SSO/SAML/SCIM routes (#496) — Enterprise identity federation.

Provides SAML 2.0 SP endpoints (metadata, ACS, SLO) and SCIM 2.0
provisioning endpoints for automated user/group lifecycle management.
"""

import hashlib
import logging
import os
import secrets
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Header, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from error_envelope import ArchmorphException
from routers.shared import limiter
from session_store import get_store

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Stores ───────────────────────────────────────────────────
_scim_user_store = get_store("scim_users", maxsize=2000, ttl=86400)
_scim_group_store = get_store("scim_groups", maxsize=500, ttl=86400)

# ── SAML Configuration ──────────────────────────────────────
SAML_ENTITY_ID = os.getenv("SAML_ENTITY_ID", "")
SAML_ACS_URL = os.getenv("SAML_ACS_URL", "")
SAML_IDP_METADATA_URL = os.getenv("SAML_IDP_METADATA_URL", "")
SAML_CERTIFICATE = os.getenv("SAML_CERTIFICATE", "")

# ── SCIM Configuration ──────────────────────────────────────
SCIM_BEARER_TOKEN = os.getenv("SCIM_BEARER_TOKEN", "")

_NS_SAML_MD = "urn:oasis:names:tc:SAML:2.0:metadata"
_NS_DS = "http://www.w3.org/2000/09/xmldsig#"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _require_saml_config():
    """Validate that SAML env vars are present."""
    if not SAML_ENTITY_ID or not SAML_ACS_URL:
        raise ArchmorphException(503, "SAML is not configured on this instance")


def _verify_scim_token(authorization: Optional[str]):
    """Validate SCIM Bearer token."""
    if not SCIM_BEARER_TOKEN:
        raise ArchmorphException(503, "SCIM is not configured on this instance")
    if not authorization or not authorization.startswith("Bearer "):
        raise ArchmorphException(401, "Missing or malformed Authorization header")
    token = authorization[7:]
    if not secrets.compare_digest(token, SCIM_BEARER_TOKEN):
        raise ArchmorphException(401, "Invalid SCIM bearer token")


# ─────────────────────────────────────────────────────────────
# SAML Models
# ─────────────────────────────────────────────────────────────

class SAMLAssertionRequest(BaseModel):
    saml_response: str = Field(..., alias="SAMLResponse", description="Base64 SAML response")
    relay_state: Optional[str] = Field(None, alias="RelayState")


class SAMLLogoutRequest(BaseModel):
    saml_request: Optional[str] = Field(None, alias="SAMLRequest")
    saml_response: Optional[str] = Field(None, alias="SAMLResponse")
    relay_state: Optional[str] = Field(None, alias="RelayState")


# ─────────────────────────────────────────────────────────────
# SCIM Models
# ─────────────────────────────────────────────────────────────

class SCIMName(BaseModel):
    givenName: Optional[str] = None
    familyName: Optional[str] = None


class SCIMEmail(BaseModel):
    value: str
    type: Optional[str] = "work"
    primary: Optional[bool] = True


class SCIMUserCreate(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    userName: str
    name: Optional[SCIMName] = None
    emails: Optional[List[SCIMEmail]] = None
    displayName: Optional[str] = None
    active: bool = True
    externalId: Optional[str] = None


class SCIMUserPatch(BaseModel):
    schemas: List[str] = ["urn:ietf:params:scim:api:messages:2.0:PatchOp"]
    Operations: List[Dict[str, Any]] = []


# ─────────────────────────────────────────────────────────────
# SAML Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/api/auth/saml/metadata")
@limiter.limit("10/minute")
async def saml_metadata(request: Request):
    """Return SAML SP metadata as XML."""
    _require_saml_config()

    root = Element(f"{{{_NS_SAML_MD}}}EntityDescriptor")
    root.set("entityID", SAML_ENTITY_ID)
    root.set("xmlns:md", _NS_SAML_MD)
    root.set("xmlns:ds", _NS_DS)

    sp_sso = SubElement(root, f"{{{_NS_SAML_MD}}}SPSSODescriptor")
    sp_sso.set("AuthnRequestsSigned", "true")
    sp_sso.set("WantAssertionsSigned", "true")
    sp_sso.set("protocolSupportEnumeration", "urn:oasis:names:tc:SAML:2.0:protocol")

    if SAML_CERTIFICATE:
        key_desc = SubElement(sp_sso, f"{{{_NS_SAML_MD}}}KeyDescriptor")
        key_desc.set("use", "signing")
        key_info = SubElement(key_desc, f"{{{_NS_DS}}}KeyInfo")
        x509_data = SubElement(key_info, f"{{{_NS_DS}}}X509Data")
        x509_cert = SubElement(x509_data, f"{{{_NS_DS}}}X509Certificate")
        x509_cert.text = SAML_CERTIFICATE

    acs = SubElement(sp_sso, f"{{{_NS_SAML_MD}}}AssertionConsumerService")
    acs.set("Binding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST")
    acs.set("Location", SAML_ACS_URL)
    acs.set("index", "1")

    xml_bytes = tostring(root, encoding="unicode", xml_declaration=True)
    return Response(content=xml_bytes, media_type="application/xml")


@router.post("/api/auth/saml/acs")
@limiter.limit("10/minute")
async def saml_acs(request: Request):
    """SAML Assertion Consumer Service — process IdP response.

    In production this must validate the XML signature against the IdP
    certificate configured via SAML_IDP_METADATA_URL.  This implementation
    provides the endpoint scaffold; full XML-DSIG validation requires a
    library such as ``python3-saml`` or ``signxml``.
    """
    _require_saml_config()

    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState")

    if not saml_response:
        raise ArchmorphException(400, "Missing SAMLResponse in form data")

    # NOTE: Full SAML response validation (XML-DSIG, conditions, audience)
    # requires python3-saml or signxml.  This scaffold extracts minimal
    # data and returns a session stub.

    import base64
    import defusedxml.ElementTree as ET

    _parse_failed = False
    try:
        decoded = base64.b64decode(saml_response)
        root = ET.fromstring(decoded)
    except Exception:
        _parse_failed = True
    if _parse_failed:
        raise ArchmorphException(400, "Invalid SAMLResponse encoding")

    # Extract NameID (best-effort; namespace-agnostic search)
    name_id = None
    for elem in root.iter():
        if elem.tag.endswith("NameID"):
            name_id = elem.text
            break

    if not name_id:
        raise ArchmorphException(400, "Could not extract NameID from SAML assertion")

    # Generate a session stub (real implementation delegates to auth.generate_session_token)
    session_id = hashlib.sha256(f"saml:{name_id}:{secrets.token_hex(8)}".encode()).hexdigest()[:32]

    logger.info("SAML ACS processed for NameID=%s", str(name_id).replace('\n', '').replace('\r', ''))

    return {
        "status": "authenticated",
        "name_id": name_id,
        "session_id": session_id,
        "relay_state": relay_state,
    }


@router.post("/api/auth/saml/slo")
@limiter.limit("10/minute")
async def saml_slo(request: Request):
    """SAML Single Logout — process logout request/response from IdP."""
    _require_saml_config()

    form = await request.form()
    saml_request = form.get("SAMLRequest")
    saml_response = form.get("SAMLResponse")

    if not saml_request and not saml_response:
        raise ArchmorphException(400, "Missing SAMLRequest or SAMLResponse")

    logger.info("SAML SLO processed")
    return {"status": "logged_out"}


# ─────────────────────────────────────────────────────────────
# SCIM Endpoints
# ─────────────────────────────────────────────────────────────

def _scim_user_resource(user_id: str, data: dict) -> dict:
    """Format a stored user as a SCIM 2.0 User resource."""
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": user_id,
        "userName": data.get("userName", ""),
        "name": data.get("name"),
        "emails": data.get("emails"),
        "displayName": data.get("displayName"),
        "active": data.get("active", True),
        "externalId": data.get("externalId"),
        "meta": {
            "resourceType": "User",
        },
    }


@router.get("/api/auth/scim/v2/Users")
@limiter.limit("30/minute")
async def scim_list_users(
    request: Request,
    authorization: Optional[str] = Header(None),
    startIndex: int = 1,
    count: int = 100,
):
    """SCIM 2.0 — List provisioned users."""
    _verify_scim_token(authorization)

    all_keys = _scim_user_store.keys("scim:user:*")
    total = len(all_keys)

    # Pagination (SCIM is 1-indexed)
    start = max(startIndex - 1, 0)
    page_keys = all_keys[start : start + count]
    resources = []
    for key in page_keys:
        data = _scim_user_store.get(key)
        if data:
            uid = key.replace("scim:user:", "")
            resources.append(_scim_user_resource(uid, data))

    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


@router.post("/api/auth/scim/v2/Users", status_code=201)
@limiter.limit("10/minute")
async def scim_create_user(
    request: Request,
    body: SCIMUserCreate,
    authorization: Optional[str] = Header(None),
):
    """SCIM 2.0 — Provision a new user."""
    _verify_scim_token(authorization)

    # Check for duplicate userName
    for key in _scim_user_store.keys("scim:user:*"):
        existing = _scim_user_store.get(key)
        if existing and existing.get("userName") == body.userName:
            raise ArchmorphException(409, f"User with userName '{body.userName}' already exists")

    user_id = hashlib.sha256(f"scim:{body.userName}:{secrets.token_hex(4)}".encode()).hexdigest()[:24]
    user_data = body.model_dump()
    _scim_user_store.set(f"scim:user:{user_id}", user_data)

    logger.info("SCIM user provisioned: %s (id=%s)", str(body.userName).replace('\n', '').replace('\r', ''), user_id)
    return _scim_user_resource(user_id, user_data)


@router.patch("/api/auth/scim/v2/Users/{user_id}")
@limiter.limit("10/minute")
async def scim_patch_user(
    request: Request,
    user_id: str,
    body: SCIMUserPatch,
    authorization: Optional[str] = Header(None),
):
    """SCIM 2.0 — Update a user via PATCH operations."""
    _verify_scim_token(authorization)

    store_key = f"scim:user:{user_id}"
    user_data = _scim_user_store.get(store_key)
    if not user_data:
        raise ArchmorphException(404, f"User '{user_id}' not found")

    for op in body.Operations:
        operation = op.get("op", "").lower()
        path = op.get("path", "")
        value = op.get("value")

        if operation == "replace":
            if path and value is not None:
                user_data[path] = value
            elif isinstance(value, dict):
                user_data.update(value)
        elif operation == "add":
            if path and value is not None:
                user_data[path] = value
        elif operation == "remove":
            if path and path in user_data:
                del user_data[path]

    _scim_user_store.set(store_key, user_data)
    logger.info("SCIM user updated: %s", str(user_id).replace('\n', '').replace('\r', ''))
    return _scim_user_resource(user_id, user_data)


@router.delete("/api/auth/scim/v2/Users/{user_id}", status_code=204)
@limiter.limit("10/minute")
async def scim_delete_user(
    request: Request,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    """SCIM 2.0 — Deprovision (delete) a user."""
    _verify_scim_token(authorization)

    store_key = f"scim:user:{user_id}"
    if store_key not in _scim_user_store:
        raise ArchmorphException(404, f"User '{user_id}' not found")

    _scim_user_store.delete(store_key)
    logger.info("SCIM user deprovisioned: %s", user_id)
    return Response(status_code=204)


@router.get("/api/auth/scim/v2/Groups")
@limiter.limit("30/minute")
async def scim_list_groups(
    request: Request,
    authorization: Optional[str] = Header(None),
    startIndex: int = 1,
    count: int = 100,
):
    """SCIM 2.0 — List provisioned groups."""
    _verify_scim_token(authorization)

    all_keys = _scim_group_store.keys("scim:group:*")
    total = len(all_keys)

    start = max(startIndex - 1, 0)
    page_keys = all_keys[start : start + count]
    resources = []
    for key in page_keys:
        data = _scim_group_store.get(key)
        if data:
            gid = key.replace("scim:group:", "")
            resources.append({
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                "id": gid,
                "displayName": data.get("displayName", ""),
                "members": data.get("members", []),
                "meta": {"resourceType": "Group"},
            })

    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }
