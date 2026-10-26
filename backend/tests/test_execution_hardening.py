import asyncio
import json
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from actor_context import ActorContext, TenantId, require_actor_context
from database import Base, get_db
from models.agent import Agent
from models.execution import Execution
from models.tenant import Organization
from routers.executions import router
from services.agent_runner import AgentRunner
from services.execution_state import transition_execution


@pytest.fixture()
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _actor(
    tenant_id: str = "org-a",
    role: str = "editor",
) -> ActorContext:
    return ActorContext(
        actor_id="actor-1",
        tenant_id=TenantId(tenant_id),
        roles=(role,),
    )


def _seed_execution(
    session_factory: sessionmaker[Session],
    *,
    execution_id: str = "execution-1",
    status: str = "queued",
) -> None:
    with session_factory() as db:
        db.add(
            Organization(
                org_id="org-a",
                name="Organization A",
                slug="org-a",
                is_active=True,
            )
        )
        db.add(
            Agent(
                id="agent-1",
                organization_id="org-a",
                name="Test Agent",
                status="active",
                model_config_data={"temperature": 0.1},
                tools=[],
            )
        )
        db.add(
            Execution(
                id=execution_id,
                agent_id="agent-1",
                organization_id="org-a",
                status=status,
                input_data={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "session_token": "session-token",
                },
            )
        )
        db.commit()


def _client(
    session_factory: sessionmaker[Session],
    actor: ActorContext,
) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_actor_context] = lambda: actor
    return TestClient(app)


def _response(*, content: str = "", tool_calls: list | None = None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=2)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=usage,
    )


def test_start_execution_preserves_contract_and_passes_actor_context(
    session_factory: sessionmaker[Session],
):
    actor = _actor()
    observed: dict[str, object] = {}

    with session_factory() as db:
        db.add(
            Organization(
                org_id="org-a",
                name="Organization A",
                slug="org-a",
                is_active=True,
            )
        )
        db.add(
            Agent(
                id="agent-1",
                organization_id="org-a",
                name="Test Agent",
                status="active",
            )
        )
        db.commit()

    class CapturingRunner:
        def __init__(self, execution_id: str, actor_context: ActorContext):
            observed["execution_id"] = execution_id
            observed["actor_context"] = actor_context

        async def run(self):
            observed["ran"] = True

    with (
        patch("routers.executions.AgentRunner", CapturingRunner),
        _client(session_factory, actor) as client,
    ):
        response = client.post(
            "/api/executions/",
            headers={"Authorization": "Bearer session-token"},
            json={
                "agent_id": "agent-1",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

    assert response.status_code == 202
    assert response.json() == {
        "id": observed["execution_id"],
        "agent_id": "agent-1",
        "thread_id": None,
        "status": "queued",
        "output_data": None,
        "error_message": None,
    }
    assert observed["actor_context"] is actor
    assert observed["ran"] is True

    with session_factory() as db:
        execution = db.get(Execution, observed["execution_id"])
        assert execution is not None
        assert execution.organization_id == "org-a"
        assert execution.input_data["session_token"] == "session-token"


def test_cancel_execution_requests_cancellation_for_running_work(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory, status="running")

    with _client(session_factory, _actor(role="admin")) as client:
        response = client.post("/api/executions/execution-1/cancel")
        repeated_response = client.post("/api/executions/execution-1/cancel")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Execution cancellation requested",
    }
    assert repeated_response.status_code == 400
    assert repeated_response.json()["detail"] == "Execution is already finished"

    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "cancel_requested"


@pytest.mark.parametrize(
    ("role", "start_status", "cancel_status"),
    [
        ("viewer", 403, 403),
        ("editor", 202, 403),
        ("admin", 202, 200),
    ],
)
def test_execution_endpoints_enforce_tenant_role_permissions(
    session_factory: sessionmaker[Session],
    role: str,
    start_status: int,
    cancel_status: int,
):
    _seed_execution(session_factory, status="running")

    class NoOpRunner:
        def __init__(self, execution_id: str, actor_context: ActorContext):
            self.execution_id = execution_id
            self.actor_context = actor_context

        async def run(self):
            pass

    with (
        patch("routers.executions.AgentRunner", NoOpRunner),
        _client(session_factory, _actor(role=role)) as client,
    ):
        read_response = client.get("/api/executions/execution-1")
        start_response = client.post(
            "/api/executions/",
            json={
                "agent_id": "agent-1",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        cancel_response = client.post("/api/executions/execution-1/cancel")

    assert read_response.status_code == 200
    assert start_response.status_code == start_status
    assert cancel_response.status_code == cancel_status


@pytest.mark.asyncio
async def test_running_cancellation_stops_active_model_and_is_acknowledged(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory)
    model_started = asyncio.Event()
    model_cancelled = asyncio.Event()

    class RacingModelClient:
        async def chat(self, **_kwargs):
            model_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                model_cancelled.set()
                raise

    class StubModelRouter:
        def __init__(self, _db: Session, _organization_id: str):
            pass

        def route(self, _strategy: str):
            return RacingModelClient()

    with (
        patch("services.agent_runner.SessionLocal", side_effect=session_factory),
        patch("services.agent_runner.ModelRouter", StubModelRouter),
    ):
        run_task = asyncio.create_task(
            AgentRunner("execution-1", actor_context=_actor()).run()
        )
        await asyncio.wait_for(model_started.wait(), timeout=1)

        with session_factory() as db:
            assert transition_execution(
                db,
                "execution-1",
                from_statuses=("running",),
                to_status="cancel_requested",
                organization_id="org-a",
            )

        await asyncio.wait_for(run_task, timeout=1)

    assert model_cancelled.is_set()
    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "cancelled"
        assert execution.output_data is None
        assert execution.error_message is None


@pytest.mark.asyncio
async def test_cancellation_before_tool_skips_tools_and_second_model_call(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory)
    tool_call = SimpleNamespace(
        id="tool-call-1",
        function=SimpleNamespace(name="test_tool", arguments="{}"),
    )

    class CancellationRequestingModelClient:
        def __init__(self):
            self.call_count = 0

        async def chat(self, **_kwargs):
            self.call_count += 1
            with session_factory() as db:
                assert transition_execution(
                    db,
                    "execution-1",
                    from_statuses=("running",),
                    to_status="cancel_requested",
                    organization_id="org-a",
                )
            return _response(tool_calls=[tool_call])

    model_client = CancellationRequestingModelClient()

    class StubModelRouter:
        def __init__(self, _db: Session, _organization_id: str):
            pass

        def route(self, _strategy: str):
            return model_client

    tool_execute = AsyncMock(return_value=json.dumps({"status": "success"}))
    with (
        patch("services.agent_runner.SessionLocal", side_effect=session_factory),
        patch("services.agent_runner.ModelRouter", StubModelRouter),
        patch("services.agent_runner.tool_registry.execute", new=tool_execute),
    ):
        await AgentRunner("execution-1", actor_context=_actor()).run()

    assert model_client.call_count == 1
    tool_execute.assert_not_awaited()
    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "cancelled"


@pytest.mark.asyncio
async def test_cancellation_after_tool_skips_second_model_call(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory)
    tool_call = SimpleNamespace(
        id="tool-call-1",
        function=SimpleNamespace(name="test_tool", arguments="{}"),
    )

    class ToolCallingModelClient:
        def __init__(self):
            self.call_count = 0

        async def chat(self, **_kwargs):
            self.call_count += 1
            return _response(tool_calls=[tool_call])

    model_client = ToolCallingModelClient()

    class StubModelRouter:
        def __init__(self, _db: Session, _organization_id: str):
            pass

        def route(self, _strategy: str):
            return model_client

    async def request_cancellation(*_args, **_kwargs):
        with session_factory() as db:
            assert transition_execution(
                db,
                "execution-1",
                from_statuses=("running",),
                to_status="cancel_requested",
                organization_id="org-a",
            )
        return json.dumps({"status": "success"})

    with (
        patch("services.agent_runner.SessionLocal", side_effect=session_factory),
        patch("services.agent_runner.ModelRouter", StubModelRouter),
        patch(
            "services.agent_runner.tool_registry.execute",
            new=AsyncMock(side_effect=request_cancellation),
        ),
    ):
        await AgentRunner("execution-1", actor_context=_actor()).run()

    assert model_client.call_count == 1
    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "cancelled"


@pytest.mark.asyncio
async def test_running_cancellation_propagates_to_active_async_tool(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory)
    tool_started = asyncio.Event()
    tool_cancelled = asyncio.Event()
    tool_call = SimpleNamespace(
        id="tool-call-1",
        function=SimpleNamespace(name="test_tool", arguments="{}"),
    )

    class ToolCallingModelClient:
        def __init__(self):
            self.call_count = 0

        async def chat(self, **_kwargs):
            self.call_count += 1
            return _response(tool_calls=[tool_call])

    model_client = ToolCallingModelClient()

    class StubModelRouter:
        def __init__(self, _db: Session, _organization_id: str):
            pass

        def route(self, _strategy: str):
            return model_client

    async def blocking_tool(*_args, **_kwargs):
        tool_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            tool_cancelled.set()
            raise

    with (
        patch("services.agent_runner.SessionLocal", side_effect=session_factory),
        patch("services.agent_runner.ModelRouter", StubModelRouter),
        patch(
            "services.agent_runner.tool_registry.execute",
            new=AsyncMock(side_effect=blocking_tool),
        ),
    ):
        run_task = asyncio.create_task(
            AgentRunner("execution-1", actor_context=_actor()).run()
        )
        await asyncio.wait_for(tool_started.wait(), timeout=1)
        with session_factory() as db:
            assert transition_execution(
                db,
                "execution-1",
                from_statuses=("running",),
                to_status="cancel_requested",
                organization_id="org-a",
            )
        await asyncio.wait_for(run_task, timeout=1)

    assert tool_cancelled.is_set()
    assert model_client.call_count == 1
    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "cancelled"


def test_terminal_execution_cannot_transition_again(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory, status="cancelled")

    with session_factory() as db:
        assert not transition_execution(
            db,
            "execution-1",
            from_statuses=("running",),
            to_status="completed",
            organization_id="org-a",
            values={"output_data": {"message": "late result"}},
        )

    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "cancelled"
        assert execution.output_data is None


@pytest.mark.asyncio
async def test_actor_tenant_reaches_model_router_and_tool_execution(
    session_factory: sessionmaker[Session],
):
    _seed_execution(session_factory)
    actor = _actor()
    observed: dict[str, object] = {}
    tool_call = SimpleNamespace(
        id="tool-call-1",
        function=SimpleNamespace(
            name="scan_cloud_infrastructure",
            arguments=json.dumps({"provider": "aws"}),
        ),
    )

    class ToolCallingModelClient:
        def __init__(self):
            self.call_count = 0

        async def chat(self, **_kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return _response(tool_calls=[tool_call])
            return _response(content="tenant-scoped result")

    model_client = ToolCallingModelClient()

    class CapturingModelRouter:
        def __init__(self, _db: Session, organization_id: str):
            observed["model_tenant_id"] = organization_id

        def route(self, _strategy: str):
            return model_client

    async def capture_tool_execution(
        function_name: str,
        arguments: str,
        **context,
    ) -> str:
        observed["tool_name"] = function_name
        observed["tool_arguments"] = arguments
        observed["tool_actor_context"] = context["actor_context"]
        observed["tool_session_token"] = context["session_token"]
        return json.dumps({"status": "success", "result": {}})

    with (
        patch("services.agent_runner.SessionLocal", side_effect=session_factory),
        patch("services.agent_runner.ModelRouter", CapturingModelRouter),
        patch(
            "services.agent_runner.tool_registry.execute",
            new=AsyncMock(side_effect=capture_tool_execution),
        ),
    ):
        await AgentRunner("execution-1", actor_context=actor).run()

    assert observed["model_tenant_id"] == "org-a"
    assert observed["tool_actor_context"] is actor
    assert observed["tool_session_token"] == "session-token"

    with session_factory() as db:
        execution = db.get(Execution, "execution-1")
        assert execution is not None
        assert execution.status == "completed"
        assert execution.output_data == {"message": "tenant-scoped result"}
