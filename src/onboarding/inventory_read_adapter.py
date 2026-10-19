"""Pure translation layer: InventoryReadPort output -> Normalizer input rows.

This adapter is additive only (Phase 8 D-08): it does not remove or modify
`queries.py`'s existing ARG specs. It exists to prove that AIOps's existing
normalizers (`normalize.py`, `network_normalize.py`) can be fed identity data
sourced from the inventory read port instead of a direct ARG query, producing
byte-identical `NormalizedGraph` output (ROADMAP success criterion 3).

The translation must not re-derive or drop any nested property: the full
`provider_payload` (Phase 7 D-08) is passed through unchanged as the row's
``properties`` field, exactly as ``Normalizer.normalize()`` already expects
from a raw ARG ``resources``/``resource_containers`` payload
(`queries.py` projection: id, name, type, tenantId, subscriptionId,
resourceGroup, location, tags, properties).
"""

from __future__ import annotations

from typing import Any


class InventoryReadAdapter:
    """Translates `InventoryReadPort` containment/resource rows back into the
    exact `resources`/`resource_containers` row shape `Normalizer.normalize()`
    already consumes."""

    @staticmethod
    def to_arg_rows(
        containment_rows: list[dict[str, Any]],
        resource_rows: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "resource_containers": _containment_to_arg_rows(containment_rows),
            "resources": _resources_to_arg_rows(resource_rows),
        }

    @staticmethod
    def from_output_dir(output_dir: str) -> InventoryReadAdapter:
        """Compatibility factory for the legacy local query seam.

        The adapter owns the old graph-shaped storage translation. Consumers
        still receive an InventoryReadPort and never open a dataset themselves.
        When only a legacy graph exists, reads enforce scope on its stored
        attributes before projecting identity; missing constrained attributes
        do not match.
        """
        from intelligence.inventory.service import InventoryService
        from storage.datasets import DatasetStore

        service = InventoryService.from_store(DatasetStore(output_dir))
        if service is not None:
            from intelligence.inventory.read_port import InventoryReadPort

            return InventoryReadAdapter(InventoryReadPort(service), output_dir)
        return InventoryReadAdapter(None, output_dir, legacy=True)

    def __init__(
        self,
        port: Any | None = None,
        output_dir: str | None = None,
        legacy: bool = False,
    ) -> None:
        self.port = port
        self.output_dir = output_dir
        self.legacy = legacy

    def resources(self, scope: Any) -> list[dict[str, Any]]:
        """Return identity rows restricted to the caller's effective scope."""
        from api.scope import scope_attributes

        if scope is None or not hasattr(scope, "matches") or not hasattr(scope, "to_dict"):
            raise TypeError("InventoryReadAdapter requires a server-derived effective scope")
        if self.port is None:
            if not self.legacy or not self.output_dir:
                return []
            rows = self._legacy_rows("VirtualMachine") + self._legacy_rows("ArcServer")
            return [
                {
                    "family": "os",
                    "resource_id": row.get("id"),
                    "resource_name": row.get("name"),
                    "resource_type": row.get("resourceType") or row.get("type"),
                    "subscription_id": row.get("subscriptionId"),
                    "resource_group": row.get("resourceGroup"),
                    "environment": row.get("environment", ""),
                    "source_type": "arc" if "hybridcompute" in str(row.get("resourceType") or row.get("type", "")).casefold() else "azure_vm",
                    "os_name": row.get("osName", ""),
                    "os_version": row.get("osVersion", ""),
                    "observed_at": row.get("lastObservedTimestamp", ""),
                }
                for row in rows
                if scope.matches(scope_attributes(row))
            ]
        return list(self.port.list_resources(scope, limit=10_000)["resources"])

    def patch_assessments(self) -> list[dict[str, Any]]:
        """Read patch-domain rows for the compatibility query projection.

        Patch assessments are deliberately not exposed by InventoryReadPort:
        they are joined to identity rows by resource ID in the consumer.
        """
        if not self.output_dir:
            return []
        return self._legacy_rows("PatchAssessment")

    def recommendations(self) -> list[dict[str, Any]]:
        if not self.output_dir:
            return []
        return self._legacy_rows("AdvisorRecommendation")

    def _legacy_rows(self, entity: str) -> list[dict[str, Any]]:
        """Read only the compatibility graph projection with path checks."""
        import json
        from pathlib import Path

        root = Path(self.output_dir).expanduser().resolve()
        current = root / "current"
        resolved_root = current.resolve(strict=True)
        try:
            resolved_root.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"Current dataset pointer resolves outside configured data root: {current}"
            ) from exc
        path = (current / "entities" / entity).with_suffix(".jsonl")
        if not path.exists():
            return []
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"Dataset path resolves outside configured data root: {path}") from exc
        if not resolved.is_file():
            raise ValueError(f"Dataset path is not a regular file: {path}")
        return [json.loads(line) for line in resolved.read_text().splitlines() if line.strip()]


def _containment_to_arg_rows(containment_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in containment_rows:
        kind = row.get("kind")
        subscription_id = str(row.get("subscription_id") or "")
        if kind == "subscription":
            rows.append(
                {
                    "id": f"/subscriptions/{subscription_id}",
                    "name": subscription_id,
                    "type": "microsoft.resources/subscriptions",
                    "tenantId": "",
                    "subscriptionId": subscription_id,
                    "resourceGroup": "",
                    "location": "",
                    "tags": {},
                    "properties": {},
                }
            )
        elif kind == "resource_group":
            resource_group = str(row.get("resource_group") or "")
            rows.append(
                {
                    "id": f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}",
                    "name": resource_group,
                    "type": "microsoft.resources/subscriptions/resourcegroups",
                    "tenantId": "",
                    "subscriptionId": subscription_id,
                    "resourceGroup": resource_group,
                    "location": "",
                    "tags": {},
                    "properties": {},
                }
            )
    return rows


def _resources_to_arg_rows(resource_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in resource_rows:
        rows.append(
            {
                "id": row.get("resource_id") or "",
                "name": row.get("resource_name") or "",
                "type": row.get("resource_type") or "",
                "tenantId": row.get("tenant_id") or "",
                "subscriptionId": row.get("subscription_id") or "",
                "resourceGroup": row.get("resource_group") or "",
                "location": row.get("location") or "",
                "tags": row.get("tags") or {},
                # Full raw provider payload, passed through unchanged. This is
                # the lossless-properties proof (Pitfall 1 / INV-11): nothing
                # nested (delegations, serviceEndpoints, etc.) is re-derived
                # or dropped en route.
                "properties": row.get("properties") or {},
            }
        )
    return rows


__all__ = ["InventoryReadAdapter"]
