"""Independent, scope-filtered change observations; never a causal or execution contract."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from intelligence.change.change_intelligence import ChangeIntelligence

from ..dependencies import Context, Page, Pagination, ReadScope
from ..errors import ApiError, ErrorCode
from ..evidence import Evidence, envelope
from ..scope import Scope, scope_attributes
from .compliance import _service
from .connections import list_connections

router = APIRouter(prefix="/api/v1/changes", tags=["changes"])

_ENUMS = {
    "publicNetworkAccess": {"Enabled", "Disabled", "SecuredByPerimeter"},
    "encryption": {"Enabled", "Disabled"},
    "minimumTlsVersion": {
        "1.0",
        "1.1",
        "1.2",
        "1.3",
        "TLS1_0",
        "TLS1_1",
        "TLS1_2",
        "TLS1_3",
    },
}
_BOOLEANS = {"httpsOnly", "allowBlobPublicAccess", "enableSoftDelete"}
_SIZES = {"sku", "vmSize"}
_ALIASES = {
    "properties.publicNetworkAccess": "publicNetworkAccess",
    "properties.encryption": "encryption",
    "properties.minimumTlsVersion": "minimumTlsVersion",
    "properties.httpsOnly": "httpsOnly",
    "properties.allowBlobPublicAccess": "allowBlobPublicAccess",
    "properties.enableSoftDelete": "enableSoftDelete",
    "properties.hardwareProfile.vmSize": "vmSize",
    "sku.name": "sku",
}
_FIELDS = set(_ENUMS) | _BOOLEANS | _SIZES | set(_ALIASES)
_VM_SIZE = re.compile(
    r"(?:Standard|Basic)_[A-Z][1-9][0-9]{0,2}[a-z]{0,4}(?:_v[1-9][0-9]?)?"
)


def _cell(state: dict, field: str) -> dict:
    if field not in state:
        return {"status": "unreported"}
    value = state[field]
    field = _ALIASES.get(field, field)
    allowed = (
        (field in _BOOLEANS and isinstance(value, bool))
        or (field in _ENUMS and isinstance(value, str) and value in _ENUMS[field])
        or (field in _SIZES and isinstance(value, str) and _VM_SIZE.fullmatch(value))
    )
    return {"status": "reported", "value": value} if allowed else {"status": "withheld"}


def configuration_observation(change: dict) -> dict:
    """Expose typed safe fields from change states, not arbitrary property paths or values."""
    before, after = change["previous_state"], change["current_state"]
    fields = set(before) | set(after) | set(change["changed_fields"])
    rows = []
    for field in sorted(fields & _FIELDS):
        left, right = _cell(before, field), _cell(after, field)
        comparable = left["status"] == right["status"] == "reported"
        rows.append(
            {
                "field": field,
                "before": left,
                "after": right,
                "comparison": (
                    "unchanged" if left["value"] == right["value"] else "changed"
                )
                if comparable
                else "not_comparable",
            }
        )
    return {
        "basis": "change_states",
        "fields": rows,
        "withheld_field_count": len(fields - _FIELDS),
    }


def _instant(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Change time filters require ISO timestamps with timezone",
        ) from exc
    if parsed.tzinfo is None:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Change time filters require an explicit timezone",
        )
    return parsed.astimezone(UTC)


def _connection_subscriptions(context: Context, scope: Scope) -> set[str] | None:
    if not scope.values("subscription_connection"):
        return None
    result = list_connections(
        context, scope, Pagination(0, 10_000), include_disabled=True
    )
    rows = result["data"]
    if result["pagination"]["total"] > len(rows):
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Complete connection membership is unavailable",
        )
    found = {row["connection_id"].casefold() for row in rows}
    if not scope.values("subscription_connection") <= found:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "Selected connection is unavailable in the authorized scope",
        )
    return {row["subscription_id"].casefold() for row in rows}


@router.get(
    "/observations",
    summary="Independent authorized change projection and typed configuration observations",
)
def observations(
    context: Context,
    scope: ReadScope,
    page: Page,
    q: Annotated[str, Query(max_length=200)] = "",
    category: Annotated[str, Query(max_length=128)] = "",
    source: Annotated[str, Query(max_length=256)] = "",
    since: Annotated[str, Query(max_length=64)] = "",
    until: Annotated[str, Query(max_length=64)] = "",
    order: Literal["newest", "oldest"] = "newest",
) -> dict[str, Any]:
    """Authorize resource membership before deriving counts, facets, pages or safe comparisons."""
    if page.limit > 100:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Change observation pages are limited to 100 rows",
        )
    start, end = _instant(since), _instant(until)
    if start and end and start > end:
        raise ApiError(
            ErrorCode.INVALID_REQUEST, "Change time range must be chronological"
        )
    subscriptions = _connection_subscriptions(context, scope)
    engine = _service(context, scope)
    resource_scope = scope.with_dimension("subscription_connection", [])
    rows = []
    for ordinal, change in enumerate(engine.changes):
        context_row = engine.context_builder.get(change["resource_key"])
        subscription = engine.context_builder._component(
            change["resource_key"], "subscriptions"
        )
        attributes = scope_attributes(
            {
                **context_row,
                "subscription": subscription,
                "criticality": context_row.get("business_criticality", ""),
            }
        )
        if not resource_scope.matches(attributes):
            continue
        if subscriptions is not None and subscription not in subscriptions:
            continue
        rows.append((change, context_row, ordinal))
    facets = {
        key: sorted({change[key] for change, _, _ in rows})
        for key in ("category", "source")
    }
    authorized_count = len(rows)
    query = q.strip().casefold()
    filtered = [
        (change, resource, ordinal)
        for change, resource, ordinal in rows
        if (not category or change["category"] == category)
        and (not source or change["source"] == source)
        and (not start or datetime.fromisoformat(change["changed_at"]) >= start)
        and (not end or datetime.fromisoformat(change["changed_at"]) <= end)
        and (
            not query
            or query
            in " ".join(
                str(value)
                for value in (
                    change["change_id"],
                    change["summary"],
                    resource["resource"]["name"],
                    resource["business_service"],
                    resource["application"],
                )
            ).casefold()
        )
    ]
    filtered.sort(
        key=lambda pair: (
            datetime.fromisoformat(pair[0]["changed_at"]),
            pair[0]["change_id"],
            pair[2],
        ),
        reverse=order == "newest",
    )
    public = []
    for change, resource, ordinal in filtered[page.offset : page.offset + page.limit]:
        identity = json.dumps(
            [change["resource_key"], change["change_id"], change["changed_at"], ordinal]
        )
        public.append(
            {
                "observation_id": hashlib.sha256(identity.encode()).hexdigest(),
                **{
                    key: ChangeIntelligence._safe_text(change[key])
                    for key in (
                        "change_id",
                        "change_type",
                        "category",
                        "changed_at",
                        "source",
                        "summary",
                    )
                },
                "resource_name": ChangeIntelligence._safe_text(
                    resource["resource"]["name"]
                ),
                "business_service": ChangeIntelligence._safe_text(
                    resource["business_service"]
                ),
                "application": ChangeIntelligence._safe_text(resource["application"]),
                "environment": ChangeIntelligence._safe_text(resource["environment"]),
                "configuration": configuration_observation(change),
            }
        )
    data = {
        "observations": public,
        "facets": {key: values[:100] for key, values in facets.items()},
        "facet_metadata": {
            key: {
                "total": len(values),
                "returned": min(100, len(values)),
                "truncated": len(values) > 100,
            }
            for key, values in facets.items()
        },
        "authorized_count": authorized_count,
        "extent": "loaded_change_projection",
        "read_only": True,
    }
    if len(json.dumps(data).encode()) > 1_048_576:
        raise ApiError(
            ErrorCode.INVALID_REQUEST,
            "Change observation response exceeds 1 MiB; request fewer rows",
        )
    return envelope(
        data,
        evidence=Evidence(
            source_engine="intelligence.change.ChangeIntelligence",
            source_table="independent_change_observations",
            timestamp=engine.freshness,
        ),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(filtered)),
        warnings=[
            "Loaded governed projection only; not an Azure Activity Log or complete estate history.",
            "Change state comparison is not baseline drift, causal confirmation, or execution approval.",
            "Connection selection narrows subscription membership, not event connection provenance.",
        ],
    )
