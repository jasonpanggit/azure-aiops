from __future__ import annotations

import inspect

from fabric_pipelines.relationship_suggestion_promoter import (
    prioritize_suggestions,
)
from fabric_pipelines.relationship_suggestions_contract import (
    RelationshipSuggestion,
)


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


def test_confidence_only_prioritizes_review_stably() -> None:
    low = _suggestion(confidence=0.1, object_id="vm-low")
    first_high = _suggestion(confidence=0.95, object_id="vm-high-1")
    second_high = _suggestion(confidence=0.95, object_id="vm-high-2")

    held = prioritize_suggestions([low, first_high, second_high])

    assert held == [first_high, second_high, low]


def test_prioritizer_has_no_authority_inputs_or_promoted_output() -> None:
    parameters = inspect.signature(prioritize_suggestions).parameters
    assert tuple(parameters) == ("suggestions",)
    assert prioritize_suggestions([]) == []
