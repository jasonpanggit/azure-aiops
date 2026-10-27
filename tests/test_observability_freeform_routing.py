"""Freeform observability questions retain reviewed scenario semantics."""

import pytest
from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, StubAgent, _context
from test_api_copilot_unified import _resource_health_page_request
from test_observability_arg_reader import ToolCtx, reader

from api.app import create_app
from api.scope import Scope
from operations import investigation
from operations.maf_orchestrator import build_deterministic_fallback
from operations.orchestration_contract import InvestigationRequest
from operations.orchestration_policy import OrchestrationPolicy
from operations.specialist_manifest import load_specialist_manifest
from operations.tools import call_tool


def _body(question):
    body = _resource_health_page_request()
    body["question"] = question
    body.pop("hint", None)
    body["snapshot"]["coverage"]["complete"] = False
    return body


@pytest.mark.parametrize("hinted", [False, True])
@pytest.mark.parametrize(
    ("question", "scenario", "status"),
    [
        (
            "Check alert rules and Action Group references.",
            "alert_delivery_coverage",
            "partial",
        ),
        (
            "Check diagnostic settings against workload logging policy.",
            "diagnostic_settings_coverage",
            "unavailable",
        ),
    ],
)
def test_hinted_and_freeform_observability_use_same_governed_scenario(
    tmp_path, monkeypatch, hinted, question, scenario, status
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    calls = []

    def observed_tool(name, arguments, **kwargs):
        calls.append((name, arguments))
        return call_tool(
            name, arguments, context=ToolCtx(reader()), scope=kwargs["scope"]
        )

    monkeypatch.setattr(investigation, "call_tool", observed_tool)
    body = _body(question)
    if hinted:
        body["hint"] = {
            "specialist_id": "resource_health_observability",
            "tool": "incidents",
            "arguments": {"scenario": scenario},
        }
    agent = StubAgent()
    response = TestClient(create_app(_context(tmp_path, agent))).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert calls == [("incidents", {"scenario": scenario})]
    assert data["status"] == status
    assert data["tool_results"][0]["status"] == status
    assert {item["status"] for item in data["citations"]} == {status}
    assert data["synthesis"]["compatibility_answer"]["model"] == "deterministic"
    assert data["coverage"]["complete"] is False
    assert data["mutation_authorized"] is False
    assert agent.calls == []


@pytest.mark.parametrize(
    "question",
    [
        "What incidents relate to these resources?",
        "Show recent alerts.",
        "Explain resource utilization.",
    ],
)
def test_unrelated_resource_health_questions_do_not_gain_coverage_scenario(question):
    request = InvestigationRequest.model_validate(_body(question))
    manifest = load_specialist_manifest()
    candidate = build_deterministic_fallback(request, manifest)
    validated = OrchestrationPolicy(manifest=manifest).validate(
        request=request,
        candidate=candidate,
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    assert all(
        "scenario" not in call.arguments
        for step in validated.steps
        for call in step.tool_calls
    )


@pytest.mark.parametrize(
    ("question", "scenario"),
    [
        ("CHECK ALERT RULES AND ACTION GROUP REFERENCES.", "alert_delivery_coverage"),
        ("Review alert delivery coverage", "alert_delivery_coverage"),
        ("Review diagnostic settings", "diagnostic_settings_coverage"),
        ("Check workload logging policy", "diagnostic_settings_coverage"),
    ],
)
def test_observability_freeform_candidate_passes_standard_policy(question, scenario):
    request = InvestigationRequest.model_validate(_body(question))
    manifest = load_specialist_manifest()
    validated = OrchestrationPolicy(manifest=manifest).validate(
        request=request,
        candidate=build_deterministic_fallback(request, manifest),
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    assert len(validated.steps) == 1
    assert validated.steps[0].specialist_id == "resource_health_observability"
    assert validated.steps[0].tool_calls[0].tool == "incidents"
    assert validated.steps[0].tool_calls[0].arguments == {"scenario": scenario}


def test_observability_intent_does_not_expand_other_page_grants():
    request = InvestigationRequest.model_validate(_body("Check alert rules."))
    request = request.model_copy(
        update={
            "snapshot": request.snapshot.model_copy(update={"page_kind": "inventory"})
        }
    )
    manifest = load_specialist_manifest()
    validated = OrchestrationPolicy(manifest=manifest).validate(
        request=request,
        candidate=build_deterministic_fallback(request, manifest),
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    assert all(
        "scenario" not in call.arguments
        for step in validated.steps
        for call in step.tool_calls
    )
