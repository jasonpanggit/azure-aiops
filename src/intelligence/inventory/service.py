"""Read-only, scope-first OS inventory projection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api.evidence import Evidence
from api.scope import Scope, scope_attributes
from hermes_arg_connector.storage import DatasetStore
from intelligence.lifecycle import EOLCatalog

from .eol_review import EOLReviewService
from .models import (
    InventorySourceStatus,
    MachineObservation,
    OSGroup,
    SoftwareGroup,
    SoftwareObservation,
    group_key,
)


@dataclass(frozen=True)
class InventorySnapshot:
    observations: tuple[MachineObservation, ...]
    source_status: tuple[InventorySourceStatus, ...]
    software_observations: tuple[SoftwareObservation, ...] = ()
    software_source_status: tuple[InventorySourceStatus, ...] = ()
    observed_at: str = ""
    query_version: str = "inventory-os-v1"
    generation_id: str = ""

    @classmethod
    def from_payload(cls, payload: Any) -> InventorySnapshot:
        if isinstance(payload, list):
            rows = payload
            metadata: dict[str, Any] = {}
        elif isinstance(payload, dict):
            rows = payload.get("observations") or payload.get("rows") or []
            metadata = payload
        else:
            raise TypeError("Inventory fixture must be a list or object")
        if not isinstance(rows, list):
            raise TypeError("Inventory observations must be a list")
        query_version = str(metadata.get("query_version") or "inventory-os-v1")
        parsed_observations = [
            row
            if isinstance(row, MachineObservation)
            else MachineObservation.from_mapping(
                row,
                default_status=str(metadata.get("default_source_status") or "ready"),
                query_version=query_version,
            )
            for row in rows
            if isinstance(row, (dict, MachineObservation))
        ]
        observations = tuple(_latest_observations(parsed_observations))
        software_rows = metadata.get("software_observations") or metadata.get("software_rows") or []
        if not isinstance(software_rows, list):
            raise TypeError("Inventory software observations must be a list")
        software_observations = tuple(
            row
            if isinstance(row, SoftwareObservation)
            else SoftwareObservation.from_mapping(row)
            for row in software_rows
            if isinstance(row, (dict, SoftwareObservation))
        )
        statuses_payload = metadata.get("source_status") or {}
        if isinstance(statuses_payload, list):
            statuses_payload = {
                str(item.get("source_type") or ""): item
                for item in statuses_payload
                if isinstance(item, dict)
            }
        statuses: list[InventorySourceStatus] = []
        if isinstance(statuses_payload, dict):
            for source_type in ("azure_vm", "arc"):
                raw = statuses_payload.get(source_type)
                if isinstance(raw, str):
                    raw = {"state": raw}
                raw = raw if isinstance(raw, dict) else {}
                statuses.append(
                    InventorySourceStatus(
                        source_type=source_type,
                        state=str(raw.get("state") or _status_from_rows(observations, source_type)),
                        observed_at=str(raw.get("observed_at") or metadata.get("observed_at") or ""),
                        query_version=str(raw.get("query_version") or query_version),
                        row_count=int(raw.get("row_count", _count_source(observations, source_type))),
                        error=str(raw.get("error") or ""),
                        workspace_count=int(raw.get("workspace_count", 0)),
                    )
                )
        else:
            statuses = [
                InventorySourceStatus(
                    source_type=source_type,
                    state=_status_from_rows(observations, source_type),
                    observed_at=str(metadata.get("observed_at") or ""),
                    query_version=query_version,
                    row_count=_count_source(observations, source_type),
                )
                for source_type in ("azure_vm", "arc")
            ]
        software_statuses_payload = metadata.get("software_source_status") or {}
        software_statuses: list[InventorySourceStatus] = []
        if isinstance(software_statuses_payload, dict):
            raw = software_statuses_payload.get("logs")
            if isinstance(raw, str):
                raw = {"state": raw}
            raw = raw if isinstance(raw, dict) else {}
            software_statuses.append(
                InventorySourceStatus(
                    source_type="logs",
                    state=str(raw.get("state") or "ready"),
                    observed_at=str(raw.get("observed_at") or metadata.get("observed_at") or _latest_software(software_observations)),
                    query_version=str(raw.get("query_version") or query_version),
                    row_count=int(raw.get("row_count", len(software_observations))),
                    error=str(raw.get("error") or ""),
                    workspace_count=int(raw.get("workspace_count", 0)),
                )
            )
        return cls(
            observations=observations,
            source_status=tuple(statuses),
            software_observations=software_observations,
            software_source_status=tuple(software_statuses),
            observed_at=str(metadata.get("observed_at") or _latest(observations)),
            query_version=query_version,
            generation_id=str(metadata.get("generation_id") or metadata.get("run_id") or ""),
        )

    @classmethod
    def from_fixture(cls, path: str | Path) -> InventorySnapshot:
        return cls.from_payload(json.loads(Path(path).read_text(encoding="utf-8")))


class InventoryService:
    """Groups only the rows inside the supplied effective ReadScope."""

    def __init__(
        self,
        source: InventorySnapshot
        | dict[str, Any]
        | list[dict[str, Any]]
        | tuple[MachineObservation, ...],
        *,
        catalog: EOLCatalog | None = None,
        now: datetime | None = None,
        eol_review: EOLReviewService | None = None,
    ) -> None:
        self.snapshot = (
            source
            if isinstance(source, InventorySnapshot)
            else InventorySnapshot.from_payload(
                source if isinstance(source, (dict, list)) else list(source)
            )
        )
        self.eol_review = eol_review or EOLReviewService(catalog=catalog)
        self.catalog = catalog or self.eol_review.catalog().catalog
        self.now = now or datetime.now(UTC)

    @classmethod
    def from_fixture(
        cls,
        path: str | Path,
        *,
        catalog: EOLCatalog | None = None,
        eol_review: EOLReviewService | None = None,
    ) -> InventoryService:
        return cls(
            InventorySnapshot.from_fixture(path),
            catalog=catalog,
            eol_review=eol_review,
        )

    @classmethod
    def from_store(
        cls,
        store: DatasetStore,
        *,
        catalog: EOLCatalog | None = None,
        eol_review: EOLReviewService | None = None,
    ) -> InventoryService | None:
        rows = store.read_dataset("inventory/os_observations")
        status_rows = store.read_dataset("inventory/source_status")
        software_rows = store.read_dataset("inventory/software_observations")
        software_status_rows = store.read_dataset("inventory/software_source_status")
        if not rows and not status_rows and not software_rows and not software_status_rows:
            return None
        manifest = _store_manifest(store)
        statuses = {
            str(item.get("source_type") or ""): item
            for item in status_rows
            if isinstance(item, dict) and item.get("source_type")
        }
        metadata = {
            "observations": rows,
            "source_status": statuses,
            "software_observations": software_rows,
            "software_source_status": {
                str(item.get("source_type") or ""): item
                for item in software_status_rows
                if isinstance(item, dict) and item.get("source_type")
            },
            "observed_at": str(manifest.get("startedAt") or ""),
            "query_version": str(manifest.get("queryVersion") or "inventory-os-v1"),
            "generation_id": str(manifest.get("runId") or ""),
        }
        return cls(
            InventorySnapshot.from_payload(metadata),
            catalog=catalog,
            eol_review=eol_review,
        )

    @property
    def observed_at(self) -> str:
        return self.snapshot.observed_at

    @property
    def query_version(self) -> str:
        return self.snapshot.query_version

    @property
    def generation_id(self) -> str:
        return self.snapshot.generation_id

    def source_status(
        self, rows: tuple[MachineObservation, ...] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Project source state with row counts limited to the effective scope."""
        scoped_rows = rows if rows is not None else self.snapshot.observations
        return {
            item.source_type: {
                **item.to_dict(),
                "row_count": _count_source(scoped_rows, item.source_type),
            }
            for item in sorted(self.snapshot.source_status, key=lambda value: value.source_type)
        }

    def _scoped(self, scope: Scope) -> tuple[MachineObservation, ...]:
        # This is intentionally the first operation before classification,
        # grouping, pagination, or evidence projection.
        rows = [
            row
            for row in self.snapshot.observations
            if scope.matches(scope_attributes(_scope_row(row)))
        ]
        return tuple(sorted(rows, key=lambda row: (group_key(row.os_name, row.os_version), row.resource_id)))

    def _classified(self, row: MachineObservation) -> MachineObservation:
        catalog = self.eol_review.catalog().catalog
        classification = catalog.classify_product(
            row.os_name, row.os_version, now=self.now
        )
        unknown = classification.status.value == "Unknown"
        return MachineObservation(
            **{
                **row.__dict__,
                "lifecycle_status": classification.status.value,
                "support_end": classification.support_end,
                "days_remaining": classification.days_remaining,
                "review_required": unknown or row.review_required,
                "support_channel": classification.support_channel,
                "lifecycle_evidence": classification.evidence,
            }
        )

    def _scoped_classified(self, scope: Scope) -> tuple[MachineObservation, ...]:
        return tuple(self._classified(row) for row in self._scoped(scope))

    def lifecycle_review(
        self, key: str, scope: Scope
    ) -> dict[str, Any] | None:
        """Return candidates only for a group visible in the effective scope."""
        rows = self._scoped_classified(scope)
        matching = tuple(row for row in rows if group_key(row.os_name, row.os_version) == key)
        if not matching:
            return None
        first = matching[0]
        return self.eol_review.review(first.os_name, first.os_version).to_dict()

    def collection(self, scope: Scope, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        rows = self._scoped_classified(scope)
        grouped: dict[str, list[MachineObservation]] = {}
        for row in rows:
            grouped.setdefault(group_key(row.os_name, row.os_version), []).append(row)
        groups = [
            _make_group(key, items)
            for key, items in sorted(grouped.items(), key=lambda pair: pair[0].casefold())
        ]
        statuses = self.source_status(rows)
        data = {
            "groups": [item.to_dict() for item in groups[offset : offset + limit]],
            "source_status": statuses,
            "observed_at": self.observed_at,
            "query_version": self.query_version,
            "generation_id": self.generation_id,
            "requested_scope": scope.to_dict(),
        }
        return {
            "data": data,
            "total": len(groups),
            "evidence": self._evidence(rows),
            "warnings": _status_warnings(statuses),
        }

    def detail(
        self, key: str, scope: Scope, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any] | None:
        rows = self._scoped_classified(scope)
        matching = tuple(row for row in rows if group_key(row.os_name, row.os_version) == key)
        if not matching:
            return None
        group = _make_group(key, list(matching))
        return {
            "data": {
                "group": group.to_dict(),
                "machines": [row.to_dict() for row in matching[offset : offset + limit]],
                "source_status": self.source_status(rows),
                "observed_at": self.observed_at,
                "query_version": self.query_version,
                "generation_id": self.generation_id,
                "requested_scope": scope.to_dict(),
            },
            "total": len(matching),
            "evidence": self._evidence(matching),
            "warnings": _status_warnings(self.source_status(rows)),
        }

    def _scoped_software(self, scope: Scope) -> tuple[SoftwareObservation, ...]:
        rows = [
            row
            for row in self.snapshot.software_observations
            if scope.matches(
                scope_attributes(
                    {
                        "subscription_id": row.subscription_id,
                        "environment": row.environment,
                        "resource_group": row.resource_group,
                    }
                )
            )
        ]
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    row.software_name.casefold(),
                    row.software_version.casefold(),
                    row.resource_id.casefold(),
                    row.machine_name.casefold(),
                ),
            )
        )

    def software_source_status(
        self, rows: tuple[SoftwareObservation, ...] | None = None
    ) -> dict[str, dict[str, Any]]:
        scoped_rows = rows if rows is not None else self.snapshot.software_observations
        statuses = self.snapshot.software_source_status or (
            InventorySourceStatus(
                source_type="logs",
                state="ready",
                observed_at=self.observed_at,
                query_version=self.query_version,
                row_count=len(self.snapshot.software_observations),
            ),
        )
        return {
            item.source_type: {
                **item.to_dict(),
                "row_count": len(scoped_rows),
            }
            for item in statuses
        }

    def software_collection(
        self, scope: Scope, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        rows = self._scoped_software(scope)
        grouped: dict[str, list[SoftwareObservation]] = {}
        for row in rows:
            grouped.setdefault(f"{row.software_name}|{row.software_version}", []).append(row)
        groups = [
            _make_software_group(key, items)
            for key, items in sorted(grouped.items(), key=lambda pair: pair[0].casefold())
        ]
        statuses = self.software_source_status(rows)
        data = {
            "groups": [item.to_dict() for item in groups[offset : offset + limit]],
            "source_status": statuses,
            "observed_at": self.observed_at,
            "query_version": self.query_version,
            "generation_id": self.generation_id,
            "requested_scope": scope.to_dict(),
        }
        return {
            "data": data,
            "total": len(groups),
            "evidence": self._software_evidence(rows),
            "warnings": _status_warnings(statuses),
        }

    def software_detail(
        self,
        software_name: str,
        software_version: str,
        scope: Scope,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        rows = self._scoped_software(scope)
        key = f"{software_name}|{software_version}"
        matching = tuple(
            row
            for row in rows
            if row.software_name == software_name and row.software_version == software_version
        )
        if not matching:
            return None
        statuses = self.software_source_status(rows)
        return {
            "data": {
                "group": _make_software_group(key, list(matching)).to_dict(),
                "machines": [row.to_dict() for row in matching[offset : offset + limit]],
                "source_status": statuses,
                "observed_at": self.observed_at,
                "query_version": self.query_version,
                "generation_id": self.generation_id,
                "requested_scope": scope.to_dict(),
            },
            "total": len(matching),
            "evidence": self._software_evidence(matching),
            "warnings": _status_warnings(statuses),
        }

    # Explicit alias for consumers that use the grouped-detail terminology.
    software_group_detail = software_detail

    def evidence_for_api(self, rows: tuple[MachineObservation, ...] = ()) -> list[Evidence]:
        return [
            Evidence(
                source_engine="intelligence.inventory.InventoryService",
                source_table="inventory/os_observations",
                timestamp=self.observed_at,
                confidence="high" if rows else "medium",
            )
        ]

    def _evidence(self, rows: tuple[MachineObservation, ...]) -> list[dict[str, str]]:
        return [
            {
                "source_engine": item.source_engine,
                "source_table": item.source_table,
                "timestamp": item.observed_at,
                "subscription_connection": "",
                "resource_id": item.source_id,
                "confidence": "high",
                "freshness": "unknown",
            }
            for item in _unique_evidence(rows)
        ]

    def _software_evidence(
        self, rows: tuple[SoftwareObservation, ...]
    ) -> list[dict[str, str]]:
        return [
            {
                "source_engine": item.get("source_engine", "Azure Monitor Logs"),
                "source_table": item.get("source_table", "ConfigurationData"),
                "timestamp": item.get("observed_at", self.observed_at),
                "subscription_connection": "",
                "resource_id": item.get("source_id", ""),
                "confidence": "high",
                "freshness": "unknown",
            }
            for item in _unique_software_evidence(rows)
        ]


def _scope_row(row: MachineObservation) -> dict[str, str]:
    return {
        "subscription_id": row.subscription_id,
        "environment": row.environment,
        "resource_group": row.resource_group,
    }


def _make_group(key: str, rows: list[MachineObservation]) -> OSGroup:
    ordered = sorted(rows, key=lambda row: (_lifecycle_rank(row.lifecycle_status), row.resource_id))
    selected = ordered[0]
    return OSGroup(
        key=key,
        os_name=selected.os_name,
        os_version=selected.os_version,
        machine_count=len(rows),
        source_types=tuple(sorted({row.source_type for row in rows})),
        lifecycle_status=selected.lifecycle_status,
        support_end=selected.support_end,
        days_remaining=selected.days_remaining,
        review_required=any(row.review_required for row in rows),
        support_channel=selected.support_channel,
        lifecycle_evidence=selected.lifecycle_evidence,
    )


def _make_software_group(key: str, rows: list[SoftwareObservation]) -> SoftwareGroup:
    selected = rows[0]
    source_types = sorted({row.source_type for row in rows if row.source_type})
    if any(row.join_status == "unlinked" for row in rows):
        source_types.append("unlinked")
    return SoftwareGroup(
        key=key,
        software_name=selected.software_name,
        software_version=selected.software_version,
        install_count=len(rows),
        source_types=tuple(source_types),
        linked_count=sum(row.join_status == "linked" for row in rows),
        unlinked_count=sum(row.join_status == "unlinked" for row in rows),
        publishers=tuple(sorted({row.publisher for row in rows if row.publisher})),
    )


def _lifecycle_rank(value: str) -> int:
    return {
        "EOL": 0,
        "Critical": 1,
        "Near EOL": 2,
        "Approaching EOL": 3,
        "Unknown": 4,
        "Supported": 5,
    }.get(value, 4)


def _count_source(rows: tuple[MachineObservation, ...], source_type: str) -> int:
    return sum(row.source_type == source_type for row in rows)


def _status_from_rows(rows: tuple[MachineObservation, ...], source_type: str) -> str:
    source_rows = [row for row in rows if row.source_type == source_type]
    if not source_rows:
        return "ready"
    states = {row.source_status for row in source_rows}
    for state in ("unavailable", "degraded", "stale", "partial", "ready"):
        if state in states:
            return state
    return "ready"


def _latest(rows: tuple[MachineObservation, ...]) -> str:
    return max((row.observed_at for row in rows), default="")


def _latest_software(rows: tuple[SoftwareObservation, ...]) -> str:
    return max((row.observed_at for row in rows), default="")


def _unique_evidence(rows: tuple[MachineObservation, ...]) -> tuple[Any, ...]:
    values: dict[tuple[str, str, str], Any] = {}
    for row in rows:
        for item in row.evidence:
            values[(item.source_engine, item.source_table, item.observed_at)] = item
    return tuple(values.values())


def _unique_software_evidence(rows: tuple[SoftwareObservation, ...]) -> tuple[dict[str, str], ...]:
    values: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        for item in row.evidence:
            source_engine = item.get("source_engine", "Azure Monitor Logs")
            source_table = item.get("source_table", "ConfigurationData")
            observed_at = item.get("observed_at", "")
            values[(source_engine, source_table, observed_at)] = item
    return tuple(values.values())


def _latest_observations(rows: list[MachineObservation]) -> list[MachineObservation]:
    """Keep one current row per exact source/resource identity."""
    selected: dict[tuple[str, str], MachineObservation] = {}
    for row in rows:
        key = (row.source_type, row.resource_id.casefold())
        previous = selected.get(key)
        if previous is None or _observation_time(row.observed_at) >= _observation_time(
            previous.observed_at
        ):
            selected[key] = row
    return sorted(
        selected.values(),
        key=lambda row: (group_key(row.os_name, row.os_version), row.resource_id.casefold()),
    )


def _store_manifest(store: DatasetStore) -> dict[str, Any]:
    """Read generation metadata without making the provider own persistence."""
    generation = store.current_generation()
    if not generation:
        return {}
    path = f"{generation}/manifest.json" if store.is_remote else Path(generation) / "manifest.json"
    try:
        if store.is_remote:
            if not store.fs.exists(path):
                return {}
            with store.fs.open(path, "rt") as handle:
                payload = json.loads(handle.read())
        else:
            manifest_path = Path(path)
            if not manifest_path.exists():
                return {}
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _observation_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


def _status_warnings(statuses: dict[str, dict[str, Any]]) -> list[str]:
    return [
        (
            f"{source} inventory source is {payload['state']}; "
            f"results may be incomplete."
        )
        for source, payload in statuses.items()
        if payload["state"] != "ready"
    ]
