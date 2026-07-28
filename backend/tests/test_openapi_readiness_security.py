"""OpenAPI contracts for readiness and supported client authentication (#1237)."""


def test_readyz_documents_success_and_dependency_failure(test_client):
    schema = test_client.get("/openapi.json").json()
    operation = schema["paths"]["/readyz"]["get"]

    assert {"200", "503"} <= set(operation["responses"])
    for status in ("200", "503"):
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ReadinessResponse"
        }
    assert operation.get("security") in (None, [])


def test_readyz_reports_schema_contract_separately(test_client, monkeypatch):
    import database
    import session_store

    monkeypatch.setattr(
        database,
        "database_readiness",
        lambda: {
            "ready_for_production": False,
            "schema_at_head": False,
            "required_schema_present": True,
        },
    )
    monkeypatch.setattr(
        session_store,
        "session_store_readiness",
        lambda: {"ready_for_horizontal_scale": True},
    )

    response = test_client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": "unavailable",
        "database_schema": "unavailable",
        "redis": "ready",
    }


def test_schema_compatibility_preflight_reports_supported_current_head(test_client, monkeypatch):
    import database

    monkeypatch.setattr(
        database,
        "database_readiness",
        lambda: {
            "postgres_configured": True,
            "connection_ok": True,
            "required_schema_present": True,
            "current_revision": "014",
        },
    )

    response = test_client.get("/api/schema-compatibility")

    assert response.status_code == 200
    assert response.json() == {
        "status": "compatible",
        "current_revision": "014",
        "minimum_revision": "014",
        "maximum_revision": "014",
        "accepted_revisions": ["014"],
        "migration_target_revision": "014",
        "alias_read_through_until": "014",
    }


def test_schema_compatibility_preflight_fails_closed_for_unknown_head(test_client, monkeypatch):
    import database

    monkeypatch.setattr(
        database,
        "database_readiness",
        lambda: {
            "postgres_configured": True,
            "connection_ok": True,
            "required_schema_present": True,
            "current_revision": "unknown",
        },
    )

    response = test_client.get("/api/schema-compatibility")

    assert response.status_code == 409
    assert response.json()["status"] == "incompatible"
    assert response.json()["current_revision"] == "unknown"


def test_restore_documents_api_key_or_bearer_security_alternatives(test_client):
    schema = test_client.get("/openapi.json").json()
    schemes = schema["components"]["securitySchemes"]

    assert schemes["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert schemes["HTTPBearer"]["type"] == "http"
    assert schemes["HTTPBearer"]["scheme"] == "bearer"
    restore = schema["paths"]["/api/diagrams/{diagram_id}/restore-session"]["post"]
    assert {tuple(item) for item in restore["security"]} == {
        ("APIKeyHeader",),
        ("HTTPBearer",),
    }
