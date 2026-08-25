"""Immutable contracts for the OS inventory read model.

Raw ARG/Logs payloads are deliberately not represented here.  Normalization
produces only the fields that are safe and useful at the API boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

MACHINE_SOURCE_TYPES = frozenset({"azure_vm", "arc"})
SOURCE_TYPES = frozenset({"azure_vm", "arc", "logs"})
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
    workspace_count: int = 0

    def __post_init__(self) -> None:
        source = _text(self.source_type).casefold()
        state = _text(self.state).casefold()
        if source not in SOURCE_TYPES:
            raise ValueError(f"Unknown inventory source type {self.source_type!r}")
        if state not in SOURCE_STATES:
            raise ValueError(f"Unknown inventory source state {self.state!r}")
        if self.row_count < 0:
            raise ValueError("Inventory source row_count cannot be negative")
        if self.workspace_count < 0:
            raise ValueError("Inventory source workspace_count cannot be negative")
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
    query_version: str = ""
    os_type: str = ""
    image_publisher: str = ""
    image_offer: str = ""
    image_sku: str = ""
    image_version: str = ""
    computer_name: str = ""
    machine_status: str = ""
    support_channel: str = ""
    lifecycle_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = ("resource_id", "machine_name", "subscription_id", "resource_group", "observed_at")
        for name in required:
            if not _text(getattr(self, name)):
                raise ValueError(f"Machine observation requires {name}")
        source = _text(self.source_type).casefold()
        if source not in MACHINE_SOURCE_TYPES:
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
        object.__setattr__(self, "query_version", _text(self.query_version))
        object.__setattr__(self, "os_type", _text(self.os_type))
        object.__setattr__(self, "image_publisher", _text(self.image_publisher))
        object.__setattr__(self, "image_offer", _text(self.image_offer))
        object.__setattr__(self, "image_sku", _text(self.image_sku))
        object.__setattr__(self, "image_version", _text(self.image_version))
        object.__setattr__(self, "computer_name", _text(self.computer_name))
        object.__setattr__(self, "machine_status", _text(self.machine_status))
        channel = _text(self.support_channel).casefold()
        if channel and channel not in {"mainstream", "extended"}:
            raise ValueError("Machine observation has an invalid support channel")
        object.__setattr__(self, "support_channel", channel)
        object.__setattr__(
            self,
            "lifecycle_evidence",
            tuple(_text(item) for item in self.lifecycle_evidence if _text(item)),
        )

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
        environment = _text(row.get("environment")) or _environment_from_tags(tags)
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
            query_version=row.get("query_version") or query_version,
            os_type=row.get("os_type") or row.get("osType") or "",
            image_publisher=row.get("image_publisher") or row.get("imagePublisher") or "",
            image_offer=row.get("image_offer") or row.get("imageOffer") or "",
            image_sku=row.get("image_sku") or row.get("imageSku") or "",
            image_version=row.get("image_version") or row.get("imageVersion") or "",
            computer_name=row.get("computer_name") or row.get("computerName") or "",
            machine_status=row.get("machine_status") or row.get("status") or "",
            support_channel=row.get("support_channel") or "",
            lifecycle_evidence=tuple(row.get("lifecycle_evidence") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        payload["lifecycle_evidence"] = list(self.lifecycle_evidence)
        return payload


@dataclass(frozen=True)
class SoftwareObservation:
    """A current ConfigurationData installation, optionally joined to a machine."""

    software_name: str
    software_version: str
    raw_software_name: str
    raw_software_version: str
    canonical_identity: str
    resource_id: str
    machine_name: str
    source_computer_id: str
    source_type: str | None
    join_status: str
    subscription_id: str
    resource_group: str
    environment: str
    publisher: str
    software_type: str
    observed_at: str
    evidence: tuple[dict[str, str], ...] = ()
    mapping_id: str = ""
    mapping_status: str = ""
    mapping_revision: int = 0
    mapping_method: str = ""
    mapping_confidence: float = 0
    mapping_provenance: dict[str, Any] | None = None
    mapping_source_timestamp: str = ""

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> SoftwareObservation:
        evidence = row.get("evidence")
        parsed_evidence = tuple(
            item
            if isinstance(item, InventoryEvidence)
            else dict(item)
            for item in evidence or ()
            if isinstance(item, (dict, InventoryEvidence))
        )
        return cls(
            software_name=str(row.get("software_name") or row.get("canonical_name") or ""),
            software_version=str(row.get("software_version") or row.get("canonical_version") or ""),
            raw_software_name=str(row.get("raw_software_name") or ""),
            raw_software_version=str(row.get("raw_software_version") or ""),
            canonical_identity=str(row.get("canonical_identity") or ""),
            resource_id=str(row.get("resource_id") or ""),
            machine_name=str(row.get("machine_name") or row.get("computer") or ""),
            source_computer_id=str(row.get("source_computer_id") or ""),
            source_type=row.get("source_type"),
            join_status=str(row.get("join_status") or row.get("resource_join_status") or "unlinked"),
            subscription_id=str(row.get("subscription_id") or ""),
            resource_group=str(row.get("resource_group") or ""),
            environment=str(row.get("environment") or ""),
            publisher=str(row.get("publisher") or ""),
            software_type=str(row.get("software_type") or ""),
            observed_at=str(row.get("observed_at") or row.get("time_generated") or ""),
            evidence=parsed_evidence,
            mapping_id=str(row.get("mapping_id") or ""),
            mapping_status=str(row.get("mapping_status") or ""),
            mapping_revision=int(row.get("mapping_revision", 0)),
            mapping_method=str(row.get("mapping_method") or ""),
            mapping_confidence=float(row.get("mapping_confidence", 0)),
            mapping_provenance=(
                dict(row["mapping_provenance"])
                if isinstance(row.get("mapping_provenance"), dict)
                else None
            ),
            mapping_source_timestamp=str(row.get("mapping_source_timestamp") or ""),
        )

    def __post_init__(self) -> None:
        if not _text(self.software_name) or not _text(self.software_version):
            raise ValueError("Software observation requires a canonical name and version")
        if self.join_status not in {"linked", "unlinked"}:
            raise ValueError("Software observation has an invalid join status")
        if self.source_type is not None and self.source_type not in MACHINE_SOURCE_TYPES:
            raise ValueError("Software observation has an invalid source type")
        object.__setattr__(self, "software_name", _text(self.software_name, "Unknown Software"))
        object.__setattr__(self, "software_version", _text(self.software_version, "Unknown"))
        object.__setattr__(self, "raw_software_name", _text(self.raw_software_name))
        object.__setattr__(self, "raw_software_version", _text(self.raw_software_version))
        object.__setattr__(
            self,
            "canonical_identity",
            _text(self.canonical_identity, f"{self.software_name}|{self.software_version}"),
        )
        object.__setattr__(self, "resource_id", _text(self.resource_id))
        object.__setattr__(self, "machine_name", _text(self.machine_name, "Unknown machine"))
        object.__setattr__(self, "source_computer_id", _text(self.source_computer_id))
        object.__setattr__(self, "subscription_id", _text(self.subscription_id))
        object.__setattr__(self, "resource_group", _text(self.resource_group, "Unknown"))
        object.__setattr__(self, "environment", _text(self.environment, "Unknown"))
        object.__setattr__(self, "publisher", _text(self.publisher))
        object.__setattr__(self, "software_type", _text(self.software_type))
        object.__setattr__(self, "observed_at", _text(self.observed_at))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if self.mapping_status and self.mapping_status not in {"suggested", "approved", "rejected"}:
            raise ValueError("Software observation has an invalid mapping status")
        if self.mapping_revision < 0 or isinstance(self.mapping_revision, bool):
            raise ValueError("Software observation has an invalid mapping revision")
        if not 0 <= self.mapping_confidence <= 1:
            raise ValueError("Software observation has an invalid mapping confidence")
        object.__setattr__(self, "mapping_id", _text(self.mapping_id))
        object.__setattr__(self, "mapping_status", _text(self.mapping_status))
        object.__setattr__(self, "mapping_method", _text(self.mapping_method))
        object.__setattr__(self, "mapping_source_timestamp", _text(self.mapping_source_timestamp))
        object.__setattr__(
            self,
            "mapping_provenance",
            dict(self.mapping_provenance) if self.mapping_provenance else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "software_name": self.software_name,
            "software_version": self.software_version,
            "canonical_name": self.software_name,
            "canonical_version": self.software_version,
            "canonical_identity": self.canonical_identity,
            "raw_software_name": self.raw_software_name,
            "raw_software_version": self.raw_software_version,
            "raw_identity": {
                "name": self.raw_software_name,
                "version": self.raw_software_version,
            },
            "resource_id": self.resource_id,
            "machine_name": self.machine_name,
            "computer": self.machine_name,
            "source_computer_id": self.source_computer_id,
            "source_type": self.source_type,
            "join_status": self.join_status,
            "resource_join_status": self.join_status,
            "subscription_id": self.subscription_id,
            "resource_group": self.resource_group,
            "environment": self.environment,
            "publisher": self.publisher,
            "software_type": self.software_type,
            "observed_at": self.observed_at,
            "time_generated": self.observed_at,
            "evidence": [
                item.to_dict() if isinstance(item, InventoryEvidence) else dict(item)
                for item in self.evidence
            ],
            "mapping_id": self.mapping_id,
            "mapping_status": self.mapping_status,
            "mapping_revision": self.mapping_revision,
            "mapping_method": self.mapping_method,
            "mapping_confidence": self.mapping_confidence,
            "mapping_provenance": self.mapping_provenance,
            "mapping_source_timestamp": self.mapping_source_timestamp,
        }


def _environment_from_tags(tags: dict[str, Any]) -> str:
    """Read only approved resource-tag keys, with deterministic precedence."""
    by_name = {
        str(key).casefold(): value
        for key, value in tags.items()
        if str(key).strip()
    }
    for key in ("environment", "env", "environmentname"):
        value = _text(by_name.get(key))
        if value:
            return value
    return "Unknown"


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
    support_channel: str = ""
    lifecycle_evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_types"] = list(self.source_types)
        payload["lifecycle_evidence"] = list(self.lifecycle_evidence)
        return payload


@dataclass(frozen=True)
class SoftwareGroup:
    key: str
    software_name: str
    software_version: str
    install_count: int
    source_types: tuple[str, ...]
    linked_count: int
    unlinked_count: int
    publishers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_types"] = list(self.source_types)
        payload["publishers"] = list(self.publishers)
        return payload
