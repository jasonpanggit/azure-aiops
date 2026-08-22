"""Evidence envelope.

Every API response wraps its payload in an envelope that states where the data
came from and how much it should be trusted. The UI renders provenance from
this, and an operator can answer "why does the platform believe this?" without
leaving the response.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Confidence bands. Deliberately coarse: the platform derives facts from
# heterogeneous sources and a false sense of numeric precision would mislead.
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_UNKNOWN = "unknown"

CONFIDENCE_LEVELS: tuple[str, ...] = (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    CONFIDENCE_UNKNOWN,
)

# Freshness bands, derived from the age of the underlying snapshot.
FRESHNESS_FRESH = "fresh"
FRESHNESS_AGING = "aging"
FRESHNESS_STALE = "stale"
FRESHNESS_UNKNOWN = "unknown"

_AGING_AFTER_HOURS = 6.0
_STALE_AFTER_HOURS = 24.0


def classify_freshness(
    observed_at: str | None, *, now: datetime | None = None
) -> str:
    """Band a timestamp into fresh/aging/stale."""
    if not observed_at:
        return FRESHNESS_UNKNOWN
    try:
        parsed = datetime.fromisoformat(str(observed_at))
    except ValueError:
        return FRESHNESS_UNKNOWN
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    age_hours = (reference - parsed).total_seconds() / 3600.0
    if age_hours < 0:
        # A future timestamp is not evidence of freshness, it is a clock fault.
        return FRESHNESS_UNKNOWN
    if age_hours <= _AGING_AFTER_HOURS:
        return FRESHNESS_FRESH
    if age_hours <= _STALE_AFTER_HOURS:
        return FRESHNESS_AGING
    return FRESHNESS_STALE


@dataclass(frozen=True)
class Evidence:
    """Provenance for one fact or one response section."""

    source_engine: str
    source_table: str = ""
    timestamp: str = ""
    subscription_connection: str = ""
    resource_id: str = ""
    confidence: str = CONFIDENCE_UNKNOWN
    freshness: str = FRESHNESS_UNKNOWN

    def __post_init__(self) -> None:
        engine = str(self.source_engine or "").strip()
        if not engine:
            raise ValueError("Evidence source_engine is required")
        object.__setattr__(self, "source_engine", engine)
        for name in ("source_table", "timestamp", "subscription_connection", "resource_id"):
            object.__setattr__(self, name, str(getattr(self, name) or "").strip())
        confidence = str(self.confidence or CONFIDENCE_UNKNOWN).strip().casefold()
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown evidence confidence {self.confidence!r}")
        object.__setattr__(self, "confidence", confidence)
        freshness = str(self.freshness or FRESHNESS_UNKNOWN).strip().casefold()
        if freshness == FRESHNESS_UNKNOWN and self.timestamp:
            freshness = classify_freshness(self.timestamp)
        object.__setattr__(self, "freshness", freshness)

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
        *,
        source_engine: str,
        source_table: str = "",
        subscription_connection: str = "",
        resource_id: str = "",
        confidence: str = CONFIDENCE_UNKNOWN,
    ) -> Evidence:
        """Derive evidence from a SemanticEngine context payload."""
        return cls(
            source_engine=source_engine,
            source_table=source_table,
            timestamp=str(context.get("freshness") or ""),
            subscription_connection=subscription_connection,
            resource_id=resource_id,
            confidence=confidence,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_engine": self.source_engine,
            "source_table": self.source_table,
            "timestamp": self.timestamp,
            "subscription_connection": self.subscription_connection,
            "resource_id": self.resource_id,
            "confidence": self.confidence,
            "freshness": self.freshness,
        }


@dataclass
class Envelope:
    """A response body: the data, its evidence, and the scope it was read under."""

    data: Any
    evidence: Sequence[Evidence] = field(default_factory=tuple)
    scope: Mapping[str, Any] = field(default_factory=dict)
    knowledge_version: str = ""
    warnings: Sequence[str] = field(default_factory=tuple)
    pagination: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "data": self.data,
            "evidence": [item.to_dict() for item in self.evidence],
            "scope": dict(self.scope),
        }
        if self.knowledge_version:
            body["knowledge_version"] = self.knowledge_version
        if self.pagination is not None:
            body["pagination"] = dict(self.pagination)
        warnings = list(dict.fromkeys((*_truncation_warnings(self.data), *self.warnings)))
        if warnings:
            body["warnings"] = warnings
        return body


def envelope(
    data: Any,
    *,
    evidence: Evidence | Sequence[Evidence] | None = None,
    scope: Mapping[str, Any] | None = None,
    knowledge_version: str = "",
    warnings: Sequence[str] | None = None,
    pagination: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience constructor returning a serialized envelope."""
    if evidence is None:
        items: Sequence[Evidence] = ()
    elif isinstance(evidence, Evidence):
        items = (evidence,)
    else:
        items = tuple(evidence)
    return Envelope(
        data=data,
        evidence=items,
        scope=scope or {},
        knowledge_version=knowledge_version,
        warnings=tuple(warnings or ()),
        pagination=pagination,
    ).to_dict()


def _truncation_warnings(value: Any) -> tuple[str, ...]:
    """Surface bounded semantic results so callers never mistake them for complete."""
    if isinstance(value, Mapping):
        if value.get("truncated") is True:
            return (
                "Results are truncated; narrow the scope or use pagination for a complete view.",
            )
        return tuple(
            warning
            for child in value.values()
            for warning in _truncation_warnings(child)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(warning for child in value for warning in _truncation_warnings(child))
    return ()
