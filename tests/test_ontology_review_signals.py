from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ontology_discovery.incremental import split_evidence_batches
from ontology_discovery.review_signals import build_review_signals


def test_review_signals_are_generation_bound_and_deterministic() -> None:
    entities = [
        {"resource_id": "vm-a", "lifecycle_status": "active"},
        {"resource_id": "vm-b", "lifecycle_status": "retired"},
        {"resource_id": "vm-orphan", "lifecycle_status": "active"},
    ]
    relationships = [
        {
            "subject_id": "vm-a",
            "subject_type": "VirtualMachine",
            "predicate": "member_of",
            "object_id": "vm-b",
            "object_type": "Application",
            "lifecycle_status": "active",
            "confidence": 0.9,
            "source": "resource_graph",
            "lineage_json": "",
            "valid_from": "2026-09-02T00:00:00Z",
            "retired_at": "2026-09-01T00:00:00Z",
        },
        {
            "subject_id": "vm-a",
            "subject_type": "VirtualMachine",
            "predicate": "invented_predicate",
            "object_id": "missing",
            "object_type": "VirtualMachine",
            "confidence": 0.2,
            "source": "fabric_data_agent",
            "lineage_json": "{}",
        },
    ]

    result = build_review_signals(
        entities=entities,
        relationships=relationships,
        source_generation_id="generation-7",
    )

    assert result["source_generation_id"] == "generation-7"
    assert result["verdict_owner"] == "deterministic_pipeline"
    assert result["advisory_use"] == "explain_and_prioritize_only"
    assert result["violations"] == {
        "dangling_relationships": 1,
        "orphan_entities": 1,
        "vocabulary_or_type_drift": 1,
        "stale_or_retired_links": 1,
        "temporal_inconsistencies": 1,
    }
    assert result["confidence_distribution"] == {"high": 1, "low": 1}
    assert result["lineage_health"]["missing_lineage"] == 1


def test_review_signals_require_immutable_generation() -> None:
    with pytest.raises(ValueError, match="source_generation_id is required"):
        build_review_signals(
            entities=[],
            relationships=[],
            source_generation_id="",
        )


def test_non_empty_batch_review_signals_require_matching_generation() -> None:
    base = {
        "batch_id": "batch-1",
        "scope": "tenant-1/sub-1",
        "source_generation_id": "generation-7",
        "observed_at": datetime.now(UTC),
        "freshness": "fresh",
        "coverage": "complete",
    }
    from ontology_discovery.contracts import EvidenceBatch

    with pytest.raises(
        ValueError,
        match="non-empty review_signals requires source_generation_id",
    ):
        EvidenceBatch(**base, review_signals={"violations": {}})
    with pytest.raises(ValueError, match="must match the batch generation"):
        EvidenceBatch(
            **base,
            review_signals={
                "source_generation_id": "generation-8",
                "violations": {},
            },
        )


def test_review_signals_are_batch_metadata_not_endpoint_free_evidence() -> None:
    signals = build_review_signals(
        entities=[
            {
                "resource_id": "vm-a",
                "lifecycle_status": "active",
            },
            {
                "resource_id": "app-a",
                "lifecycle_status": "active",
            },
        ],
        relationships=[],
        source_generation_id="generation-7",
    )
    batches = split_evidence_batches(
        changed_entities=[
            {
                "scope": "tenant-1/sub-1",
                "entity_id": "vm-a",
                "resource_id": "vm-a",
            },
            {
                "scope": "tenant-1/sub-1",
                "entity_id": "app-a",
                "resource_id": "app-a",
            },
        ],
        candidate_pairs=[
            {
                "scope": "tenant-1/sub-1",
                "pair_id": "pair-1",
                "subject_id": "vm-a",
                "object_id": "app-a",
            },
        ],
        evidence_records=[
            {
                "scope": "tenant-1/sub-1",
                "evidence_id": "evidence-1",
                "entity_ids": ["vm-a", "app-a"],
            },
        ],
        source_generation_id="generation-7",
        observed_at=datetime.now(UTC),
        freshness="fresh",
        coverage="complete",
        review_signals=signals,
    )

    assert len(batches) == 1
    assert batches[0].review_signals == signals
    assert batches[0].to_dict()["review_signals"] == signals
