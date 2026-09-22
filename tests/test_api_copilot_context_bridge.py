from types import SimpleNamespace

from api.routers.copilot import _run_context_via_canonical
from operations.orchestration_contract import (
    CandidatePlan,
    Citation,
    OrchestrationResult,
    SnapshotCoverage,
)
from operations.orchestration_service import OrchestrationService
from tests.copilot_authorization_fixtures import rollout_decision_for_test


def test_context_canonical_selected_vnet_uses_network_plan_and_narrator(
    monkeypatch,
) -> None:
    """The Network drawer keeps its shared legacy narration contract."""

    selected_vnet_id = (
        "/subscriptions/sub-a/resourceGroups/rg/providers/"
        "Microsoft.Network/virtualNetworks/hub-vnet"
    )
    network_agent = object()
    shared_agent = object()
    captured: dict[str, object] = {}
    fake_result = OrchestrationResult(
        status="ok",
        policy_status="accepted",
        selected_specialists=["network"],
        selected_tools=["network_topology", "hub_dependents"],
        coverage=SnapshotCoverage(visible_count=1, total_count=1, complete=False),
        citations=[
            Citation(
                citation_id="network:visible",
                source="network",
                status="ok",
            )
        ],
        thread_id="thr-" + "b" * 32,
        thread_revision=1,
        synthesis={
            "status": "synthesized",
            "mode": "foundry",
            "agent": "network-narrator",
            "narration": "Topology is hub-and-spoke.\n\nHub has two dependents.",
            "claims": [
                {"summary": "Topology is hub-and-spoke."},
                {"summary": "Hub has two dependents."},
            ],
        },
    )

    def _capture_execute(self, request, **_kwargs):
        captured["executive_agent"] = self.executive_agent
        captured["plan"] = self.planner(request) if self.planner else None
        return fake_result

    monkeypatch.setattr(OrchestrationService, "execute", _capture_execute)
    snapshot = SimpleNamespace(
        page_kind="network",
        page_id="network-topology",
        question="What depends on this hub?",
        evidence=[],
        freshness=[],
        selected_resources=[
            SimpleNamespace(
                resource_id=selected_vnet_id,
                resource_type="Microsoft.Network/virtualNetworks",
            )
        ],
    )
    context = SimpleNamespace(
        specialist_agent=lambda agent_id: (
            network_agent if agent_id == "network" else None
        ),
        foundry_agent=lambda: shared_agent,
    )
    scope = SimpleNamespace(to_dict=lambda: {"subscription": ["sub-a"]})
    rollout_decision = rollout_decision_for_test(
        principal_subject="test@example.com"
    )

    ledger = _run_context_via_canonical(
        snapshot,
        context=context,
        scope=scope,
        principal=SimpleNamespace(subject="test@example.com"),
        principal_subject="test@example.com",
        rollout_decision=rollout_decision,
    )

    plan = captured["plan"]
    assert captured["executive_agent"] is network_agent
    assert isinstance(plan, CandidatePlan)
    assert [call.tool for call in plan.steps[0].tool_calls] == [
        "network_topology",
        "hub_dependents",
    ]
    assert plan.steps[0].tool_calls[1].arguments == {"vnet_id": selected_vnet_id}
    assert ledger["synthesis"]["mode"] == "foundry"
    assert ledger["synthesis"]["narration"] == (
        "Topology is hub-and-spoke.\n\nHub has two dependents."
    )
    assert ledger["synthesis"]["synthesis_agent"] == "network-narrator"
    assert ledger["synthesis_mode"] == "foundry"
    assert ledger["synthesis_agent"] == "network-narrator"

    fallback_context = SimpleNamespace(
        specialist_agent=lambda _agent_id: None,
        foundry_agent=lambda: shared_agent,
    )
    _run_context_via_canonical(
        snapshot,
        context=fallback_context,
        scope=scope,
        principal=SimpleNamespace(subject="test@example.com"),
        principal_subject="test@example.com",
        rollout_decision=rollout_decision,
    )
    assert captured["executive_agent"] is shared_agent
