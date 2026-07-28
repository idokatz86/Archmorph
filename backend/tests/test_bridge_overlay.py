import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def test_bridge_overlay_is_bounded_requires_postgres_and_never_runs_ddl():
    sitecustomize = (BACKEND / "bridge_overlay" / "sitecustomize.py").read_text()
    entrypoint = (BACKEND / "bridge_overlay" / "bridge_entrypoint.py").read_text()
    ast.parse(sitecustomize)
    ast.parse(entrypoint)

    assert "Base.metadata.create_all" not in sitecustomize
    assert 'os.environ.setdefault("ENFORCE_POSTGRES", "true")' in sitecustomize
    assert 'os.environ.setdefault("SCHEDULER_DISABLED", "1")' in sitecustomize
    assert '_BRIDGE_REVISIONS = frozenset({"013", "014"})' in sitecustomize
    assert 'text("SELECT 1")' in sitecustomize
    assert 'text("SELECT version_num FROM alembic_version ORDER BY version_num")' in sitecustomize
    assert "database.database_readiness = _bridge_database_readiness" in sitecustomize
    assert "ArchmorphMiddleware._ORIGIN_LOCK_SKIP" in entrypoint
    assert "job_queue.durable_job_worker.start = _bridge_worker_start" in entrypoint
    assert "class BridgeReadOnlyMiddleware" in entrypoint
    assert 'status_code=503' in entrypoint
    assert 'headers={"Retry-After": "30"}' in entrypoint


def test_bridge_image_requires_an_immutable_base_supplied_by_workflow():
    dockerfile = (BACKEND / "bridge_overlay" / "Dockerfile").read_text()
    assert "ARG BRIDGE_BASE_IMAGE" in dockerfile
    assert "FROM ${BRIDGE_BASE_IMAGE}" in dockerfile
    assert "bridge_entrypoint:app" in dockerfile
    assert ":latest" not in dockerfile


def test_bridge_read_only_middleware_blocks_feature_requests():
    source = (BACKEND / "bridge_overlay" / "bridge_entrypoint.py").read_text()
    middleware_source = source.split("class BridgeReadOnlyMiddleware", 1)[1].split(
        "app.add_middleware", 1
    )[0]
    namespace: dict[str, object] = {}
    exec(
        "class BridgeReadOnlyMiddleware" + middleware_source,
        {
            "BaseHTTPMiddleware": __import__(
                "starlette.middleware.base", fromlist=["BaseHTTPMiddleware"]
            ).BaseHTTPMiddleware,
            "JSONResponse": __import__(
                "fastapi.responses", fromlist=["JSONResponse"]
            ).JSONResponse,
            "Request": __import__("starlette.requests", fromlist=["Request"]).Request,
            "_BRIDGE_PATHS": frozenset({"/healthz", "/readyz", "/api/schema-compatibility"}),
        },
        namespace,
    )
    middleware = namespace["BridgeReadOnlyMiddleware"]
    app = FastAPI()
    app.add_middleware(middleware)

    @app.get("/api/health")
    async def health():
        return {"status": "healthy"}

    response = TestClient(app).get("/api/health")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert response.json() == {"status": "bridge_read_only", "retryable": True}