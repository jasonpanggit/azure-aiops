from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from fabric.dataset_mapper import (
    ONTOLOGY_RELATIONSHIP_TYPES,
    allowed_relationship_triples,
    is_allowed_relationship_triple,
)
from ontology.ontology_validator import OntologyValidator
from ontology_discovery.policy import ProposalPolicy

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
