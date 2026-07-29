import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
BRIDGE = BACKEND / "bridge_overlay" / "bridge_readonly.py"
SPEC = importlib.util.spec_from_file_location("bridge_readonly", BRIDGE)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(bridge.BridgeReadOnlyMiddleware)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/api/schema-compatibility")
    async def compatibility():
        return {"status": "compatible"}

    @app.get("/api/replays")
    async def effectful_get():
        return {"unsafe": True}

    @app.post("/api/workspaces")
    async def create_workspace():
        return {"unsafe": True}

    @app.options("/api/workspaces")
    async def workspace_options():
        return {"status": "preflight"}

    return app


def _schema(engine, revision: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(50))"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(
            text(
                "CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY, "
                "owner_user_id VARCHAR(100) NOT NULL, tenant_id VARCHAR(100), "
                "name VARCHAR(300) NOT NULL, description TEXT, source_cloud VARCHAR(20), "
                "target_cloud VARCHAR(20), status VARCHAR(20), is_public BOOLEAN, "
                + ("is_default BOOLEAN, " if revision == "014" else "")
                + "created_at TIMESTAMP, updated_at TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE analyses (id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36), "
                "source_asset_id VARCHAR(36), owner_user_id VARCHAR(100), tenant_id VARCHAR(100), "
                "diagram_id VARCHAR(100), title VARCHAR(300), source_cloud VARCHAR(20), "
                "target_cloud VARCHAR(20), status VARCHAR(20), services_detected INTEGER, "
                "confidence_avg FLOAT, current_version INTEGER, created_at TIMESTAMP, "
                "updated_at TIMESTAMP)"
            )
        )


def _seed(engine) -> None:
    with engine.begin() as connection:
        for owner, tenant, suffix in (
            ("owner-a", "tenant-a", "a"),
            ("owner-b", "tenant-b", "b"),
        ):
            connection.execute(
                text(
                    "INSERT INTO workspaces "
                    "(id, owner_user_id, tenant_id, name, source_cloud, target_cloud, "
                    "status, is_public, created_at, updated_at) VALUES "
                    "(:id, :owner, :tenant, :name, 'aws', 'azure', 'active', false, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": f"workspace-{suffix}",
                    "owner": owner,
                    "tenant": tenant,
                    "name": f"Workspace {suffix.upper()}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO analyses "
                    "(id, workspace_id, owner_user_id, tenant_id, title, source_cloud, "
                    "target_cloud, status, services_detected, current_version, created_at, "
                    "updated_at) VALUES (:id, :workspace, :owner, :tenant, :title, "
                    "'aws', 'azure', 'completed', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": f"analysis-{suffix}",
                    "workspace": f"workspace-{suffix}",
                    "owner": owner,
                    "tenant": tenant,
                    "title": f"Analysis {suffix.upper()}",
                },
            )


def test_bridge_overlay_is_bounded_requires_postgres_and_never_runs_ddl():
    sitecustomize = (BACKEND / "bridge_overlay" / "sitecustomize.py").read_text()
    entrypoint = (BACKEND / "bridge_overlay" / "bridge_entrypoint.py").read_text()
    readonly = BRIDGE.read_text()
    ast.parse(sitecustomize)
    ast.parse(entrypoint)
    ast.parse(readonly)

    assert "Base.metadata.create_all" not in sitecustomize + entrypoint + readonly
    assert 'os.environ.setdefault("ENFORCE_POSTGRES", "true")' in sitecustomize
    assert 'os.environ.setdefault("SCHEDULER_DISABLED", "1")' in sitecustomize
    assert '_BRIDGE_REVISIONS = frozenset({"013", "014"})' in sitecustomize
    assert 'text("SELECT 1")' in sitecustomize
    assert 'text("SELECT version_num FROM alembic_version ORDER BY version_num")' in sitecustomize
    assert "database.database_readiness = _bridge_database_readiness" in sitecustomize
    assert "ArchmorphMiddleware._ORIGIN_LOCK_SKIP" in entrypoint
    assert "job_queue.durable_job_worker.start = _bridge_worker_start" in entrypoint
    assert "class BridgeReadOnlyMiddleware" in readonly
    assert "SET TRANSACTION READ ONLY" in readonly
    assert "INSERT " not in readonly
    assert "UPDATE " not in readonly
    assert "DELETE " not in readonly
    assert "SESSION_STORE" not in readonly
    assert "USER_CACHE" not in readonly
    assert "USER_STORE" not in readonly
    assert "get_user_from_bearer_headers_read_only" in readonly


def test_bridge_image_requires_immutable_base_and_includes_read_adapter():
    dockerfile = (BACKEND / "bridge_overlay" / "Dockerfile").read_text()
    assert "ARG BRIDGE_BASE_IMAGE" in dockerfile
    assert "FROM ${BRIDGE_BASE_IMAGE}" in dockerfile
    assert "bridge_entrypoint:app" in dockerfile
    assert "bridge_readonly.py /app/bridge_readonly.py" in dockerfile
    assert ":latest" not in dockerfile


@pytest.mark.parametrize("revision", ["013", "014"])
def test_safe_core_reads_are_dual_schema_and_tenant_isolated(monkeypatch, revision):
    engine = create_engine("sqlite://")
    _schema(engine, revision)
    _seed(engine)
    import database

    monkeypatch.setattr(database, "engine", engine)
    own = bridge.execute_safe_read(
        operation="workspace_list",
        identifiers={},
        parameters={},
        owner="owner-a",
        tenant="tenant-a",
    )
    assert [item["id"] for item in own["workspaces"]] == ["workspace-a"]
    assert own["customer_mode"] == "degraded_read_only"

    with pytest.raises(bridge.ArchmorphException, match="Analysis not found"):
        bridge.execute_safe_read(
            operation="analysis_get",
            identifiers={"analysis": "analysis-b"},
            parameters={},
            owner="owner-a",
            tenant="tenant-a",
        )


def test_safe_read_requires_canonical_authenticated_tenant(monkeypatch):
    client = TestClient(_app())
    response = client.get("/api/workspaces")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(
        bridge,
        "get_user_from_bearer_headers_read_only",
        lambda _headers: SimpleNamespace(
            id="owner-a",
            tenant_id=None,
            provider=bridge.AuthProvider.GOOGLE,
            provider_subject="owner-a",
        ),
    )
    response = client.get("/api/workspaces")
    assert response.status_code == 401


def test_authenticated_safe_read_uses_canonical_principal_and_never_browser_scope(
    monkeypatch,
):
    observed = {}
    monkeypatch.setattr(
        bridge,
        "get_user_from_bearer_headers_read_only",
        lambda _headers: SimpleNamespace(
            id="legacy-b2c-id",
            tenant_id="tenant-a",
            provider=bridge.AuthProvider.AZURE_AD_B2C,
            provider_subject="canonical-owner",
        ),
    )

    def execute(**kwargs):
        observed.update(kwargs)
        return {"workspaces": [], "total": 0, "limit": 20, "offset": 0}

    monkeypatch.setattr(bridge, "execute_safe_read", execute)
    response = TestClient(_app()).get(
        "/api/workspaces?limit=20&offset=0",
        headers={"Authorization": "Bearer signed-session"},
    )
    assert response.status_code == 200
    assert response.headers["x-archmorph-customer-mode"] == "degraded-read-only"
    assert response.headers["cache-control"] == "no-store"
    assert observed["owner"] == "canonical-owner"
    assert observed["tenant"] == "tenant-a"


def test_safe_read_cors_reflects_only_reviewed_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://frontend.example")
    monkeypatch.setattr(
        bridge,
        "get_user_from_bearer_headers_read_only",
        lambda _headers: SimpleNamespace(
            id="owner-a",
            tenant_id="tenant-a",
            provider=bridge.AuthProvider.GOOGLE,
            provider_subject="owner-a",
        ),
    )
    monkeypatch.setattr(
        bridge,
        "execute_safe_read",
        lambda **_kwargs: {"workspaces": [], "total": 0, "limit": 20, "offset": 0},
    )
    client = TestClient(_app())
    approved = client.get(
        "/api/workspaces",
        headers={"Origin": "https://frontend.example"},
    )
    rejected = client.get(
        "/api/workspaces",
        headers={"Origin": "https://attacker.example"},
    )
    assert approved.headers["access-control-allow-origin"] == "https://frontend.example"
    assert approved.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in rejected.headers


def test_valid_bearer_read_does_not_mutate_auth_caches_and_swa_state_is_denied(
    monkeypatch,
):
    import auth

    user = auth.User(
        id="google_user-a",
        provider=auth.AuthProvider.GOOGLE,
        provider_subject="user-a",
        tenant_id="tenant-a",
    )
    token = auth.generate_session_token(user)
    auth.USER_CACHE.pop(token, None)
    cache_before = dict(auth.USER_CACHE)
    store_before = dict(auth.USER_STORE)
    monkeypatch.setattr(
        bridge,
        "execute_safe_read",
        lambda **_kwargs: {"workspaces": [], "total": 0, "limit": 20, "offset": 0},
    )
    client = TestClient(_app())
    response = client.get(
        "/api/workspaces",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert auth.USER_CACHE == cache_before
    assert auth.USER_STORE == store_before

    monkeypatch.setattr(
        bridge,
        "request_has_untrusted_swa_principal",
        lambda headers: bool(headers.get("x-ms-client-principal")),
    )
    swa_only = client.get(
        "/api/workspaces",
        headers={"x-ms-client-principal": "browser-state-is-not-authority"},
    )
    assert swa_only.status_code == 401
    bearer_plus_swa = client.get(
        "/api/workspaces",
        headers={
            "Authorization": f"Bearer {token}",
            "x-ms-client-principal": "browser-state-is-not-authority",
        },
    )
    assert bearer_plus_swa.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/workspaces"),
        ("PATCH", "/api/workspaces/workspace-a"),
        ("GET", "/api/replays"),
        ("GET", "/api/diagrams/diagram-a/cost-estimate"),
        ("GET", "/api/workspaces?export_capability=stale-or-foreign"),
    ],
)
def test_writes_effectful_gets_and_capability_smuggling_are_denied(method, path):
    response = TestClient(_app()).request(method, path)
    assert response.status_code in {400, 503}
    if response.status_code == 503:
        assert response.headers["retry-after"] == "30"
        assert response.json()["customer_mode"] == "degraded_read_only"
        assert response.json()["reason"] == "route_not_proven_dual_schema_read_safe"
    assert response.headers["cache-control"] == "no-store"


def test_health_schema_and_safe_read_cors_preflight_remain_available():
    client = TestClient(_app())
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/schema-compatibility").status_code == 200
    assert client.options("/api/workspaces").status_code == 200
