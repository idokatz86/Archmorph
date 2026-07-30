"""Authenticated, dual-schema-safe reads for the 013/014 migration bridge."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from auth import (
    AuthProvider,
    get_user_from_bearer_headers_read_only,
    request_has_untrusted_swa_principal,
)
from error_envelope import ArchmorphException, _build_envelope


_RETRY_AFTER = "30"
_DEGRADED_HEADERS = {
    "Cache-Control": "no-store",
    "X-Archmorph-Customer-Mode": "degraded-read-only",
}
_HEALTH_PATHS = frozenset(
    {"/healthz", "/readyz", "/api/health", "/api/schema-compatibility"}
)
_IDENTIFIER = r"[A-Za-z0-9_-]{1,100}"
_SAFE_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("workspace_list", re.compile(r"^/api/workspaces$")),
    ("workspace_get", re.compile(rf"^/api/workspaces/(?P<workspace>{_IDENTIFIER})$")),
    (
        "analysis_list",
        re.compile(rf"^/api/workspaces/(?P<workspace>{_IDENTIFIER})/analyses$"),
    ),
    ("analysis_get", re.compile(rf"^/api/analyses/(?P<analysis>{_IDENTIFIER})$")),
    (
        "version_list",
        re.compile(rf"^/api/analyses/(?P<analysis>{_IDENTIFIER})/versions$"),
    ),
    (
        "version_get",
        re.compile(
            rf"^/api/analyses/(?P<analysis>{_IDENTIFIER})/versions/"
            r"(?P<version>[0-9]{1,10})$"
        ),
    ),
    (
        "artifact_list",
        re.compile(rf"^/api/analyses/(?P<analysis>{_IDENTIFIER})/artifacts$"),
    ),
    (
        "decision_list",
        re.compile(rf"^/api/analyses/(?P<analysis>{_IDENTIFIER})/decisions$"),
    ),
)


def classify_safe_read(path: str) -> tuple[str, dict[str, str]] | None:
    for operation, pattern in _SAFE_ROUTES:
        match = pattern.fullmatch(path)
        if match is not None:
            return operation, match.groupdict()
    return None


def _query_values(request: Request, allowed: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed or key in result:
            raise ArchmorphException(
                400, "Unsupported or duplicate bridge read parameter"
            )
        result[key] = value
    return result


def _integer_parameter(
    values: dict[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = values.get(name)
    if raw is None:
        return default
    if not raw.isdigit():
        raise ArchmorphException(422, f"{name} must be an integer")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ArchmorphException(422, f"{name} is outside the allowed range")
    return value


def _optional_filter(values: dict[str, str], name: str, *, maximum: int) -> str:
    value = values.get(name, "")
    if value and (len(value) > maximum or not re.fullmatch(r"[A-Za-z0-9_-]+", value)):
        raise ArchmorphException(422, f"{name} is invalid")
    return value


def _json_value(value: object) -> object:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row(row: Any) -> dict[str, object]:
    return {str(key): _json_value(value) for key, value in row._mapping.items()}


def _current_revision(connection) -> str:
    revisions = tuple(
        connection.execute(
            text("SELECT version_num FROM alembic_version ORDER BY version_num")
        ).scalars()
    )
    if len(revisions) != 1 or revisions[0] not in {"013", "014"}:
        raise ArchmorphException(503, "Bridge schema compatibility cannot be proven")
    return str(revisions[0])


def _analysis_exists(connection, *, analysis: str, owner: str, tenant: str) -> bool:
    return (
        connection.execute(
            text(
                "SELECT 1 FROM analyses "
                "WHERE id = :analysis AND owner_user_id = :owner "
                "AND tenant_id = :tenant"
            ),
            {"analysis": analysis, "owner": owner, "tenant": tenant},
        ).first()
        is not None
    )


def _authenticated_scope(request: Request) -> tuple[str, str]:
    user = get_user_from_bearer_headers_read_only(dict(request.headers))
    if user is None:
        raise ArchmorphException(401, "Canonical bearer authentication is required")
    owner = (
        user.provider_subject
        if user.provider is AuthProvider.AZURE_AD_B2C and user.provider_subject
        else user.id
    )
    if not owner or not user.tenant_id:
        raise ArchmorphException(401, "Authenticated tenant context is required")
    return owner, user.tenant_id


def execute_safe_read(
    *,
    operation: str,
    identifiers: dict[str, str],
    parameters: dict[str, str],
    owner: str,
    tenant: str,
) -> object:
    """Execute only reviewed SELECT statements in a read-only transaction."""
    from database import engine

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = '5s'"))
                connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            revision = _current_revision(connection)
            scope = {"owner": owner, "tenant": tenant}
            if operation == "workspace_list":
                limit = _integer_parameter(
                    parameters, "limit", default=20, minimum=1, maximum=100
                )
                offset = _integer_parameter(
                    parameters,
                    "offset",
                    default=0,
                    minimum=0,
                    maximum=1_000_000,
                )
                status = _optional_filter(parameters, "status", maximum=20)
                if status and status not in {"active", "archived", "deleting"}:
                    raise ArchmorphException(422, "status is invalid")
                status_clause = " AND status = :status" if status else ""
                query_parameters = {
                    **scope,
                    "status": status,
                    "limit": limit,
                    "offset": offset,
                }
                count = connection.execute(
                    text(
                        "SELECT count(*) FROM workspaces "
                        "WHERE owner_user_id = :owner AND tenant_id = :tenant"
                        + status_clause
                    ),
                    query_parameters,
                ).scalar_one()
                is_default = ", is_default" if revision == "014" else ""
                rows = connection.execute(
                    text(
                        "SELECT id, owner_user_id, tenant_id, name, description, "
                        "source_cloud, target_cloud, status, is_public, created_at, updated_at"
                        f"{is_default} FROM workspaces "
                        "WHERE owner_user_id = :owner AND tenant_id = :tenant"
                        f"{status_clause} ORDER BY created_at DESC, id ASC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    query_parameters,
                )
                workspaces = [_row(item) for item in rows]
                if revision == "013":
                    for workspace in workspaces:
                        workspace["is_default"] = False
                return {
                    "workspaces": workspaces,
                    "total": int(count),
                    "limit": limit,
                    "offset": offset,
                    "customer_mode": "degraded_read_only",
                }
            if operation == "workspace_get":
                is_default = ", is_default" if revision == "014" else ""
                found = connection.execute(
                    text(
                        "SELECT id, owner_user_id, tenant_id, name, description, "
                        "source_cloud, target_cloud, status, is_public, created_at, updated_at"
                        f"{is_default} FROM workspaces WHERE id = :workspace "
                        "AND owner_user_id = :owner AND tenant_id = :tenant"
                    ),
                    {**scope, "workspace": identifiers["workspace"]},
                ).first()
                if found is None:
                    raise ArchmorphException(404, "Workspace not found")
                workspace = _row(found)
                if revision == "013":
                    workspace["is_default"] = False
                return workspace
            if operation == "analysis_list":
                limit = _integer_parameter(
                    parameters, "limit", default=20, minimum=1, maximum=100
                )
                offset = _integer_parameter(
                    parameters,
                    "offset",
                    default=0,
                    minimum=0,
                    maximum=1_000_000,
                )
                workspace = identifiers["workspace"]
                workspace_exists = connection.execute(
                    text(
                        "SELECT 1 FROM workspaces WHERE id = :workspace "
                        "AND owner_user_id = :owner AND tenant_id = :tenant"
                    ),
                    {**scope, "workspace": workspace},
                ).first()
                if workspace_exists is None:
                    raise ArchmorphException(404, "Workspace not found")
                query_parameters = {
                    **scope,
                    "workspace": workspace,
                    "limit": limit,
                    "offset": offset,
                }
                count = connection.execute(
                    text(
                        "SELECT count(*) FROM analyses WHERE workspace_id = :workspace "
                        "AND owner_user_id = :owner AND tenant_id = :tenant"
                    ),
                    query_parameters,
                ).scalar_one()
                rows = connection.execute(
                    text(
                        "SELECT id, workspace_id, source_asset_id, owner_user_id, tenant_id, "
                        "diagram_id, title, source_cloud, target_cloud, status, services_detected, "
                        "confidence_avg, current_version, created_at, updated_at FROM analyses "
                        "WHERE workspace_id = :workspace AND owner_user_id = :owner "
                        "AND tenant_id = :tenant ORDER BY created_at DESC, id ASC "
                        "LIMIT :limit OFFSET :offset"
                    ),
                    query_parameters,
                )
                return {
                    "analyses": [_row(item) for item in rows],
                    "total": int(count),
                    "limit": limit,
                    "offset": offset,
                }
            analysis = identifiers.get("analysis", "")
            if operation == "analysis_get":
                found = connection.execute(
                    text(
                        "SELECT id, workspace_id, source_asset_id, owner_user_id, tenant_id, "
                        "diagram_id, title, source_cloud, target_cloud, status, services_detected, "
                        "confidence_avg, current_version, created_at, updated_at FROM analyses "
                        "WHERE id = :analysis AND owner_user_id = :owner AND tenant_id = :tenant"
                    ),
                    {**scope, "analysis": analysis},
                ).first()
                if found is None:
                    raise ArchmorphException(404, "Analysis not found")
                return _row(found)
            if not _analysis_exists(
                connection,
                analysis=analysis,
                owner=owner,
                tenant=tenant,
            ):
                raise ArchmorphException(404, "Analysis not found")
            if operation == "version_list":
                rows = connection.execute(
                    text(
                        "SELECT id, analysis_id, version_number, label, content_hash, "
                        "created_by, restored_from, created_at FROM analysis_versions "
                        "WHERE analysis_id = :analysis ORDER BY version_number DESC"
                    ),
                    {"analysis": analysis},
                )
                return {"versions": [_row(item) for item in rows]}
            if operation == "version_get":
                found = connection.execute(
                    text(
                        "SELECT id, analysis_id, version_number, label, snapshot, content_hash, "
                        "created_by, restored_from, created_at FROM analysis_versions "
                        "WHERE analysis_id = :analysis AND version_number = :version"
                    ),
                    {"analysis": analysis, "version": int(identifiers["version"])},
                ).first()
                if found is None:
                    raise ArchmorphException(404, "Version not found")
                version = _row(found)
                try:
                    snapshot = json.loads(str(version["snapshot"]))
                except json.JSONDecodeError as error:
                    raise ArchmorphException(
                        503, "Version snapshot is unavailable"
                    ) from error
                if not isinstance(snapshot, dict):
                    raise ArchmorphException(503, "Version snapshot is unavailable")
                for key in (
                    "_owner_user_id",
                    "_tenant_id",
                    "export_capability",
                    "exportCapability",
                ):
                    snapshot.pop(key, None)
                version["snapshot"] = snapshot
                return version
            if operation == "artifact_list":
                artifact_type = _optional_filter(
                    parameters, "artifact_type", maximum=50
                )
                limit = _integer_parameter(
                    parameters, "limit", default=50, minimum=1, maximum=100
                )
                offset = _integer_parameter(
                    parameters,
                    "offset",
                    default=0,
                    minimum=0,
                    maximum=1_000_000,
                )
                type_clause = (
                    " AND artifact_type = :artifact_type" if artifact_type else ""
                )
                query_parameters = {
                    **scope,
                    "analysis": analysis,
                    "artifact_type": artifact_type,
                    "limit": limit,
                    "offset": offset,
                }
                count = connection.execute(
                    text(
                        "SELECT count(*) FROM artifacts WHERE analysis_id = :analysis "
                        "AND owner_user_id = :owner AND tenant_id = :tenant"
                        + type_clause
                    ),
                    query_parameters,
                ).scalar_one()
                rows = connection.execute(
                    text(
                        "SELECT id, analysis_id, version_id, source_asset_id, owner_user_id, "
                        "tenant_id, artifact_type, format, storage_url, content_hash, size_bytes, "
                        "created_at FROM artifacts WHERE analysis_id = :analysis "
                        "AND owner_user_id = :owner AND tenant_id = :tenant"
                        f"{type_clause} ORDER BY created_at DESC, id ASC LIMIT :limit OFFSET :offset"
                    ),
                    query_parameters,
                )
                return {
                    "artifacts": [_row(item) for item in rows],
                    "total": int(count),
                    "limit": limit,
                    "offset": offset,
                }
            if operation == "decision_list":
                decision_type = _optional_filter(
                    parameters, "decision_type", maximum=50
                )
                type_clause = (
                    " AND decision_type = :decision_type" if decision_type else ""
                )
                rows = connection.execute(
                    text(
                        "SELECT id, analysis_id, version_id, owner_user_id, tenant_id, "
                        "decision_type, title, description, severity, status, extra_data, "
                        "created_at, updated_at FROM decisions WHERE analysis_id = :analysis "
                        "AND owner_user_id = :owner AND tenant_id = :tenant"
                        f"{type_clause} ORDER BY created_at DESC, id ASC"
                    ),
                    {**scope, "analysis": analysis, "decision_type": decision_type},
                )
                return {"decisions": [_row(item) for item in rows]}
            raise ArchmorphException(503, "Bridge read route is not proven compatible")
        finally:
            transaction.rollback()


def _error_response(error: ArchmorphException) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=_build_envelope(error.status_code, error.detail, error.details),
        headers={**_DEGRADED_HEADERS, **(error.headers or {})},
    )


def _response_headers(request: Request, *, retry_after: bool = False) -> dict[str, str]:
    headers = {
        **_DEGRADED_HEADERS,
        "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "0",
    }
    if retry_after:
        headers["Retry-After"] = _RETRY_AFTER
    origin = request.headers.get("origin", "")
    allowed = {
        item.strip()
        for item in os.getenv("ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    if origin and origin in allowed:
        headers.update(
            {
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Origin": origin,
                "Vary": "Origin",
            }
        )
    return headers


def _canonical_ingress_error(request: Request) -> JSONResponse | None:
    if request_has_untrusted_swa_principal(request.headers):
        return JSONResponse(
            _build_envelope(
                401,
                "x-ms-client-principal is not accepted on this deployment. "
                "Use the standard signed bearer flow.",
                {"error": "untrusted_swa_principal"},
            ),
            status_code=401,
            headers=_response_headers(request),
        )
    from main import ArchmorphMiddleware

    error = ArchmorphMiddleware._validate_trusted_origin(request, "bridge-read-only")
    if error is not None:
        error.headers.update(_response_headers(request))
    return error


async def bridge_read_response(request: Request) -> JSONResponse:
    classified = classify_safe_read(request.url.path)
    if classified is None:
        return maintenance_response(request)

    operation, identifiers = classified
    allowed_parameters = {
        "workspace_list": {"status", "limit", "offset"},
        "analysis_list": {"limit", "offset"},
        "artifact_list": {"artifact_type", "limit", "offset"},
        "decision_list": {"decision_type"},
    }.get(operation, set())
    try:
        parameters = _query_values(request, allowed_parameters)
        owner, tenant = _authenticated_scope(request)
        payload = await run_in_threadpool(
            lambda: execute_safe_read(
                operation=operation,
                identifiers=identifiers,
                parameters=parameters,
                owner=owner,
                tenant=tenant,
            )
        )
    except ArchmorphException as error:
        response = _error_response(error)
        response.headers.update(_response_headers(request))
        return response
    return JSONResponse(payload, headers=_response_headers(request))


def maintenance_response(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "bridge_read_only",
            "customer_mode": "degraded_read_only",
            "retryable": True,
            "reason": "route_not_proven_dual_schema_read_safe",
        },
        status_code=503,
        headers=_response_headers(request, retry_after=True),
    )


class BridgeReadOnlyMiddleware(BaseHTTPMiddleware):
    """Serve reviewed reads and block every mutation/effectful or unknown GET."""

    async def dispatch(self, request: Request, call_next: Callable):
        classified = classify_safe_read(request.url.path)
        if request.method == "GET" and classified is not None:
            ingress_error = _canonical_ingress_error(request)
            if ingress_error is not None:
                return ingress_error
            return await bridge_read_response(request)
        if request.url.path in _HEALTH_PATHS:
            return await call_next(request)
        if request.method == "OPTIONS" and classified is not None:
            return await call_next(request)
        return maintenance_response(request)
