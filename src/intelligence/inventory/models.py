"""Immutable contracts for the OS inventory read model.

Raw ARG/Logs payloads are deliberately not represented here.  Normalization
produces only the fields that are safe and useful at the API boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

SOURCE_TYPES = frozenset({"azure_vm", "arc"})
SOURCE_STATES = frozenset({"ready", "partial", "stale", "degraded", "unavailable"})


def _text(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def group_key(os_name: str, os_version: str) -> str:
    """Return the stable server-owned key used by group-detail URLs."""
    return f"{_text(os_name, 'Unknown OS')}|{_text(os_version, 'Unknown')}"


@dataclass(frozen=True)
class InventoryEvidence:
    source_engine: str
    source_table: str
    observed_at: str
    source_id: str = ""
    query_version: str = ""

    def __post_init__(self) -> None:
        if not _text(self.source_engine) or not _text(self.source_table):
            raise ValueError("Inventory evidence requires a source engine and table")
        object.__setattr__(self, "source_engine", _text(self.source_engine))
        object.__setattr__(self, "source_table", _text(self.source_table))
        object.__setattr__(self, "observed_at", _text(self.observed_at))
        object.__setattr__(self, "source_id", _text(self.source_id))
        object.__setattr__(self, "query_version", _text(self.query_version))

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class InventorySourceStatus:
    source_type: str
    state: str
    observed_at: str = ""
    query_version: str = ""
    row_count: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        source = _text(self.source_type).casefold()
        state = _text(self.state).casefold()
        if source not in SOURCE_TYPES:
            raise ValueError(f"Unknown inventory source type {self.source_type!r}")
        if state not in SOURCE_STATES:
            raise ValueError(f"Unknown inventory source state {self.state!r}")
        if self.row_count < 0:
            raise ValueError("Inventory source row_count cannot be negative")
        object.__setattr__(self, "source_type", source)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "observed_at", _text(self.observed_at))
        object.__setattr__(self, "query_version", _text(self.query_version))
        object.__setattr__(self, "error", _text(self.error))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MachineObservation:
    """A normalized machine row safe to expose after scope filtering."""

    resource_id: str
    machine_name: str
    source_type: str
    os_name: str
    os_version: str
    subscription_id: str
    resource_group: str
    environment: str
    observed_at: str
    evidence: tuple[InventoryEvidence, ...]
    source_status: str
    lifecycle_status: str = "Unknown"
    support_end: str | None = None
    days_remaining: int | None = None
    review_required: bool = False

    def __post_init__(self) -> None:
        required = ("resource_id", "machine_name", "subscription_id", "resource_group", "observed_at")
        for name in required:
            if not _text(getattr(self, name)):
                raise ValueError(f"Machine observation requires {name}")
        source = _text(self.source_type).casefold()
        if source not in SOURCE_TYPES:
            raise ValueError(f"Unknown inventory source type {self.source_type!r}")
        status = _text(self.source_status).casefold()
        if status not in SOURCE_STATES:
            raise ValueError(f"Unknown inventory source state {self.source_status!r}")
        object.__setattr__(self, "resource_id", _text(self.resource_id))
        object.__setattr__(self, "machine_name", _text(self.machine_name))
        object.__setattr__(self, "source_type", source)
        object.__setattr__(self, "os_name", _text(self.os_name, "Unknown OS"))
        object.__setattr__(self, "os_version", _text(self.os_version, "Unknown"))
        object.__setattr__(self, "subscription_id", _text(self.subscription_id))
        object.__setattr__(self, "resource_group", _text(self.resource_group, "Unknown"))
        object.__setattr__(self, "environment", _text(self.environment, "Unknown"))
        object.__setattr__(self, "observed_at", _text(self.observed_at))
        object.__setattr__(self, "source_status", status)
        object.__setattr__(self, "lifecycle_status", _text(self.lifecycle_status, "Unknown"))
        object.__setattr__(self, "support_end", _text(self.support_end) or None)
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @classmethod
    def from_mapping(
        cls,
        row: dict[str, Any],
        *,
        default_status: str = "ready",
        query_version: str = "",
    ) -> MachineObservation:
        """Normalize common ARG property spellings without retaining payloads."""
        properties = row.get("properties")
        props = properties if isinstance(properties, dict) else {}
        tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
        source = _text(row.get("source_type")).casefold()
        resource_type = _text(row.get("type")).casefold()
        if not source:
            source = "arc" if "hybridcompute/machines" in resource_type else "azure_vm"
        os_name = (
            row.get("os_name")
            or row.get("osName")
            or props.get("osName")
            or props.get("os_name")
            or "Unknown OS"
        )
        os_version = (
            row.get("os_version")
            or row.get("osVersion")
            or props.get("osVersion")
            or props.get("os_version")
            or "Unknown"
        )
        evidence = row.get("evidence")
        if isinstance(evidence, list):
            evidence_rows = evidence
        else:
            evidence_rows = [
                {
                    "source_engine": "hermes_arg_connector",
                    "source_table": "Resources",
                    "observed_at": row.get("observed_at") or row.get("observedAt") or "",
                    "source_id": row.get("id") or row.get("resource_id") or "",
                    "query_version": query_version,
                }
            ]
        parsed_evidence = tuple(
            item
            if isinstance(item, InventoryEvidence)
            else InventoryEvidence(
                source_engine=item.get("source_engine", "hermes_arg_connector"),
                source_table=item.get("source_table", "Resources"),
                observed_at=item.get("observed_at") or row.get("observed_at") or "",
                source_id=item.get("source_id", ""),
                query_version=item.get("query_version", query_version),
            )
            for item in evidence_rows
            if isinstance(item, dict)
        )
        environment = (
            row.get("environment")
            or tags.get("environment")
            or tags.get("env")
            or props.get("environment")
            or "Unknown"
        )
        return cls(
            resource_id=row.get("resource_id") or row.get("id") or "",
            machine_name=row.get("machine_name") or row.get("name") or row.get("computer", ""),
            source_type=source,
            os_name=os_name,
            os_version=os_version,
            subscription_id=row.get("subscription_id") or row.get("subscriptionId") or "",
            resource_group=row.get("resource_group") or row.get("resourceGroup") or "",
            environment=environment,
            observed_at=row.get("observed_at") or row.get("observedAt") or "",
            evidence=parsed_evidence,
            source_status=row.get("source_status") or default_status,
            lifecycle_status=row.get("lifecycle_status", "Unknown"),
            support_end=row.get("support_end"),
            days_remaining=row.get("days_remaining"),
            review_required=bool(row.get("review_required", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


@dataclass(frozen=True)
class OSGroup:
    key: str
    os_name: str
    os_version: str
    machine_count: int
    source_types: tuple[str, ...]
    lifecycle_status: str
    support_end: str | None
    days_remaining: int | None
    review_required: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_types"] = list(self.source_types)
        return payload
