from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from actor_context import ActorContext, TenantId, require_actor_context, resolve_actor_context
from auth import AuthProvider, User
from database import Base, get_db
from error_envelope import ArchmorphException
from models.agent import Agent, AgentVersion
from models.tenant import Organization, TeamMember
from routers.agents import router


@pytest.fixture()
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = testing_session()
    try:
        for org_id in ("org-a", "org-b", "actor-1"):
            session.add(
                Organization(
                    org_id=org_id,
                    name=f"Organization {org_id}",
                    slug=org_id,
                    is_active=True,
                )
            )
        session.add(
            TeamMember(
                org_id="org-a",
                user_id="actor-1",
                email="actor-1@example.test",
                role="editor",
                is_active=True,
            )
        )
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(*, tenant_id: str) -> User:
    return User(
        id="actor-1",
        email="actor-1@example.test",
        provider=AuthProvider.GITHUB,
        tenant_id=tenant_id,
        roles=["admin"],
    )


def _payload(organization_id: str) -> dict:
    return {
        "name": "Compatibility Agent",
        "organization_id": organization_id,
    }


def _client(db: Session, actor: ActorContext) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def override_get_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_actor_context] = lambda: actor
    return TestClient(app)


def _agent(
    db: Session,
    *,
    agent_id: str,
    organization_id: str,
    created_by: str,
) -> Agent:
    agent = Agent(
        id=agent_id,
        organization_id=organization_id,
        name=f"Agent {agent_id}",
        description="Tenant isolation fixture",
        version="1.0.0",
        status="draft",
        model_config_data={},
        tools=[],
        data_sources=[],
        memory_config={},
        created_by=created_by,
    )
    db.add(agent)
    db.add(
        AgentVersion(
            id=f"version-{agent_id}",
            agent_id=agent_id,
            version="1.0.0",
            config_snapshot={},
            created_by=created_by,
        )
    )
    db.commit()
    return agent


def test_actor_context_derives_tenant_and_role_from_active_membership(db: Session):
    actor = resolve_actor_context(_user(tenant_id="org-a"), db)

    assert actor.actor_id == "actor-1"
    assert actor.tenant_id == TenantId("org-a")
    assert actor.roles == ("editor",)


def test_actor_context_rejects_identity_without_selected_tenant_membership(db: Session):
    with pytest.raises(ArchmorphException) as exc_info:
        resolve_actor_context(_user(tenant_id="org-b"), db)

    assert exc_info.value.status_code == 403


def test_actor_context_rejects_ambiguous_selected_tenant_membership(db: Session):
    db.add(
        TeamMember(
            org_id="org-a",
            user_id="actor-1",
            email="actor-1-duplicate@example.test",
            role="viewer",
            is_active=True,
        )
    )
    db.commit()

    with pytest.raises(ArchmorphException) as exc_info:
        resolve_actor_context(_user(tenant_id="org-a"), db)

    assert exc_info.value.status_code == 403


def test_create_agent_preserves_matching_legacy_organization_id(db: Session):
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        response = client.post("/agents", json=_payload("org-a"))

    assert response.status_code == 201
    assert response.json()["organization_id"] == "org-a"
    created = db.query(Agent).filter(Agent.id == response.json()["id"]).one()
    assert created.organization_id == "org-a"
    assert created.created_by == "actor-1"


def test_create_agent_rejects_caller_supplied_other_tenant(db: Session):
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        response = client.post("/agents", json=_payload("org-b"))

    assert response.status_code == 403
    assert db.query(Agent).count() == 0


def test_create_agent_does_not_confuse_owner_user_id_with_tenant_id(db: Session):
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        response = client.post("/agents", json=_payload("actor-1"))

    assert response.status_code == 403
    assert db.query(Agent).count() == 0


def test_list_agents_rejects_other_tenant_and_does_not_enumerate(db: Session):
    _agent(db, agent_id="agent-a", organization_id="org-a", created_by="actor-1")
    _agent(db, agent_id="agent-b", organization_id="org-b", created_by="actor-2")
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        own_response = client.get("/agents", params={"organization_id": "org-a"})
        other_response = client.get("/agents", params={"organization_id": "org-b"})

    assert own_response.status_code == 200
    assert [agent["id"] for agent in own_response.json()] == ["agent-a"]
    assert other_response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("get", "/agents/agent-b", None),
        ("put", "/agents/agent-b", {"name": "Cross-tenant update"}),
        ("delete", "/agents/agent-b", None),
        ("patch", "/agents/agent-b/status?status=active", None),
        ("get", "/agents/agent-b/versions", None),
        ("post", "/agents/agent-b/clone", None),
    ],
)
def test_agent_operations_hide_other_tenant_resources(
    db: Session,
    method: str,
    path: str,
    json: dict | None,
):
    foreign_agent = _agent(
        db,
        agent_id="agent-b",
        organization_id="org-b",
        created_by="actor-2",
    )
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        response = client.request(method, path, json=json)

    assert response.status_code == 404
    db.refresh(foreign_agent)
    assert foreign_agent.name == "Agent agent-b"
    assert foreign_agent.status == "draft"
    assert db.query(Agent).filter(Agent.organization_id == "org-b").count() == 1
    assert db.query(AgentVersion).filter(AgentVersion.agent_id == "agent-b").count() == 1


def test_update_and_clone_keep_actor_as_creator_not_tenant_identity(db: Session):
    source = _agent(db, agent_id="agent-a", organization_id="org-a", created_by="original-creator")
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        update_response = client.put(f"/agents/{source.id}", json={"description": "Updated"})
        clone_response = client.post(f"/agents/{source.id}/clone")

    assert update_response.status_code == 200
    assert clone_response.status_code == 200
    assert clone_response.json() == {}
    clone = (
        db.query(Agent)
        .filter(
            Agent.organization_id == "org-a",
            Agent.id != source.id,
        )
        .one()
    )
    assert clone.organization_id == "org-a"
    assert clone.created_by == "actor-1"
    latest_versions = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id.in_([source.id, clone.id]))
        .filter(AgentVersion.created_by == "actor-1")
        .count()
    )
    assert latest_versions == 2


def test_viewer_can_read_agent_definitions_and_versions(db: Session):
    source = _agent(db, agent_id="agent-a", organization_id="org-a", created_by="actor-1")
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("viewer",))

    with _client(db, actor) as client:
        list_response = client.get("/agents", params={"organization_id": "org-a"})
        get_response = client.get(f"/agents/{source.id}")
        versions_response = client.get(f"/agents/{source.id}/versions")

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert versions_response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("post", "/agents", _payload("org-a")),
        ("put", "/agents/agent-a", {"name": "Viewer update"}),
        ("post", "/agents/agent-a/clone", None),
        ("delete", "/agents/agent-a", None),
        ("patch", "/agents/agent-a/status?status=active", None),
    ],
)
def test_viewer_cannot_mutate_agents(
    db: Session,
    method: str,
    path: str,
    json: dict | None,
):
    source = _agent(db, agent_id="agent-a", organization_id="org-a", created_by="actor-1")
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("viewer",))

    with _client(db, actor) as client:
        response = client.request(method, path, json=json)

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient tenant permissions"
    db.refresh(source)
    assert source.name == "Agent agent-a"
    assert source.status == "draft"
    assert db.query(Agent).count() == 1
    assert db.query(AgentVersion).count() == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("delete", "/agents/agent-a"),
        ("patch", "/agents/agent-a/status?status=active"),
    ],
)
def test_editor_cannot_perform_admin_agent_mutations(
    db: Session,
    method: str,
    path: str,
):
    source = _agent(db, agent_id="agent-a", organization_id="org-a", created_by="actor-1")
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("editor",))

    with _client(db, actor) as client:
        response = client.request(method, path)

    assert response.status_code == 403
    db.refresh(source)
    assert source.status == "draft"


def test_admin_can_change_status_and_archive_agents(db: Session):
    status_agent = _agent(
        db,
        agent_id="status-agent",
        organization_id="org-a",
        created_by="actor-1",
    )
    archive_agent = _agent(
        db,
        agent_id="archive-agent",
        organization_id="org-a",
        created_by="actor-1",
    )
    actor = ActorContext(actor_id="actor-1", tenant_id=TenantId("org-a"), roles=("admin",))

    with _client(db, actor) as client:
        status_response = client.patch(f"/agents/{status_agent.id}/status", params={"status": "active"})
        archive_response = client.delete(f"/agents/{archive_agent.id}")

    assert status_response.status_code == 200
    assert archive_response.status_code == 200
    db.refresh(status_agent)
    db.refresh(archive_agent)
    assert status_agent.status == "active"
    assert archive_agent.status == "archived"
