"""Bounded ARM history reads through an existing, unambiguous connection."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import httpx
from azure.core.exceptions import AzureError

from api.scope import Scope, scope_attributes
from operations.incident_scenarios import instant, validate_parameters

_LOGGER = logging.getLogger(__name__)
_ARM = "https://management.azure.com"
_VERSIONS = {"changes": "2015-04-01", "health": "2025-05-01"}
_RETENTION_DAYS = {"changes": 90, "health": 30}


def unavailable_history(code: str = "not_configured") -> dict[str, Any]:
    """Return explicit missing-source receipts, never success-shaped empty data."""
    return {
        family: {
            "rows": [],
            "status": "unavailable",
            "complete": False,
            "error_code": code,
            "observed_at": "",
        }
        for family in _VERSIONS
    }


class ArmIncidentHistoryReader:
    """Read one authorized resource/window without inventory or credential fallback."""

    def __init__(
        self,
        connections: Callable[[], list[Any]],
        credential_factory: Callable[[Any], Any],
        *,
        requester: Callable[..., httpx.Response] = httpx.request,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retry_sleep: Callable[[float], None] = time.sleep,
        max_pages: int = 3,
        max_rows: int = 200,
    ) -> None:
        if not 1 <= max_pages <= 3 or not 1 <= max_rows <= 200:
            raise ValueError(
                "History limits cannot exceed three pages/two hundred rows"
            )
        self._connections = connections
        self._credential_factory = credential_factory
        self._requester = requester
        self._clock = clock
        self._sleep = retry_sleep
        self._max_pages = max_pages
        self._max_rows = max_rows

    def read(
        self, scope: Scope, args: Mapping[str, Any], identity: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Recheck the inventory binding and scope before resolving any credential."""
        resource, start, end = validate_parameters(args)
        if (
            not isinstance(scope, Scope)
            or not scope.matches(scope_attributes(identity))
            or str(identity.get("resource_id") or "").rstrip("/").casefold()
            != resource.casefold()
            or str(identity.get("subscription_id") or "").casefold()
            != resource.split("/")[2].casefold()
        ):
            return unavailable_history("scope_denied")
        now = instant(self._clock())
        # Do not query beyond native retention or fabricate archival coverage.
        eligible = {
            family
            for family, days in _RETENTION_DAYS.items()
            if 0 <= (now - start).total_seconds() <= days * 86400 and end <= now
        }
        result = unavailable_history("outside_native_retention_or_future")
        if not eligible:
            return result
        subscription = resource.split("/")[2].casefold()
        selected = scope.values("subscription_connection")
        bound_connection = str(identity.get("subscription_connection") or "").casefold()
        matches = [
            connection
            for connection in self._connections()
            if getattr(connection, "is_active", True)
            and str(getattr(connection, "subscription_id", "")).casefold()
            == subscription
            and (not selected or str(connection.connection_id).casefold() in selected)
            and (
                not bound_connection
                or str(connection.connection_id).casefold() == bound_connection
            )
        ]
        if len(matches) != 1:
            return unavailable_history("connection_missing_or_ambiguous")
        try:
            credential = self._credential_factory(matches[0])
            token = credential.get_token(f"{_ARM}/.default").token
            if not token:
                raise ValueError("Empty ARM token")
        except (AzureError, OSError, RuntimeError, ValueError):
            _LOGGER.warning("incident_history_unavailable code=credential_unavailable")
            return unavailable_history("credential_unavailable")
        for family in _VERSIONS:
            if family in eligible:
                result[family] = self._read_family(
                    family, resource, start, end, now, token
                )
        return result

    def _read_family(
        self,
        family: str,
        resource: str,
        start: datetime,
        end: datetime,
        now: datetime,
        token: str,
    ) -> dict[str, Any]:
        encoded = quote(resource, safe="/")
        path = (
            f"/subscriptions/{quote(resource.split('/')[2], safe='')}"
            "/providers/Microsoft.Insights/eventtypes/management/values"
            if family == "changes"
            else f"{encoded}/providers/Microsoft.ResourceHealth/availabilityStatuses"
        )
        params = {"api-version": _VERSIONS[family]}
        if family == "changes":
            params.update(
                {
                    "$filter": (
                        f"eventTimestamp ge '{_z(start)}' and eventTimestamp le '{_z(end)}'"
                        f" and resourceUri eq '{resource}'"
                    ),
                    "$select": (
                        "eventDataId,eventTimestamp,submissionTimestamp,resourceId,"
                        "operationName,status"
                    ),
                }
            )
        url = f"{_ARM}{path}"
        binding_params = dict(params)
        rows: list[dict[str, Any]] = []
        seen_links: set[str] = set()
        seen_rows: set[str] = set()
        pages = inspected = invalid = excluded = 0
        error = ""
        exhausted = False
        while pages < self._max_pages:
            try:
                response = self._request(url, params, token)
                if response.status_code != 200:
                    error = {
                        401: "denied",
                        403: "denied",
                        404: "unsupported_or_missing",
                        429: "throttled",
                    }.get(response.status_code, "provider_error")
                    break
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("value"), list
                ):
                    error = "malformed_response"
                    break
                pages += 1
                raw_rows = payload["value"]
                remaining = self._max_rows - inspected
                for raw in raw_rows[:remaining]:
                    inspected += 1
                    try:
                        row = _normalize(family, raw, resource, start, end, now)
                    except (TypeError, ValueError, KeyError):
                        invalid += 1
                        continue
                    if row is None:
                        excluded += 1
                    elif row["identity"] not in seen_rows:
                        rows.append(row)
                        seen_rows.add(row["identity"])
                link = payload.get("nextLink")
                if len(raw_rows) > remaining or (inspected >= self._max_rows and link):
                    error = "truncated"
                    break
                if link is None or link == "":
                    exhausted = True
                    break
                if (
                    not isinstance(link, str)
                    or link in seen_links
                    or not _safe_next(link, path, binding_params)
                ):
                    error = "invalid_continuation"
                    break
                seen_links.add(link)
                parsed = urlsplit(link)
                query = parse_qs(parsed.query)
                # Some provider continuations omit the original filter. Keep
                # the exact resource/window even when only a token is returned.
                query.update({key: [value] for key, value in binding_params.items()})
                url = urlunsplit(parsed._replace(query=urlencode(query, doseq=True)))
                params = {}
            except (httpx.HTTPError, ValueError, TypeError):
                error = "transport_or_malformed_response"
                break
        if not exhausted and not error:
            error = "truncated"
        age = (instant(self._clock()) - now).total_seconds()
        freshness = "fresh" if 0 <= age <= 900 else "stale"
        if freshness == "stale":
            error = error or "stale_collection"
        if error:
            _LOGGER.warning(
                "incident_history_incomplete family=%s code=%s", family, error
            )
        return {
            "rows": sorted(rows, key=lambda row: (row["timestamp"], row["identity"])),
            "status": "partial" if rows or exhausted else "unavailable",
            "complete": False,
            "observed_at": now.isoformat(),
            "source": "azure_activity_log"
            if family == "changes"
            else "azure_resource_health",
            "api_version": _VERSIONS[family],
            "window": {"since": start.isoformat(), "until": end.isoformat()},
            "resource_id": resource,
            "pages_fetched": pages,
            "rows_inspected": inspected,
            "invalid_rows": invalid,
            "excluded_rows": excluded,
            "pagination_exhausted": exhausted,
            "truncated": error == "truncated",
            "error_code": error,
            "freshness": freshness,
            "retention_days": _RETENTION_DAYS[family],
            "limitations": (
                "Control-plane operations only; ingestion delay and missing operations remain possible."
                if family == "changes"
                else "Availability transitions only; not metrics, full alert history or application health."
            ),
        }

    def _request(
        self, url: str, params: Mapping[str, str], token: str
    ) -> httpx.Response:
        for attempt in range(2):
            response = self._requester(
                "GET",
                url,
                params=params or None,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
                follow_redirects=False,
            )
            if response.status_code not in {429, 500, 502, 503, 504} or attempt:
                return response
            # Do not log provider bodies, headers, tokens or continuation URLs.
            self._sleep(1)
        raise RuntimeError("Unreachable retry state")


def _z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _safe_next(link: str, path: str, params: Mapping[str, str]) -> bool:
    parsed = urlsplit(link)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "management.azure.com"
        or parsed.path.casefold() != path.casefold()
        or parsed.fragment
        or len(link) > 8192
    ):
        return False
    query = parse_qs(parsed.query)
    return set(query) <= {*params, "$skiptoken", "skiptoken", "$skipToken"} and all(
        key not in query or query[key] == [value] for key, value in params.items()
    )


def _normalize(
    family: str,
    raw: Any,
    resource: str,
    start: datetime,
    end: datetime,
    now: datetime,
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        raise TypeError("Malformed history row")
    if family == "changes":
        if (
            str(raw.get("resourceId") or "").rstrip("/").casefold()
            != resource.casefold()
        ):
            raise ValueError("Missing or out-of-scope target")
        timestamp = instant(raw.get("eventTimestamp"))
        reported = instant(raw.get("submissionTimestamp"))
        state = raw.get("status")
        state = state.get("value") if isinstance(state, Mapping) else None
        status = str(state or "").casefold()
        status = (
            status
            if status in {"succeeded", "failed", "started", "accepted", "canceled"}
            else "unknown"
        )
        operation = raw.get("operationName")
        operation = operation.get("value") if isinstance(operation, Mapping) else ""
        action = str(operation).rsplit("/", 1)[-1].casefold()
        action = action if action in {"write", "delete", "action"} else "other"
        kind = (
            "change"
            if status == "succeeded" and action in {"write", "delete"}
            else "activity"
        )
        identity = raw.get("eventDataId")
    else:
        raw_id = str(raw.get("id") or "")
        prefix = f"{resource}/providers/Microsoft.ResourceHealth/availabilityStatuses/"
        if (
            not raw_id.casefold().startswith(prefix.casefold())
            or not raw_id[len(prefix) :]
            or "/" in raw_id[len(prefix) :]
        ):
            raise ValueError("Missing or out-of-scope target")
        props = raw.get("properties")
        if not isinstance(props, Mapping):
            raise TypeError("Malformed health properties")
        timestamp = instant(props.get("occurredTime"))
        reported = instant(props.get("reportedTime"))
        state = str(props.get("availabilityState") or "").casefold()
        status = {
            "available": "healthy",
            "unavailable": "unhealthy",
            "degraded": "degraded",
            "unknown": "unknown",
        }.get(state)
        if status is None:
            raise ValueError("Unrecognized availability state")
        kind, action, identity = "health", "", raw_id
    if (
        not isinstance(identity, str)
        or not identity
        or reported < timestamp
        or (reported - now).total_seconds() > 60
    ):
        raise ValueError("Missing identity or inconsistent provider chronology")
    if not start <= timestamp <= end:
        return None
    digest = hashlib.sha256(
        f"{family}\0{identity}\0{timestamp.isoformat()}\0{status}".encode()
    ).hexdigest()
    return {
        "identity": digest,
        "resource_id": resource,
        "timestamp": timestamp.isoformat(),
        "reported_at": reported.isoformat(),
        "kind": kind,
        "status": status,
        "source": "azure_activity_log"
        if family == "changes"
        else "azure_resource_health",
        **({"operation": action} if action else {}),
        **(
            {
                "configuration": {
                    "status": "withheld",
                    "reason": "Configuration values, callers and free text are not collected.",
                }
            }
            if kind == "change"
            else {}
        ),
    }
