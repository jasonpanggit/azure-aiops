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
from operations.tools import Evidence, ToolResult

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
    assert body["mutation_authorized"] is False
    for field in (
        "selected_specialists",
        "selected_tools",
        "coverage",
        "freshness",
        "uncertainty",
        "citations",
        "synthesis",
    ):
        assert field in body
        assert body[field] is not None


def test_compatibility_projection_cites_tool_status_without_provider_evidence(
    client, monkeypatch
):
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *_args, **_kwargs: ToolResult(
            status="unavailable",
            warning="The semantic provider is deferred",
        ),
    )

    body = _investigate(client, "production applications").json()["data"]

    assert body["citations"] == [
        {
            "citation_id": "legacy:0:status:search",
            "source": "tool:search",
            "status": "unavailable",
            "observed_at": "",
            "query_version": "",
            "resource_id": "",
        }
    ]
    assert body["synthesis"]["claims"][0]["evidence_refs"] == [
        "legacy:0:status:search"
    ]
    assert body["answer"]["model"] == "deterministic"
    assert "No provider-backed records were returned" in body["answer"]["text"]
    assert "search" not in body["answer"]["text"]
    assert "The semantic provider is deferred" not in body["answer"]["text"]
    assert "could not access required provider data" in body["answer"]["text"]


@pytest.mark.parametrize(
    ("status", "warning", "expected"),
    [
        (
            "empty",
            "application_context returned empty",
            "found no matching records",
        ),
        (
            "unavailable",
            "inventory_resources failed to answer",
            "could not access required provider data",
        ),
        (
            "denied",
            "risk_context denied for supplied arguments",
            "not permitted for the current scope",
        ),
    ],
)
def test_status_only_narration_never_leaks_tool_or_warning_details(
    client,
    monkeypatch,
    status,
    warning,
    expected,
):
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *_args, **_kwargs: ToolResult(
            status=status,
            warning=warning,
        ),
    )

    body = _investigate(
        client,
        "anything",
        tool="search",
        tool_arguments={"query": "anything"},
    ).json()["data"]

    answer = body["answer"]["text"]
    assert expected in answer.casefold()
    assert "search" not in answer
    assert "application_context" not in answer
    assert "inventory_resources" not in answer
    assert "risk_context" not in answer
    assert warning not in answer


def test_status_only_fallback_does_not_hide_successful_uncited_tool_data(
    client, agent, monkeypatch
):
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *_args, **_kwargs: ToolResult(
            status="ok",
            data={"items": [{"entity_id": "entity-1"}], "total_count": 1},
        ),
    )

    body = _investigate(
        client,
        "anything",
        tool="list_changed_entities",
    ).json()["data"]

    assert body["answer"]["text"] == "Narrated answer."
    assert body["synthesis"]["status"] == "degraded"
    assert body["synthesis"]["claims"] == []
    assert agent.calls


def test_compatibility_claim_uses_aging_evidence_freshness(
    client, monkeypatch
):
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *_args, **_kwargs: ToolResult(
            status="ok",
            data={"resources": [{"resource_name": "vm1"}], "total": 1},
            evidence=(
                Evidence(
                    source_engine="inventory",
                    source_table="resource_observations",
                    timestamp="2026-09-16T05:00:00Z",
                    freshness="aging",
                ),
            ),
        ),
    )

    body = _investigate(client, "show list of VMs").json()["data"]

    assert body["freshness"] == [
        {
            "source": "inventory/resource_observations",
            "observed_at": "2026-09-16T05:00:00Z",
            "status": "aging",
        }
    ]
    assert body["synthesis"]["claims"][0]["freshness"] == "aging"


@pytest.mark.parametrize(
    "untrusted_field",
    [
        {"page_kind": "inventory"},
        {"requested_scope": {"subscription": ["sub-other"]}},
    ],
)
def test_compatibility_rejects_page_and_scope_authority_before_tool_io(
    client, monkeypatch, untrusted_field
):
    calls = []
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    response = client.post(
        "/api/v1/copilot/investigate",
        json={"question": "show list of VMs", **untrusted_field},
        headers=HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert calls == []


@pytest.mark.parametrize(
    "question",
    [
        "servers with failed patches",
        "Which servers have failed patches?",
        "Show VM patch priorities.",
    ],
)
def test_failed_patch_starter_does_not_join_unrelated_inventory(
    client, agent, monkeypatch, question
):
    def execute(tool, _arguments, **_kwargs):
        if tool == "patch_priorities":
            return ToolResult(
                status="ok",
                data={
                    "total_count": 1,
                    "items": [
                        {
                            "kb_id": "5123099",
                            "affected_server_count": 1,
                        }
                    ],
                },
                evidence=(
                    Evidence(
                        source_engine="patch",
                        source_table="patch_priorities",
                        timestamp="2026-09-16T07:43:15Z",
                        freshness="stale",
                    ),
                ),
                warning="KB snapshot freshness is stale",
            )
        assert tool == "inventory_resources"
        return ToolResult(
            status="ok",
            data={
                "resources": [
                    {"resource_name": "vm1"},
                    {"resource_name": "vm2"},
                ],
                "total": 2,
            },
            evidence=(
                Evidence(
                    source_engine="inventory",
                    source_table="resource_observations",
                    timestamp="2026-09-16T16:31:16Z",
                    freshness="fresh",
                ),
            ),
        )

    monkeypatch.setattr("operations.investigation.call_tool", execute)

    response = _investigate(client, question)

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["mutation_authorized"] is False
    assert body["selected_specialist"] == "patch"
    assert body["selected_specialists"] == ["patch"]
    assert body["selected_tools"] == [
        "patch_priorities",
        "inventory_resources",
    ]
    assert body["coverage"] == {
        "visible_count": 3,
        "total_count": 3,
        "complete": False,
        "basis": "bounded_tool_record_sum",
    }
    assert len(body["freshness"]) == 2
    assert len(body["citations"]) == 2
    citation_ids = {item["citation_id"] for item in body["citations"]}
    assert set(body["synthesis"]["claims"][0]["evidence_refs"]) == citation_ids
    assert body["synthesis"]["claims"][0]["freshness"] == "stale"
    assert body["uncertainty"] == [
        "patch_priorities: KB snapshot freshness is stale"
    ]
    assert body["answer"]["model"] == "deterministic"
    assert "No specific resource can be confirmed" in body["answer"]["text"]
    assert "vm1" not in body["answer"]["text"]
    assert "vm2" not in body["answer"]["text"]
    assert agent.calls == []


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


@pytest.mark.parametrize(
    "resource_type",
    [123, [], {}, True, None, "", "   "],
)
def test_investigation_rejects_malformed_tool_arguments_before_io(
    client, monkeypatch, resource_type
):
    calls = []
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    response = _investigate(
        client,
        "show list of VMs",
        tool="inventory_resources",
        tool_arguments={"resource_type": resource_type},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert calls == []


@pytest.mark.parametrize(
    "tool_arguments",
    [
        {},
        {"resource_type": "Microsoft.Compute/virtualMachines"},
    ],
)
def test_investigation_accepts_valid_or_omitted_inventory_filter(
    client, monkeypatch, tool_arguments
):
    calls = []

    def execute(name, arguments, **_kwargs):
        calls.append((name, arguments))
        return ToolResult(status="empty")

    monkeypatch.setattr("operations.investigation.call_tool", execute)

    response = _investigate(
        client,
        "show list of VMs",
        tool="inventory_resources",
        tool_arguments=tool_arguments,
    )

    assert response.status_code == 200
    assert calls == [("inventory_resources", tool_arguments)]


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
