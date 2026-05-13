from fastapi.testclient import TestClient

from main import app


def _origin_lock_headers(*, fdid: str = "fd-guid", host: str = "archmorph-api-prod.azurefd.net") -> dict[str, str]:
    return {
        "X-Azure-FDID": fdid,
        "Host": host,
    }


def test_origin_lock_blocks_production_requests_without_front_door_headers(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_FDID", "fd-guid")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_HOSTS", "archmorph-api-prod.azurefd.net")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TRUSTED_ORIGIN_REQUIRED"


def test_origin_lock_allows_configured_front_door_contract(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_FDID", "fd-guid")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_HOSTS", "archmorph-api-prod.azurefd.net")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/openapi.json", headers=_origin_lock_headers())

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Archmorph API"


def test_origin_lock_rejects_wrong_front_door_profile(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_FDID", "fd-guid")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_HOSTS", "archmorph-api-prod.azurefd.net")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/openapi.json",
            headers=_origin_lock_headers(fdid="other-front-door"),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "TRUSTED_ORIGIN_REQUIRED"


def test_origin_lock_keeps_healthz_available_for_platform_probes(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_FDID", "fd-guid")
    monkeypatch.setenv("TRUSTED_FRONT_DOOR_HOSTS", "archmorph-api-prod.azurefd.net")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"
