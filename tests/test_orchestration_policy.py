from __future__ import annotations

from copy import deepcopy

import pytest

from api.scope import Scope
from operations.orchestration_contract import (
    COVERAGE_CITATION_ID,
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
    "evidence_id",
    [
        "tool:0:0:inventory_data_health:inventory_resources:0",
        "snapshot:coverage",
    ],
)
def test_snapshot_rejects_server_generated_citation_namespaces(evidence_id):
    with pytest.raises(ValueError, match="reserved citation namespace"):
        SnapshotEvidence(
            evidence_id=evidence_id,
            source="caller-supplied-snapshot",
        )


def test_snapshot_accepts_normal_caller_evidence_id():
    evidence = SnapshotEvidence(
        evidence_id="inventory:visible",
        source="inventory-page",
    )

    assert evidence.evidence_id == "inventory:visible"


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


# ---------------------------------------------------------------------------
# Plan 11-03 Task 1: Generalized keyword fallback and multi-specialist policy
# ---------------------------------------------------------------------------


def test_deterministic_keyword_fallback_produces_valid_candidate():
    """build_deterministic_fallback constructs a CandidatePlan that passes
    the same policy validator applied to model-proposed candidates."""
    from operations.maf_orchestrator import build_deterministic_fallback

    manifest = load_specialist_manifest()
    request = _request()
    candidate = build_deterministic_fallback(request, manifest)

    policy = OrchestrationPolicy(manifest=manifest)
    validated = policy.validate(
        request=request,
        candidate=candidate,
        effective_scope=Scope({"subscription": ["sub-a"]}),
    )
    assert validated.steps
    for step in validated.steps:
        spec = manifest.require(step.specialist_id)
        assert request.snapshot.page_kind in spec.page_mappings
        for call in step.tool_calls:
            assert call.tool in spec.operations_mcp_tools


def test_keyword_fallback_page_constrains_specialist_selection():
    """The fallback only selects specialists whose page_mappings include
    the request's page_kind — a network specialist cannot appear for
    an inventory snapshot."""
    from operations.maf_orchestrator import build_deterministic_fallback

    manifest = load_specialist_manifest()
    # Question mentions network keywords, but page is inventory
    request = InvestigationRequest(
        question="Show network topology and firewall gaps for these resources.",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(visible_count=1, total_count=1, complete=True),
            evidence=[
                SnapshotEvidence(
                    evidence_id="inv:row1",
                    source="inventory-page",
                    status="ok",
                )
            ],
        ),
    )
    candidate = build_deterministic_fallback(request, manifest)

    # Every step must map to inventory, regardless of network keywords
    for step in candidate.steps:
        spec = manifest.require(step.specialist_id)
        assert "inventory" in spec.page_mappings
    # Must not select network specialist (maps to network/twin only)
    assert not any(step.specialist_id == "network" for step in candidate.steps)


def test_keyword_fallback_citations_reference_submitted_evidence():
    """Fallback candidate citations are drawn from the request's evidence,
    never from fabricated or empty references."""
    from operations.maf_orchestrator import build_deterministic_fallback

    manifest = load_specialist_manifest()
    request = _request()
    candidate = build_deterministic_fallback(request, manifest)

    evidence_ids = {item.evidence_id for item in request.snapshot.evidence}
    evidence_ids.add(COVERAGE_CITATION_ID)
    for step in candidate.steps:
        for call in step.tool_calls:
            assert call.citation_ids
            assert set(call.citation_ids) <= evidence_ids


def test_keyword_fallback_empty_evidence_uses_coverage_citation():
    """When the snapshot has no evidence rows, fallback uses the canonical
    coverage citation so the policy's requires_citations check passes."""
    from operations.maf_orchestrator import build_deterministic_fallback

    manifest = load_specialist_manifest()
    request = InvestigationRequest(
        question="Show inventory resources.",
        requested_scope={"subscription": ["sub-a"]},
        snapshot=EvidenceSnapshotV2(
            page_kind="inventory",
            page_id="inventory",
            coverage=SnapshotCoverage(
                visible_count=0, total_count=0, complete=True
            ),
        ),
    )
    candidate = build_deterministic_fallback(request, manifest)

    for step in candidate.steps:
        for call in step.tool_calls:
            assert COVERAGE_CITATION_ID in call.citation_ids


def test_keyword_fallback_no_mutation_intent():
    """The deterministic fallback never sets mutation_intent, matching the
    no-production-mutation decision (D-10)."""
    from operations.maf_orchestrator import build_deterministic_fallback

    manifest = load_specialist_manifest()
    candidate = build_deterministic_fallback(_request(), manifest)

    assert candidate.mutation_intent is False
    for step in candidate.steps:
        for call in step.tool_calls:
            assert call.mutation is False
