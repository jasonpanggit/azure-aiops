from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from hermes_arg_connector.queries import QuerySpec


class ResourceGraphReader(Protocol):
    def query(self, spec: QuerySpec, scope_ids: list[str]) -> list[dict]: ...


@dataclass(frozen=True)
class LiveObservation:
    """A request-time observation with freshness and provider status."""

    rows: tuple[dict, ...]
    observed_at: str
    source: str = "azure-resource-graph"
    status: str = "ok"


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
        for connection in matches:
            observation = LiveResourceProvider(
                self.reader_factory(connection), max_rows=self.max_rows
            ).get_resource(
                resource_id,
                subscription_ids=[str(connection.subscription_id)],
            )
            rows.extend(observation.rows)
            observed_at = max(observed_at, observation.observed_at)
        if len(rows) > self.max_rows:
            raise RuntimeError("Live resource provider exceeded its result bound")
        return LiveObservation(tuple(rows), observed_at)

    def query(
        self, spec: QuerySpec, *, subscription_ids: list[str]
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
        for connection in matches:
            observation = LiveResourceProvider(
                self.reader_factory(connection), max_rows=self.max_rows
            ).query(spec, subscription_ids=[str(connection.subscription_id)])
            rows.extend(observation.rows)
            observed_at = max(observed_at, observation.observed_at)
        if len(rows) > self.max_rows:
            raise RuntimeError("Live resource provider exceeded its result bound")
        return LiveObservation(tuple(rows), observed_at)

    def search_resources(
        self, query: str, *, subscription_ids: list[str]
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
        for connection in matches:
            observation = LiveResourceProvider(
                self.reader_factory(connection), max_rows=self.max_rows
            ).search_resources(
                query, subscription_ids=[str(connection.subscription_id)]
            )
            rows.extend(observation.rows)
            observed_at = max(observed_at, observation.observed_at)
        if len(rows) > self.max_rows:
            raise RuntimeError("Live resource provider exceeded its result bound")
        return LiveObservation(tuple(rows), observed_at)
