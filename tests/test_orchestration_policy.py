from __future__ import annotations

from copy import deepcopy

import pytest

from api.scope import Scope
from operations.orchestration_contract import (
    CandidatePlan,
    EvidenceSnapshotV2,
    InvestigationRequest,
    SnapshotCoverage,
    SnapshotEvidence,
    SnapshotFreshness,
    SpecialistStep,
    ToolCallCandidate,
)
from operations.orchestration_policy import OrchestrationPolicy, PolicyViolation
from operations.specialist_manifest import (
    INVENTORY_DATA_HEALTH_ID,
    load_specialist_manifest,
)


def _request(*, scope: dict[str, list[str]] | None = None) -> InvestigationRequest:
    return InvestigationRequest(
        question="Show the inventory resources and whether the data is current.",
        requested_scope=scope or {"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(visible_count=1, total_count=2, complete=False),
            freshness=[
                SnapshotFreshness(
                    source="inventory",
                    observed_at="2026-09-01T00:00:00Z",
                    status="stale",
                )
            ],
            evidence=[
                SnapshotEvidence(
                    evidence_id="inventory:visible",
                    source="inventory-page",
                    status="ok",
                    observed_at="2026-09-01T00:00:00Z",
                    data={"visible": 1},
                )
            ],
        ),
    )


def _candidate() -> CandidatePlan:
    return CandidatePlan(
        steps=[
            SpecialistStep(
                specialist_id=INVENTORY_DATA_HEALTH_ID,
                tool_calls=[
                    ToolCallCandidate(
                        tool="inventory_resources",
                        arguments={},
                        citation_ids=["inventory:visible"],
                    )
                ],
            )
        ],
        estimated_tokens=500,
        max_wall_seconds=5,
    )


def test_inventory_manifest_is_strict_credential_free_and_read_only():
    manifest = load_specialist_manifest()
    specialist = manifest.require(INVENTORY_DATA_HEALTH_ID)

    assert specialist.display_name == "Inventory & Data Health"
    assert specialist.operations_mcp_tools == ("inventory_resources",)
    assert specialist.read_only is True
    assert set(specialist.page_mappings) == {
        "inventory",
        "connections",
        "connections_fabric",
    }
    serialized = manifest.model_dump_json().casefold()
    assert all(
        marker not in serialized
        for marker in ("client_secret", "access_token", "api_key", "password")
    )


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda plan: plan["steps"][0].update(
                {"specialist_id": "unknown_specialist"}
            ),
            "unknown_specialist",
        ),
        (
            lambda plan: plan["steps"][0]["tool_calls"][0].update(
                {"tool": "network_topology"}
            ),
            "tool_not_granted",
        ),
        (
            lambda plan: plan["steps"][0]["tool_calls"][0].update(
                {"tool": "unknown_tool"}
            ),
            "unknown_tool",
        ),
        (
            lambda plan: plan["steps"][0]["tool_calls"][0].update(
                {"arguments": {"unexpected": "value"}}
            ),
            "invalid_arguments",
        ),
        (
            lambda plan: plan["steps"][0].update(
                {"depends_on": [INVENTORY_DATA_HEALTH_ID]}
            ),
            "dependency_cycle",
        ),
        (
            lambda plan: plan.update({"estimated_tokens": 100_000}),
            "budget_exceeded",
        ),
        (
            lambda plan: plan.update({"mutation_intent": True}),
            "mutation_forbidden",
        ),
        (
            lambda plan: plan["steps"][0]["tool_calls"][0].update(
                {"citation_ids": ["foreign:evidence"]}
            ),
            "foreign_citation",
        ),
        (
            lambda plan: plan["steps"][0]["tool_calls"][0].update(
                {"citation_ids": []}
            ),
            "citation_required",
        ),
    ],
)
def test_rejected_candidate_is_denied_before_executor_io(mutate, code):
    policy = OrchestrationPolicy()
    payload = deepcopy(_candidate().model_dump(mode="json"))
    mutate(payload)
    candidate = CandidatePlan.model_validate(payload)
    calls: list[str] = []

    with pytest.raises(PolicyViolation, match=code):
        policy.validate(
            request=_request(),
            candidate=candidate,
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )

    assert calls == []


def test_widened_scope_is_rejected_before_candidate_execution():
    with pytest.raises(PolicyViolation, match="scope_widening"):
        OrchestrationPolicy().validate(
            request=_request(scope={"subscription": ["sub-a", "sub-b"]}),
            candidate=_candidate(),
            effective_scope=Scope({"subscription": ["sub-a"]}),
        )
