from __future__ import annotations

import pytest

from semantic.semantic_assertions import RelationshipAssertion, SemanticModel


def test_semantic_model_serializes_relationship_assertions_only():
    assertion = RelationshipAssertion(
        subject_id="app:payments",
        subject_type="Application",
        predicate="depends_on",
        object_id="svc:checkout",
        object_type="Service",
        confidence=0.92,
        evidence=("tag:depends-on=svc:checkout",),
        provenance={"model": "aiops", "run_id": "run-1"},
        lifecycle_status="proposed",
    )

    row = SemanticModel((assertion,), model_version="model-v1").relationship_rows()[0]

    assert row["resource_id"] == "assertion:app:payments:depends_on:svc:checkout"
    assert row["confidence"] == 0.92
    assert row["evidence_json"] == ["tag:depends-on=svc:checkout"]
    assert row["provenance_json"] == {"model": "aiops", "run_id": "run-1"}
    assert "properties" not in row
    assert "status" not in row


@pytest.mark.parametrize("status", ["invalid", "", "active"])
def test_semantic_assertion_rejects_unknown_lifecycle(status: str):
    with pytest.raises(ValueError, match="lifecycle"):
        RelationshipAssertion(
            subject_id="a",
            subject_type="Application",
            predicate="depends_on",
            object_id="b",
            object_type="Service",
            confidence=0.5,
            lifecycle_status=status,
        )
