from __future__ import annotations

from typing import Any
from urllib.parse import unquote


class IncidentContextBuilder:
    """Bounded operational context keyed by canonical resource identity."""

    def __init__(
        self,
        resources: list[dict[str, Any]],
        *,
        max_resources: int = 5000,
        max_collection_items: int = 50,
        max_string_length: int = 512,
    ) -> None:
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (max_resources, max_collection_items, max_string_length)
            )
            or max_resources < 1
            or max_collection_items < 1
            or max_string_length < 16
            or len(resources) > max_resources
        ):
            raise ValueError("Incident resource snapshot exceeds configured bound")
        self.max_collection_items = max_collection_items
        self.max_string_length = max_string_length
        self._resources: dict[str, dict[str, Any]] = {}
        for source in resources:
            row = dict(source)
            key = self.canonical_key(row.get("resource_key"))
            if not key:
                raise ValueError("Incident resources require canonical resource_key")
            if key in self._resources:
                raise ValueError("Duplicate incident resource identity")
            self._resources[key] = self._public(row, key)

    def get(self, resource_key: str) -> dict[str, Any]:
        key = self.canonical_key(resource_key)
        return dict(self._resources.get(key) or self._unknown(key))

    def _public(self, row: dict[str, Any], key: str) -> dict[str, Any]:
        collection_names = (
            "impacted_applications",
            "impacted_services",
            "impacted_business_services",
            "upstream_dependencies",
            "downstream_dependents",
            "business_functions",
        )
        for name in collection_names:
            value = row.get(name, [])
            if not isinstance(value, list) or any(
                not isinstance(item, (str, int, float, bool, type(None)))
                for item in value
            ):
                raise TypeError(f"Incident context collection {name} must be a list of scalars")
        collections = {
            name: sorted({self._bounded_text(x) for x in row.get(name, []) if x})
            for name in collection_names
        }
        truncated = any(
            len(values) > self.max_collection_items for values in collections.values()
        ) or any(
            len(str(value)) > self.max_string_length
            for name in collections
            for value in row.get(name, [])
        ) or any(
            len(str(row.get(name) or "")) > self.max_string_length
            for name in (
                "name",
                "entity_type",
                "application",
                "business_service",
                "owner",
                "support_team",
                "environment",
                "business_criticality",
            )
        )
        return {
            "_resource_key": key,
            "resource": {
                "name": self._bounded_text(row.get("name") or "Unknown"),
                "entity_type": self._bounded_text(
                    row.get("entity_type") or "Resource"
                ),
            },
            "application": self._bounded_text(row.get("application") or "Unknown"),
            "business_service": self._bounded_text(
                row.get("business_service") or "Unknown"
            ),
            "owner": self._bounded_text(row.get("owner") or "Unknown"),
            "support_team": self._bounded_text(
                row.get("support_team") or "Unknown"
            ),
            "environment": self._bounded_text(row.get("environment") or "Unknown"),
            "business_criticality": self._bounded_text(
                row.get("business_criticality") or "Unknown"
            ),
            "subscription_alias": self._bounded_text(
                row.get("subscription_alias") or "Unknown"
            ),
            "patch_score": self._optional_score(row.get("patch_score")),
            "lifecycle_score": self._optional_score(row.get("lifecycle_score")),
            "risk_score": self._optional_score(row.get("risk_score")),
            **{
                name: values[: self.max_collection_items]
                for name, values in collections.items()
            },
            "context_truncated": truncated,
        }

    def _unknown(self, key: str) -> dict[str, Any]:
        return self._public({"name": "Unknown", "entity_type": "Resource"}, key)

    @staticmethod
    def canonical_key(value: Any) -> str:
        key = str(value or "").strip()
        while True:
            decoded = unquote(key)
            if decoded == key:
                break
            key = decoded
        return key.rstrip("/").casefold()

    def _bounded_text(self, value: Any) -> str:
        text = str(value or "")
        if len(text) <= self.max_string_length:
            return text
        return text[: self.max_string_length - 12] + "…[truncated]"

    @staticmethod
    def _optional_score(value):
        if value is None:
            return None
        if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=100:
            raise ValueError("Incident context scores must be integers from 0 to 100")
        return value
