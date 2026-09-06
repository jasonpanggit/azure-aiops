from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from fabric.dataset_mapper import (
    ONTOLOGY_RELATIONSHIP_TYPES,
    allowed_relationship_triples,
    is_allowed_relationship_triple,
)
from ontology.ontology_validator import OntologyValidator
from ontology_discovery.contracts import (
    AdmissionEvaluationSnapshot,
    proposal_content_id,
)
from ontology_discovery.coordinator import ProposalPolicyCoordinator
from ontology_discovery.policy import (
    ProposalPolicy,
    evaluate_release_eligibility,
)
from ontology_discovery.store import (
    OntologyRunStore,
    PairReleaseDisabled,
    ProposalReviewConflict,
    ReviewerUnauthorized,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
SCOPE = "tenant-1/sub-1"
GENERATION = "generation-1"


def _entity(
    resource_id: str,
    entity_type: str,
    *,
    subscription_id: str = "sub-1",
    lifecycle_status: str = "active",
) -> dict[str, object]:
    retired_at = "" if lifecycle_status == "active" else NOW.isoformat()
    return {
        "tenant_id": "tenant-1",
        "subscription_id": subscription_id,
        "scope": f"tenant-1/{subscription_id}",
        "resource_id": resource_id,
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": GENERATION,
        "entity_type": entity_type,
        "name": resource_id,
        "resource_type": entity_type,
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": lifecycle_status,
        "valid_from": NOW.isoformat(),
        "retired_at": retired_at,
        "ontology_version": "v1",
    }


def _proposal(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "evidence_refs": ["evidence-1", "evidence-2"],
        "observed_at": NOW.isoformat(),
        "rationale": "Two current inventory sources support this exact edge.",
        "confidence": 0.98,
        "uncertainty": [],
        "disposition": "propose",
    }
    value.update(overrides)
    return value


def _evidence(
    evidence_id: str,
    source: str,
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "evidence_id": evidence_id,
        "scope": SCOPE,
        "source_generation_id": GENERATION,
        "source": source,
        "observed_at": NOW.isoformat(),
        "freshness": "fresh",
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "supports": True,
        "contradicts": False,
    }
    value.update(overrides)
    return value


def _policy_inputs() -> dict[str, object]:
    return {
        "entities": {
            "vm-1": _entity("vm-1", "VirtualMachine"),
            "app-1": _entity("app-1", "Application"),
        },
        "evidence_records": {
            "evidence-1": _evidence("evidence-1", "azure-resource-graph"),
            "evidence-2": _evidence("evidence-2", "fabric-lineage"),
        },
        "scope": SCOPE,
        "source_generation_id": GENERATION,
    }


def _relationship(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "scope": SCOPE,
        "resource_id": "relationship://vm-1/member_of/app-1",
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": GENERATION,
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "source": "model",
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
        "confidence": 0.98,
    }
    value.update(overrides)
    return value


def test_exact_triple_helpers_have_one_authoritative_source() -> None:
    assert allowed_relationship_triples() == frozenset(
        ONTOLOGY_RELATIONSHIP_TYPES
    )
    assert is_allowed_relationship_triple(
        "VirtualMachine", "member_of", "Application"
    )
    assert not is_allowed_relationship_triple(
        "Application", "member_of", "VirtualMachine"
    )
    assert not is_allowed_relationship_triple(
        "VirtualMachine", "MEMBER_OF", "Application"
    )


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (("proposal", "object_id", "missing"), "unknown_endpoint"),
        (("proposal", "subject_type", "Application"), "endpoint_type_mismatch"),
        (("proposal", "predicate", "contains"), "unsupported_triple"),
        (("entity", "app-1", "scope", "tenant-1/sub-2"), "cross_scope"),
        (("evidence", "evidence-1", "scope", "tenant-1/sub-2"), "cross_scope"),
        (("evidence", "evidence-1", "freshness", "stale"), "stale_evidence"),
        (("evidence", "evidence-1", "supports", False), "unsupported_evidence"),
        (("evidence", "evidence-1", "contradicts", True), "contradictory_evidence"),
        (("remove_evidence", "evidence-2"), "insufficient_corroboration"),
    ],
)
def test_policy_fails_closed_for_every_deterministic_defect(
    mutation: tuple[str, ...],
    expected_reason: str,
) -> None:
    proposal = _proposal()
    inputs = _policy_inputs()
    category, *parts = mutation
    if category == "proposal":
        proposal[parts[0]] = parts[1]
    elif category == "entity":
        entities = deepcopy(inputs["entities"])
        entities[parts[0]][parts[1]] = parts[2]
        inputs["entities"] = entities
    elif category == "evidence":
        evidence = deepcopy(inputs["evidence_records"])
        evidence[parts[0]][parts[1]] = (
            parts[2] == "True" if parts[2] in {"True", "False"} else parts[2]
        )
        inputs["evidence_records"] = evidence
    else:
        evidence = deepcopy(inputs["evidence_records"])
        evidence.pop(parts[0])
        inputs["evidence_records"] = evidence

    decision = ProposalPolicy(now=lambda: NOW).evaluate(
        proposal,
        review_status="accepted",
        **inputs,
    )

    assert decision.admitted is False
    assert expected_reason in decision.reasons


def test_accepted_review_is_durable_but_shadow_never_admits_model_edge() -> None:
    decision = ProposalPolicy(shadow_mode=True, now=lambda: NOW).evaluate(
        _proposal(),
        review_status="accepted",
        **_policy_inputs(),
    )

    assert decision.review_status == "accepted"
    assert decision.policy_eligible is True
    assert decision.admitted is False
    assert decision.reasons == ("shadow_review_only",)

    candidate = ProposalPolicy(shadow_mode=True).assemble_candidate(
        deterministic_edges=[_relationship(source="deterministic")],
        proposal_decisions=[decision],
    )
    assert [edge["source"] for edge in candidate] == ["deterministic"]


def test_deterministic_edge_wins_collision_even_outside_shadow_test_path() -> None:
    inputs = _policy_inputs()
    decision = ProposalPolicy(
        shadow_mode=False,
        allow_pair_release_testing=True,
        now=lambda: NOW,
    ).evaluate(
        _proposal(),
        review_status="accepted",
        admission_release={
            "status": "enabled",
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_type": "Application",
        },
        **inputs,
    )
    deterministic = _relationship(source="deterministic")

    candidate = ProposalPolicy(
        shadow_mode=False,
        allow_pair_release_testing=True,
    ).assemble_candidate(
        deterministic_edges=[deterministic],
        proposal_decisions=[decision],
    )

    assert candidate == [deterministic]


def test_full_candidate_validation_rechecks_scope_lifecycle_duplicates_and_triples() -> None:
    validator = OntologyValidator()
    entities = [
        _entity("vm-1", "VirtualMachine"),
        _entity("app-1", "Application"),
    ]
    valid = _relationship(source="deterministic")
    assert validator.validate(entities, [valid]).passed is True

    invalid_cases = [
        [_relationship(predicate="contains")],
        [_relationship(subscription_id="sub-2", scope="tenant-1/sub-2")],
        [_relationship(lifecycle_status="active", object_id="retired-app")],
        [valid, deepcopy(valid)],
        [
            valid,
            _relationship(resource_id="relationship://different-id-same-edge"),
        ],
    ]
    retired_entities = [
        entities[0],
        _entity("retired-app", "Application", lifecycle_status="retired"),
    ]
    for relationships in invalid_cases:
        selected_entities = (
            retired_entities
            if relationships[0]["object_id"] == "retired-app"
            else entities
        )
        report = validator.validate(selected_entities, relationships)
        assert report.passed is False
        assert report.invalid_relationships + report.duplicate_relationships >= 1


def test_evidence_past_source_freshness_deadline_is_stale() -> None:
    inputs = _policy_inputs()
    evidence = deepcopy(inputs["evidence_records"])
    evidence["evidence-1"]["observed_at"] = (
        NOW - timedelta(hours=2)
    ).isoformat()
    evidence["evidence-1"]["expires_at"] = (
        NOW - timedelta(seconds=1)
    ).isoformat()
    inputs["evidence_records"] = evidence

    decision = ProposalPolicy(now=lambda: NOW).evaluate(
        _proposal(),
        review_status="accepted",
        **inputs,
    )

    assert decision.admitted is False
    assert "stale_evidence" in decision.reasons


def _proposal_identity(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "proposal": _proposal(),
        "scope": SCOPE,
        "source_generation_id": GENERATION,
        "schema_version": "proposal-schema-v1",
        "policy_version": "proposal-policy-v1",
    }
    values.update(overrides)
    return values


def _eligible_snapshot(
    *,
    subject_type: str = "VirtualMachine",
    predicate: str = "member_of",
    object_type: str = "Application",
    evaluated_at: datetime = NOW,
    shadow_days: int = 30,
    expert_count: int = 200,
    critical_failures: tuple[str, ...] = (),
    escalation_recall: float = 1.0,
    recall: float = 0.9,
    precision_true_positives: int = 200,
    precision_total: int = 200,
    approvals: tuple[str, ...] = (
        "ontology_steward",
        "security_owner",
        "fabric_governance_steward",
    ),
    ai_spec_gates_passed: bool = True,
) -> AdmissionEvaluationSnapshot:
    return AdmissionEvaluationSnapshot.create(
        subject_type=subject_type,
        predicate=predicate,
        object_type=object_type,
        shadow_started_at=evaluated_at - timedelta(days=shadow_days),
        evaluated_at=evaluated_at,
        expert_adjudicated_eligible_count=expert_count,
        critical_failures=critical_failures,
        escalation_recall=escalation_recall,
        recall=recall,
        precision_true_positives=precision_true_positives,
        precision_total=precision_total,
        approvals=approvals,
        ai_spec_gates_passed=ai_spec_gates_passed,
    )


def test_proposal_identity_covers_scope_generation_triple_evidence_and_versions() -> None:
    baseline = _proposal_identity()
    proposal_id = proposal_content_id(**baseline)
    assert proposal_id == proposal_content_id(
        **{
            **baseline,
            "proposal": {
                **_proposal(),
                "evidence_refs": ["evidence-2", "evidence-1"],
            },
        }
    )

    mutations = [
        {"scope": "tenant-1/sub-2"},
        {"source_generation_id": "generation-2"},
        {"proposal": _proposal(predicate="hosted_on")},
        {"proposal": _proposal(evidence_refs=["evidence-1", "evidence-3"])},
        {"schema_version": "proposal-schema-v2"},
        {"policy_version": "proposal-policy-v2"},
    ]
    assert all(
        proposal_content_id(**{**baseline, **mutation}) != proposal_id
        for mutation in mutations
    )


def test_review_cas_is_authorized_immutable_and_restart_durable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ontology-runs.json"
    store = OntologyRunStore(path)
    proposal, created = store.save_proposal(**_proposal_identity(), now=NOW)
    assert created is True

    with pytest.raises(ReviewerUnauthorized):
        store.review_proposal(
            proposal["proposal_id"],
            action="accept",
            expected_revision=0,
            actor="reader@example.com",
            actor_roles={"reader"},
            reason="not authorized",
            now=NOW,
        )

    accepted = store.review_proposal(
        proposal["proposal_id"],
        action="accept",
        expected_revision=0,
        actor="steward@example.com",
        actor_roles={"ontology_steward"},
        reason="Evidence reproduced.",
        now=NOW,
    )
    with pytest.raises(ProposalReviewConflict):
        store.review_proposal(
            proposal["proposal_id"],
            action="reject",
            expected_revision=0,
            actor="steward@example.com",
            actor_roles={"ontology_steward"},
            reason="stale decision",
            now=NOW,
        )

    restarted = OntologyRunStore(path)
    restored = restarted.get_review(proposal["proposal_id"])
    assert restored == accepted
    assert restored["status"] == "accepted"
    assert restored["events"][0] == {
        "revision": 1,
        "action": "accept",
        "status": "accepted",
        "actor": "steward@example.com",
        "actor_roles": ["ontology_steward"],
        "reason": "Evidence reproduced.",
        "recorded_at": NOW.isoformat(),
    }

    reversed_review = restarted.review_proposal(
        proposal["proposal_id"],
        action="reverse",
        expected_revision=1,
        actor="steward@example.com",
        actor_roles={"ontology_steward"},
        reason="New contradictory evidence.",
        now=NOW + timedelta(seconds=1),
    )
    assert reversed_review["status"] == "pending"
    assert accepted["status"] == "accepted"
    assert accepted["events"][0]["reason"] == "Evidence reproduced."


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (_eligible_snapshot(shadow_days=29), "shadow_days"),
        (_eligible_snapshot(expert_count=199), "expert_adjudications"),
        (_eligible_snapshot(critical_failures=("scope_disclosure",)), "critical_failures"),
        (_eligible_snapshot(escalation_recall=0.99), "escalation_recall"),
        (_eligible_snapshot(recall=0.89), "recall"),
        (
            _eligible_snapshot(
                precision_true_positives=199,
                precision_total=200,
            ),
            "precision_wilson_lower_bound",
        ),
        (
            _eligible_snapshot(
                approvals=("ontology_steward", "security_owner"),
            ),
            "required_approvals",
        ),
        (_eligible_snapshot(ai_spec_gates_passed=False), "ai_spec_gates"),
    ],
)
def test_pair_release_eligibility_requires_every_exact_gate(
    snapshot: AdmissionEvaluationSnapshot,
    reason: str,
) -> None:
    result = evaluate_release_eligibility(snapshot)

    assert result.status == "BLOCKED/PENDING"
    assert reason in result.reasons


def test_release_snapshot_identity_is_immutable_and_content_addressed() -> None:
    snapshot = _eligible_snapshot()
    assert evaluate_release_eligibility(snapshot).status == "ELIGIBLE"
    with pytest.raises(ValidationError, match="snapshot identity"):
        AdmissionEvaluationSnapshot.model_validate(
            {
                **snapshot.model_dump(mode="python"),
                "expert_adjudicated_eligible_count": 201,
            }
        )


def test_pair_release_is_disabled_by_default_and_scoped_revocation_is_immediate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ontology-runs.json"
    snapshot = _eligible_snapshot()
    production = OntologyRunStore(path)
    pending = production.evaluate_admission_release(
        snapshot,
        actor="release-evaluator",
        now=NOW,
    )
    assert pending["status"] == "BLOCKED/PENDING"
    assert pending["eligible"] is True
    with pytest.raises(PairReleaseDisabled):
        production.activate_admission_release(
            snapshot.snapshot_id,
            expected_revision=0,
            actor="release-owner",
            now=NOW,
        )

    test_store = OntologyRunStore(path, allow_pair_release_testing=True)
    enabled = test_store.activate_admission_release(
        snapshot.snapshot_id,
        expected_revision=0,
        actor="release-owner",
        now=NOW,
    )
    admitted = ProposalPolicy(
        shadow_mode=False,
        allow_pair_release_testing=True,
        now=lambda: NOW,
    ).evaluate(
        _proposal(),
        review_status="accepted",
        admission_release=enabled,
        **_policy_inputs(),
    )
    assert admitted.admitted is True
    second_snapshot = _eligible_snapshot(
        subject_type="Application",
        predicate="depends_on",
        object_type="Application",
    )
    second = test_store.evaluate_admission_release(
        second_snapshot,
        actor="release-evaluator",
        now=NOW,
    )
    second_enabled = test_store.activate_admission_release(
        second_snapshot.snapshot_id,
        expected_revision=second["revision"],
        actor="release-owner",
        now=NOW,
    )

    revoked = test_store.revoke_admission_release(
        enabled["pair_key"],
        expected_revision=enabled["revision"],
        actor="security-owner",
        reason="critical_event",
        now=NOW + timedelta(seconds=1),
    )
    releases = {
        item["pair_key"]: item for item in test_store.list_admission_releases()
    }
    assert revoked["status"] == "REVOKED"
    assert releases[second_enabled["pair_key"]]["status"] == "ENABLED"


def test_coordinator_persists_accepted_review_but_returns_shadow_candidate(
    tmp_path: Path,
) -> None:
    store = OntologyRunStore(tmp_path / "ontology-runs.json")
    proposal, _ = store.save_proposal(**_proposal_identity(), now=NOW)
    store.review_proposal(
        proposal["proposal_id"],
        action="accept",
        expected_revision=0,
        actor="steward@example.com",
        actor_roles={"ontology_steward"},
        reason="Accepted for shadow evidence only.",
        now=NOW,
    )
    deterministic = _relationship(source="deterministic")
    coordinator = ProposalPolicyCoordinator(
        store=OntologyRunStore(tmp_path / "ontology-runs.json"),
        policy=ProposalPolicy(shadow_mode=True, now=lambda: NOW),
    )

    result = coordinator.build_candidate(
        proposals=[proposal],
        deterministic_edges=[deterministic],
        **_policy_inputs(),
    )

    assert result["candidate"] == [deterministic]
    assert result["decisions"][0].review_status == "accepted"
    assert result["decisions"][0].reasons == ("shadow_review_only",)
