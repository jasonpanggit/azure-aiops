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
