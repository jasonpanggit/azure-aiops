"""Business metadata assigned to a subscription connection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CRITICALITY_LEVELS = ("critical", "high", "medium", "low")

_FIELDS = (
    "business_service",
    "application",
    "environment",
    "project_owner",
    "support_team",
    "criticality",
    "region",
    "cost_center",
)


@dataclass(frozen=True)
class BusinessMetadata:
    """Business context mapped onto a connection.

    All fields are optional so a connection can be created first and enriched
    later via ``hermes subscriptions map``.
    """

    business_service: str | None = None
    application: str | None = None
    environment: str | None = None
    project_owner: str | None = None
    support_team: str | None = None
    criticality: str | None = None
    region: str | None = None
    cost_center: str | None = None

    def __post_init__(self) -> None:
        for name in _FIELDS:
            object.__setattr__(self, name, _clean(getattr(self, name)))
        if self.criticality is not None:
            level = self.criticality.casefold()
            if level not in CRITICALITY_LEVELS:
                raise ValueError(
                    f"criticality must be one of {', '.join(CRITICALITY_LEVELS)}; got '{self.criticality}'"
                )
            object.__setattr__(self, "criticality", level)
        if self.environment is not None:
            object.__setattr__(self, "environment", self.environment.casefold())

    @classmethod
    def from_mapping(cls, value: Any) -> BusinessMetadata:
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("BusinessMetadata must be a mapping or BusinessMetadata")
        return cls(**{name: value.get(name) for name in _FIELDS if name in value})

    def merge(self, other: BusinessMetadata) -> BusinessMetadata:
        """Return a copy where non-empty values from ``other`` win."""
        return BusinessMetadata(
            **{
                name: (getattr(other, name) if getattr(other, name) is not None else getattr(self, name))
                for name in _FIELDS
            }
        )

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, name) is None for name in _FIELDS)

    def missing_fields(self) -> list[str]:
        return [name for name in _FIELDS if getattr(self, name) is None]

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _FIELDS}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["CRITICALITY_LEVELS", "BusinessMetadata"]
