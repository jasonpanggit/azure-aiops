from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from intelligence.vulnerability.acquisition import (
    classify_provider_error,
    safe_error_summary,
)
from onboarding.query_contract import QuerySpec


class ResourceGraphReader(Protocol):
    def query(self, spec: QuerySpec, scope_ids: list[str]) -> list[dict]: ...


@dataclass(frozen=True)
class LiveObservation:
    """A request-time observation with freshness and provider status."""

    rows: tuple[dict, ...]
    observed_at: str
    source: str = "azure-resource-graph"
    status: str = "ok"
    source_status: tuple[LiveConnectionStatus, ...] = ()
    represented_count: int = 0
    expected_count: int = 0
    completeness: str = "complete"


@dataclass(frozen=True)
class LiveConnectionStatus:
    """Secret-free outcome for one authorized connection and source family."""

    connection_id: str
    display_name: str
    source_family: str
    status: str
    completeness: str
    represented_count: int
    expected_count: int = 1
    safe_error_code: str = ""
    safe_error_summary: str = ""
    observed_at: str = ""


class LiveResourceProvider:
    """Fetch current Azure resource state without writing a source snapshot."""

    def __init__(self, reader: ResourceGraphReader, *, max_rows: int = 100) -> None:
        if max_rows < 1:
            raise ValueError("Live resource max_rows must be positive")
        self.reader = reader
        self.max_rows = max_rows

    def get_resource(
        self, resource_id: str, *, subscription_ids: list[str]
    ) -> LiveObservation:
        if not resource_id.strip():
            raise ValueError("Live resource id is required")
        if not subscription_ids:
            raise ValueError("Live resource reads require subscription scope")
        escaped_id = resource_id.replace("'", "''")
        spec = QuerySpec(
            name="live_resource",
            table="Resources",
            query=(
                "Resources "
                f"| where id =~ '{escaped_id}' "
                "| project id, name, type, tenantId, subscriptionId, "
                "resourceGroup, location, tags, properties"
            ),
            incremental=False,
        )
        rows = self.reader.query(spec, subscription_ids)
        if len(rows) > self.max_rows:
            raise RuntimeError("Live resource provider exceeded its result bound")
        return LiveObservation(
            rows=tuple(rows),
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def query(
        self, spec: QuerySpec, *, subscription_ids: list[str]
    ) -> LiveObservation:
        """Execute a bounded request-time ARG query without persisting its rows."""
        if not subscription_ids:
            raise ValueError("Live resource queries require subscription scope")
        rows = self.reader.query(spec, subscription_ids)
        if len(rows) > self.max_rows:
            raise RuntimeError("Live resource provider exceeded its result bound")
        return LiveObservation(
            rows=tuple(rows),
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )

    def search_resources(
        self, query: str, *, subscription_ids: list[str]
    ) -> LiveObservation:
        if not query.strip():
            raise ValueError("Live resource search query is required")
        if not subscription_ids:
            raise ValueError("Live resource searches require subscription scope")
        search_term = query
        if query.casefold().startswith("show list of"):
            search_term = query[len("show list of") :].strip()
        escaped = search_term.replace("'", "''")
        spec = QuerySpec(
            name="live_resource_search",
            table="Resources",
            query=(
                "Resources "
                f"| where name contains~ '{escaped}' or type contains~ '{escaped}' "
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, "
                "location, tags, properties"
            ),
            incremental=False,
        )
        rows = self.reader.query(spec, subscription_ids)
        if len(rows) > self.max_rows:
            raise RuntimeError("Live resource provider exceeded its result bound")
        return LiveObservation(
            rows=tuple(rows),
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )


class ConnectionScopedLiveResourceProvider:
    """Resolve ARG credentials per registered connection and query live state."""

    def __init__(
        self,
        connections: Callable[[], list[Any]],
        reader_factory: Callable[[Any], ResourceGraphReader],
        *,
        max_rows: int = 100,
    ) -> None:
        self.connections = connections
        self.reader_factory = reader_factory
        self.max_rows = max_rows

    def get_resource(
        self, resource_id: str, *, subscription_ids: list[str]
    ) -> LiveObservation:
        return self._collect(
            subscription_ids=subscription_ids,
            source_family="azure_resource",
            operation=lambda provider, connection: provider.get_resource(
                resource_id,
                subscription_ids=[str(connection.subscription_id)],
            ),
        )

    def query(
        self, spec: QuerySpec, *, subscription_ids: list[str]
    ) -> LiveObservation:
        return self._collect(
            subscription_ids=subscription_ids,
            source_family=spec.source_family or spec.name,
            operation=lambda provider, connection: provider.query(
                spec,
                subscription_ids=[str(connection.subscription_id)],
            ),
        )

    def search_resources(
        self, query: str, *, subscription_ids: list[str]
    ) -> LiveObservation:
        return self._collect(
            subscription_ids=subscription_ids,
            source_family="azure_resource",
            operation=lambda provider, connection: provider.search_resources(
                query,
                subscription_ids=[str(connection.subscription_id)],
            ),
        )

    def _collect(
        self,
        *,
        subscription_ids: list[str],
        source_family: str,
        operation: Callable[[LiveResourceProvider, Any], LiveObservation],
    ) -> LiveObservation:
        matches = [
            connection
            for connection in self.connections()
            if getattr(connection, "is_active", True)
            and str(getattr(connection, "subscription_id", "")) in subscription_ids
        ]
        if not matches:
            raise ValueError("No active connection matches the requested subscription scope")
        rows: list[dict] = []
        observed_at = ""
        statuses: list[LiveConnectionStatus] = []
        for index, connection in enumerate(matches):
            connection_id = str(
                getattr(connection, "connection_id", "") or f"connection-{index + 1}"
            )
            display_name = _safe_connection_display_name(
                connection,
                fallback=connection_id,
            )
            try:
                observation = operation(
                    LiveResourceProvider(
                        self.reader_factory(connection),
                        max_rows=self.max_rows,
                    ),
                    connection,
                )
                if len(rows) + len(observation.rows) > self.max_rows:
                    raise RuntimeError(
                        "Live resource provider exceeded its result bound"
                    )
            except Exception as exc:  # noqa: BLE001 - isolate one connection
                code = classify_provider_error(exc)
                statuses.append(
                    LiveConnectionStatus(
                        connection_id=connection_id,
                        display_name=display_name,
                        source_family=source_family,
                        status="failed",
                        completeness="unavailable",
                        represented_count=0,
                        safe_error_code=code.value,
                        safe_error_summary=safe_error_summary(code),
                    )
                )
                continue
            rows.extend(observation.rows)
            observed_at = max(observed_at, observation.observed_at)
            statuses.append(
                LiveConnectionStatus(
                    connection_id=connection_id,
                    display_name=display_name,
                    source_family=source_family,
                    status="succeeded",
                    completeness=(
                        "healthy-empty" if not observation.rows else "complete"
                    ),
                    represented_count=1,
                    observed_at=observation.observed_at,
                )
            )

        represented = sum(item.represented_count for item in statuses)
        expected = len(statuses)
        if represented == 0:
            completeness = "unavailable"
        elif represented < expected:
            completeness = "partial"
        elif statuses and all(
            item.completeness == "healthy-empty" for item in statuses
        ):
            completeness = "healthy-empty"
        else:
            completeness = "complete"
        return LiveObservation(
            rows=tuple(rows),
            observed_at=observed_at,
            status=(
                "ok"
                if completeness in {"complete", "healthy-empty"}
                else completeness
            ),
            source_status=tuple(statuses),
            represented_count=represented,
            expected_count=expected,
            completeness=completeness,
        )


def _safe_connection_display_name(connection: Any, *, fallback: str) -> str:
    for field in ("display_name", "name", "connection_name"):
        value = " ".join(str(getattr(connection, field, "") or "").split())
        if value:
            return value[:128]
    return " ".join(str(fallback).split())[:128] or "connection"
