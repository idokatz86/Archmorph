import pytest
from fastapi.testclient import TestClient
from main import app
from database import get_db, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from routers.auth import get_current_user

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_fastapi.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return {"user_id": "test_user", "organization_id": "default", "roles": ["admin"]}

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user
client = TestClient(app)

def test_models_registry_get():
    response = client.get("/api/v1/models/")
    assert response.status_code in (200, 201)
    assert isinstance(response.json(), list)

def test_models_registry_create():
    payload = {
        "name": "E2E Test Model",
        "provider": "openai",
        "model_version": "gpt-4o",
        "connection_config": {"api_key": "sk-dummy"}
    }
    response = client.post("/api/v1/models/", json=payload)
    assert response.status_code in (200, 201)
    assert response.json()["name"] == "E2E Test Model"

def test_agent_memory_episodes_get():
    # memory requires agent ID format since it mounts to /api/v1/agents/{agent_id}/memory
    response = client.get("/api/v1/agents/dummy-agent-123/memory/episodes")
    assert response.status_code == 404 # agent not found
    

def test_agent_policy_lifecycle():
    app.dependency_overrides[get_current_user] = override_get_current_user
    payload = {
        "name": "E2E Security Policy",
        "description": "Prevent secrets",
        "policy_type": "input",
        "rules": {"contains": "password"},
        "enforcement_level": "block"
    }
    r = client.post("/api/v1/policies/", json=payload)
    assert r.status_code == 201
    
    r2 = client.get("/api/v1/policies/")
    assert r2.status_code == 200
    assert any(p["name"] == "E2E Security Policy" for p in r2.json())
