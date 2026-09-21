from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context
from test_api_copilot_unified import _canonical_body

from api.app import create_app
from api.evidence import Evidence
from operations.foundry_agent import (
    FoundryAgentError,
    FoundryCoordinatorPlanner,
    FoundryCoordinatorSynthesisAgent,
)
from operations.investigation import run_investigation
from operations.orchestration_service import OrchestrationService
from operations.tools import STATUS_OK, ToolResult
from tests.copilot_authorization_fixtures import enable_authorized_canary


class CountingExecutiveAgent:
    def __init__(self) -> None:
        self.calls = 0

    def answer(self, **_kwargs):
        self.calls += 1
        raise FoundryAgentError("offline test provider")


@pytest.mark.parametrize(
    (
        "mode",
        "percentage",
        "canonical_enabled",
        "shadow_validated",
        "execution_path",
    ),
    (
        ("compatibility", None, False, False, "compatibility"),
        ("shadow", None, False, True, "compatibility"),
        ("canary", "10", True, False, "canonical"),
    ),
)
def test_drawer_endpoint_applies_rollout_once_without_duplicate_io(
    tmp_path,
    monkeypatch,
    mode,
    percentage,
    canonical_enabled,
    shadow_validated,
    execution_path,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", mode)
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)
    if percentage is None:
        monkeypatch.delenv("AIOPS_COPILOT_CANARY_PERCENTAGE", raising=False)
    else:
        monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", percentage)
    if mode == "canary":
        enable_authorized_canary(monkeypatch)

    resource_id = (
        "/subscriptions/sub-a/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/vm-1"
    )
    compatibility_tool_calls: list[str] = []
    canonical_tool_calls: list[str] = []
    compatibility_executions = 0
    canonical_executions = 0

    def compatibility_execute(*args, **kwargs):
        nonlocal compatibility_executions
        compatibility_executions += 1
        return run_investigation(*args, **kwargs)

    original_canonical_execute = OrchestrationService.execute

    def canonical_execute(self, *args, **kwargs):
        nonlocal canonical_executions
        canonical_executions += 1
        return original_canonical_execute(self, *args, **kwargs)

    def compatibility_call_tool(name, arguments, *, context, scope, principal=None):
        compatibility_tool_calls.append(name)
        return ToolResult(
            status=STATUS_OK,
            data={"resource_id": resource_id},
            evidence=(
                Evidence(
                    source_engine="test",
                    source_table="compatibility-rollout",
                    resource_id=resource_id,
                    confidence="high",
                ),
            ),
        )

    def canonical_call_tool(name, arguments, *, context, scope, principal=None):
        canonical_tool_calls.append(name)
        return ToolResult(
            status=STATUS_OK,
            data={"resource_id": resource_id},
            evidence=(
                Evidence(
                    source_engine="test",
                    source_table="rollout",
                    resource_id=resource_id,
                    confidence="high",
                ),
            ),
        )

    executive = CountingExecutiveAgent()
    context = _context(tmp_path, executive)
    context.executive_summary_agent_provider = lambda: executive
    monkeypatch.setattr(
        "api.routers.copilot.run_investigation",
        compatibility_execute,
    )
    monkeypatch.setattr(OrchestrationService, "execute", canonical_execute)
    monkeypatch.setattr(
        "operations.investigation.call_tool",
        compatibility_call_tool,
    )
    monkeypatch.setattr("api.routers.copilot.call_tool", canonical_call_tool)
    body = _canonical_body()
    body.pop("hint")
    body["question"] = "Give an executive overview of this resource."
    body["snapshot"] = {
        **body["snapshot"],
        "page_kind": "overview",
        "page_id": "operations-overview",
        "selected_entities": [{"type": "azure", "resource_id": resource_id}],
        "evidence": [],
    }

    response = TestClient(
        create_app(context),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["rollout"]["mode"] == mode
    assert result["rollout"]["canonical_enabled"] is canonical_enabled
    assert result["rollout"]["shadow_enabled"] is (mode == "shadow")
    assert result["rollout"]["shadow_validated"] is shadow_validated
    assert result["policy_status"] == (
        "accepted" if canonical_enabled else "fallback"
    )
    if execution_path == "compatibility":
        assert compatibility_tool_calls == result["selected_tools"]
        assert compatibility_tool_calls
        assert canonical_tool_calls == []
        assert compatibility_executions == 1
        assert canonical_executions == 0
    else:
        assert canonical_tool_calls == result["selected_tools"]
        assert canonical_tool_calls
        assert compatibility_tool_calls == []
        assert compatibility_executions == 0
        assert canonical_executions == 1
    assert executive.calls == 1


def test_shadow_reports_deterministic_plan_comparison_without_canonical_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "shadow")
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    compatibility_calls: list[str] = []
    canonical_calls: list[str] = []

    def compatibility_call_tool(name, arguments, *, context, scope, principal=None):
        compatibility_calls.append(name)
        return ToolResult(status=STATUS_OK)

    def canonical_call_tool(name, arguments, *, context, scope, principal=None):
        canonical_calls.append(name)
        return ToolResult(status=STATUS_OK)

    def fail_canonical_path(*_args, **_kwargs):
        raise AssertionError("shadow preview executed a canonical I/O path")

    monkeypatch.setattr(
        "operations.investigation.call_tool",
        compatibility_call_tool,
    )
    monkeypatch.setattr("api.routers.copilot.call_tool", canonical_call_tool)
    monkeypatch.setattr(OrchestrationService, "execute", fail_canonical_path)
    monkeypatch.setattr(
        FoundryCoordinatorPlanner,
        "__call__",
        fail_canonical_path,
    )
    monkeypatch.setattr(
        FoundryCoordinatorSynthesisAgent,
        "answer",
        fail_canonical_path,
    )
    body = _canonical_body()
    body.pop("hint")
    body["question"] = "Give an executive overview of this resource."
    body["snapshot"] = {
        **body["snapshot"],
        "page_kind": "overview",
        "page_id": "operations-overview",
        "selected_entities": [],
        "evidence": [],
    }

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    comparison = result["rollout"]["comparison"]
    assert result["rollout"]["shadow_reason"] == "accepted"
    assert comparison["compatibility"]["plan_outcome"] == "planned"
    assert comparison["compatibility"]["selected_tools"] == compatibility_calls
    assert comparison["canonical"]["policy_status"] == "accepted"
    assert comparison["canonical"]["plan_outcome"] == "planned"
    assert comparison["canonical"]["selected_tools"]
    assert canonical_calls == []
    assert result["rollout"]["canonical_preview_external_io"] == {
        "tool_calls": 0,
        "model_or_narration_calls": 0,
    }
    assert all(
        count == 0
        for count in result["rollout"][
            "canonical_preview_external_io"
        ].values()
    )
    assert comparison["matches"]["plan_outcome"] is True
    assert comparison["matches"]["selected_tools"] is True
    assert comparison["divergent_fields"] == []


def test_drawer_endpoint_honors_invalid_rollback_as_compatibility(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    monkeypatch.delenv("AIOPS_COPILOT_CANARY_PERCENTAGE", raising=False)
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "canonical")
    body = _canonical_body()
    body.pop("hint")

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["rollout"] == {
        "mode": "compatibility",
        "canonical_enabled": False,
        "shadow_enabled": False,
        "shadow_validated": False,
        "shadow_reason": "",
    }


def test_drawer_default_without_separate_authority_is_denied(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "deterministic")
    body = _canonical_body()
    body.pop("hint")

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_request"
    assert "rollout percentage is malformed" in response.json()["error"]["message"]


def test_shadow_rejects_invalid_hint_before_primary_or_preview_io(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "shadow")
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    compatibility_calls: list[str] = []
    canonical_calls: list[str] = []

    def compatibility_call_tool(name, arguments, *, context, scope, principal=None):
        compatibility_calls.append(name)
        return ToolResult(status=STATUS_OK)

    def canonical_call_tool(name, arguments, *, context, scope, principal=None):
        canonical_calls.append(name)
        return ToolResult(status=STATUS_OK)

    monkeypatch.setattr(
        "operations.investigation.call_tool",
        compatibility_call_tool,
    )
    monkeypatch.setattr("api.routers.copilot.call_tool", canonical_call_tool)
    body = _canonical_body(
        hint={
            "specialist_id": "remediation",
            "tool": "inventory_resources",
            "arguments": {},
        }
    )

    response = TestClient(
        create_app(_context(tmp_path, None)),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=body,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["reason"] == "page_not_granted"
    assert compatibility_calls == []
    assert canonical_calls == []
