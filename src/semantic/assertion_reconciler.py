from __future__ import annotations

from dataclasses import replace

from .semantic_assertions import RelationshipAssertion


class AssertionReconciler:
    """Reconcile a modeler result without destroying assertion history."""

    def reconcile(
        self,
        existing: list[RelationshipAssertion],
        proposed: list[RelationshipAssertion],
    ) -> list[RelationshipAssertion]:
        active_by_key = {
            self._key(item): item
            for item in existing
            if item.lifecycle_status not in {"expired", "rejected"}
        }
        proposed_by_key = {self._key(item): item for item in proposed}
        result: list[RelationshipAssertion] = []
        for item in existing:
            key = self._key(item)
            if key in proposed_by_key:
                candidate = proposed_by_key.pop(key)
                result.append(
                    replace(
                        candidate,
                        lifecycle_status=item.lifecycle_status
                        if item.lifecycle_status == "accepted"
                        else candidate.lifecycle_status,
                        assertion_id=item.assertion_id or candidate.assertion_id,
                    )
                )
            elif key in active_by_key:
                result.append(replace(item, lifecycle_status="expired"))
            else:
                result.append(item)
        result.extend(proposed_by_key.values())
        return result

    @staticmethod
    def _key(item: RelationshipAssertion) -> tuple[str, str, str]:
        return item.subject_id, item.predicate, item.object_id
