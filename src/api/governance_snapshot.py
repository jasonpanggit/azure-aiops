"""Scoped view over identity and cost rows from the ontology snapshot.

Sits between the raw ontology rows and the stateless governance engines. Its
one job is to hand each engine only the rows a caller is entitled to see, so
subscription isolation is enforced in exactly one place instead of being
re-implemented in every route.

Rows arrive as ontology entities whose type-specific fields live inside
``payload_json``. This class unpacks that once and caches the result, since
every governance route needs the same unpacked view.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from functools import cached_property
from typing import Any

_IDENTITY_TYPES = ("RoleAssignment", "RoleDefinition", "ManagedIdentity")


def _unpack(row: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten an ontology row's ``payload_json`` back onto the row.

    The payload holds the source ARG fields (``principalId``,
    ``assignmentScope``, ...). Top-level ontology columns win on conflict
    because they are the validated, canonicalized values.
    """
    merged: dict[str, Any] = {}
    payload = row.get("payload_json")
    if isinstance(payload, str) and payload:
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, Mapping):
            merged.update(decoded)
    elif isinstance(payload, Mapping):
        merged.update(payload)
    for key, value in row.items():
        if key == "payload_json":
            continue
        if value not in (None, ""):
            merged[key] = value
    merged.setdefault("id", row.get("resource_id") or "")
    return merged


class GovernanceSnapshot:
    """Ontology rows, unpacked and filterable by scope."""

    def __init__(
        self,
        entities: Iterable[Mapping[str, Any]],
        *,
        observed_at: str = "",
        connections: Sequence[Mapping[str, Any]] = (),
        warnings: Sequence[str] = (),
        generation_available: bool = True,
    ) -> None:
        self._entities = [dict(row) for row in entities]
        self.observed_at = observed_at
        self.connections = [dict(row) for row in connections]
        self.warnings = list(dict.fromkeys(warnings))
        self.generation_available = generation_available

    @cached_property
    def _by_type(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._entities:
            entity_type = str(row.get("entity_type") or "")
            if not entity_type:
                continue
            grouped.setdefault(entity_type, []).append(_unpack(row))
        return grouped

    def rows(self, entity_type: str) -> list[dict[str, Any]]:
        return list(self._by_type.get(entity_type, ()))

    @property
    def has_identity_data(self) -> bool:
        """True when any identity family was observed.

        Used to distinguish "no privileged access" from "identity data was
        never synced" -- reporting the second as the first would be a
        dangerous false assurance on a security surface.
        """
        return any(self._by_type.get(name) for name in _IDENTITY_TYPES)

    def scoped(self, scope: Any) -> GovernanceSnapshot:
        """Return a copy containing only rows the scope admits."""
        if scope is None or scope.is_unrestricted():
            return self
        entities = [row for row in self._entities if self._matches(row, scope)]
        connections = [
            connection
            for connection in self.connections
            if self._matches(connection, scope)
        ]
        snapshot = GovernanceSnapshot(
            entities,
            observed_at=self.observed_at,
            connections=connections,
            warnings=self.warnings,
            generation_available=self.generation_available,
        )
        return snapshot

    @staticmethod
    def _matches(row: Mapping[str, Any], scope: Any) -> bool:
        from .scope import scope_attributes

        # Match against the unpacked row: subscription id often lives in the
        # payload rather than as a top-level ontology column, and filtering on
        # the un-unpacked row would silently admit rows whose subscription
        # could not be read.
        return bool(scope.matches(scope_attributes(_unpack(row))))


__all__ = ["GovernanceSnapshot"]
