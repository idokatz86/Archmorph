import os
import sys

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from main import app  # noqa: E402


def _resolve_schema(schema: dict, openapi_schema: dict) -> dict:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return schema
        node: object = openapi_schema
        for key in ref[2:].split("/"):
            node = node[key]
        return _resolve_schema(node, openapi_schema)
    if isinstance(schema, dict):
        return {k: _resolve_schema(v, openapi_schema) for k, v in schema.items()}
    if isinstance(schema, list):
        return [_resolve_schema(v, openapi_schema) for v in schema]
    return schema


def _response_schema(openapi_schema: dict, path: str, method: str, status_code: int) -> dict:
    operation = openapi_schema["paths"][path][method]
    response = operation["responses"][str(status_code)]
    schema = response["content"]["application/json"]["schema"]
    return _resolve_schema(schema, openapi_schema)


@pytest.fixture(scope="module")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="module")
def openapi_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def _assert_conforms(response, schema: dict) -> None:
    Draft202012Validator(schema).validate(response.json())


@pytest.mark.contract
def test_runtime_openapi_success_envelope_live_contact(client, openapi_schema):
    response = client.get("/api/contact")
    assert response.status_code == 200
    _assert_conforms(response, _response_schema(openapi_schema, "/api/contact", "get", 200))


@pytest.mark.contract
def test_runtime_openapi_success_envelope_live_contact_v1(client, openapi_schema):
    response = client.get("/api/v1/contact")
    assert response.status_code == 200
    _assert_conforms(response, _response_schema(openapi_schema, "/api/v1/contact", "get", 200))


@pytest.mark.contract
def test_runtime_openapi_error_envelope_live_auth_login(client, openapi_schema):
    response = client.post("/api/auth/login")
    assert response.status_code == 422
    _assert_conforms(response, _response_schema(openapi_schema, "/api/auth/login", "post", 422))


@pytest.mark.contract
def test_runtime_openapi_error_envelope_live_auth_login_v1(client, openapi_schema):
    response = client.post("/api/v1/auth/login")
    assert response.status_code == 422
    _assert_conforms(response, _response_schema(openapi_schema, "/api/v1/auth/login", "post", 422))
