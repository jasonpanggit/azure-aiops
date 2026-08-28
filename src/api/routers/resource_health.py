"""Live resource utilization (CPU, disk, network) via Azure Monitor Metrics.

Unlike most routes this has no snapshot-backed fallback: utilization is only
meaningful as a live reading, so the route requires an explicit subscription
scope and always calls the hybrid (per-connection, live) provider. There is no
platform-metric equivalent for OS-level memory or disk-space utilization for
an ordinary VM -- both require Azure Monitor Agent + Log Analytics guest
counters, which are not wired into this route. Every response says so via
``unavailable_metrics`` rather than silently omitting the fields.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..dependencies import Context, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope

router = APIRouter(prefix="/api/v1/resource-health", tags=["resource-health"])

SOURCE_ENGINE = "intelligence.health.ResourceHealthService"
SOURCE_TABLE = "azure_monitor_metrics"


@router.get("", summary="Live CPU/disk/network utilization for compute resources")
def resource_health(context: Context, scope: ReadScope) -> dict[str, Any]:
    subscription_ids = list(scope.values("subscription"))
    if not context.hybrid_resource_health_provider or not subscription_ids:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Resource health requires a subscription scope",
            {"capability": "resource_health", "provider_state": "unavailable"},
        )
    service = context.hybrid_resource_health_provider(subscription_ids)
    snapshot = service.snapshot(subscription_ids=subscription_ids)
    return envelope(
        snapshot.to_dict(),
        # Read directly from Azure Monitor at request time, not derived.
        evidence=Evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=snapshot.observed_at,
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )
