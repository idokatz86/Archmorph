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
