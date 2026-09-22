"""Regression coverage for foundry-topology-narration (budget starvation).

Live production symptom: an authenticated /network investigate-context call
consistently entered deterministic fallback with fallback_reason reported
alongside uncertainty "Foundry narration timed out", even though the
container's published Foundry agent manifests (operations-copilot v6,
network agent v16, executive-summary agent v16, gpt-5.4-mini) were validated
with timeout_seconds=30 -- far more than the ~8-11 second end-to-end request
duration actually observed.

Root cause: ``OrchestrationService.execute_turn`` computed a single
wall-clock ``deadline`` from the *candidate's own* ``max_wall_seconds``
(governing tool-call execution, defaulting to 5 seconds when a resolved
CandidatePlan does not declare a larger value -- which is exactly what both
``build_deterministic_fallback`` and most coordinator-proposed plans yield)
and then reused that same shrinking deadline, unmodified, as the timeout
budget handed to the downstream Foundry executive/narration call in
``_synthesize``. Any time consumed by the (unrelated) tool-execution loop
came directly out of the narrator's budget, so by the time narration was
attempted it was routinely given a small fraction of a second -- nowhere
near the 30-second window the pinned agent was actually provisioned and
validated for -- guaranteeing a local ``FutureTimeoutError``/
``FoundryAgentError`` cancellation long before the provider could ever
respond.

Fix: narration now gets its own deadline, measured from the same
``execution_started`` instant but bounded by the governance policy ceiling
(``OrchestrationPolicy.limits.max_wall_seconds``, 30s by default) rather than
by the tool-execution candidate's own (often much smaller) declared budget.
"""

from __future__ import annotations

import json

from api.evidence import Evidence
from api.scope import Scope
from operations import maf_orchestrator
from operations.foundry_agent import AgentAnswer
from operations.maf_orchestrator import build_deterministic_fallback
from operations.orchestration_contract import (
    EvidenceSnapshotV2,
    InvestigationRequest,
    SnapshotCoverage,
)
from operations.orchestration_service import OrchestrationService
from operations.specialist_manifest import load_specialist_manifest
from operations.tools import STATUS_OK, ToolResult
from tests.copilot_authorization_fixtures import route_authority_for_test


class _Clock:
    """Deterministic monotonic clock a test can advance explicitly."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _network_request() -> InvestigationRequest:
    return InvestigationRequest(
        question="Show me the network topology",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="network",
            page_id="network-topology",
            coverage=SnapshotCoverage(visible_count=2, total_count=2, complete=True),
        ),
    )


_HUB_ID = (
    "/subscriptions/sub-a/resourceGroups/rg/providers/"
    "Microsoft.Network/virtualNetworks/hub-vnet"
)
_ISOLATED_ID = (
    "/subscriptions/sub-a/resourceGroups/rg/providers/"
    "Microsoft.Network/virtualNetworks/isolated-vnet"
)


def _network_topology_tool_result() -> ToolResult:
    return ToolResult(
        status=STATUS_OK,
        data={
            "summary": {
                "hub_count": 1,
                "spoke_count": 0,
                "isolated_vnet_count": 1,
                "shared_service_count": 2,
            },
            "topology": {
                "hubs": [{
                    "id": _HUB_ID,
                    "name": "hub-vnet",
                    "entity_type": "Microsoft.Network/virtualNetworks",
                    "role": "hub",
                    "peer_count": 1,
                }],
                "isolated": [{
                    "id": _ISOLATED_ID,
                    "name": "isolated-vnet",
                    "entity_type": "Microsoft.Network/virtualNetworks",
                    "role": "isolated",
                    "peer_count": 0,
                }],
            },
        },
        evidence=(
            Evidence(
                source_engine="network.topology",
                source_table="topology/hubs",
                resource_id=_HUB_ID,
                confidence="high",
            ),
            Evidence(
                source_engine="network.topology",
                source_table="topology/isolated",
                resource_id=_ISOLATED_ID,
                confidence="high",
            ),
        ),
    )


class _RecordingExecutiveAgent:
    """Stub narrator that records the timeout budget it is given."""

    def __init__(self) -> None:
        self.calls: list[float | None] = []

    def answer(self, *, question, context, timeout_seconds=None, **_kwargs):
        self.calls.append(timeout_seconds)
        return AgentAnswer(
            text=json.dumps([
                {
                    "specialist_id": "network",
                    "summary": "Narration synthesized within budget.",
                    "evidence_refs": [],
                }
            ]),
            agent_name="executive-summary",
            agent_version="16",
        )


def test_narration_deadline_is_not_starved_by_a_small_tool_execution_budget(
    monkeypatch,
):
    """The exact production shape: a small candidate wall-clock budget must
    not leave the Foundry narrator with only its remainder.

    Reproduces the live symptom directly: a resolved candidate declares the
    Pydantic-default ``max_wall_seconds=5`` (what ``build_deterministic_fallback``
    and most coordinator-proposed plans yield when they do not declare a
    larger tool-execution budget of their own), and the tool-execution loop
    consumes almost all of it before narration is ever attempted.
    """

    # Deterministically select the canonical execution route regardless of
    # the test principal's hash bucket (mirrors the shared authorization
    # test fixtures' approach without depending on their broken packaged-
    # manifest setup, which is unrelated to this bug).
    monkeypatch.setattr(maf_orchestrator, "_canary_bucket", lambda _stable_key: 0)

    clock = _Clock()
    executive_agent = _RecordingExecutiveAgent()

    def slow_executor(name, arguments, *, context, scope):
        # Consume 4.9 of the candidate's 5-second tool-execution budget --
        # exactly the kind of network/KQL round trip that made production
        # requests take several seconds before narration was ever reached.
        clock.advance(4.9)
        return _network_topology_tool_result()

    manifest = load_specialist_manifest()
    request = _network_request()
    service = OrchestrationService(
        planner=lambda _request: build_deterministic_fallback(_request, manifest),
        executor=slow_executor,
        executive_agent=executive_agent,
        clock=clock,
        always_synthesize=True,
    )

    result = service.execute(
        request,
        context=object(),
        principal_subject="operator-a",
        effective_scope=Scope({"subscription": ["sub-a"]}),
        route_authority=route_authority_for_test(request),
    )

    assert executive_agent.calls, (
        "the executive/narration agent must actually be invoked once tool "
        "execution completes, not skipped as budget-exhausted"
    )
    narration_budget = executive_agent.calls[0]
    assert narration_budget is not None
    # The old behaviour reused the tool-execution deadline (execution_started
    # + 5s candidate budget); after 4.9s of tool execution that left ~0.1s --
    # nowhere near enough for a real Foundry round trip. The fix measures
    # narration's own budget from the same execution_started instant against
    # the governance policy ceiling (30s), so narration must still see most
    # of that window even though the tool loop nearly exhausted its own
    # much smaller 5-second candidate budget.
    assert narration_budget > 20.0, (
        "narration must receive a budget bounded by the governance policy "
        "ceiling, not by whatever the tool-execution loop already consumed "
        f"out of the candidate's own (much smaller) wall_seconds; got "
        f"{narration_budget!r}"
    )
    # The narrator was actually reached (not skipped/timed out locally) --
    # the essential regression proof above (a real, non-starved budget)
    # already demonstrates the fix; result wiring for the final response
    # is exercised separately by test_topology_insights_empty_fallback.py.
    assert result.status in {"ok", "partial"}
