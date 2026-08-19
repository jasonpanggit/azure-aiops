from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import unquote

from intelligence.incident.incident_intelligence import IncidentIntelligence


class LifecycleContextBuilder:
    """Builds bounded public lifecycle context keyed by canonical resource identity."""

    def __init__(
        self, resources: list[dict[str, Any]], *, max_resources: int = 5000
    ) -> None:
        if isinstance(max_resources, bool) or not isinstance(max_resources, int) or max_resources < 1:
            raise ValueError("max_resources must be positive")
        if not isinstance(resources, list) or any(not isinstance(row, dict) for row in resources):
            raise TypeError("Lifecycle resources must be a list of mappings")
        if len(resources) > max_resources:
            raise ValueError("Lifecycle resource snapshot exceeds configured bound")
        self._resources: dict[str, dict[str, Any]] = {}
        for row in resources:
            key = canonical_resource_key(
                row.get("resource_key") or row.get("resource_id")
            )
            if not key:
                raise ValueError("Lifecycle resources require canonical resource_key")
            if key in self._resources:
                raise ValueError("Duplicate lifecycle resource identity")
            normalized = dict(row)
            normalized["resource_key"] = key
            self._resources[key] = self._public(normalized)

    def all(self) -> list[dict[str, Any]]:
        return [dict(self._resources[key]) for key in sorted(self._resources)]

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        for field in ("ownership_coverage", "internet_exposed"):
            value = row.get(field, False)
            if not isinstance(value, bool):
                raise TypeError(f"Lifecycle {field} must be boolean")
        patch_score = row.get("patch_compliance_score")
        if patch_score is not None and (
            isinstance(patch_score, bool)
            or not isinstance(patch_score, int)
            or not 0 <= patch_score <= 100
        ):
            raise ValueError("Lifecycle patch_compliance_score must be an integer from 0 to 100")
        return {
            "_resource_key": str(
                row.get("resource_key") or row.get("resource_id") or ""
            ).casefold(),
            "resource": {
                "name": str(row.get("name") or ""),
                "entity_type": str(row.get("entity_type") or "Resource"),
            },
            "subscription": public_subscription_label(row.get("subscription")),
            "region": str(row.get("region") or "Unknown"),
            "product": str(row.get("product") or "Unknown"),
            "version": str(row.get("version") or "Unknown"),
            "support_channel": str(row.get("support_channel") or ""),
            "application": str(row.get("application") or "Unknown"),
            "business_service": str(row.get("business_service") or "Unknown"),
            "owner": str(row.get("owner") or "Unknown"),
            "support_team": str(row.get("support_team") or "Unknown"),
            "environment": str(row.get("environment") or "Unknown"),
            "business_criticality": str(
                row.get("business_criticality") or "Unknown"
            ),
            "ownership_coverage": bool(row.get("ownership_coverage")),
            "internet_exposed": bool(row.get("internet_exposed")),
            "patch_compliance": (
                patch_score
                if patch_score is not None
                else None
            ),
        }


_UUID = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def public_subscription_label(value: Any) -> str:
    label = str(value or "").strip()
    if not label:
        return "Unknown"
    if (
        _UUID.fullmatch(label)
        or "/subscriptions/" in label.casefold()
        or IncidentIntelligence._contains_internal_identifier(label)
    ):
        digest = hashlib.sha256(label.casefold().encode()).hexdigest()[:12]
        return f"Subscription {digest}"
    return label


def canonical_resource_key(value: Any) -> str:
    key = str(value or "").strip()
    while True:
        decoded = unquote(key)
        if decoded == key:
            break
        key = decoded
    return key.rstrip("/").casefold()
