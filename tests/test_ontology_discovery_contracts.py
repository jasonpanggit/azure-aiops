from __future__ import annotations

import pytest

from ontology_discovery_contract_harness import (
    ContractHarness,
    EvidenceBatch,
    FencedPointerStore,
    RelationshipEdge,
    RollbackError,
    StaleFenceError,
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
