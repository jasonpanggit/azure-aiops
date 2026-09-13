"""Azure Monitor managed-Prometheus access for OpenTelemetry guest metrics.

VMs that emit OpenTelemetry (OTel) host-metrics -- rather than the "classic"
Azure Monitor Agent logs-based guest performance counters handled by
:mod:`onboarding.monitor_logs` -- land in an Azure Monitor Workspace (AMW,
resource type ``Microsoft.Monitor/accounts``), not a Log Analytics workspace.
That data is queried with PromQL against a Prometheus-compatible REST API
rather than KQL against the Logs Query API, so it needs its own client with
its own token scope, endpoint shape, and response parser.

Two addressing modes exist for that API:

* Workspace-scoped: ``https://<workspace>.<region>.prometheus.monitor.azure.com``,
  read directly off the AMW resource's own metrics endpoint.
* Resource-scoped: the shared regional endpoint
  ``https://query.<region>.prometheus.monitor.azure.com`` plus an
  ``x-ms-azure-scoping`` header naming the resource/RG/subscription to query,
  used when the caller only knows the AMW's region and not its specific
  endpoint URL.

Callers of this module (see ``onboarding.runtime``) resolve whichever
endpoint is available via ARG discovery and pass it straight through; this
client does not care which mode produced the endpoint it is given.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

PROMETHEUS_QUERY_SCOPE = "https://prometheus.monitor.azure.com/.default"

# The OTel host-metrics semantic-convention names for memory and filesystem
# utilization (see the Azure "metrics-guest-reference" docs). Both are gauges
# in the 0-1 range broken down by a `state` label, so "percent used" and
# "percent free" have to be derived rather than read directly:
#   * memory: 1 - the "free" state fraction, expressed as a percentage.
#   * filesystem: the "free" state fraction directly, expressed as a
#     percentage, restricted to the OS volume (POSIX "/" or Windows "C:\\")
#     since a host can report many mount points and this mirrors the classic
#     path's "_Total"/OS-disk scoping.
MEMORY_PERCENT_QUERY = "100 * (1 - system_memory_utilization{state=\"free\"})"
DISK_FREE_PERCENT_QUERY = (
    'system_filesystem_utilization{state="free", mountpoint=~"^(/|C:\\\\\\\\)$"} * 100'
)

# Candidate label keys for the resource-id dimension across observed label
# normalizations (Prometheus label names cannot contain "." so the source
# `Microsoft.resourceid` dimension may surface with different casing/
# separators depending on the collector). Checked case-insensitively.
_RESOURCE_ID_LABEL_CANDIDATES = ("microsoft_resourceid", "microsoft.resourceid")

_REGION = re.compile(r"^[a-z0-9]+$")


class PrometheusRequester(Protocol):
    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


@dataclass(frozen=True)
class PrometheusEndpoint:
    """Where and how to query one Azure Monitor Workspace's PromQL API.

    ``scoping_id`` is set only for resource-scoped queries (see module
    docstring); when set, the client sends it via ``x-ms-azure-scoping``
    instead of assuming the endpoint URL alone already scopes the query.
    """

    query_url: str
    scoping_id: str = ""


def resource_scoped_endpoint(region: str, scoping_id: str) -> PrometheusEndpoint:
    """Build the shared regional endpoint for resource-scoped PromQL queries."""
    normalized = str(region or "").strip().lower()
    if not _REGION.fullmatch(normalized):
        raise ValueError("Prometheus endpoint region is invalid")
    if not str(scoping_id or "").strip():
        raise ValueError("Prometheus resource-scoped queries require a scoping id")
    return PrometheusEndpoint(
        query_url=f"https://query.{normalized}.prometheus.monitor.azure.com/api/v1/query",
        scoping_id=str(scoping_id).strip(),
    )


def workspace_scoped_endpoint(prometheus_query_endpoint: str) -> PrometheusEndpoint:
    """Build the endpoint for workspace-scoped PromQL queries.

    ``prometheus_query_endpoint`` is the AMW resource's own query endpoint
    (e.g. discovered via ARG), with or without the trailing API path.
    """
    base = str(prometheus_query_endpoint or "").strip().rstrip("/")
    if not base:
        raise ValueError("Prometheus workspace endpoint is invalid")
    if not base.endswith("/api/v1/query"):
        base = f"{base}/api/v1/query"
    return PrometheusEndpoint(query_url=base)


class AzureMonitorPrometheusClient:
    """Query an Azure Monitor Workspace's PromQL API for OTel guest metrics."""

    def __init__(
        self,
        credential: Any,
        *,
        timeout: int = 30,
        requester: PrometheusRequester | None = None,
        max_retries: int = 3,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credential = credential
        self.timeout = timeout
        self.requester = requester or httpx.request
        if max_retries < 0:
            raise ValueError("Prometheus max_retries cannot be negative")
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def query_guest_performance(
        self, endpoint: PrometheusEndpoint
    ) -> dict[str, dict[str, float]]:
        """Latest OTel memory/disk-free guest metrics, keyed by resource ID.

        Returns ``{resource_id_lower: {"memory_percent": ..., "disk_free_percent": ...}}``,
        the same shape :meth:`AzureMonitorLogsClient.query_guest_performance` returns for
        the classic path, so both can be merged interchangeably by the caller.
        Never raises for "no data" -- an empty vector result yields an empty dict.
        """
        merged: dict[str, dict[str, float]] = {}
        for field_name, query in (
            ("memory_percent", MEMORY_PERCENT_QUERY),
            ("disk_free_percent", DISK_FREE_PERCENT_QUERY),
        ):
            for resource_id, value in self._query_instant(endpoint, query).items():
                merged.setdefault(resource_id, {})[field_name] = value
        return merged

    def _query_instant(
        self, endpoint: PrometheusEndpoint, query: str
    ) -> dict[str, float]:
        token = self.credential.get_token(PROMETHEUS_QUERY_SCOPE)
        access_token = getattr(token, "token", "")
        if not access_token:
            raise RuntimeError("Azure AD returned an empty access token for Azure Monitor Prometheus")

        response = self._request_with_retry(endpoint, access_token=access_token, query=query)
        if response.is_error:
            detail = response.text.strip()[:512] or f"HTTP {response.status_code}"
            raise RuntimeError(f"Prometheus query failed: {detail}")
        payload = _load_json(response.text or "{}")
        return _parse_vector_result(payload)

    def _request_with_retry(
        self, endpoint: PrometheusEndpoint, *, access_token: str, query: str
    ) -> httpx.Response:
        response: httpx.Response | None = None
        headers = {"Authorization": f"Bearer {access_token}"}
        if endpoint.scoping_id:
            headers["x-ms-azure-scoping"] = endpoint.scoping_id
        params = {"query": query, "time": _iso_z(datetime.now(UTC))}
        for attempt in range(self.max_retries + 1):
            response = self.requester(
                "GET",
                endpoint.query_url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            if response.status_code not in {429, 503} or attempt >= self.max_retries:
                return response
            self.retry_sleep(_retry_delay(response, attempt))
        if response is None:
            raise RuntimeError("Prometheus request was not attempted")
        return response


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(2.0 ** attempt, 8.0)


def _load_json(text: str) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise RuntimeError("Prometheus response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TypeError("Prometheus response was not a JSON object")
    return payload


def _parse_vector_result(payload: dict[str, Any]) -> dict[str, float]:
    """Parse a Prometheus instant-query response into ``{resource_id: value}``.

    Only the ``vector`` result type is supported (what an instant query
    without a range returns); anything else, or a malformed/empty payload,
    yields an empty dict rather than raising, so one metric's odd response
    shape can't block the other.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        return {}
    result = data.get("result")
    if not isinstance(result, list):
        return {}
    parsed: dict[str, float] = {}
    for series in result:
        if not isinstance(series, dict):
            continue
        metric = series.get("metric")
        value_pair = series.get("value")
        if not isinstance(metric, dict) or not isinstance(value_pair, list) or len(value_pair) != 2:
            continue
        resource_id = _resource_id_label(metric)
        if not resource_id:
            continue
        try:
            parsed[resource_id] = float(value_pair[1])
        except (TypeError, ValueError):
            continue
    return parsed


def _resource_id_label(metric: dict[str, Any]) -> str:
    lowered = {str(key).casefold(): value for key, value in metric.items()}
    for candidate in _RESOURCE_ID_LABEL_CANDIDATES:
        value = lowered.get(candidate)
        if value:
            return str(value).strip().casefold()
    return ""
