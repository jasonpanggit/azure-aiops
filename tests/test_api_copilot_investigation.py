"""Multi-step Operations Copilot investigation route.

Complements ``test_api_copilot.py`` (single-shot ``/copilot/ask``) with the
tool-calling loop: ``/copilot/investigate`` plans and executes governed tool
calls, ``/copilot/tools`` publishes the contract, and ``/copilot/history``
returns bounded, principal-scoped conversation state.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_connection_lineage_integration import _build_engine, make_connection

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.foundry_agent import AgentAnswer, FoundryAgentError
from operations.investigation import conversation_store

TOKEN = "admin-token-0123456789abcdef"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class StubAgent:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def answer(self, *, question: str, context) -> AgentAnswer:
        self.calls.append({"question": question, "context": context})
        if self.fail:
            raise FoundryAgentError("agent unreachable")
        return AgentAnswer(text="Narrated answer.", agent_name="operations-copilot")


def _context(tmp_path, agent, *, engine=None, principals=None) -> ApiContext:
    engine = engine or _build_engine(make_connection())
    principals = principals or {
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),))
    }
    return ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: engine,
        foundry_agent_provider=(lambda: agent) if agent is not None else None,
    )


@pytest.fixture(autouse=True)
def _clean_conversation_store():
    # The store is a process-wide singleton; keep tests isolated from
    # each other's session ids.
    yield
    conversation_store()._sessions.clear()


@pytest.fixture
def agent() -> StubAgent:
    return StubAgent()


@pytest.fixture
def client(tmp_path, agent) -> TestClient:
    return TestClient(create_app(_context(tmp_path, agent)), raise_server_exceptions=False)


def _investigate(client: TestClient, question: str, **kwargs):
    body = {"question": question, **kwargs}
    return client.post("/api/v1/copilot/investigate", json=body, headers=HEADERS)


def test_tool_catalog_is_published(client):
    response = client.get("/api/v1/copilot/tools", headers=HEADERS)
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["data"]["tools"]}
    assert {"business_service_context", "traffic_flow", "cve_exposure", "incidents"} <= names


def test_investigation_plans_tools_and_narrates(client, agent):
    response = _investigate(client, "Tell me about Retail Banking")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["tool_calls"], "a subject-bearing question must select at least one tool"
    tool_names = {call["tool"] for call in body["tool_calls"]}
    assert "business_service_context" in tool_names
    assert body["answer"]["text"] == "Narrated answer."
    # The agent must be handed structured per-tool facts, not raw provider dumps.
    grounding = agent.calls[0]["context"]
    assert "facts" in grounding
    assert all("status" in fact for fact in grounding["facts"])


def test_investigation_reports_fact_status_ok_for_matched_service(client):
    body = _investigate(client, "Tell me about Retail Banking").json()["data"]
    matched = [
        call for call in body["tool_calls"] if call["tool"] == "business_service_context"
    ]
    assert matched and matched[0]["status"] == "ok"
    assert matched[0]["evidence"], "an observed fact must carry evidence"


def test_investigation_hint_tool_bypasses_planner(client):
    response = _investigate(
        client,
        "anything",
        tool="business_service_context",
        tool_arguments={"name": "Retail Banking"},
    )
    body = response.json()["data"]
    assert [call["tool"] for call in body["tool_calls"]] == ["business_service_context"]


def test_investigation_rejects_unknown_tool_hint(client):
    response = _investigate(client, "anything", tool="delete_everything")
    assert response.status_code == 400


def test_investigation_degrades_when_agent_unavailable(tmp_path):
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    response = _investigate(client, "Tell me about Retail Banking")
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["answer"] is None
    assert any("Foundry" in warning for warning in body.get("warnings", []))


def test_investigation_degrades_when_agent_fails(tmp_path):
    client = TestClient(
        create_app(_context(tmp_path, StubAgent(fail=True))), raise_server_exceptions=False
    )
    response = _investigate(client, "Tell me about Retail Banking")
    body = response.json()
    assert response.status_code == 200
    assert body["data"]["answer"] is None
    assert any("Foundry" in warning for warning in body.get("warnings", []))
    # A tool result was still returned even though narration failed.
    assert body["data"]["tool_calls"]


def test_investigation_records_and_returns_bounded_history(client):
    _investigate(client, "Tell me about Retail Banking", session_id="s1")
    _investigate(client, "What should be fixed first?", session_id="s1")

    response = client.get("/api/v1/copilot/history/s1", headers=HEADERS)
    assert response.status_code == 200
    turns = response.json()["data"]["turns"]
    assert len(turns) == 2
    assert turns[0]["question"] == "Tell me about Retail Banking"
    assert turns[1]["question"] == "What should be fixed first?"


def test_history_is_isolated_per_principal(tmp_path):
    principals = {
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        "other-token-0123456789abcdef01": Principal(
            subject="other@example.com", grants=(Grant("admin"),)
        ),
    }
    engine = _build_engine(make_connection())
    context = _context(tmp_path, StubAgent(), engine=engine, principals=principals)
    client = TestClient(create_app(context), raise_server_exceptions=False)

    client.post(
        "/api/v1/copilot/investigate",
        json={"question": "Tell me about Retail Banking", "session_id": "shared"},
        headers=HEADERS,
    )

    other_headers = {"Authorization": "Bearer other-token-0123456789abcdef01"}
    response = client.get("/api/v1/copilot/history/shared", headers=other_headers)
    assert response.status_code == 200
    # Same session id, different principal: must not see the admin's turns.
    assert response.json()["data"]["turns"] == []


def test_investigation_denies_out_of_scope_incident(tmp_path):
    """A scoped reader asking about an incident outside their scope must get
    a denial, never a silently-empty or leaked result.
    """
    engine = _build_engine(make_connection())
    principals = {
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        "reader-token-0123456789abcdef01": Principal(
            subject="reader@example.com",
            grants=(
                Grant("reader", Scope.from_mapping({"business_service": ["Nonexistent Service"]})),
            ),
        ),
    }
    context = _context(tmp_path, StubAgent(), engine=engine, principals=principals)
    client = TestClient(create_app(context), raise_server_exceptions=False)
    response = client.post(
        "/api/v1/copilot/investigate",
        json={
            "question": "anything",
            "tool": "business_service_context",
            "tool_arguments": {"name": "Retail Banking"},
        },
        headers={"Authorization": "Bearer reader-token-0123456789abcdef01"},
    )
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["tool_calls"][0]["status"] == "denied"
