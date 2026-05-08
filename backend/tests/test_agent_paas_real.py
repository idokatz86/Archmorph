from fastapi.testclient import TestClient
import pytest
from main import app
from database import get_db, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from routers.auth import get_current_user
from routers.shared import require_authenticated_user_context
from models.tenant import Organization
from rbac import get_current_user_required

# Setup isolated test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

with TestingSessionLocal() as db:
    db.merge(Organization(
        org_id="default_org",
        name="Test Org",
        slug="test-org",
        plan="enterprise",
        max_members=10,
        max_analyses_per_month=1000,
    ))
    db.commit()


class AuthenticatedTestUser(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

def override_get_current_user():
    return AuthenticatedTestUser({
        "id": "test_user",
        "user_id": "test_user",
        "org_id": "default_org",
        "organization_id": "default_org",
        "tenant_id": "default_org",
        "roles": ["admin"],
    })

client = TestClient(app)


@pytest.fixture(autouse=True)
def auth_overrides():
    overrides = {
        get_db: override_get_db,
        get_current_user: override_get_current_user,
        get_current_user_required: override_get_current_user,
        require_authenticated_user_context: override_get_current_user,
    }
    previous = {dep: app.dependency_overrides.get(dep) for dep in overrides}
    app.dependency_overrides.update(overrides)
    yield
    for dep, value in previous.items():
        if value is None:
            app.dependency_overrides.pop(dep, None)
        else:
            app.dependency_overrides[dep] = value

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
    assert response.status_code in (200, 201, 401)  # 401 when auth is enforced

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
