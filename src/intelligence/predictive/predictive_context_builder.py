from __future__ import annotations

from typing import Any
from urllib.parse import unquote


class PredictiveContextBuilder:
    def __init__(self, resources: list[dict[str, Any]], *, max_resources=5000):
        if isinstance(max_resources, bool) or not isinstance(max_resources, int):
            raise TypeError("max_resources must be an integer")
        if max_resources < 1 or len(resources) > max_resources:
            raise ValueError("Predictive resource snapshot exceeds configured bound")
        self._resources = {}
        for source in resources:
            row = dict(source); key = self.canonical_key(row.get("resource_key"))
            if not key: raise ValueError("Predictive resources require canonical resource_key")
            if key in self._resources: raise ValueError("Duplicate predictive resource identity")
            numeric = ("patch_risk_score", "patch_debt", "lifecycle_risk_score", "incident_count_30d", "incident_count_90d", "change_risk_score", "configuration_drift_count", "security_finding_count", "advisor_recommendation_count")
            for name in numeric:
                if name not in row or row[name] is None:
                    continue
                if isinstance(row[name], bool) or not isinstance(row[name], int):
                    raise TypeError(f"{name} must be an integer")
                if row[name] < 0:
                    raise ValueError(f"{name} must be nonnegative")
                if name.endswith("risk_score") and row[name] > 100:
                    raise ValueError(f"{name} must not exceed 100")
            if "ownership_coverage" in row and not isinstance(
                row["ownership_coverage"], bool
            ):
                raise TypeError("ownership_coverage must be boolean")
            signal_coverage = sum(
                name in row and row.get(name) is not None for name in numeric
            ) / len(numeric)
            known_signals = {
                name for name in numeric if name in row and row.get(name) is not None
            }
            self._resources[key] = {
                "_resource_key": key,
                "resource": {"name": str(row.get("name") or "Unknown")[:512], "entity_type": str(row.get("entity_type") or "Resource")[:128]},
                "application": str(row.get("application") or "Unknown")[:512], "business_service": str(row.get("business_service") or "Unknown")[:512],
                "owner": str(row.get("owner") or "Unknown")[:512], "support_team": str(row.get("support_team") or "Unknown")[:512],
                "environment": str(row.get("environment") or "Unknown")[:128], "business_criticality": str(row.get("business_criticality") or "Unknown")[:128],
                **{name: max(int(row.get(name) or 0), 0) for name in numeric},
                "ownership_coverage": (
                    bool(row.get("ownership_coverage"))
                    if "ownership_coverage" in row
                    else None
                ),
                "signal_coverage": signal_coverage,
                "_known_signals": known_signals,
                "_subscription_key": self._arm_component(key, "subscriptions"),
                "_resource_group_key": self._arm_component(key, "resourcegroups"),
            }
        subscriptions = {
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
        resource_groups = {
            value: f"Resource Group {index}"
            for index, value in enumerate(
                sorted(
                    {
                        (row["_subscription_key"], row["_resource_group_key"])
                        for row in self._resources.values()
                        if row["_resource_group_key"]
                    }
                ),
                1,
            )
        }
        for row in self._resources.values():
            row["subscription_alias"] = subscriptions.get(
                row["_subscription_key"], "Unknown"
            )
            row["resource_group_alias"] = resource_groups.get(
                (row["_subscription_key"], row["_resource_group_key"]), "Unknown"
            )

    def all(self): return [dict(self._resources[key]) for key in sorted(self._resources)]

    @staticmethod
    def canonical_key(value):
        text=str(value or "").strip()
        while True:
            decoded=unquote(text)
            if decoded==text: break
            text=decoded
        return text.strip().rstrip("/").strip().casefold()

    @staticmethod
    def _arm_component(resource_key, component):
        parts = resource_key.split("/")
        try:
            index = parts.index(component)
        except ValueError:
            return ""
        return parts[index + 1] if index + 1 < len(parts) else ""
