from __future__ import annotations

from typing import Any
from urllib.parse import unquote


class ChangeContextBuilder:
    def __init__(self, resources: list[dict[str, Any]], *, max_resources: int = 5000) -> None:
        if max_resources < 1 or len(resources) > max_resources:
            raise ValueError("Change resource snapshot exceeds configured bound")
        self._resources = {}
        for source in resources:
            row = dict(source)
            key = self.canonical_key(row.get("resource_key"))
            if not key:
                raise ValueError("Change resource requires canonical resource_key")
            if key in self._resources:
                raise ValueError("Duplicate change resource identity")
            for field in ("expected_configuration", "observed_configuration"):
                if field in row and not isinstance(row[field], dict):
                    raise TypeError(f"{field} must be a mapping")
            dependency_count = row.get("dependency_count", 0)
            if isinstance(dependency_count, bool) or not isinstance(
                dependency_count, int
            ):
                raise TypeError("dependency_count must be an integer")
            if dependency_count < 0:
                raise ValueError("dependency_count must be nonnegative")
            historical_count = row.get("historical_correlation_count", 0)
            if isinstance(historical_count, bool) or not isinstance(
                historical_count, int
            ):
                raise TypeError("historical_correlation_count must be an integer")
            if historical_count < 0:
                raise ValueError("historical_correlation_count must be nonnegative")
            self._resources[key] = {
                "_resource_key": key,
                "resource": {"name": str(row.get("name") or "Unknown")[:512], "entity_type": str(row.get("entity_type") or "Resource")[:128]},
                "application": str(row.get("application") or "Unknown")[:512],
                "business_service": str(row.get("business_service") or "Unknown")[:512],
                "owner": str(row.get("owner") or "Unknown")[:512],
                "support_team": str(row.get("support_team") or "Unknown")[:512],
                "environment": str(row.get("environment") or "Unknown")[:128],
                "business_criticality": str(row.get("business_criticality") or "Unknown")[:128],
                "dependency_count": dependency_count,
                "historical_correlation_count": historical_count,
                "expected_configuration": dict(row.get("expected_configuration") or {}),
                "observed_configuration": dict(row.get("observed_configuration") or {}),
                "_subscription_key": self._component(key, "subscriptions"),
            }
        aliases = {
            value: f"Subscription {index}"
            for index, value in enumerate(
                sorted(
                    {
                        row["_subscription_key"]
                        for row in self._resources.values()
                        if row["_subscription_key"]
                    }
                ),
                1,
            )
        }
        for row in self._resources.values():
            row["subscription_alias"] = aliases.get(
                row["_subscription_key"], "Unknown"
            )

    def get(self, resource_key: str) -> dict[str, Any]:
        key = self.canonical_key(resource_key)
        return dict(self._resources.get(key) or {
            "_resource_key": key, "resource": {"name": "Unknown", "entity_type": "Resource"},
            "application": "Unknown", "business_service": "Unknown", "owner": "Unknown",
            "support_team": "Unknown", "environment": "Unknown", "business_criticality": "Unknown",
            "dependency_count": 0, "historical_correlation_count": 0,
            "subscription_alias": "Unknown",
            "expected_configuration": {}, "observed_configuration": {}
        })

    def all(self) -> list[dict[str, Any]]:
        return [dict(self._resources[key]) for key in sorted(self._resources)]

    @staticmethod
    def canonical_key(value: Any) -> str:
        text = str(value or "").strip()
        while True:
            decoded = unquote(text)
            if decoded == text:
                break
            text = decoded
        return text.strip().rstrip("/").strip().casefold()

    @staticmethod
    def _component(resource_key: str, name: str) -> str:
        parts = resource_key.split("/")
        try:
            index = parts.index(name)
        except ValueError:
            return ""
        return parts[index + 1] if index + 1 < len(parts) else ""
