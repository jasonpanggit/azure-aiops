"""Public inventory identity fields shared by HTTP and governed tool consumers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_ASSET_FIELDS = (
    "family", "resource_id", "resource_name", "resource_type", "subscription_id",
    "resource_group", "environment", "location", "sku", "tier", "runtime",
    "provisioning_state", "os_name", "os_version", "source_type", "observed_at",
    "query_version", "containment",
)


def public_inventory_asset(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project a public identity without exposing internal raw provider payloads."""
    return {"environment": "", **{key: row[key] for key in _ASSET_FIELDS if key in row}}
