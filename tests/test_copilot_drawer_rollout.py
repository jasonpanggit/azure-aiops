from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_api_copilot_investigation import HEADERS, _context
from test_api_copilot_unified import _canonical_body

from api.app import create_app
from api.evidence import Evidence
from operations.foundry_agent import FoundryAgentError
from operations.tools import STATUS_OK, ToolResult


class CountingExecutiveAgent:
    def __init__(self) -> None:
        self.calls = 0

    def answer(self, **_kwargs):
        self.calls += 1
        raise FoundryAgentError("offline test provider")


@pytest.mark.parametrize(
    ("mode", "percentage", "canonical_enabled", "shadow_validated"),
    (
        ("compatibility", None, False, False),
        ("shadow", None, False, True),
        ("canary", "0", False, False),
        ("canary", "100", True, False),
        ("default", None, True, False),
    ),
)
def test_drawer_endpoint_applies_rollout_once_without_duplicate_io(
    tmp_path,
    monkeypatch,
    mode,
    percentage,
    canonical_enabled,
    shadow_validated,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", mode)
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)
    if percentage is None:
        monkeypatch.delenv("AIOPS_COPILOT_CANARY_PERCENTAGE", raising=False)
    else:
        monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", percentage)

    resource_id = (
        "/subscriptions/sub-a/resourceGroups/rg/providers/"
        "Microsoft.Compute/virtualMachines/vm-1"
    )
    tool_calls: list[str] = []

    def call_tool(name, arguments, *, context, scope, principal=None):
        tool_calls.append(name)
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
    context = _context(tmp_path, None)
    context.executive_summary_agent_provider = lambda: executive
    monkeypatch.setattr("api.routers.copilot.call_tool", call_tool)
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
    assert result["rollout"] == {
        "mode": mode,
        "canonical_enabled": canonical_enabled,
        "shadow_enabled": mode == "shadow",
        "shadow_validated": shadow_validated,
        "shadow_reason": "accepted" if shadow_validated else "",
        "shadow_comparison": result["rollout"]["shadow_comparison"],
    }
    assert result["policy_status"] == (
        "accepted" if canonical_enabled else "fallback"
    )
    assert result["fallback_reason"] == (
        "" if canonical_enabled else "compatibility_rollout"
    )
    if mode == "shadow":
        assert result["rollout"]["shadow_comparison"] is not None
        assert result["rollout"]["shadow_comparison"]["canonical"]
        assert result["rollout"]["shadow_comparison"]["compatibility"]
    else:
        assert result["rollout"]["shadow_comparison"] is None
    assert len(tool_calls) == len(result["selected_tools"])
    assert tool_calls
    assert executive.calls == 1


def test_drawer_endpoint_honors_invalid_rollback_as_compatibility(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
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
        "shadow_comparison": None,
    }


def test_drawer_default_respects_deterministic_emergency_override(
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

    assert response.status_code == 200, response.text
    assert response.json()["data"]["rollout"] == {
        "mode": "compatibility",
        "canonical_enabled": False,
        "shadow_enabled": False,
        "shadow_validated": False,
        "shadow_reason": "",
        "shadow_comparison": None,
    }


def test_shadow_rejection_does_not_fail_or_duplicate_primary_execution(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "shadow")
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    calls: list[str] = []

    def call_tool(name, arguments, *, context, scope, principal=None):
        calls.append(name)
        return ToolResult(status=STATUS_OK)

    monkeypatch.setattr("api.routers.copilot.call_tool", call_tool)
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

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["rollout"]["shadow_validated"] is False
    assert result["rollout"]["shadow_reason"].startswith("candidate_rejected:")
    assert calls == ["inventory_resources"]
