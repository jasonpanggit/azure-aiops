from __future__ import annotations

from fabric_pipelines.relationship_suggestion_promoter import (
    AUTO_PROMOTED_SUGGESTION_SOURCE,
    promote_suggestions,
)
from fabric_pipelines.relationship_suggestions_contract import RelationshipSuggestion


def _suggestion(**overrides) -> RelationshipSuggestion:
    fields = {
        "subject_id": "vm-a",
        "subject_type": "VirtualMachine",
        "predicate": "depends_on",
        "object_id": "vm-b",
        "object_type": "VirtualMachine",
        "confidence": 0.9,
        "rationale": "co-tagged and co-deployed",
        "suggested_by": "fabric_data_agent",
    }
    fields.update(overrides)
    return RelationshipSuggestion(**fields)


def test_above_threshold_with_both_ids_known_is_promoted():
    suggestion = _suggestion(confidence=0.9)

    promoted, held = promote_suggestions(
        [suggestion], known_entity_ids={"vm-a", "vm-b"}, auto_accept_threshold=0.85
    )

    assert held == []
    assert len(promoted) == 1
    row = promoted[0]
    assert row["subject_id"] == "vm-a"
    assert row["predicate"] == "depends_on"
    assert row["object_id"] == "vm-b"
    assert row["confidence"] == 0.9
    assert row["source"] == AUTO_PROMOTED_SUGGESTION_SOURCE == "fabric_data_agent_llm"
    assert row["resource_id"]
    assert row["change_version"]


def test_below_threshold_is_held_for_review():
    suggestion = _suggestion(confidence=0.5)

    promoted, held = promote_suggestions(
        [suggestion], known_entity_ids={"vm-a", "vm-b"}, auto_accept_threshold=0.85
    )

    assert promoted == []
    assert held == [suggestion]


def test_unknown_entity_id_is_held_for_review_even_above_threshold():
    suggestion = _suggestion(confidence=0.99, object_id="vm-does-not-exist")

    promoted, held = promote_suggestions(
        [suggestion], known_entity_ids={"vm-a"}, auto_accept_threshold=0.85
    )

    assert promoted == []
    assert held == [suggestion]


def test_empty_input_returns_empty_output():
    promoted, held = promote_suggestions([], known_entity_ids=set())

    assert promoted == []
    assert held == []


def test_known_entity_ids_are_matched_case_insensitively():
    suggestion = _suggestion(confidence=0.9, subject_id="VM-A", object_id="VM-B")

    promoted, held = promote_suggestions(
        [suggestion], known_entity_ids={"vm-a", "vm-b"}, auto_accept_threshold=0.85
    )

    assert held == []
    assert len(promoted) == 1


def test_mixed_batch_splits_correctly_and_preserves_review_order():
    above = _suggestion(confidence=0.9, object_id="vm-b")
    below = _suggestion(confidence=0.1, object_id="vm-c")
    unknown = _suggestion(confidence=0.95, object_id="vm-unknown")

    promoted, held = promote_suggestions(
        [above, below, unknown],
        known_entity_ids={"vm-a", "vm-b", "vm-c"},
        auto_accept_threshold=0.85,
    )

    assert len(promoted) == 1
    assert held == [below, unknown]
