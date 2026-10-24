"""Live resource utilization (CPU, disk, network) via Azure Monitor Metrics.

Live reads have no snapshot-backed fallback: utilization is only
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

Separate personal retention routes store explicit, authorized collection
receipts. They do not replace live reads or imply continuous availability.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from intelligence.health.service import SUPPORTED_RESOURCE_TYPES, ResourceHealthNotFound
from onboarding.runtime import connection_cache_identity
from operations.overview_history import HistoryCapture
from operations.resource_health_history import (
    ResourceHealthHistoryStore,
    health_observation,
)
from storage.onelake_documents import DocumentConflictError

from ..dependencies import Context, CurrentPrincipal, ReadScope, live_subscription_ids
from ..errors import ApiError, ErrorCode
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope

router = APIRouter(prefix="/api/v1/resource-health", tags=["resource-health"])
_LOGGER = logging.getLogger(__name__)

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
    request: Request,
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
    if identity is None:
        raise _resource_not_found(request=request, reason="inventory_identity_absent")
    if str(identity.get("resource_type") or "").casefold() not in SUPPORTED_RESOURCE_TYPES:
        raise _resource_not_found(request=request, reason="unsupported_resource_type")

    canonical_resource_id = str(identity.get("resource_id") or "")
    subscription_id = str(identity.get("subscription_id") or "")
    if not canonical_resource_id or not subscription_id:
        raise _resource_not_found(request=request, reason="incomplete_inventory_identity")

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
            reason = exc.reason if isinstance(exc, ResourceHealthNotFound) else "service_lookup_error"
            raise _resource_not_found(request=request, reason=reason) from exc
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


def _resource_not_found(*, request: Request | None = None, reason: str = "") -> ApiError:
    if request is not None:
        _LOGGER.warning(
            "resource_health_not_found correlation_id=%s reason=%s",
            getattr(request.state, "correlation_id", ""),
            reason,
        )
    return ApiError(ErrorCode.NOT_FOUND, "Resource health was not found")


def _authorized_history(
    context: Context,
    scope: ReadScope,
    resource_id: str,
) -> tuple[ResourceHealthHistoryStore, str]:
    identity = context.inventory_read_port().get_resource(scope, resource_id)
    if (
        identity is None
        or str(identity.get("resource_type") or "").casefold()
        not in SUPPORTED_RESOURCE_TYPES
        or not identity.get("resource_id")
        or not identity.get("subscription_id")
    ):
        raise _resource_not_found()
    if context.resource_health_history_store is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Durable resource health history is unavailable",
        )
    return context.resource_health_history_store, str(identity["resource_id"])


def _history_response(data: dict, scope: ReadScope) -> dict:
    return envelope(
        data,
        scope=scope.to_dict(),
        evidence=Evidence(
            source_engine="resource_health.retained_observations",
            source_table="state/resource-health-history",
            timestamp=data["observations"][-1]["captured_at"]
            if data["observations"]
            else "",
            confidence="unknown",
        ),
        warnings=[
            "Explicit provider-collection receipts for an authorized resource address, not continuous history, availability, SLOs or resource-incarnation continuity.",
            "Original metric aggregation windows and rate semantics are unreported. Cached captures are not independent telemetry samples.",
        ],
    )


@router.get("/resource/history")
def resource_history(
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
    resource_id: str = Query(..., min_length=1, max_length=4096),
) -> dict:
    """Reauthorize current Inventory membership before reading retained personal history."""
    store, canonical_id = _authorized_history(context, scope, resource_id)
    return _history_response(
        store.read(principal.subject, scope.to_dict(), canonical_id), scope
    )


@router.post("/resource/history", status_code=201)
def capture_resource_history(
    payload: HistoryCapture,
    context: Context,
    principal: CurrentPrincipal,
    scope: ReadScope,
    request: Request,
    resource_id: str = Query(..., min_length=1, max_length=4096),
) -> dict:
    """Acquire one server-side per-resource observation; no submitted metrics or execution."""
    store, canonical_id = _authorized_history(context, scope, resource_id)
    if (
        store.read(principal.subject, scope.to_dict(), canonical_id)["revision"]
        != payload.expected_revision
    ):
        raise ApiError(
            ErrorCode.CONFLICT, "Health history changed; reload before capturing"
        )
    started = datetime.now(UTC).isoformat()
    result = resource_health_resource(
        context, scope, request, canonical_id, force_refresh=False,
    )
    finished = datetime.now(UTC).isoformat()
    try:
        observation = health_observation(
            result["data"], canonical_id, started, finished
        )
    except (ValueError, KeyError) as exc:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The reported resource health collection cannot be retained; no capture was saved",
        ) from exc
    store, _ = _authorized_history(context, scope, canonical_id)
    try:
        data = store.append(
            principal.subject,
            scope.to_dict(),
            canonical_id,
            payload.expected_revision,
            observation,
        )
    except DocumentConflictError as exc:
        raise ApiError(ErrorCode.CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, str(exc)) from exc
    return _history_response(data, scope)
