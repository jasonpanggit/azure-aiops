from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from onboarding.graph_normalize import Normalizer
from ontology_discovery.contracts import (
    MAX_CANDIDATE_PAIRS,
    MAX_CHANGED_ENTITIES,
    MAX_EVIDENCE_RECORDS,
    EvidenceBatch,
)
from ontology_discovery.incremental import (
    BatchRejectionReason,
    EvidenceBatchRejected,
    classify_incremental,
    split_evidence_batches,
)

OBSERVED_AT = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)


def _resource(resource_id: str, **extra: object) -> dict[str, object]:
    return {
        "id": resource_id,
        "name": resource_id.rsplit("/", 1)[-1],
        "type": "Microsoft.Compute/virtualMachines",
        "tags": {"owner": "platform", "environment": "test"},
        **extra,
    }


def _entity(resource_id: str, scope: str = "tenant-a/sub-a") -> dict[str, object]:
    return {
        "resource_id": resource_id,
        "scope": scope,
        "endpoint_match": True,
        "authority": 10,
        "freshness": "fresh",
        "corroboration": 2,
    }


def _pair(
    pair_id: str,
    subject_id: str,
    object_id: str,
    scope: str = "tenant-a/sub-a",
) -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "subject_id": subject_id,
        "object_id": object_id,
        "scope": scope,
        "endpoint_match": True,
        "authority": 10,
        "freshness": "fresh",
        "corroboration": 2,
    }


def _evidence(
    evidence_id: str,
    entity_id: str,
    scope: str = "tenant-a/sub-a",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "entity_ids": [entity_id],
        "scope": scope,
        "endpoint_match": True,
        "authority": 10,
        "freshness": "fresh",
        "corroboration": 2,
        "observed_at": OBSERVED_AT.isoformat(),
    }


def _batch(**overrides: object) -> EvidenceBatch:
    values: dict[str, object] = {
        "batch_id": "batch-1",
        "scope": "tenant-a/sub-a",
        "source_generation_id": "generation-1",
        "observed_at": OBSERVED_AT,
        "freshness": "fresh",
        "coverage": "complete",
        "changed_entities": (),
        "candidate_pairs": (),
        "evidence_records": (),
    }
    values.update(overrides)
    return EvidenceBatch(**values)


def test_normalized_row_hash_ignores_key_list_order_and_wall_clock() -> None:
    first = _resource(
        "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a",
        observed_at="2026-09-06T10:00:00Z",
        zones=["2", "1"],
    )
    reordered = {
        "zones": ["1", "2"],
        "observed_at": "2026-09-06T11:00:00Z",
        "tags": {"environment": "test", "owner": "platform"},
        "type": first["type"],
        "name": first["name"],
        "id": first["id"],
    }

    left = Normalizer().normalize({"resources": [first]}, OBSERVED_AT)
    right = Normalizer().normalize(
        {"resources": [reordered]},
        datetime(2026, 9, 6, 11, 0, tzinfo=UTC),
    )

    assert left.row_hashes == right.row_hashes


def test_incremental_classifier_records_all_delta_classes_and_provenance() -> None:
    delta = classify_incremental(
        previous_row_hashes={"same": "1", "changed": "1", "gone": "1", "waiting": "1"},
        current_row_hashes={"same": "1", "changed": "2", "added": "1"},
        unresolved_ids={"waiting"},
        stale_ids={"same"},
        source_generation_id="generation-2",
        observed_at=OBSERVED_AT,
        freshness="stale",
        coverage="complete",
    )

    assert delta.added == ("added",)
    assert delta.changed == ("changed",)
    assert delta.retired == ("gone",)
    assert delta.unresolved == ("waiting",)
    assert delta.stale == ("same",)
    assert delta.source_generation_id == "generation-2"
    assert delta.observed_at == OBSERVED_AT
    assert delta.freshness == "stale"
    assert delta.coverage == "complete"
    assert delta.apply_to({"same": "1", "changed": "1", "gone": "1", "waiting": "1"}) == {
        "same": "1",
        "changed": "2",
        "added": "1",
    }


@pytest.mark.parametrize("coverage", ["partial", "degraded"])
def test_non_authoritative_scan_never_retires_missing_rows(coverage: str) -> None:
    delta = classify_incremental(
        previous_row_hashes={"kept": "1", "missing-from-scan": "1"},
        current_row_hashes={"kept": "1"},
        source_generation_id="generation-degraded",
        observed_at=OBSERVED_AT,
        freshness="unknown",
        coverage=coverage,
    )

    assert delta.retired == ()
    assert delta.unresolved == ("missing-from-scan",)
    assert delta.apply_to(
        {"kept": "1", "missing-from-scan": "1"}
    ) == {"kept": "1", "missing-from-scan": "1"}


@pytest.mark.parametrize(
    ("field", "count", "reason"),
    [
        ("changed_entities", MAX_CHANGED_ENTITIES + 1, "changed_entities"),
        ("candidate_pairs", MAX_CANDIDATE_PAIRS + 1, "candidate_pairs"),
        ("evidence_records", MAX_EVIDENCE_RECORDS + 1, "evidence_records"),
    ],
)
def test_evidence_batch_rejects_values_above_exact_caps(
    field: str, count: int, reason: str
) -> None:
    factories = {
        "changed_entities": lambda index: _entity(f"entity-{index}"),
        "candidate_pairs": lambda index: _pair(
            f"pair-{index}", "entity-a", "entity-b"
        ),
        "evidence_records": lambda index: _evidence(
            f"evidence-{index}", "entity-a"
        ),
    }

    with pytest.raises(ValueError, match=reason):
        _batch(**{field: tuple(factories[field](index) for index in range(count))})


def test_split_is_scope_first_deterministic_bounded_and_lossless() -> None:
    entities = [
        _entity(f"entity-{index}", scope="tenant-a/sub-a")
        for index in range(MAX_CHANGED_ENTITIES + 7)
    ]
    entities += [_entity("other-entity", scope="tenant-b/sub-b")]
    pairs = [
        _pair(f"pair-{index}", f"entity-{index % 10}", f"entity-{(index + 1) % 10}")
        for index in range(MAX_CANDIDATE_PAIRS + 3)
    ]
    evidence = [
        _evidence(f"evidence-{index}", f"entity-{index % 10}")
        for index in range(MAX_EVIDENCE_RECORDS + 2)
    ]

    first = split_evidence_batches(
        changed_entities=entities,
        candidate_pairs=pairs,
        evidence_records=evidence,
        source_generation_id="generation-3",
        observed_at=OBSERVED_AT,
        freshness="fresh",
        coverage="complete",
    )
    second = split_evidence_batches(
        changed_entities=list(reversed(entities)),
        candidate_pairs=list(reversed(pairs)),
        evidence_records=list(reversed(evidence)),
        source_generation_id="generation-3",
        observed_at=OBSERVED_AT,
        freshness="fresh",
        coverage="complete",
    )

    assert [batch.to_dict() for batch in first] == [batch.to_dict() for batch in second]
    assert all(len(batch.changed_entities) <= MAX_CHANGED_ENTITIES for batch in first)
    assert all(len(batch.candidate_pairs) <= MAX_CANDIDATE_PAIRS for batch in first)
    assert all(len(batch.evidence_records) <= MAX_EVIDENCE_RECORDS for batch in first)
    assert all(
        {str(record["scope"]) for record in batch.all_records()} == {batch.scope}
        for batch in first
    )
    assert {
        str(record["resource_id"])
        for batch in first
        for record in batch.changed_entities
    } == {str(record["resource_id"]) for record in entities}
    assert {
        str(record["pair_id"])
        for batch in first
        for record in batch.candidate_pairs
    } == {str(record["pair_id"]) for record in pairs}
    assert {
        str(record["evidence_id"])
        for batch in first
        for record in batch.evidence_records
    } == {str(record["evidence_id"]) for record in evidence}
    assert json.dumps([batch.to_dict() for batch in first], sort_keys=True)


def test_split_rejects_malformed_or_indivisible_records_with_typed_reason() -> None:
    with pytest.raises(EvidenceBatchRejected) as malformed:
        split_evidence_batches(
            changed_entities=[{"resource_id": "entity-a"}],
            candidate_pairs=[],
            evidence_records=[],
            source_generation_id="generation-4",
            observed_at=OBSERVED_AT,
            freshness="fresh",
            coverage="complete",
        )
    assert malformed.value.reason is BatchRejectionReason.MALFORMED_RECORD

    with pytest.raises(EvidenceBatchRejected) as indivisible:
        split_evidence_batches(
            changed_entities=[_entity("entity-a")],
            candidate_pairs=[],
            evidence_records=[
                {
                    **_evidence("evidence-a", "entity-a"),
                    "changed_entity_ids": [
                        f"entity-{index}" for index in range(MAX_CHANGED_ENTITIES + 1)
                    ],
                }
            ],
            source_generation_id="generation-4",
            observed_at=OBSERVED_AT,
            freshness="fresh",
            coverage="complete",
        )
    assert indivisible.value.reason is BatchRejectionReason.INDIVISIBLE_RECORD


def test_complete_reconciliation_converges_to_clean_rebuild() -> None:
    previous = {"same": "1", "changed": "old", "retired": "old"}
    current = {"same": "1", "changed": "new", "added": "new"}

    delta = classify_incremental(
        previous_row_hashes=previous,
        current_row_hashes=current,
        source_generation_id="full-reconcile-1",
        observed_at=OBSERVED_AT,
        freshness="fresh",
        coverage="complete",
    )

    assert delta.apply_to(previous) == current
