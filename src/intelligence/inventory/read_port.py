from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from .service import InventoryService


@dataclass(frozen=True)
class InventoryReadPort:
    """Scope-required internal read port for Fabric-backed inventory consumers."""

    service: InventoryService

    def list_resources(
        self,
        scope: Any,
        *,
        family: str | None = None,
        resource_type: str | None = None,
        query: str | None = None,
        resource_group: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        _require_scope(scope)
        result = self.service.resources(scope, offset=0, limit=None)
        rows = list(result["data"]["resources"])
        facets = {
            key: [
                {"value": value, "count": count}
                for value, count in sorted(
                    Counter(str(row.get(key) or "") for row in rows).items()
                )
                if value
            ]
            for key in ("family", "resource_type", "resource_group")
        }
        represented_count = len(rows)
        if family:
            rows = [row for row in rows if row.get("family") == family]
        if resource_type:
            wanted = resource_type.casefold()
            rows = [
                row
                for row in rows
                if str(row.get("resource_type") or "").casefold() == wanted
            ]
        if resource_group:
            rows = [
                row for row in rows
                if str(row.get("resource_group") or "").casefold() == resource_group.casefold()
            ]
        if query:
            wanted_query = query.casefold()
            rows = [
                row for row in rows
                if any(
                    wanted_query in str(row.get(key) or "").casefold()
                    for key in ("resource_name", "resource_id", "resource_type")
                )
            ]
        grouped_result = (
            self.service.collection(scope, offset=0, limit=10_000)
            if family == "os"
            else self.service.software_collection(scope, offset=0, limit=10_000)
            if family == "software"
            else self.service.paas_collection(scope, offset=0, limit=10_000)
            if family == "paas"
            else None
        )
        groups = (
            list(grouped_result["data"]["groups"])
            if grouped_result is not None
            else []
        )
        if resource_type:
            groups = [
                group
                for group in groups
                if str(group.get("resource_type") or "").casefold() == wanted
            ]
        rows.sort(key=lambda row: (str(row.get("family") or ""), str(row.get("resource_id") or "")))
        return {
            "resources": rows[offset : offset + limit],
            "total": len(rows),
            "groups": groups,
            "group_total": (
                len(groups) if grouped_result is not None else None
            ),
            "family_availability": result["data"]["family_availability"],
            "observed_at": self.service.observed_at,
            "query_version": self.service.query_version,
            "warnings": result["warnings"],
            "facets": facets,
            "represented_count": represented_count,
        }

    def get_resource(self, scope: Any, resource_id: str) -> dict[str, Any] | None:
        """Resolve an exact authorized identity without a page-size cutoff."""
        _require_scope(scope)
        wanted = str(resource_id or "").casefold()
        if not wanted:
            return None
        for row in self.service.resources(scope, limit=None)["data"]["resources"]:
            if str(row.get("resource_id") or "").casefold() == wanted:
                resolved = dict(row)
                resolved["containment"] = self._containment_for(row)
                return resolved
        return None

    def list_containment(self, scope: Any) -> list[dict[str, Any]]:
        """Return management-group/subscription/resource-group rows derived
        in-process from existing observation data (no separate ResourceContainers
        acquisition path — ROADMAP success criterion 2)."""
        _require_scope(scope)
        rows = self.service.resources(scope, limit=None)["data"]["resources"]
        containment: dict[str, dict[str, Any]] = {}
        for row in rows:
            subscription_id = str(row.get("subscription_id") or "").strip()
            resource_group = str(row.get("resource_group") or "").strip()
            if not subscription_id:
                continue
            subscription_key = f"/subscriptions/{subscription_id}".casefold()
            if subscription_key not in containment:
                containment[subscription_key] = {
                    "id": subscription_key,
                    "kind": "subscription",
                    "parent_id": None,
                    "subscription_id": subscription_id,
                }
            if resource_group:
                rg_key = f"{subscription_key}/resourcegroups/{resource_group}".casefold()
                if rg_key not in containment:
                    containment[rg_key] = {
                        "id": rg_key,
                        "kind": "resource_group",
                        "parent_id": subscription_key,
                        "subscription_id": subscription_id,
                        "resource_group": resource_group,
                    }
        return sorted(containment.values(), key=lambda item: item["id"])

    def _containment_for(self, row: dict[str, Any]) -> dict[str, Any]:
        subscription_id = str(row.get("subscription_id") or "").strip()
        resource_group = str(row.get("resource_group") or "").strip()
        subscription_key = f"/subscriptions/{subscription_id}".casefold() if subscription_id else ""
        resource_group_key = (
            f"{subscription_key}/resourcegroups/{resource_group}".casefold()
            if subscription_key and resource_group
            else ""
        )
        return {
            # Management group ancestry is not yet carried on ResourceObservation
            # rows (Phase 7 scope); left None until a management-group-aware
            # ingestion source populates it. Absent, not fabricated.
            "management_group_id": None,
            "subscription_id": subscription_key or None,
            "resource_group_id": resource_group_key or None,
        }


def _require_scope(scope: Any) -> None:
    if scope is None or not hasattr(scope, "matches") or not hasattr(scope, "to_dict"):
        raise TypeError("InventoryReadPort requires a server-derived effective scope")


__all__ = ["InventoryReadPort"]
