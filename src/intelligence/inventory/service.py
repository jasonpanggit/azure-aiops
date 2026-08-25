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

from .models import (
    SOURCE_STATES,
    InventorySourceStatus,
    MachineObservation,
    OSGroup,
    group_key,
)


@dataclass(frozen=True)
class InventorySnapshot:
    observations: tuple[MachineObservation, ...]
    source_status: tuple[InventorySourceStatus, ...]
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
        observations = tuple(
            row
            if isinstance(row, MachineObservation)
            else MachineObservation.from_mapping(
                row,
                default_status=str(metadata.get("default_source_status") or "ready"),
                query_version=query_version,
            )
            for row in rows
            if isinstance(row, (dict, MachineObservation))
        )
        statuses_payload = metadata.get("source_status") or {}
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
        return cls(
            observations=observations,
            source_status=tuple(statuses),
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
        source: InventorySnapshot | list[dict[str, Any]] | tuple[MachineObservation, ...],
        *,
        catalog: EOLCatalog | None = None,
        now: datetime | None = None,
    ) -> None:
        self.snapshot = (
            source
            if isinstance(source, InventorySnapshot)
            else InventorySnapshot.from_payload(list(source))
        )
        self.catalog = catalog or EOLCatalog.default()
        self.now = now or datetime.now(UTC)

    @classmethod
    def from_fixture(
        cls, path: str | Path, *, catalog: EOLCatalog | None = None
    ) -> InventoryService:
        return cls(InventorySnapshot.from_fixture(path), catalog=catalog)

    @classmethod
    def from_store(
        cls, store: DatasetStore, *, catalog: EOLCatalog | None = None
    ) -> InventoryService | None:
        rows = store.read_dataset("inventory/os_observations")
        if not rows:
            return None
        return cls(rows, catalog=catalog)

    @property
    def observed_at(self) -> str:
        return self.snapshot.observed_at

    @property
    def query_version(self) -> str:
        return self.snapshot.query_version

    @property
    def generation_id(self) -> str:
        return self.snapshot.generation_id

    def source_status(self) -> dict[str, dict[str, Any]]:
        return {
            item.source_type: item.to_dict()
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
        classification = self.catalog.classify_product(
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
            }
        )

    def _scoped_classified(self, scope: Scope) -> tuple[MachineObservation, ...]:
        return tuple(self._classified(row) for row in self._scoped(scope))

    def collection(self, scope: Scope, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        rows = self._scoped_classified(scope)
        grouped: dict[str, list[MachineObservation]] = {}
        for row in rows:
            grouped.setdefault(group_key(row.os_name, row.os_version), []).append(row)
        groups = [
            _make_group(key, items)
            for key, items in sorted(grouped.items(), key=lambda pair: pair[0].casefold())
        ]
        statuses = self.source_status()
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
                "source_status": self.source_status(),
                "observed_at": self.observed_at,
                "query_version": self.query_version,
                "generation_id": self.generation_id,
                "requested_scope": scope.to_dict(),
            },
            "total": len(matching),
            "evidence": self._evidence(matching),
            "warnings": _status_warnings(self.source_status()),
        }

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


def _unique_evidence(rows: tuple[MachineObservation, ...]) -> tuple[Any, ...]:
    values: dict[tuple[str, str, str], Any] = {}
    for row in rows:
        for item in row.evidence:
            values[(item.source_engine, item.source_table, item.observed_at)] = item
    return tuple(values.values())


def _status_warnings(statuses: dict[str, dict[str, Any]]) -> list[str]:
    return [
        (
            f"{source} inventory source is {payload['state']}; "
            f"results may be incomplete."
        )
        for source, payload in statuses.items()
        if payload["state"] != "ready"
    ]
