"""Connection health derived from validation results and sync freshness."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ontology.subscription_connection import (
    ConnectionHealth,
    SubscriptionConnection,
    SyncState,
)

from .validation import ValidationReport


class HealthEvaluator:
    """Combines validation status and data freshness into a ConnectionHealth record."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def from_validation(
        self,
        connection: SubscriptionConnection,
        report: ValidationReport,
    ) -> ConnectionHealth:
        previous = connection.health
        now = _iso(self.clock())
        healthy = report.passed
        status = report.status
        failure_count = 0 if healthy else (previous.failure_count + 1 if previous else 1)
        details = _validation_details(report)
        return ConnectionHealth(
            connection_id=connection.connection_id,
            status=status,
            last_checked_at=now,
            last_success_at=now if healthy else (previous.last_success_at if previous else None),
            last_failure_at=(previous.last_failure_at if previous else None) if healthy else now,
            failure_count=failure_count,
            details=details,
            healthy=healthy,
        )

    def from_sync(
        self,
        connection: SubscriptionConnection,
        state: SyncState,
    ) -> ConnectionHealth:
        previous = connection.health
        now = _iso(self.clock())
        succeeded = state.status == "succeeded"
        failure_count = 0 if succeeded else (previous.failure_count + 1 if previous else 1)
        return ConnectionHealth(
            connection_id=connection.connection_id,
            status="healthy" if succeeded else "failed",
            last_checked_at=now,
            last_success_at=now if succeeded else (previous.last_success_at if previous else None),
            last_failure_at=(previous.last_failure_at if previous else None) if succeeded else now,
            failure_count=failure_count,
            details=state.message or f"sync {state.status}",
            healthy=succeeded,
        )

    def summarize(
        self,
        connection: SubscriptionConnection,
        freshness: dict[str, Any],
    ) -> dict[str, Any]:
        """Operator-facing health summary for one connection."""
        health = connection.health
        sync_state = connection.sync_state or SyncState()
        if not connection.is_active:
            overall = "disabled"
        elif health is None:
            overall = "unknown"
        elif not health.healthy:
            overall = "unhealthy"
        elif freshness.get("stale"):
            overall = "stale"
        else:
            overall = "healthy"
        return {
            "connection_id": connection.connection_id,
            "name": connection.name,
            "subscription_id": connection.subscription_id,
            "tenant_id": connection.tenant_id,
            "is_active": connection.is_active,
            "overall": overall,
            "health": health.to_dict() if health else None,
            "sync": sync_state.to_dict(),
            "freshness": freshness,
            "evaluated_at": _iso(self.clock()),
        }


def _validation_details(report: ValidationReport) -> str:
    failures = [*report.required_failures, *report.optional_failures]
    if not failures:
        return f"all {len(report.checks)} connection checks passed"
    names = ", ".join(check.name for check in failures)
    return f"{len(failures)} of {len(report.checks)} checks failed: {names}"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = ["HealthEvaluator"]
