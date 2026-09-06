"""Safe, low-cardinality operational metrics for Exposure.

The module deliberately owns the complete metric and dimension vocabulary.
Callers provide counts and bounded outcomes only; scoped identities, queries,
cursor material, vulnerability identifiers, URLs, and exception text have no
API through which they can become metric attributes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics


@dataclass(frozen=True)
class ExposureMetricSpec:
    unit: str
    instrument: str
    description: str


EXPOSURE_METRIC_SPECS: dict[str, ExposureMetricSpec] = {
    "aiops.exposure.ingestion.rows": ExposureMetricSpec(
        unit="{row}",
        instrument="histogram",
        description="Attempted and effective Exposure rows per source cycle",
    ),
    "aiops.exposure.ingestion.drop.rows": ExposureMetricSpec(
        unit="{row}",
        instrument="histogram",
        description="Absolute effective-row drop from last known good",
    ),
    "aiops.exposure.ingestion.drop.ratio": ExposureMetricSpec(
        unit="1",
        instrument="histogram",
        description="Effective-row drop ratio from last known good",
    ),
    "aiops.exposure.source.age": ExposureMetricSpec(
        unit="s",
        instrument="histogram",
        description="Age of the effective source-family data",
    ),
    "aiops.exposure.source.cycles": ExposureMetricSpec(
        unit="{cycle}",
        instrument="counter",
        description="Exposure source-family ingestion cycle outcomes",
    ),
    "aiops.exposure.merge.rows": ExposureMetricSpec(
        unit="{row}",
        instrument="histogram",
        description="Exposure publication merge outcomes",
    ),
    "aiops.exposure.enrichment.items": ExposureMetricSpec(
        unit="{item}",
        instrument="histogram",
        description="Attempted, successful, and failed enrichment items",
    ),
    "aiops.exposure.enrichment.quality": ExposureMetricSpec(
        unit="1",
        instrument="histogram",
        description="Successful enrichment ratio",
    ),
    "aiops.exposure.coverage.resources": ExposureMetricSpec(
        unit="{resource}",
        instrument="histogram",
        description="Represented, total, and unknown Exposure resources",
    ),
    "aiops.exposure.coverage.ratio": ExposureMetricSpec(
        unit="1",
        instrument="histogram",
        description="Represented Exposure resource ratio",
    ),
    "aiops.exposure.reconciliation.mismatches": ExposureMetricSpec(
        unit="{mismatch}",
        instrument="histogram",
        description="Old/new Exposure semantic mismatches",
    ),
    "aiops.exposure.reconciliation.drift.ratio": ExposureMetricSpec(
        unit="1",
        instrument="histogram",
        description="Old/new Exposure semantic mismatch ratio",
    ),
    "aiops.exposure.query.duration": ExposureMetricSpec(
        unit="ms",
        instrument="histogram",
        description="Scoped Exposure count, facet, page, and cursor latency",
    ),
    "aiops.exposure.query.rows": ExposureMetricSpec(
        unit="{row}",
        instrument="histogram",
        description="Rows returned by a scoped Exposure query operation",
    ),
    "aiops.exposure.query.events": ExposureMetricSpec(
        unit="{event}",
        instrument="counter",
        description="Scoped Exposure query outcomes and cursor restarts",
    ),
}

_DIMENSION_VALUES: dict[str, frozenset[str]] = {
    "environment": frozenset(
        {"dev", "test", "stage", "prod", "local", "unknown"}
    ),
    "source_family": frozenset(
        {
            "azure_update_manager_missing",
            "defender_subassessment",
            "defender_image",
            "workloads",
            "enrichment",
            "all",
            "unknown",
        }
    ),
    "target_kind": frozenset({"server", "container_image", "all", "unknown"}),
    "outcome": frozenset(
        {
            "attempted",
            "effective",
            "dropped",
            "succeeded",
            "failed",
            "partial",
            "unavailable",
            "insert",
            "update",
            "noop",
            "conflict",
            "represented",
            "total",
            "unknown",
            "ok",
            "error",
            "restart",
            "expected_change",
            "unexpected_drift",
        }
    ),
    "completeness": frozenset(
        {
            "complete",
            "healthy-empty",
            "stale",
            "partial",
            "unavailable",
            "unknown",
        }
    ),
    "adapter": frozenset(
        {"fabric_sql", "delta", "legacy", "gold", "shadow", "unknown"}
    ),
    "operation": frozenset(
        {
            "ingestion",
            "source",
            "merge",
            "enrichment",
            "coverage",
            "count",
            "facet",
            "page",
            "cursor",
            "publish",
            "reconcile",
            "shadow_read",
        }
    ),
    "mismatch_class": frozenset(
        {
            "none",
            "scope_widening",
            "source_class_disappearance",
            "false_healthy_empty",
            "false_clear",
            "missing_image_relationship",
            "cursor_duplicate",
            "cursor_omission",
            "stable_key",
            "state",
            "order",
            "count",
            "completeness",
            "freshness",
            "recommendation",
            "target_kind",
            "time_varying_enrichment_score",
        }
    ),
}
_ENVIRONMENT_ALIASES = {
    "development": "dev",
    "testing": "test",
    "staging": "stage",
    "production": "prod",
}
_MERGE_OUTCOMES = ("insert", "update", "noop", "conflict")


def build_exposure_dimensions(**dimensions: Any) -> dict[str, str]:
    """Build attributes from the closed Exposure telemetry vocabulary.

    This intentionally accepts no arbitrary pass-through mapping. Hashing a
    forbidden value does not make it acceptable: both dimension names and
    values must be members of the finite allowlists above.
    """

    unexpected = sorted(set(dimensions) - set(_DIMENSION_VALUES))
    if unexpected:
        raise TypeError(
            f"Unsupported Exposure metric dimension/attribute: {unexpected[0]}"
        )
    result: dict[str, str] = {}
    for name, raw_value in dimensions.items():
        if raw_value is None:
            continue
        value = str(raw_value).strip().casefold()
        if name == "environment":
            value = _ENVIRONMENT_ALIASES.get(value, value)
        if value not in _DIMENSION_VALUES[name]:
            raise ValueError(
                f"Unsupported Exposure metric {name} value: {value!r}"
            )
        result[name] = value
    return result


class ExposureMetrics:
    """Typed Exposure instruments with a closed low-cardinality schema."""

    def __init__(
        self,
        meter: Any = None,
        *,
        environment: str | None = None,
    ) -> None:
        self._meter = meter or metrics.get_meter(
            "aiops.operations.exposure",
            "1.0.0",
        )
        self._environment = _environment(environment)
        self._instruments: dict[str, Any] = {}
        for name, spec in EXPOSURE_METRIC_SPECS.items():
            factory = getattr(self._meter, f"create_{spec.instrument}")
            self._instruments[name] = factory(
                name,
                unit=spec.unit,
                description=spec.description,
            )

    def record_ingestion_cycle(
        self,
        *,
        source_family: str,
        target_kind: str,
        attempted_rows: int,
        effective_rows: int,
        previous_effective_rows: int,
        source_age_seconds: float,
        outcome: str,
        completeness: str,
    ) -> None:
        attempted = _count(attempted_rows, "attempted_rows")
        effective = _count(effective_rows, "effective_rows")
        previous = _count(
            previous_effective_rows,
            "previous_effective_rows",
        )
        age = _number(source_age_seconds, "source_age_seconds")
        dimensions = {
            "environment": self._environment,
            "source_family": source_family,
            "target_kind": target_kind,
            "completeness": completeness,
            "operation": "ingestion",
        }
        for row_outcome, value in (
            ("attempted", attempted),
            ("effective", effective),
        ):
            self._record(
                "aiops.exposure.ingestion.rows",
                value,
                **dimensions,
                outcome=row_outcome,
            )
        dropped = max(0, previous - effective)
        ratio = dropped / previous if previous else 0.0
        self._record(
            "aiops.exposure.ingestion.drop.rows",
            dropped,
            **dimensions,
            outcome="dropped",
        )
        self._record(
            "aiops.exposure.ingestion.drop.ratio",
            ratio,
            **dimensions,
            outcome="dropped",
        )
        source_dimensions = {
            "environment": self._environment,
            "source_family": source_family,
            "target_kind": target_kind,
            "outcome": outcome,
            "completeness": completeness,
            "operation": "source",
        }
        self._record(
            "aiops.exposure.source.age",
            age,
            **source_dimensions,
        )
        self._add(
            "aiops.exposure.source.cycles",
            1,
            **source_dimensions,
        )

    def record_merge(
        self,
        outcomes: Mapping[str, int],
        *,
        target_kind: str = "all",
    ) -> None:
        unexpected = sorted(set(outcomes) - set(_MERGE_OUTCOMES))
        if unexpected:
            raise ValueError(f"Unsupported Exposure merge outcome: {unexpected[0]}")
        for outcome in _MERGE_OUTCOMES:
            self._record(
                "aiops.exposure.merge.rows",
                _count(outcomes.get(outcome, 0), f"merge {outcome}"),
                environment=self._environment,
                target_kind=target_kind,
                outcome=outcome,
                operation="merge",
            )

    def record_enrichment(
        self,
        *,
        attempted: int,
        succeeded: int,
        target_kind: str = "all",
        completeness: str = "unknown",
    ) -> None:
        attempted_count = _count(attempted, "enrichment attempted")
        succeeded_count = _count(succeeded, "enrichment succeeded")
        if succeeded_count > attempted_count:
            raise ValueError("enrichment succeeded cannot exceed attempted")
        failed_count = attempted_count - succeeded_count
        dimensions = {
            "environment": self._environment,
            "target_kind": target_kind,
            "completeness": completeness,
            "operation": "enrichment",
        }
        for outcome, value in (
            ("attempted", attempted_count),
            ("succeeded", succeeded_count),
            ("failed", failed_count),
        ):
            self._record(
                "aiops.exposure.enrichment.items",
                value,
                **dimensions,
                outcome=outcome,
            )
        self._record(
            "aiops.exposure.enrichment.quality",
            succeeded_count / attempted_count if attempted_count else 0.0,
            **dimensions,
            outcome="succeeded",
        )

    def record_coverage(
        self,
        *,
        represented: int,
        total: int,
        unknown: int,
        target_kind: str = "all",
        completeness: str = "unknown",
    ) -> None:
        represented_count = _count(represented, "represented")
        total_count = _count(total, "total")
        unknown_count = _count(unknown, "unknown")
        if represented_count > total_count or unknown_count > total_count:
            raise ValueError("Exposure coverage counts cannot exceed total")
        dimensions = {
            "environment": self._environment,
            "target_kind": target_kind,
            "completeness": completeness,
            "operation": "coverage",
        }
        for outcome, value in (
            ("represented", represented_count),
            ("total", total_count),
            ("unknown", unknown_count),
        ):
            self._record(
                "aiops.exposure.coverage.resources",
                value,
                **dimensions,
                outcome=outcome,
            )
        self._record(
            "aiops.exposure.coverage.ratio",
            represented_count / total_count if total_count else 0.0,
            **dimensions,
            outcome="represented",
        )

    def record_reconciliation(
        self,
        *,
        mismatch_class: str,
        mismatch_count: int,
        compared_count: int,
        outcome: str,
        completeness: str,
        adapter: str = "shadow",
    ) -> None:
        mismatches = _count(mismatch_count, "mismatch_count")
        compared = _count(compared_count, "compared_count")
        dimensions = {
            "environment": self._environment,
            "adapter": adapter,
            "operation": "reconcile",
            "outcome": outcome,
            "completeness": completeness,
            "mismatch_class": mismatch_class,
        }
        self._record(
            "aiops.exposure.reconciliation.mismatches",
            mismatches,
            **dimensions,
        )
        self._record(
            "aiops.exposure.reconciliation.drift.ratio",
            mismatches / compared if compared else (1.0 if mismatches else 0.0),
            **dimensions,
        )

    def record_query(
        self,
        *,
        operation: str,
        duration_ms: float,
        rows_returned: int,
        outcome: str,
        adapter: str = "fabric_sql",
    ) -> None:
        dimensions = {
            "environment": self._environment,
            "adapter": adapter,
            "operation": operation,
            "outcome": outcome,
        }
        self._record(
            "aiops.exposure.query.duration",
            _number(duration_ms, "query duration_ms"),
            **dimensions,
        )
        self._record(
            "aiops.exposure.query.rows",
            _count(rows_returned, "query rows_returned"),
            **dimensions,
        )
        self._add(
            "aiops.exposure.query.events",
            1,
            **dimensions,
        )

    def record_query_event(
        self,
        *,
        operation: str,
        outcome: str,
        adapter: str = "fabric_sql",
    ) -> None:
        self._add(
            "aiops.exposure.query.events",
            1,
            environment=self._environment,
            adapter=adapter,
            operation=operation,
            outcome=outcome,
        )

    def _record(self, name: str, value: float, **dimensions: Any) -> None:
        self._instruments[name].record(
            value,
            build_exposure_dimensions(**dimensions),
        )

    def _add(self, name: str, value: float, **dimensions: Any) -> None:
        self._instruments[name].add(
            value,
            build_exposure_dimensions(**dimensions),
        )


def _environment(value: str | None) -> str:
    candidate = value if value is not None else os.getenv("AIOPS_ENVIRONMENT", "")
    normalized = str(candidate or "unknown").strip().casefold()
    normalized = _ENVIRONMENT_ALIASES.get(normalized, normalized)
    return normalized if normalized in _DIMENSION_VALUES["environment"] else "unknown"


def _count(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Exposure {field_name} must be a non-negative integer")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"Exposure {field_name} must be non-negative")
    return float(value)


__all__ = [
    "EXPOSURE_METRIC_SPECS",
    "ExposureMetricSpec",
    "ExposureMetrics",
    "build_exposure_dimensions",
]
