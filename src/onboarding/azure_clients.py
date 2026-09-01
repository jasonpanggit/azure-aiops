from __future__ import annotations

import json
import logging
import subprocess  # nosec B404
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import httpx

from .query_contract import QuerySpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, command: list[str], timeout: int) -> CommandResult: ...


class HttpRequester(Protocol):
    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response: ...


class SubprocessRunner:
    def run(self, command: list[str], timeout: int) -> CommandResult:
        # Safe: command is an internal argv list, never shell text.
        completed = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class AzureMcpClient:
    """Thin process adapter over the official Azure MCP CLI."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        command_prefix: tuple[str, ...] = ("azmcp",),
        timeout: int = 60,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        if not command_prefix:
            raise ValueError("Azure MCP command_prefix cannot be empty")
        self.command_prefix = command_prefix
        self.timeout = timeout

    def list_subscriptions(self, tenant_id: str = "") -> list[dict]:
        command = [*self.command_prefix, "subscription", "list"]
        if tenant_id:
            command.extend(["--tenant", tenant_id])
        result = self.runner.run(command, self.timeout)
        if result.returncode:
            raise RuntimeError(f"Azure MCP subscription discovery failed: {result.stderr.strip()}")
        payload = _load_json(result.stdout, "Azure MCP")
        if int(payload.get("status", 500)) >= 400:
            raise RuntimeError(f"Azure MCP subscription discovery failed: {payload.get('message', payload)}")
        rows = payload.get("results") or []
        if isinstance(rows, dict):
            rows = rows.get("subscriptions") or []
        if not isinstance(rows, list):
            raise TypeError("Azure MCP returned an invalid subscription result")
        return rows


class AzureCliArgClient:
    """ARG query fallback because Azure MCP has no arbitrary ARG query tool."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        page_size: int = 1000,
        max_pages: int = 1000,
        timeout: int = 60,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout = timeout

    def query(self, spec: QuerySpec, scope_ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        continuation_token: str | None = None
        for _ in range(self.max_pages):
            command = [
                "az",
                "graph",
                "query",
                "--graph-query",
                spec.query,
                "--first",
                str(self.page_size),
                "--only-show-errors",
                "--output",
                "json",
            ]
            if scope_ids:
                scope_option = (
                    "--management-groups"
                    if spec.scope == "management_groups"
                    else "--subscriptions"
                )
                command.extend([scope_option, *scope_ids])
            if continuation_token:
                command.extend(["--skip-token", continuation_token])
            result = self.runner.run(command, self.timeout)
            if result.returncode:
                detail = result.stderr.strip() or result.stdout.strip() or "unknown Azure CLI error"
                raise RuntimeError(f"ARG query '{spec.name}' failed: {detail}")
            payload = _load_json(result.stdout, f"ARG query {spec.name}")
            page = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(page, list):
                raise TypeError(f"ARG query '{spec.name}' returned an invalid page")
            rows.extend(item for item in page if isinstance(item, dict))
            raw_token = (
                (payload or {}).get("skip_token")
                or (payload or {}).get("skipToken")
                or (payload or {}).get("$skipToken")
            )
            continuation_token = str(raw_token) if raw_token else None
            if not continuation_token:
                return rows
        raise RuntimeError(f"ARG query '{spec.name}' exceeded max_pages={self.max_pages}")


class AzureResourceGraphClient:
    """Query Azure Resource Graph with the connection's token credential."""

    endpoint = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
    api_version = "2022-10-01"

    def __init__(
        self,
        credential: Any,
        *,
        page_size: int = 1000,
        max_pages: int = 1000,
        timeout: int = 60,
        requester: HttpRequester | None = None,
    ) -> None:
        self.credential = credential
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout = timeout
        self.requester = requester or httpx.request

    def query(self, spec: QuerySpec, scope_ids: list[str]) -> list[dict]:
        if not scope_ids:
            raise ValueError(f"ARG query '{spec.name}' requires at least one subscription scope")

        token = self.credential.get_token("https://management.azure.com/.default")
        access_token = getattr(token, "token", "")
        if not access_token:
            raise RuntimeError("Azure AD returned an empty access token for Azure Resource Graph")

        rows: list[dict] = []
        skip_token: str | None = None
        for _ in range(self.max_pages):
            options: dict[str, Any] = {"$top": self.page_size}
            if skip_token:
                options["$skipToken"] = skip_token
            response = self.requester(
                "POST",
                self.endpoint,
                params={"api-version": self.api_version},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "subscriptions": scope_ids,
                    "query": spec.query,
                    "options": options,
                },
                timeout=self.timeout,
            )
            if response.is_error:
                detail = response.text.strip() or f"HTTP {response.status_code}"
                raise RuntimeError(f"ARG query '{spec.name}' failed: {detail}")
            payload = response.json()
            page = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(page, list):
                raise TypeError(f"ARG query '{spec.name}' returned an invalid page")
            rows.extend(item for item in page if isinstance(item, dict))
            skip_token = (
                payload.get("$skipToken") or payload.get("skipToken")
                if isinstance(payload, dict)
                else None
            )
            if not skip_token:
                return rows
        raise RuntimeError(f"ARG query '{spec.name}' exceeded max_pages={self.max_pages}")


class AzureCostManagementClient:
    """Query Azure Cost Management actual-cost data for a subscription."""

    endpoint_template = (
        "https://management.azure.com/subscriptions/{subscription_id}/providers/"
        "Microsoft.CostManagement/query"
    )
    api_version = "2023-11-01"

    def __init__(
        self,
        credential: Any,
        *,
        timeout: int = 60,
        requester: HttpRequester | None = None,
        max_retries: int = 3,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credential = credential
        self.timeout = timeout
        self.requester = requester or httpx.request
        if max_retries < 0:
            raise ValueError("Cost Management max_retries cannot be negative")
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def query_actual_costs(
        self,
        subscription_ids: list[str],
        *,
        end: datetime | None = None,
        lookback: timedelta = timedelta(days=30),
    ) -> list[dict[str, Any]]:
        if not subscription_ids:
            raise ValueError("Cost Management query requires at least one subscription scope")
        if lookback.days < 1:
            raise ValueError("Cost Management lookback must be at least one day")

        token = self.credential.get_token("https://management.azure.com/.default")
        access_token = getattr(token, "token", "")
        if not access_token:
            raise RuntimeError("Azure AD returned an empty access token for Cost Management")

        end_date = (end or datetime.now(UTC)).astimezone(UTC).date()
        start_date = end_date - lookback + timedelta(days=1)
        rows: list[dict[str, Any]] = []
        failures: list[str] = []
        for subscription_id in subscription_ids:
            # Cost Management throttles per-subscription. One throttled or
            # unauthorized subscription must not discard the cost actuals
            # already collected for every other subscription in the scope,
            # so failures are isolated and only escalate if *every*
            # subscription failed.
            try:
                rows.extend(
                    self._query_subscription(
                        str(subscription_id),
                        access_token=access_token,
                        start=start_date,
                        end=end_date,
                    )
                )
            except (RuntimeError, TypeError) as exc:
                failures.append(str(subscription_id))
                logger.warning(
                    "Cost Management query failed for subscription '%s'; "
                    "continuing with remaining subscriptions: %s",
                    subscription_id,
                    exc,
                )
        if failures and len(failures) == len(subscription_ids):
            raise RuntimeError(
                "Cost Management query failed for every subscription in scope: "
                + ", ".join(failures)
            )
        return rows

    def _query_subscription(
        self,
        subscription_id: str,
        *,
        access_token: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        response = self._request_with_retry(
            subscription_id,
            access_token=access_token,
            start=start,
            end=end,
        )
        if response.is_error:
            detail = response.text.strip() or f"HTTP {response.status_code}"
            raise RuntimeError(
                f"Cost Management query for subscription '{subscription_id}' failed: {detail}"
            )
        payload = response.json()
        properties = payload.get("properties") if isinstance(payload, dict) else None
        if not isinstance(properties, dict):
            raise TypeError("Cost Management returned an invalid payload")
        columns = [
            str(column.get("name") or "")
            for column in properties.get("columns") or []
            if isinstance(column, dict)
        ]
        raw_rows = properties.get("rows") or []
        if not isinstance(raw_rows, list):
            raise TypeError("Cost Management returned an invalid rows payload")
        return [
            _cost_row(subscription_id, columns, raw)
            for raw in raw_rows
            if isinstance(raw, list)
        ]

    def _request_with_retry(
        self,
        subscription_id: str,
        *,
        access_token: str,
        start: date,
        end: date,
    ) -> httpx.Response:
        response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            response = self.requester(
                "POST",
                self.endpoint_template.format(subscription_id=subscription_id),
                params={"api-version": self.api_version},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "type": "ActualCost",
                    "timeframe": "Custom",
                    "timePeriod": {
                        "from": start.isoformat(),
                        "to": end.isoformat(),
                    },
                    "dataset": {
                        "granularity": "Daily",
                        "aggregation": {
                            "cost": {
                                "name": "PreTaxCost",
                                "function": "Sum",
                            }
                        },
                        "grouping": [
                            {"type": "Dimension", "name": "ResourceId"},
                            {"type": "Dimension", "name": "ResourceGroupName"},
                            {"type": "Dimension", "name": "ServiceName"},
                        ],
                    },
                },
                timeout=self.timeout,
            )
            if response.status_code not in {429, 503} or attempt >= self.max_retries:
                return response
            self.retry_sleep(_retry_delay(response, attempt))
        if response is None:
            raise RuntimeError("Cost Management request was not attempted")
        return response


#: Platform metrics available for VMs without a guest agent. "Percentage CPU"
#: is the closest platform signal to OS-level CPU utilization; there is no
#: platform-metric equivalent for memory or disk-space utilization, which
#: require Azure Monitor Agent + Log Analytics guest performance counters.
VM_METRIC_NAMES: tuple[str, ...] = (
    "Percentage CPU",
    "Network In Total",
    "Network Out Total",
    "Disk Read Bytes",
    "Disk Write Bytes",
    "OS Disk Queue Depth",
)


class AzureMonitorMetricsClient:
    """Query the Azure Monitor Metrics REST API for one resource's platform metrics."""

    endpoint_template = "https://management.azure.com/{resource_id}/providers/microsoft.insights/metrics"
    api_version = "2018-01-01"
    metrics_scope = "https://management.azure.com/.default"

    def __init__(
        self,
        credential: Any,
        *,
        timeout: int = 30,
        requester: HttpRequester | None = None,
        max_retries: int = 3,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credential = credential
        self.timeout = timeout
        self.requester = requester or httpx.request
        if max_retries < 0:
            raise ValueError("Monitor Metrics max_retries cannot be negative")
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def query_resource_metrics(
        self,
        resource_id: str,
        *,
        metric_names: tuple[str, ...] = VM_METRIC_NAMES,
        end: datetime | None = None,
        lookback: timedelta = timedelta(hours=1),
        interval: str = "PT5M",
    ) -> dict[str, Any]:
        """Fetch the latest platform metric values for a single resource.

        Returns a dict keyed by metric name, each holding the most recent
        non-null data point plus its unit, or ``None`` when Azure Monitor has
        no recent data for that metric (e.g. a stopped VM, or a metric that
        does not apply to the resource type).
        """
        if not resource_id.strip():
            raise ValueError("Monitor Metrics query requires a resource id")
        if not metric_names:
            raise ValueError("Monitor Metrics query requires at least one metric name")

        token = self.credential.get_token(self.metrics_scope)
        access_token = getattr(token, "token", "")
        if not access_token:
            raise RuntimeError("Azure AD returned an empty access token for Monitor Metrics")

        end_time = (end or datetime.now(UTC)).astimezone(UTC)
        start_time = end_time - lookback
        response = self._request_with_retry(
            resource_id,
            access_token=access_token,
            metric_names=metric_names,
            start=start_time,
            end=end_time,
            interval=interval,
        )
        if response.is_error:
            detail = response.text.strip()[:512] or f"HTTP {response.status_code}"
            raise RuntimeError(f"Monitor Metrics query for '{resource_id}' failed: {detail}")
        payload = _load_json(response.text or "{}", "Monitor Metrics")
        return _parse_metrics_payload(payload)

    def _request_with_retry(
        self,
        resource_id: str,
        *,
        access_token: str,
        metric_names: tuple[str, ...],
        start: datetime,
        end: datetime,
        interval: str,
    ) -> httpx.Response:
        response: httpx.Response | None = None
        # Azure Monitor's Metrics API rejects a literal "+00:00" UTC offset in
        # the timespan query parameter with a BadRequest ("Detected invalid
        # time interval input") once the "+" survives transport as a raw
        # character instead of being percent-encoded — some intermediary
        # (e.g. an ASGI test client or proxy) can decode it back to a space
        # per application/x-www-form-urlencoded rules. Using the "Z" suffix
        # (equivalent to +00:00 for UTC) sidesteps this entirely.
        params = {
            "api-version": self.api_version,
            "metricnames": ",".join(metric_names),
            "timespan": f"{_iso_z(start)}/{_iso_z(end)}",
            "interval": interval,
            "aggregation": "Average",
        }
        for attempt in range(self.max_retries + 1):
            response = self.requester(
                "GET",
                self.endpoint_template.format(resource_id=resource_id.lstrip("/")),
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout,
            )
            if response.status_code not in {429, 503} or attempt >= self.max_retries:
                return response
            self.retry_sleep(_retry_delay(response, attempt))
        if response is None:
            raise RuntimeError("Monitor Metrics request was not attempted")
        return response


def _iso_z(value: datetime) -> str:
    """Format a timezone-aware UTC datetime with a "Z" suffix rather than
    "+00:00", so the timespan query parameter never contains a literal "+"
    character (see the comment at its call site)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_metrics_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse an Azure Monitor Metrics list response into a per-metric dict.

    Each entry keeps both the most recent non-null value (for status/threshold
    checks and the data table) and the full ordered series of
    ``{timestamp, value}`` points across the queried window (for trend
    charts). The series is intentionally the full timeseries the platform
    Metrics API already returned in this single call -- no extra requests are
    needed to plot a trend line.
    """
    metrics = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(metrics, list):
        return {}
    result: dict[str, Any] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = ((metric.get("name") or {}).get("value")) if isinstance(metric.get("name"), dict) else None
        if not name:
            continue
        unit = str(metric.get("unit") or "")
        timeseries = metric.get("timeseries") or []
        latest_value: float | None = None
        latest_timestamp = ""
        points: list[dict[str, Any]] = []
        if isinstance(timeseries, list):
            for series in timeseries:
                if not isinstance(series, dict):
                    continue
                for point in series.get("data") or []:
                    if not isinstance(point, dict):
                        continue
                    value = point.get("average")
                    if value is None:
                        continue
                    latest_value = float(value)
                    latest_timestamp = str(point.get("timeStamp") or "")
                    points.append({"timestamp": latest_timestamp, "value": latest_value})
        result[str(name)] = {
            "value": latest_value,
            "unit": unit,
            "timestamp": latest_timestamp,
            "series": points,
        }
    return result


def _cost_row(subscription_id: str, columns: list[str], raw: list[Any]) -> dict[str, Any]:
    values = {name: raw[index] for index, name in enumerate(columns) if index < len(raw)}
    return {
        "subscriptionId": subscription_id,
        "usageDate": _cost_usage_date(values.get("UsageDate")),
        "cost": values.get("PreTaxCost") or values.get("Cost") or 0,
        "currency": str(values.get("Currency") or ""),
        "resourceId": str(values.get("ResourceId") or ""),
        "resourceGroup": str(values.get("ResourceGroupName") or ""),
        "serviceName": str(values.get("ServiceName") or ""),
        "billingPeriodStart": values.get("BillingPeriodStartDate") or "",
        "billingPeriodEnd": values.get("BillingPeriodEndDate") or "",
        "properties": values,
    }


def _cost_usage_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    # Cost Management does not always send a standard ``Retry-After``; its
    # throttling budget is published through vendor-specific headers instead,
    # and ignoring them made the client retry far sooner than the service
    # allows, burning the whole retry budget on guaranteed-429 attempts.
    for header in (
        "Retry-After",
        "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
        "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
        "x-ms-ratelimit-microsoft.costmanagement-client-retry-after",
    ):
        raw = response.headers.get(header)
        if not raw:
            continue
        try:
            return max(float(raw), 0.0)
        except ValueError:
            continue
    return min(2.0**attempt, 30.0)


def _load_json(text: str, source: str) -> dict:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{source} returned a non-object payload")
    return payload
