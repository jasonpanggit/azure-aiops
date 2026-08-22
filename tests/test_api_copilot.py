"""Operations Copilot tests.

Exercised against a real semantic knowledge graph (the same harness the other
API semantic tests use) so the grounding contract is proven on real entities.
The Foundry agent itself is stubbed: the value under test is the *composition*
— retrieval, scope filtering, degradation, and the evidence envelope — not
Azure's HTTP surface.
"""

from __future__ import annotations

import json
from dataclasses import replace

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
from operations.foundry_agent import (
    AgentAnswer,
    FoundryAgentError,
    FoundryAgentNotConfigured,
    FoundryPromptAgent,
    _build_prompt,
    _extract_text,
)

TOKEN = "admin-token-0123456789abcdef"
SCOPED_TOKEN = "retail-reader-token-01234567"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class StubAgent:
    """Records what it was grounded on and returns a canned narration."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    def answer(self, *, question: str, context) -> AgentAnswer:
        self.calls.append({"question": question, "context": context})
        if self.fail:
            raise FoundryAgentError("agent unreachable")
        return AgentAnswer(
            text="Two virtual machines are in scope.",
            agent_name="operations-copilot",
            model="gpt-5-mini",
        )


def _context(tmp_path, agent, *, engine=None, principals=None) -> ApiContext:
    engine = engine or _build_engine(make_connection())
    principals = principals or {
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),))
    }
    return ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "hermes"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        semantic_provider=lambda: engine,
        foundry_agent_provider=(lambda: agent) if agent is not None else None,
    )


@pytest.fixture
def agent() -> StubAgent:
    return StubAgent()


@pytest.fixture
def client(tmp_path, agent) -> TestClient:
    return TestClient(create_app(_context(tmp_path, agent)), raise_server_exceptions=False)


def _ask(client: TestClient, question: str, **kwargs):
    return client.post(
        "/api/v1/copilot/ask",
        json={"question": question},
        headers=HEADERS,
        **kwargs,
    )


def test_narrates_retrieved_context(client, agent):
    response = _ask(client, "show list of VMs")
    assert response.status_code == 200
    body = response.json()

    assert body["data"]["answer"]["text"] == "Two virtual machines are in scope."
    assert body["data"]["answer"]["agent_name"] == "operations-copilot"
    assert body["data"]["results"], "retrieval must supply the facts"
    # The envelope omits `warnings` entirely when there are none.
    assert not body.get("warnings")

    # The narration must be evidenced separately from the retrieval it restates.
    engines = {item["source_engine"] for item in body["evidence"]}
    assert engines == {"semantic.SemanticEngine", "operations.FoundryPromptAgent"}


def test_agent_is_grounded_only_on_retrieved_context(client, agent):
    body = _ask(client, "show list of VMs").json()
    grounding = agent.calls[0]["context"]

    # The agent is handed the scope-filtered retrieval payload, and the rows it
    # saw are exactly the rows the caller was shown.
    assert grounding["items"] == body["data"]["results"]
    assert grounding["intent"] == body["data"]["intent"]


def test_degrades_to_retrieval_when_agent_fails(tmp_path):
    client = TestClient(
        create_app(_context(tmp_path, StubAgent(fail=True))),
        raise_server_exceptions=False,
    )
    response = _ask(client, "show list of VMs")

    assert response.status_code == 200, "narration failure must not fail the turn"
    body = response.json()
    assert body["data"]["answer"] is None
    assert body["data"]["results"], "evidence-backed results are still returned"
    assert any("could not be reached" in warning for warning in body["warnings"])


def test_degrades_when_no_agent_is_configured(tmp_path):
    client = TestClient(create_app(_context(tmp_path, None)), raise_server_exceptions=False)
    response = _ask(client, "show list of VMs")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["answer"] is None
    assert any("No Foundry prompt agent" in warning for warning in body["warnings"])
    # Only retrieval is evidenced when nothing narrated the answer.
    assert [item["source_engine"] for item in body["evidence"]] == [
        "semantic.SemanticEngine"
    ]


def test_unsupported_intent_is_rejected_not_hallucinated(client, agent):
    response = _ask(client, "what will break next quarter")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert not agent.calls, "an ungroundable question must never reach the model"


def test_requires_authentication(client):
    assert client.post("/api/v1/copilot/ask", json={"question": "show list of VMs"}).status_code == 401


def test_rejects_empty_and_oversized_questions(client):
    assert _ask(client, "").status_code == 400
    assert _ask(client, "x" * 2000).status_code == 400


def test_out_of_scope_rows_never_reach_the_model(tmp_path):
    """A scoped reader's excluded rows must be filtered *before* grounding."""
    retail = make_connection()
    wealth = replace(
        make_connection(
            business_service="Wealth", application="Advisory", environment="production"
        ),
        connection_id="wealth-core",
        name="Wealth Core",
        subscription_id="sub-wealth",
    )
    engine = _build_engine(retail, wealth)
    agent = StubAgent()
    principals = {
        SCOPED_TOKEN: Principal(
            subject="retail@example.com",
            grants=(
                Grant("reader", Scope.from_mapping({"business_service": ["Retail"]})),
            ),
        )
    }
    client = TestClient(
        create_app(_context(tmp_path, agent, engine=engine, principals=principals)),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/v1/copilot/ask",
        json={"question": "show list of VMs"},
        headers={"Authorization": f"Bearer {SCOPED_TOKEN}"},
    )
    assert response.status_code == 200

    grounded = json.dumps(agent.calls[0]["context"], default=str).casefold()
    assert "wealth" not in grounded, "out-of-scope facts must not be sent to Foundry"


# ---------------------------------------------------------------------------
# Foundry client unit behaviour
# ---------------------------------------------------------------------------


def test_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("FOUNDRY_AGENT_NAME", raising=False)
    assert FoundryPromptAgent.from_env() is None


def test_from_env_builds_configured_agent(monkeypatch):
    monkeypatch.setenv(
        "FOUNDRY_PROJECT_ENDPOINT",
        "https://example.services.ai.azure.com/api/projects/ops/",
    )
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "operations-copilot")
    built = FoundryPromptAgent.from_env()

    assert built is not None
    assert built.agent_name == "operations-copilot"
    # A trailing slash would produce a double slash in every request path.
    assert built.project_endpoint.endswith("/projects/ops")
    assert built.api_version == "v1"


def test_partial_configuration_is_rejected():
    with pytest.raises(FoundryAgentNotConfigured):
        FoundryPromptAgent(project_endpoint="https://example", agent_name="")


def test_prompt_forbids_speculation_and_bounds_context():
    prompt = _build_prompt(question="how many VMs?", context={"results": ["x" * 40_000]})
    assert "do not\nspeculate" in prompt or "speculate" in prompt
    assert "(truncated)" in prompt
    assert "how many VMs?" in prompt


@pytest.mark.parametrize(
    "payload",
    [
        {"output_text": "hello"},
        {"output_text": ["hello"]},
        {"output": [{"content": [{"text": "hello"}]}]},
        {"output": [{"content": [{"text": {"value": "hello"}}]}]},
        {"output": [{"content": "hello"}]},
    ],
)
def test_extracts_text_from_supported_response_shapes(payload):
    assert _extract_text(payload) == "hello"


def test_extracting_text_from_an_empty_response_yields_nothing():
    assert _extract_text({"output": []}) == ""
