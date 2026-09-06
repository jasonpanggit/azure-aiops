from __future__ import annotations

import json
from pathlib import Path

import pytest
from ontology_discovery_contract_harness import (
    ContractHarness,
    EvidenceBatch,
    FencedPointerStore,
    RelationshipEdge,
    RollbackError,
    StaleFenceError,
    candidate_membership_hash,
    materialize_fixture_batch,
    normalized_fixture_hash,
)

REFERENCE_FIXTURE = (
    Path(__file__).parent / "fixtures" / "ontology_discovery" / "reference.jsonl"
)


def _batch() -> EvidenceBatch:
    entity_ids = (
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/networkInterfaces/nic-1",
        "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-1",
    )
    deterministic = RelationshipEdge(
        edge_id="edge-deterministic",
        subject_id=entity_ids[1],
        subject_type="NetworkInterface",
        predicate="attached_to",
        object_id=entity_ids[0],
        object_type="VirtualMachine",
        source="deterministic",
        evidence_refs=("evidence-arm-1",),
    )
    proposed = RelationshipEdge(
        edge_id="edge-model",
        subject_id=entity_ids[0],
        subject_type="VirtualMachine",
        predicate="connected_to",
        object_id=entity_ids[2],
        object_type="VirtualNetwork",
        source="model",
        evidence_refs=("evidence-flow-1",),
    )
    return EvidenceBatch(
        batch_id="batch-1",
        scope="tenant-1/sub-1",
        source_generation="source-1",
        entity_ids=entity_ids,
        candidate_pairs=(deterministic, proposed),
        evidence_ids=("evidence-arm-1", "evidence-flow-1"),
    )


def test_non_authoritative_tracer_excludes_reviewed_model_edge_and_rolls_back() -> None:
    pointer = FencedPointerStore(initial_generation="generation-0", initial_fence=1)
    trace = ContractHarness(pointer).run(
        _batch(),
        reviewed_proposal_ids={"edge-model"},
        shadow_mode=True,
        fencing_token=2,
    )

    assert trace.reviewed_proposal_ids == ("edge-model",)
    assert trace.candidate.edge_ids == ("edge-deterministic",)
    assert trace.validation_passed is True
    assert trace.promoted_generation == trace.candidate.generation_id
    assert trace.consumer_generation == trace.candidate.generation_id
    assert trace.rolled_back_generation == "generation-0"
    assert pointer.resolve() == "generation-0"


def test_released_mode_can_admit_only_an_explicitly_released_reviewed_triple() -> None:
    pointer = FencedPointerStore(initial_generation="generation-0", initial_fence=1)
    proposal = _batch().candidate_pairs[1]

    trace = ContractHarness(pointer).run(
        _batch(),
        reviewed_proposal_ids={proposal.edge_id},
        shadow_mode=False,
        released_triples={proposal.triple},
        fencing_token=2,
    )

    assert trace.candidate.edge_ids == ("edge-deterministic", "edge-model")


def test_stale_fence_and_failed_rollback_preserve_prior_test_pointer() -> None:
    pointer = FencedPointerStore(initial_generation="generation-0", initial_fence=5)
    harness = ContractHarness(pointer)
    candidate = harness.build_candidate(
        _batch(),
        reviewed_proposal_ids={"edge-model"},
        shadow_mode=True,
    )
    harness.validate(candidate, _batch())

    with pytest.raises(StaleFenceError):
        pointer.promote(
            candidate,
            expected_generation="generation-0",
            fencing_token=5,
        )
    assert pointer.resolve() == "generation-0"

    pointer.promote(
        candidate,
        expected_generation="generation-0",
        fencing_token=6,
    )
    with pytest.raises(RollbackError):
        pointer.rollback(
            target_generation="generation-0",
            expected_generation=candidate.generation_id,
            fencing_token=7,
            fail_before_swap=True,
        )
    assert pointer.resolve() == candidate.generation_id


def _reference_cases() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in REFERENCE_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_reference_corpus_is_bounded_synthetic_and_threat_complete() -> None:
    cases = _reference_cases()
    categories = {
        str(category)
        for case in cases
        for category in case["categories"]
    }

    assert len(cases) >= 32
    assert len({case["scenario_id"] for case in cases}) == len(cases)
    assert sum(int(case["input"]["candidate_pair_count"]) for case in cases) >= 100
    assert {
        "normal",
        "hard-negative",
        "stale",
        "partial",
        "collision",
        "injection",
        "duplicate",
        "fence",
        "cancellation",
        "review",
        "promotion",
        "rollback",
    } <= categories
    assert all(str(case["scope"]).startswith("synthetic/") for case in cases)


def test_reference_corpus_records_exact_hashes_membership_and_pointer_outcomes() -> None:
    for case in _reference_cases():
        assert case["schema_version"] == "ontology-discovery-wave0.v1"
        assert case["fixture_hash"] == normalized_fixture_hash(case)
        expected = case["expected"]
        assert expected["pre_promotion_generation"] == "generation-0"
        assert expected["post_rollback_generation"] == "generation-0"

        expected_error = str(expected["error"])
        if expected_error:
            with pytest.raises(ValueError, match=expected_error):
                materialize_fixture_batch(case)
            continue

        batch = materialize_fixture_batch(case)
        pointer = FencedPointerStore(initial_generation="generation-0", initial_fence=1)
        harness = ContractHarness(pointer)
        reviewed = {
            edge.edge_id for edge in batch.candidate_pairs if edge.source == "model"
        }
        shadow = harness.build_candidate(
            batch,
            reviewed_proposal_ids=reviewed,
            shadow_mode=True,
        )
        released = harness.build_candidate(
            batch,
            reviewed_proposal_ids=reviewed,
            shadow_mode=False,
            released_triples={edge.triple for edge in batch.candidate_pairs},
        )

        assert candidate_membership_hash(shadow) == expected["shadow_membership_hash"]
        assert len(shadow.edges) == expected["shadow_edge_count"]
        assert candidate_membership_hash(released) == expected["released_membership_hash"]
        assert len(released.edges) == expected["released_edge_count"]
        assert expected["post_promotion_generation"] == shadow.generation_id


@pytest.mark.parametrize(
    ("category", "message"),
    [
        ("over-limit-entities", "changed entities exceeds limit 50: 51"),
        ("over-limit-pairs", "candidate pairs exceeds limit 200: 201"),
        ("over-limit-evidence", "evidence records exceeds limit 40: 41"),
    ],
)
def test_reference_corpus_proves_every_hard_batch_limit(
    category: str, message: str
) -> None:
    case = next(
        item for item in _reference_cases() if category in item["categories"]
    )

    with pytest.raises(ValueError, match=message):
        materialize_fixture_batch(case)


def test_reference_corpus_materializes_exact_maximum_batch() -> None:
    case = next(
        item for item in _reference_cases() if "boundary-max" in item["categories"]
    )

    batch = materialize_fixture_batch(case)

    assert len(batch.entity_ids) == 50
    assert len(batch.candidate_pairs) == 200
    assert len(batch.evidence_ids) == 40
