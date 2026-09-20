"""Live resource utilization (CPU, disk, network) via Azure Monitor Metrics.

Unlike most routes this has no snapshot-backed fallback: utilization is only
meaningful as a live reading, so the route always calls the hybrid
(per-connection, live) provider. There is no platform-metric equivalent for
OS-level memory or disk-space utilization for an ordinary VM -- both require
Azure Monitor Agent + Log Analytics guest counters, which are not wired into
this route. Every response says so via ``unavailable_metrics`` rather than
silently omitting the fields.

Like every other route, an unconstrained scope (no subscription filter) means
"all onboarded subscriptions" rather than "nothing" -- the live query is
simply run for every onboarded, enabled subscription instead of the caller's
narrowed set. A caller can still filter to one or more subscriptions the same
way as any other page.

A per-scope, in-process TTL cache sits in front of the live provider (same
shape as ``hybrid_network``'s cache in ``runtime.py``): utilization is derived
from Azure Monitor Metrics/Logs queries issued per resource, so a wide scope
with many VMs and both classic + guest-performance readers can add up to a
lot of calls per page load. Without a cache, every dashboard refresh (or
several browser tabs) re-issues the full fan-out and risks Monitor
throttling (429s). The cache is intentionally short-lived and always
bypassable with ``?force_refresh=true`` so an operator chasing a live
incident can always get a fresh reading on demand.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from intelligence.health.service import SUPPORTED_RESOURCE_TYPES
from onboarding.runtime import connection_cache_identity

from ..dependencies import Context, ReadScope, live_subscription_ids
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope

router = APIRouter(prefix="/api/v1/resource-health", tags=["resource-health"])

SOURCE_ENGINE = "intelligence.health.ResourceHealthService"
SOURCE_TABLE = "azure_monitor_metrics"

# Keyed by subscription scope plus the full non-secret connection identities,
# so neither a different scope nor a replaced/rotated connection can reuse an
# earlier SPN's observation. Value is (cached_at_monotonic, snapshot).
_RESOURCE_HEALTH_CACHE_TTL_SECONDS = 120
_resource_health_cache: dict[
    tuple[tuple[str, ...], tuple[tuple[str, ...], ...]],
    tuple[float, Any],
] = {}
_resource_health_detail_cache: dict[
    tuple[tuple[str, ...], tuple[tuple[str, ...], ...], str],
    tuple[float, Any],
] = {}


@router.get("", summary="Live CPU/disk/network utilization for compute resources")
def resource_health(
    context: Context,
    scope: ReadScope,
    force_refresh: bool = Query(
        False,
        description=(
            "Bypass the resource-health cache and re-query Azure Monitor "
            "live, even if a cached reading for this subscription scope is "
            "still within its TTL."
        ),
    ),
) -> dict[str, Any]:
    subscription_ids = live_subscription_ids(context, scope, default_all=True)
    if not context.hybrid_resource_health_provider or not subscription_ids:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Resource health is unavailable because no subscription has been onboarded",
            {"capability": "resource_health", "provider_state": "unavailable"},
        )
    requested = {value.casefold() for value in subscription_ids}
    connection_identities = tuple(
        sorted(
            connection_cache_identity(connection)
            for connection in context.onboarding.registry.list(include_disabled=False)
            if str(connection.subscription_id).casefold() in requested
        )
    )
    cache_key = (tuple(sorted(requested)), connection_identities)
    now = time.monotonic()
    cached = _resource_health_cache.get(cache_key)
    is_cached = False
    if (
        not force_refresh
        and cached is not None
        and now - cached[0] < _RESOURCE_HEALTH_CACHE_TTL_SECONDS
    ):
        snapshot = cached[1]
        is_cached = True
    else:
        service = context.hybrid_resource_health_provider(subscription_ids)
        snapshot = service.snapshot(subscription_ids=subscription_ids)
        _resource_health_cache[cache_key] = (now, snapshot)

    payload = snapshot.to_dict()
    payload["cached"] = is_cached
    payload["cache_ttl_seconds"] = _RESOURCE_HEALTH_CACHE_TTL_SECONDS
    return envelope(
        payload,
        # Cached readings still report the Azure Monitor observation
        # timestamp from when they were fetched, not "now", so a caller can
        # tell how stale a cached response is.
        evidence=Evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=snapshot.observed_at,
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


@router.get(
    "/resource",
    summary="Live CPU/disk/network utilization for one authorized compute resource",
)
def resource_health_resource(
    context: Context,
    scope: ReadScope,
    resource_id: str = Query(..., min_length=1),
    force_refresh: bool = Query(
        False,
        description=(
            "Bypass the per-resource health cache and re-query Azure Monitor "
            "even when the current reading is still within its TTL."
        ),
    ),
) -> dict[str, Any]:
    """Return one inventory-authorized resource's live health snapshot."""
    identity = context.inventory_read_port().get_resource(scope, resource_id)
    if (
        identity is None
        or str(identity.get("resource_type") or "").casefold()
        not in SUPPORTED_RESOURCE_TYPES
    ):
        raise _resource_not_found()

    canonical_resource_id = str(identity.get("resource_id") or "")
    subscription_id = str(identity.get("subscription_id") or "")
    if not canonical_resource_id or not subscription_id:
        raise _resource_not_found()

    # Authorization above is deliberately performed before cache or provider
    # access on every request. Unrestricted administrators still resolve the
    # provider for only the authorized identity's subscription.
    effective_scope = tuple(
        sorted(
            value.casefold()
            for value in (scope.values("subscription") or {subscription_id})
        )
    )
    requested = {subscription_id.casefold()}
    connection_identities = tuple(
        sorted(
            connection_cache_identity(connection)
            for connection in context.onboarding.registry.list(include_disabled=False)
            if str(connection.subscription_id).casefold() in requested
        )
    )
    cache_key = (
        effective_scope,
        connection_identities,
        canonical_resource_id.casefold(),
    )
    now = time.monotonic()
    cached = _resource_health_detail_cache.get(cache_key)
    is_cached = False
    if (
        not force_refresh
        and cached is not None
        and now - cached[0] < _RESOURCE_HEALTH_CACHE_TTL_SECONDS
    ):
        snapshot = cached[1]
        is_cached = True
    else:
        if context.hybrid_resource_health_provider is None:
            raise ApiError(
                ErrorCode.PROVIDER_UNAVAILABLE,
                "Resource health is unavailable because no provider is configured",
                {"capability": "resource_health", "provider_state": "unavailable"},
            )
        service = context.hybrid_resource_health_provider([subscription_id])
        try:
            snapshot = service.snapshot_resource(
                identity,
                subscription_ids=[subscription_id],
            )
        except LookupError as exc:
            raise _resource_not_found() from exc
        _resource_health_detail_cache[cache_key] = (now, snapshot)

    payload = snapshot.to_dict()
    payload["cached"] = is_cached
    payload["cache_ttl_seconds"] = _RESOURCE_HEALTH_CACHE_TTL_SECONDS
    return envelope(
        payload,
        evidence=Evidence(
            source_engine=SOURCE_ENGINE,
            source_table=SOURCE_TABLE,
            timestamp=snapshot.observed_at,
            confidence=CONFIDENCE_HIGH,
        ),
        scope=scope.to_dict(),
        warnings=snapshot.warnings,
    )


def _resource_not_found() -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND, "Resource health was not found")
