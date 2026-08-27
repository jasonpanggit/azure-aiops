"""Tests for the Data Agent suggestion -> approval -> pipeline feedback loop:
``relationship_suggestions_contract.accepted_suggestion_to_relationship_row``
and ``ontology_pipeline.merge_approved_relationship_suggestions``.

These prove the *design* described in
``docs/fabric-data-agent-relationship-suggestions.md`` actually works as
pure, deterministic Python: an accepted suggestion row promotes into a
relationship row shaped exactly like ``RelationshipBuilder``'s own output,
tagged with a distinct provenance ``source``, is idempotent across repeated
runs, and never overwrites a deterministically-derived relationship for the
same subject/predicate/object -- it is reported as a conflict instead.

This does NOT require a live Data Agent response -- it operates on
hand-built suggestion rows, exactly the shape a human would produce by
running suggestion rows through ``suggestions_to_rows`` and then flipping
their ``status`` to ``"accepted"`` out of band."""

from __future__ import annotations

from fabric_pipelines.ontology_pipeline import (
    derive_entities,
    derive_relationships,
    merge_approved_relationship_suggestions,
)
from fabric_pipelines.relationship_suggestions_contract import (
    ACCEPTED_SUGGESTION_STATUS,
    APPROVED_SUGGESTION_RELATIONSHIP_SOURCE,
    DEFAULT_SUGGESTION_STATUS,
    RelationshipSuggestion,
    accepted_suggestion_to_relationship_row,
    to_suggestion_row,
)

RUN_ID = "feedback-loop-test-run"
TIMESTAMP = "2026-08-27T00:00:00Z"


def _sample_entities() -> list[dict]:
    rows = [
        {
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-a",
            "resourceType": "Microsoft.Compute/virtualMachines",
            "tenant_id": "tenant-1",
            "subscription_id": "sub-1",
            "timestamp": TIMESTAMP,
            "tags": {"costCenter": "finance"},
        },
        {
            "resource_id": "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.Compute/virtualMachines/vm-b",
            "resourceType": "Microsoft.Compute/virtualMachines",
            "tenant_id": "tenant-1",
            "subscription_id": "sub-1",
            "timestamp": TIMESTAMP,
            "tags": {"costCenter": "finance"},
        },
    ]
    return derive_entities(rows, run_id=RUN_ID, timestamp=TIMESTAMP)


def _accepted_suggestion_row(subject_id: str, predicate: str, object_id: str) -> dict:
    suggestion = RelationshipSuggestion(
        subject_id=subject_id,
        subject_type="VirtualMachine",
        predicate=predicate,
        object_id=object_id,
        object_type="VirtualMachine",
        confidence=0.71,
        rationale="Both resources share tag costCenter=finance.",
    )
    row = to_suggestion_row(
        suggestion,
        tenant_id="tenant-1",
        subscription_id="sub-1",
        run_id=RUN_ID,
        timestamp=TIMESTAMP,
        change_version="cv-1",
        suggestion_id="suggestion-1",
    )
    row["status"] = ACCEPTED_SUGGESTION_STATUS
    return row


def test_accepted_suggestion_promotes_to_relationship_shaped_row():
    row = _accepted_suggestion_row("vm-a", "possiblyRelatedTo", "vm-b")
    promoted = accepted_suggestion_to_relationship_row(row, run_id=RUN_ID)

    assert promoted["subject_id"] == "vm-a"
    assert promoted["object_id"] == "vm-b"
    assert promoted["predicate"] == "possiblyRelatedTo"
    assert promoted["source"] == APPROVED_SUGGESTION_RELATIONSHIP_SOURCE
    # Same field shape as RelationshipBuilder's own output.
    for field in (
        "resource_id",
        "change_version",
        "subject_type",
        "object_type",
        "confidence",
        "payload_json",
        "lineage_json",
        "lifecycle_status",
        "valid_from",
        "retired_at",
        "ontology_version",
    ):
        assert field in promoted


def test_promotion_is_idempotent_across_repeated_calls():
    row = _accepted_suggestion_row("vm-a", "possiblyRelatedTo", "vm-b")
    first = accepted_suggestion_to_relationship_row(row, run_id=RUN_ID)
    second = accepted_suggestion_to_relationship_row(row, run_id=RUN_ID)
    assert first == second
    assert first["resource_id"] == second["resource_id"]
    assert first["change_version"] == second["change_version"]


def test_merge_adds_accepted_suggestion_not_already_deterministically_derived():
    entities = _sample_entities()
    deterministic = derive_relationships(entities, RUN_ID)

    entity_ids = {row["resource_id"] for row in entities}
    novel_subject = next(iter(entity_ids))
    novel_object = next(rid for rid in entity_ids if rid != novel_subject)
    accepted = _accepted_suggestion_row(novel_subject, "possiblyRelatedTo", novel_object)

    result = merge_approved_relationship_suggestions(
        deterministic, [accepted], run_id=RUN_ID
    )

    assert result.approved_count == 1
    assert result.conflict_count == 0
    assert len(result.merged) == len(deterministic) + 1
    added = [row for row in result.merged if row not in deterministic]
    assert len(added) == 1
    assert added[0]["source"] == APPROVED_SUGGESTION_RELATIONSHIP_SOURCE
    assert added[0]["predicate"] == "possiblyRelatedTo"


def test_merge_ignores_suggestions_not_yet_accepted():
    entities = _sample_entities()
    deterministic = derive_relationships(entities, RUN_ID)
    pending = _accepted_suggestion_row(
        next(iter({row["resource_id"] for row in entities})),
        "possiblyRelatedTo",
        next(reversed([row["resource_id"] for row in entities])),
    )
    pending["status"] = DEFAULT_SUGGESTION_STATUS  # still pending_review

    result = merge_approved_relationship_suggestions(
        deterministic, [pending], run_id=RUN_ID
    )

    assert result.approved_count == 0
    assert result.merged == deterministic


def test_merge_keeps_deterministic_relationship_on_conflict_and_reports_it():
    entities = _sample_entities()
    deterministic = derive_relationships(entities, RUN_ID)
    assert deterministic, "fixture must produce at least one deterministic edge"

    existing = deterministic[0]
    colliding_suggestion = _accepted_suggestion_row(
        existing["subject_id"], existing["predicate"], existing["object_id"]
    )

    result = merge_approved_relationship_suggestions(
        deterministic, [colliding_suggestion], run_id=RUN_ID
    )

    # Deterministic wins: merged output is unchanged, and the conflict is
    # explicitly reported rather than silently dropped.
    assert result.merged == deterministic
    assert result.conflict_count == 1
    assert result.conflicts[0]["relationship_id"] == existing["resource_id"]
    assert result.conflicts[0]["resolution"] == "deterministic_kept"
    kept = next(
        row for row in result.merged if row["resource_id"] == existing["resource_id"]
    )
    assert kept["source"] == existing["source"]
    assert kept["source"] != APPROVED_SUGGESTION_RELATIONSHIP_SOURCE
