from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from ontology.ontology_validator import OntologyValidator
from ontology_discovery.contracts import CheckpointResult, EvidenceBatch
from ontology_discovery.coordinator import OntologyDiscoveryCoordinator
from ontology_discovery.curator import (
    MAX_INPUT_TOKENS,
    NORMAL_OUTPUT_TOKENS,
    REQUEST_TIMEOUT_SECONDS,
    CuratorInputTooLarge,
    OntologyCurator,
)
from ontology_discovery.generation_resolver import (
    CONSUMER_INVENTORY,
    GenerationResolver,
)
from ontology_discovery.incremental import split_evidence_batches
from ontology_discovery.policy import ProposalPolicy
from ontology_discovery.publisher import (
    APPROVED_PUBLICATION_CHECKPOINTS,
    OntologyGenerationCandidate,
    OntologyGenerationPublisher,
    PublicationSafetyError,
)
from ontology_discovery.store import OntologyRunStore
from storage.datasets import DatasetStore, GenerationPointerConditions
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore

NOW = datetime(2026, 9, 7, 1, 0, tzinfo=UTC)
COMPATIBILITY = {
    "api": True,
    "fabric": True,
    "agent": True,
    "export": True,
    "semantic": True,
}


def _entity(resource_id: str, entity_type: str) -> dict[str, Any]:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": entity_type,
        "name": resource_id,
        "resource_type": "test/resource",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
        "scope": "tenant-1/sub-1",
    }


def _deterministic_relationship(generation: str) -> dict[str, Any]:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": f"relationship://{generation}",
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "source": "deterministic",
        "scope": "tenant-1/sub-1",
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
        "confidence": 1.0,
    }


def _model_proposal() -> dict[str, Any]:
    return {
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "evidence_refs": ["arg-1", "fabric-1"],
    }


def _evidence() -> dict[str, dict[str, Any]]:
    common = {
        "scope": "tenant-1/sub-1",
        "source_generation_id": "source-1",
        "freshness": "current",
        "expires_at": "2026-09-08T00:00:00+00:00",
        "supports": True,
        "contradicts": False,
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
    }
    return {
        "arg-1": {**common, "source": "azure-resource-graph"},
        "fabric-1": {**common, "source": "fabric-lineage"},
    }


def _candidate(
    generation_id: str,
    source_generation: str,
    relationships: list[dict[str, Any]],
    *,
    proposal_id: str,
) -> OntologyGenerationCandidate:
    return OntologyGenerationCandidate(
        generation_id=generation_id,
        source_generation=source_generation,
        entities=(
            _entity("vm-1", "VirtualMachine"),
            _entity("app-1", "Application"),
        ),
        relationships=tuple(relationships),
        proposal_lineage=(proposal_id,),
        decision_lineage=(f"decision:{proposal_id}:shadow-excluded",),
        policy_version="ontology-policy/v1",
        schema_version="ontology-generation/v1",
    )


def test_one_run_splits_exact_record_bounds_and_rejects_budget_overages():
    entities = [
        {
            "scope": "tenant-1/sub-1",
            "entity_id": f"entity-{index}",
        }
        for index in range(51)
    ]
    pairs = [
        {
            "scope": "tenant-1/sub-1",
            "pair_id": f"pair-{index}",
            "subject_id": "entity-0",
            "object_id": f"entity-{(index % 50) + 1}",
        }
        for index in range(201)
    ]
    evidence = [
        {
            "scope": "tenant-1/sub-1",
            "evidence_id": f"evidence-{index}",
            "entity_ids": ["entity-0"],
        }
        for index in range(41)
    ]

    batches = split_evidence_batches(
        changed_entities=entities,
        candidate_pairs=pairs,
        evidence_records=evidence,
        source_generation_id="source-1",
        observed_at=NOW,
        freshness="current",
        coverage="complete",
    )

    assert sum(len(batch.changed_entities) for batch in batches) == 51
    assert sum(len(batch.candidate_pairs) for batch in batches) == 201
    assert sum(len(batch.evidence_records) for batch in batches) == 41
    assert max(len(batch.changed_entities) for batch in batches) == 50
    assert max(len(batch.candidate_pairs) for batch in batches) == 200
    assert max(len(batch.evidence_records) for batch in batches) == 40


class _BudgetTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], float]] = []

    async def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        copied = dict(payload)
        self.calls.append((copied, timeout_seconds))
        prompt = json.loads(copied["input"][0]["content"])
        return {
            "id": "response-1",
            "model": "gpt-5.4-mini",
            "output_text": json.dumps(
                {
                    "batch_id": prompt["evidence"]["batch_id"],
                    "status": "insufficient_evidence",
                    "proposals": [],
                    "missing_evidence": ["independent-lineage"],
                }
            ),
            "usage": {
                "input_tokens": MAX_INPUT_TOKENS,
                "output_tokens": NORMAL_OUTPUT_TOKENS,
            },
        }


def _curator_batch() -> EvidenceBatch:
    return EvidenceBatch(
        batch_id="batch-1",
        scope="tenant-1/sub-1",
        source_generation_id="source-1",
        observed_at=NOW,
        freshness="current",
        coverage="complete",
        changed_entities=(
            {
                "scope": "tenant-1/sub-1",
                "entity_id": "vm-1",
            },
        ),
        candidate_pairs=(),
        evidence_records=(),
    )


def test_normal_token_budgets_and_sixty_second_attempt_deadline():
    transport = _BudgetTransport()
    curator = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=transport,
        timeout_seconds=61,
        token_estimator=lambda _prompt: MAX_INPUT_TOKENS,
    )

    result = asyncio.run(
        curator.propose(
            {"run_id": "run-1"},
            _curator_batch().to_dict(),
            requested_output_tokens=NORMAL_OUTPUT_TOKENS,
        )
    )

    assert result["status"] == "insufficient_evidence"
    payload, timeout = transport.calls[0]
    prompt = json.loads(payload["input"][0]["content"])
    assert prompt["requested_output_tokens"] == NORMAL_OUTPUT_TOKENS == 1_200
    assert timeout == curator.timeout_seconds == REQUEST_TIMEOUT_SECONDS == 60

    oversized = OntologyCurator(
        project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        agent_name="ontology-curator",
        transport=_BudgetTransport(),
        token_estimator=lambda _prompt: MAX_INPUT_TOKENS + 1,
    )
    with pytest.raises(CuratorInputTooLarge):
        asyncio.run(
            oversized.propose({"run_id": "run-2"}, _curator_batch().to_dict())
        )
    with pytest.raises(ValueError, match="output budget"):
        asyncio.run(
            curator.propose(
                {"run_id": "run-3"},
                _curator_batch().to_dict(),
                requested_output_tokens=NORMAL_OUTPUT_TOKENS + 1,
            )
        )


def test_real_coordinator_shadow_publication_consumer_cutover_and_rollback(
    tmp_path,
    monkeypatch,
):
    dataset_store = DatasetStore(tmp_path / "ontology")
    adapter = dataset_store.authoritative_publisher(
        publisher_identity="ontology-publisher",
        approved_publisher_identity="ontology-publisher",
    )
    publisher = OntologyGenerationPublisher(
        adapter,
        validator=OntologyValidator(
            allowed_triples={("VirtualMachine", "member_of", "Application")}
        ),
        approved_publisher_identity="ontology-publisher",
    )
    fences = MonotonicFenceAllocator(
        OneLakeDocumentStore(tmp_path / "publication-control")
    )
    entities = {
        "vm-1": _entity("vm-1", "VirtualMachine"),
        "app-1": _entity("app-1", "Application"),
    }
    policy = ProposalPolicy(now=lambda: NOW)
    decision = policy.evaluate(
        _model_proposal(),
        entities=entities,
        evidence_records=_evidence(),
        scope="tenant-1/sub-1",
        source_generation_id="source-1",
        review_status="accepted",
    )
    relationships = policy.assemble_candidate(
        deterministic_edges=[_deterministic_relationship("generation-0")],
        proposal_decisions=[decision],
    )
    assert decision.reasons == ("shadow_review_only",)
    assert decision.admitted is False
    assert len(relationships) == 1
    assert all(edge["source"] != "model" for edge in relationships)

    synthetic_release_policy = ProposalPolicy(
        shadow_mode=False,
        allow_pair_release_testing=True,
        now=lambda: NOW,
    )
    assert (
        synthetic_release_policy.evaluate(
            _model_proposal(),
            entities=entities,
            evidence_records=_evidence(),
            scope="tenant-1/sub-1",
            source_generation_id="source-1",
            review_status="accepted",
        ).admitted
        is False
    )
    synthetic_decision = synthetic_release_policy.evaluate(
        _model_proposal(),
        entities=entities,
        evidence_records=_evidence(),
        scope="tenant-1/sub-1",
        source_generation_id="source-1",
        review_status="accepted",
        admission_release={
            "status": "ENABLED",
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_type": "Application",
        },
    )
    assert synthetic_decision.admitted is True
    assert ProposalPolicy().shadow_mode is True

    class _PublishingProcessor:
        async def advance(self, run: Mapping[str, Any]) -> CheckpointResult:
            fence = fences.allocate(
                scope="tenant-1/sub-1",
                owner_id="coordinator-writer",
            )
            publisher.publish(
                _candidate(
                    "generation-0",
                    str(run["source_generation_id"]),
                    relationships,
                    proposal_id=decision.proposal_id,
                ),
                publisher_identity="ontology-publisher",
                checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
                pointer_conditions=GenerationPointerConditions.initial(),
                owner_id=fence.owner_id,
                fence=fence.value,
                consumer_compatibility=COMPATIBILITY,
                cancellation_check=lambda: bool(run.get("cancel_requested")),
                lease_guard=lambda: None,
            )
            return CheckpointResult(
                checkpoint="deterministic_generation_promoted",
                payload={"generation_id": "generation-0"},
                complete=True,
            )

    run_store = OntologyRunStore(tmp_path / "runs.json")
    run_store.get_or_create_run(
        connection_id="connection-1",
        source_generation_id="source-1",
        trigger="scheduled",
        requested_by="scheduler",
        now=NOW,
    )
    counts = asyncio.run(
        OntologyDiscoveryCoordinator(
            store=run_store,
            processor=_PublishingProcessor(),
            owner="coordinator-writer",
            now=lambda: NOW,
        ).run_once(now=NOW, limit=1)
    )
    assert counts["processed"] == 1

    resolver = GenerationResolver(dataset_store)
    baseline = resolver.resolve()
    assert baseline.generation_id == "generation-0"
    assert baseline.pointer_etag
    assert baseline.source_generation == "source-1"
    assert {
        entry.family for entry in CONSUMER_INVENTORY
    } == {"api", "fabric", "agent", "export", "semantic"}
    assert resolver.read_dataset(
        "ontology_relationships",
        selection=baseline,
    ) == relationships

    predecessor = GenerationPointerConditions.from_snapshot(adapter.read_pointer())
    old_fence = fences.allocate(
        scope="tenant-1/sub-1",
        owner_id="paused-old-writer",
    )
    new_fence = fences.allocate(
        scope="tenant-1/sub-1",
        owner_id="new-writer",
    )
    original_audit = adapter.persist_generation_audit
    new_result = None

    def pause_old_after_audit(generation_id: str, audit: dict[str, Any]) -> None:
        nonlocal new_result
        original_audit(generation_id, audit)
        if generation_id == "generation-old":
            new_relationships = [_deterministic_relationship("generation-new")]
            new_result = publisher.publish(
                _candidate(
                    "generation-new",
                    "source-2",
                    new_relationships,
                    proposal_id=decision.proposal_id,
                ),
                publisher_identity="ontology-publisher",
                checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
                pointer_conditions=predecessor,
                owner_id=new_fence.owner_id,
                fence=new_fence.value,
                consumer_compatibility=COMPATIBILITY,
                cancellation_check=lambda: False,
                lease_guard=lambda: None,
            )

    monkeypatch.setattr(adapter, "persist_generation_audit", pause_old_after_audit)
    with pytest.raises(PublicationSafetyError, match="stale"):
        publisher.publish(
            _candidate(
                "generation-old",
                "source-old",
                [_deterministic_relationship("generation-old")],
                proposal_id=decision.proposal_id,
            ),
            publisher_identity="ontology-publisher",
            checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
            pointer_conditions=predecessor,
            owner_id=old_fence.owner_id,
            fence=old_fence.value,
            consumer_compatibility=COMPATIBILITY,
            cancellation_check=lambda: False,
            lease_guard=lambda: None,
        )
    assert new_result is not None
    assert resolver.resolve().generation_id == "generation-new"

    rollback_fence = fences.allocate(
        scope="tenant-1/sub-1",
        owner_id="rollback-writer",
    )
    rolled_back = publisher.rollback(
        target_generation_id="generation-0",
        source_generation="source-1",
        publisher_identity="ontology-publisher",
        checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
        pointer_conditions=GenerationPointerConditions.from_snapshot(new_result),
        owner_id=rollback_fence.owner_id,
        fence=rollback_fence.value,
        cancellation_check=lambda: False,
        lease_guard=lambda: None,
    )
    selection = resolver.resolve()
    assert selection.generation_id == "generation-0"
    assert selection.prior_generation is not None
    assert selection.prior_generation.endswith("/generation-new")
    assert rolled_back.pointer.active_generation == "generation-0"
    assert resolver.read_dataset(
        "ontology_relationships",
        selection=selection,
    ) == relationships
