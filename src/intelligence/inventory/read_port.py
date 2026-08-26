from __future__ import annotations

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
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        _require_scope(scope)
        result = self.service.resources(scope, offset=0, limit=10_000)
        rows = list(result["data"]["resources"])
        if family:
            rows = [row for row in rows if row.get("family") == family]
        if resource_type:
            wanted = resource_type.casefold()
            rows = [
                row
                for row in rows
                if str(row.get("resource_type") or "").casefold() == wanted
            ]
        rows.sort(key=lambda row: (str(row.get("family") or ""), str(row.get("resource_id") or "")))
        return {
            "resources": rows[offset : offset + limit],
            "total": len(rows),
            "family_availability": result["data"]["family_availability"],
            "warnings": result["warnings"],
        }

    def get_resource(self, scope: Any, resource_id: str) -> dict[str, Any] | None:
        _require_scope(scope)
        wanted = str(resource_id or "").casefold()
        if not wanted:
            return None
        for row in self.list_resources(scope, limit=10_000)["resources"]:
            if str(row.get("resource_id") or "").casefold() == wanted:
                return row
        return None


def _require_scope(scope: Any) -> None:
    if scope is None or not hasattr(scope, "matches") or not hasattr(scope, "to_dict"):
        raise TypeError("InventoryReadPort requires a server-derived effective scope")


__all__ = ["InventoryReadPort"]
