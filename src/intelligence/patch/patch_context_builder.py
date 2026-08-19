from __future__ import annotations

from typing import Any

from intelligence.lifecycle.lifecycle_context_builder import (
    canonical_resource_key,
    public_subscription_label,
)


class PatchContextBuilder:
    """Builds bounded public context from semantic resource projections."""

    def __init__(self, resources: list[dict[str, Any]], *, max_resources: int = 5000) -> None:
        if isinstance(max_resources, bool) or not isinstance(max_resources, int) or max_resources < 1:
            raise ValueError("max_resources must be positive")
        if not isinstance(resources, list) or any(not isinstance(row, dict) for row in resources):
            raise TypeError("Patch resources must be a list of mappings")
        if len(resources) > max_resources:
            raise ValueError("Patch semantic snapshot exceeds the configured resource bound")
        self._resources: dict[str, dict[str, Any]] = {}
        self._keys_by_name: dict[str, list[str]] = {}
        for row in resources:
            name = str(row.get("name") or "").strip()
            if not name:
                raise ValueError("Patch resources require name and canonical identity")
            public = self._public(row)
            key = self._identity(row)
            if key in self._resources:
                raise ValueError("Duplicate canonical resource identity in patch snapshot")
            public["_resource_key"] = key
            self._resources[key] = public
            self._keys_by_name.setdefault(name.casefold(), []).append(key)

    def build(self, resource: str) -> dict[str, Any]:
        key = self.key_for({"resource": resource})
        return dict(self._resources[key])

    def all(self) -> list[dict[str, Any]]:
        return [dict(self._resources[key]) for key in sorted(self._resources)]

    def key_for(self, evidence: dict[str, Any]) -> str:
        explicit = canonical_resource_key(
            evidence.get("resource_key") or evidence.get("resource_id")
        )
        if explicit:
            if explicit not in self._resources:
                raise LookupError("Patch evidence references an unknown canonical resource")
            return explicit
        name = str(evidence.get("resource") or "").casefold()
        keys = self._keys_by_name.get(name, [])
        if not keys:
            raise LookupError("Patch evidence references an unknown resource name")
        if len(keys) != 1:
            raise ValueError(
                "Patch evidence has an ambiguous resource name; canonical resource identity is required"
            )
        return keys[0]

    @staticmethod
    def _identity(row: dict[str, Any]) -> str:
        explicit = canonical_resource_key(
            row.get("resource_key") or row.get("resource_id")
        )
        if explicit:
            return explicit
        return "|".join(
            (
                str(row.get("subscription") or "Unknown").casefold(),
                str(row.get("entity_type") or "Resource").casefold(),
                str(row.get("name") or "").casefold(),
            )
        )

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        application = str(row.get("application") or "Unknown")
        business_service = str(row.get("business_service") or "Unknown")
        blast_radius = row.get("blast_radius")
        ownership = row.get("ownership_coverage", False)
        if not isinstance(ownership, bool):
            raise TypeError("Patch ownership_coverage must be boolean")
        if not isinstance(blast_radius, dict):
            blast_radius = {
                "resource_count": 1,
                "application_count": int(application != "Unknown"),
                "business_service_count": int(business_service != "Unknown"),
                "service_count": 0,
            }
        blast_counts = {}
        for key in (
            "resource_count",
            "application_count",
            "business_service_count",
            "service_count",
        ):
            value = blast_radius.get(key)
            if value is None:
                value = 0
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"Patch blast radius {key} must be a non-negative integer")
            blast_counts[key] = value
        return {
            "resource": {
                "name": str(row.get("name") or ""),
                "entity_type": str(row.get("entity_type") or "Resource"),
            },
            "subscription": public_subscription_label(row.get("subscription")),
            "application": application,
            "business_service": business_service,
            "owner": str(row.get("owner") or "Unknown"),
            "support_team": str(row.get("support_team") or "Unknown"),
            "environment": str(row.get("environment") or "Unknown"),
            "business_criticality": str(row.get("business_criticality") or "Unknown"),
            "application_impact": str(row.get("application_impact") or "Unknown"),
            "ownership_coverage": ownership,
            "blast_radius": blast_counts,
        }
