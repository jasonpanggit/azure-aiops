"""Read-only, scope-first OS inventory projection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from intelligence.lifecycle import EOLCatalog
from storage.datasets import DatasetStore

from .eol_review import EOLReviewService
from .mapping_repository import SoftwareMapping, SoftwareMappingRepository
from .models import (
    InventorySourceStatus,
    MachineObservation,
    OSGroup,
    ResourceObservation,
    SoftwareGroup,
    SoftwareObservation,
    group_key,
)
from .software_normalization import (
    mapping_for_observation,
    project_mapping,
)


@dataclass(frozen=True)
class InventorySnapshot:
    observations: tuple[MachineObservation, ...]
    source_status: tuple[InventorySourceStatus, ...]
    software_observations: tuple[SoftwareObservation, ...] = ()
    software_source_status: tuple[InventorySourceStatus, ...] = ()
    resource_observations: tuple[ResourceObservation, ...] = ()
    observed_at: str = ""
    query_version: str = "inventory-os-v1"
    generation_id: str = ""
    software_mapping_suggestions: tuple[dict[str, Any], ...] = ()

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
        suggestions_payload = (
            metadata.get("software_mapping_suggestions")
            or metadata.get("mapping_suggestions")
            or []
        )
        if not isinstance(suggestions_payload, list):
            raise TypeError("Inventory mapping suggestions must be a list")
        resource_rows = metadata.get("resource_observations") or []
        if not isinstance(resource_rows, list):
            raise TypeError("Inventory resource observations must be a list")
        resource_observations = tuple(
            row
            if isinstance(row, ResourceObservation)
            else ResourceObservation.from_fabric_row(row)
            for row in resource_rows
            if isinstance(row, (dict, ResourceObservation))
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
            resource_observations=resource_observations,
            observed_at=str(metadata.get("observed_at") or _latest(observations)),
            query_version=query_version,
            generation_id=str(metadata.get("generation_id") or metadata.get("run_id") or ""),
            software_mapping_suggestions=tuple(
                dict(item) for item in suggestions_payload if isinstance(item, dict)
            ),
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
        mapping_repository: SoftwareMappingRepository | None = None,
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
        self.mapping_repository = mapping_repository or SoftwareMappingRepository()
        self._persist_mapping_suggestions()

    @classmethod
    def from_fixture(
        cls,
        path: str | Path,
        *,
        catalog: EOLCatalog | None = None,
        eol_review: EOLReviewService | None = None,
        mapping_repository: SoftwareMappingRepository | None = None,
    ) -> InventoryService:
        return cls(
            InventorySnapshot.from_fixture(path),
            catalog=catalog,
            eol_review=eol_review,
            mapping_repository=mapping_repository,
        )

    @classmethod
    def from_store(
        cls,
        store: DatasetStore,
        *,
        catalog: EOLCatalog | None = None,
        eol_review: EOLReviewService | None = None,
        mapping_repository: SoftwareMappingRepository | None = None,
    ) -> InventoryService | None:
        rows = store.read_dataset("inventory/os_observations")
        status_rows = store.read_dataset("inventory/source_status")
        software_rows = store.read_dataset("inventory/software_observations")
        software_status_rows = store.read_dataset("inventory/software_source_status")
        resource_rows = store.read_dataset("inventory/resource_observations")
        if not resource_rows:
            resource_rows = store.read_dataset("inventory_resource_observations")
        if not rows and not status_rows and not software_rows and not software_status_rows and not resource_rows:
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
            "resource_observations": resource_rows,
            "observed_at": str(manifest.get("startedAt") or ""),
            "query_version": str(manifest.get("queryVersion") or "inventory-os-v1"),
            "generation_id": str(manifest.get("runId") or ""),
        }
        return cls(
            InventorySnapshot.from_payload(metadata),
            catalog=catalog,
            eol_review=eol_review,
            mapping_repository=mapping_repository,
        )

    def family_availability(self, *, registry=None) -> dict[str, dict[str, Any]]:
        from .registry import default_inventory_registry

        registry = registry or default_inventory_registry()
        os_state = "ready" if self.snapshot.observations or self.snapshot.source_status else "unavailable"
        software_status = self.software_source_status()
        software_state = (
            next(iter(software_status.values())).get("state")
            if software_status
            else "unavailable"
        )
        base = {
            "os": {
                "family": "os",
                "state": os_state,
                "row_count": len(self.snapshot.observations),
                "logical_dataset": "inventory/os_observations",
            },
            "software": {
                "family": "software",
                "state": software_state,
                "row_count": len(self.snapshot.software_observations),
                "logical_dataset": "inventory/software_observations",
            },
            "paas": {
                "family": "paas",
                "state": "ready" if self.snapshot.resource_observations else "unavailable",
                "row_count": len(self.snapshot.resource_observations),
                "logical_dataset": "inventory/resource_observations",
            },
        }
        return {
            family.family: base.get(
                family.family,
                {
                    "family": family.family,
                    "state": "unavailable",
                    "row_count": 0,
                    "logical_dataset": family.logical_dataset,
                },
            )
            for family in registry.families
        }

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
        from api.scope import scope_attributes

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
        from api.scope import scope_attributes

        rows: list[SoftwareObservation] = []
        for raw_row in self.snapshot.software_observations:
            mapping = mapping_for_observation(raw_row, self.mapping_repository)
            if mapping is not None:
                if mapping.status != "approved":
                    # Suggestions and rejections stay in the review API, not
                    # aggregate counts.
                    continue
                row = project_mapping(raw_row, mapping)
            else:
                row = raw_row
            if scope.matches(
                scope_attributes(
                    {
                        "subscription_id": row.subscription_id,
                        "environment": row.environment,
                        "resource_group": row.resource_group,
                    }
                )
            ):
                rows.append(row)
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

    def _visible_mappings(self, scope: Scope) -> tuple[SoftwareMapping, ...]:
        from .software_normalization import scopes_overlap

        return tuple(
            sorted(
                (
                    item
                    for item in self.mapping_repository.read().mappings
                    if scopes_overlap(scope, _scope_from_mapping(item.scope_predicate))
                ),
                key=lambda item: (item.status, item.raw_name.casefold(), item.mapping_id),
            )
        )

    def mapping_collection(
        self, scope: Scope, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        snapshot = self.mapping_repository.read()
        mappings = self._visible_mappings(scope)
        warnings = [
            "One or more mapping suggestions failed validation."
            for item in mappings
            if item.provenance.get("validation_error")
        ]
        return {
            "data": {
                "mappings": [item.to_dict() for item in mappings[offset : offset + limit]],
                "repository_revision": snapshot.repository_revision,
                "requested_scope": scope.to_dict(),
            },
            "total": len(mappings),
            "warnings": list(dict.fromkeys(warnings)),
        }

    def mapping_detail(self, mapping_id: str, scope: Scope) -> dict[str, Any] | None:
        item = next(
            (candidate for candidate in self._visible_mappings(scope)
             if candidate.mapping_id == mapping_id),
            None,
        )
        if item is None:
            return None
        return {
            "data": {"mapping": item.to_dict(), "requested_scope": scope.to_dict()},
            "total": 1,
            "warnings": (
                ["Mapping suggestion failed validation."]
                if item.provenance.get("validation_error")
                else []
            ),
        }

    def _persist_mapping_suggestions(self) -> None:
        from .software_normalization import suggestion_from_model_output

        for suggestion in self.snapshot.software_mapping_suggestions:
            try:
                suggestion_from_model_output(
                    repository=self.mapping_repository,
                    raw_name=str(
                        suggestion.get("raw_name")
                        or suggestion.get("software_name")
                        or ""
                    ),
                    raw_version=str(
                        suggestion.get("raw_version")
                        or suggestion.get("software_version")
                        or ""
                    ),
                    publisher=str(suggestion.get("publisher") or ""),
                    model_output=(
                        suggestion.get("model_output")
                        if isinstance(suggestion.get("model_output"), dict)
                        else suggestion
                    ),
                    source_timestamp=str(
                        suggestion.get("source_timestamp")
                        or suggestion.get("observed_at")
                        or self.observed_at
                    ),
                    scope_predicate=suggestion.get("scope_predicate"),
                )
            except (TypeError, ValueError):
                # Provider malformation cannot make an otherwise usable
                # inventory snapshot unavailable.
                continue

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

    def paas_collection(self, scope: Scope, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        rows = self._scoped_resources(scope, family="paas")
        grouped: dict[str, list[ResourceObservation]] = {}
        for row in rows:
            grouped.setdefault(resource_group_key(row), []).append(row)
        groups = [
            {
                "key": key,
                "resource_type": items[0].resource_type,
                "sku": items[0].sku,
                "tier": items[0].tier,
                "resource_count": len(items),
            }
            for key, items in sorted(grouped.items(), key=lambda pair: pair[0].casefold())
        ]
        data = {
            "groups": groups[offset : offset + limit],
            "source_status": {"paas": self.family_availability()["paas"]},
            "observed_at": self.observed_at,
            "query_version": self.query_version,
            "generation_id": self.generation_id,
            "requested_scope": scope.to_dict(),
        }
        return {
            "data": data,
            "total": len(groups),
            "evidence": self._resource_evidence(rows),
            "warnings": _status_warnings(data["source_status"]),
        }

    def paas_detail(
        self, key: str, scope: Scope, *, offset: int = 0, limit: int = 100
    ) -> dict[str, Any] | None:
        rows = self._scoped_resources(scope, family="paas")
        matching = tuple(row for row in rows if resource_group_key(row) == key)
        if not matching:
            return None
        return {
            "data": {
                "group": {
                    "key": key,
                    "resource_type": matching[0].resource_type,
                    "sku": matching[0].sku,
                    "tier": matching[0].tier,
                    "resource_count": len(matching),
                },
                "resources": [row.to_api_dict() for row in matching[offset : offset + limit]],
                "source_status": {"paas": self.family_availability()["paas"]},
                "observed_at": self.observed_at,
                "query_version": self.query_version,
                "generation_id": self.generation_id,
                "requested_scope": scope.to_dict(),
            },
            "total": len(matching),
            "evidence": self._resource_evidence(matching),
            "warnings": _status_warnings({"paas": self.family_availability()["paas"]}),
        }

    def resources(self, scope: Scope, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        rows = [
            {
                "family": "os",
                "resource_id": row.resource_id,
                "resource_name": row.machine_name,
                "resource_type": (
                    "microsoft.hybridcompute/machines"
                    if row.source_type == "arc"
                    else "microsoft.compute/virtualmachines"
                ),
                "subscription_id": row.subscription_id,
                "resource_group": row.resource_group,
                "environment": row.environment,
            }
            for row in self._scoped(scope)
        ]
        rows.extend(row.to_api_dict() for row in self._scoped_resources(scope))
        rows.sort(key=lambda row: (row["family"], row["resource_id"]))
        return {
            "data": {
                "resources": rows[offset : offset + limit],
                "family_availability": self.family_availability(),
                "requested_scope": scope.to_dict(),
                "query_version": self.query_version,
            },
            "total": len(rows),
            "evidence": self._resource_evidence(self._scoped_resources(scope)),
            "warnings": _status_warnings(self.family_availability()),
        }

    def narrative_aggregates(
        self,
        scope: Scope,
        *,
        max_os_groups: int = 12,
        max_software_groups: int = 12,
    ) -> dict[str, Any]:
        """Return bounded, scope-filtered aggregates for optional narration.

        This deliberately exposes groups and source metadata, never the machine
        or installation rows used to calculate them.  The narrative layer can
        therefore send a small, already-authorized fact set to an external model
        without creating a second retrieval path.
        """
        os_rows = self._scoped_classified(scope)
        software_rows = self._scoped_software(scope)
        os_grouped: dict[str, list[MachineObservation]] = {}
        for row in os_rows:
            os_grouped.setdefault(group_key(row.os_name, row.os_version), []).append(row)
        os_groups = [
            _make_group(key, items)
            for key, items in os_grouped.items()
        ]
        software_grouped: dict[str, list[SoftwareObservation]] = {}
        for row in software_rows:
            software_grouped.setdefault(
                f"{row.software_name}|{row.software_version}", []
            ).append(row)
        software_groups = [
            _make_software_group(key, items)
            for key, items in software_grouped.items()
        ]
        os_groups.sort(key=lambda item: (-item.machine_count, item.key.casefold()))
        software_groups.sort(
            key=lambda item: (-item.install_count, item.key.casefold())
        )
        os_limit = max(0, min(int(max_os_groups), 50))
        software_limit = max(0, min(int(max_software_groups), 50))
        os_status = self.source_status(os_rows)
        software_status = self.software_source_status(software_rows)
        paas_rows = self._scoped_resources(scope, family="paas")
        return {
            "os_groups": [item.to_dict() for item in os_groups[:os_limit]],
            "software_groups": [
                item.to_dict() for item in software_groups[:software_limit]
            ],
            "os_machine_count": len(os_rows),
            "software_install_count": len(software_rows),
            "paas_resource_count": len(paas_rows),
            "source_status": {**os_status, **software_status},
            "evidence": [
                *self._evidence(os_rows),
                *self._software_evidence(software_rows),
                *self._resource_evidence(paas_rows),
            ],
        }

    def evidence_for_api(self, rows: tuple[MachineObservation, ...] = ()) -> list[Evidence]:
        from api.evidence import Evidence

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

    def _scoped_resources(
        self, scope: Scope, *, family: str | None = None
    ) -> tuple[ResourceObservation, ...]:
        from api.scope import scope_attributes

        rows = [
            row
            for row in self.snapshot.resource_observations
            if (family is None or row.family == family)
            and scope.matches(
                scope_attributes(
                    {
                        "subscription_id": row.subscription_id,
                        "resource_group": row.resource_group,
                    }
                )
            )
        ]
        return tuple(sorted(rows, key=lambda row: row.resource_id.casefold()))

    def _resource_evidence(
        self, rows: tuple[ResourceObservation, ...]
    ) -> list[dict[str, str]]:
        return [
            {
                "source_engine": item.source_type or "arg",
                "source_table": "inventory/resource_observations",
                "timestamp": item.observed_at,
                "subscription_connection": "",
                "resource_id": item.resource_id,
                "confidence": "high",
                "freshness": "unknown",
            }
            for item in rows
        ]


def _scope_row(row: MachineObservation) -> dict[str, str]:
    return {
        "subscription_id": row.subscription_id,
        "environment": row.environment,
        "resource_group": row.resource_group,
    }


def _scope_from_mapping(values: dict[str, Any]):
    from api.scope import Scope

    return Scope.from_mapping(values)


def resource_group_key(row: ResourceObservation) -> str:
    resource_type = row.resource_type.replace("/", ":")
    return f"{resource_type}|{row.sku or 'Unknown'}|{row.tier or 'Unknown'}"


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
