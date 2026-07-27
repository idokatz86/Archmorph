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
