from __future__ import annotations

from semantic.assertion_reconciler import AssertionReconciler
from semantic.semantic_assertions import RelationshipAssertion


def assertion(object_id: str, status: str = "proposed") -> RelationshipAssertion:
    return RelationshipAssertion(
        subject_id="app:payments",
        subject_type="Application",
        predicate="depends_on",
        object_id=object_id,
        object_type="Service",
        confidence=0.9,
        lifecycle_status=status,
    )


def test_reconcile_preserves_acceptance_and_expires_disappeared_assertions():
    result = AssertionReconciler().reconcile(
        [assertion("svc:checkout", "accepted"), assertion("svc:legacy")],
        [assertion("svc:checkout"), assertion("svc:fraud")],
    )

    states = {item.object_id: item.lifecycle_status for item in result}
    assert states == {
        "svc:checkout": "accepted",
        "svc:legacy": "expired",
        "svc:fraud": "proposed",
    }
