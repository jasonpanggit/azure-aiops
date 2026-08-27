from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

_LIFECYCLE_STATES = frozenset({"proposed", "accepted", "rejected", "expired"})


@dataclass(frozen=True)
class RelationshipAssertion:
    """A semantic relationship emitted by deterministic or LLM modelers."""

    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    confidence: float
    evidence: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    lifecycle_status: str = "proposed"
    assertion_id: str = ""

    def __post_init__(self) -> None:
        required = (
            self.subject_id,
            self.subject_type,
            self.predicate,
            self.object_id,
            self.object_type,
        )
        if not all(isinstance(value, str) and value.strip() for value in required):
            raise ValueError("Relationship assertion identity fields are required")
        if not isinstance(self.confidence, (int, float)) or not 0 <= self.confidence <= 1:
            raise ValueError("Relationship assertion confidence must be between 0 and 1")
        if self.lifecycle_status not in _LIFECYCLE_STATES:
            raise ValueError(
                f"Unsupported relationship assertion lifecycle: {self.lifecycle_status}"
            )
        if any(not isinstance(item, str) or not item.strip() for item in self.evidence):
            raise ValueError("Relationship assertion evidence must contain strings")

    def to_row(self) -> dict[str, Any]:
        """Return the graph relationship shape without copying source facts."""
        row = asdict(self)
        row["evidence_json"] = list(row.pop("evidence"))
        row["provenance_json"] = row.pop("provenance")
        row["resource_id"] = self.assertion_id or (
            f"assertion:{self.subject_id}:{self.predicate}:{self.object_id}"
        )
        return row


@dataclass(frozen=True)
class SemanticModel:
    """The complete graph contribution from one modeler run."""

    assertions: tuple[RelationshipAssertion, ...] = ()
    model_version: str = ""

    def __post_init__(self) -> None:
        if any(not isinstance(item, RelationshipAssertion) for item in self.assertions):
            raise TypeError("Semantic model assertions must be RelationshipAssertion values")

    def relationship_rows(self) -> list[dict[str, Any]]:
        """Serialize assertions for ontology graph publication."""
        return [assertion.to_row() for assertion in self.assertions]
