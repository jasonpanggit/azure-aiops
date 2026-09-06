"""Safe, low-cardinality operational metrics for Exposure.

The module deliberately owns the complete metric and dimension vocabulary.
Callers provide counts and bounded outcomes only; scoped identities, queries,
cursor material, vulnerability identifiers, URLs, and exception text have no
API through which they can become metric attributes.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from collections.abc import Iterable, Mapping
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
            "enrichment_score",
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
RECONCILIATION_MISMATCH_CLASSES = (
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
    "enrichment_score",
    "time_varying_enrichment_score",
)
HARD_RECONCILIATION_FAILURE_CLASSES = frozenset(
    {
        "scope_widening",
        "source_class_disappearance",
        "false_healthy_empty",
        "false_clear",
        "missing_image_relationship",
        "cursor_duplicate",
        "cursor_omission",
    }
)
EXPECTED_RECONCILIATION_CHANGE_CLASSES = frozenset(
    {"time_varying_enrichment_score"}
)


@dataclass(frozen=True)
class ExposureReconciliationPolicy:
    """Exact cutover policy for bounded old/new comparisons."""

    max_unexpected_mismatch_count: int = 0
    max_unexpected_mismatch_ratio: float = 0.0
    max_rows_per_arm: int = 10_000
    max_redacted_samples: int = 10
    hard_failure_classes: frozenset[str] = HARD_RECONCILIATION_FAILURE_CLASSES
    expected_change_classes: frozenset[str] = (
        EXPECTED_RECONCILIATION_CHANGE_CLASSES
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_unexpected_mismatch_count, bool)
            or self.max_unexpected_mismatch_count < 0
        ):
            raise ValueError(
                "max_unexpected_mismatch_count must be non-negative"
            )
        if not 0 <= self.max_unexpected_mismatch_ratio <= 1:
            raise ValueError(
                "max_unexpected_mismatch_ratio must be between zero and one"
            )
        if self.max_rows_per_arm < 1:
            raise ValueError("max_rows_per_arm must be positive")
        if self.max_redacted_samples < 0:
            raise ValueError("max_redacted_samples must be non-negative")
        unsupported_hard = set(self.hard_failure_classes) - set(
            RECONCILIATION_MISMATCH_CLASSES
        )
        unsupported_expected = set(self.expected_change_classes) - set(
            RECONCILIATION_MISMATCH_CLASSES
        )
        if unsupported_hard or unsupported_expected:
            raise ValueError("Reconciliation policy contains an unknown class")

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_unexpected_mismatch_count": (
                self.max_unexpected_mismatch_count
            ),
            "max_unexpected_mismatch_ratio": (
                self.max_unexpected_mismatch_ratio
            ),
            "max_rows_per_arm": self.max_rows_per_arm,
            "max_redacted_samples": self.max_redacted_samples,
            "hard_failure_classes": sorted(self.hard_failure_classes),
            "expected_change_classes": sorted(self.expected_change_classes),
        }


@dataclass(frozen=True)
class ExposureReconciliationReport:
    generation_id: str
    checkpoint: str
    old_count: int
    new_count: int
    compared_count: int
    mismatch_counts: dict[str, int]
    expected_change_counts: dict[str, int]
    unexpected_mismatch_count: int
    mismatch_ratio: float
    hard_failure_classes: tuple[str, ...]
    passed: bool
    blocks_cutover: bool
    policy: dict[str, Any]
    redacted_samples: tuple[dict[str, str], ...]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "generation_id": self.generation_id,
            "checkpoint": self.checkpoint,
            "old_count": self.old_count,
            "new_count": self.new_count,
            "compared_count": self.compared_count,
            "mismatch_counts": dict(self.mismatch_counts),
            "expected_change_counts": dict(self.expected_change_counts),
            "unexpected_mismatch_count": self.unexpected_mismatch_count,
            "mismatch_ratio": self.mismatch_ratio,
            "hard_failure_classes": list(self.hard_failure_classes),
            "passed": self.passed,
            "blocks_cutover": self.blocks_cutover,
            "policy": dict(self.policy),
            "redacted_samples": [
                dict(sample) for sample in self.redacted_samples
            ],
        }


def reconcile_exposure_arms(
    old_rows: Iterable[Mapping[str, Any]],
    new_rows: Iterable[Mapping[str, Any]],
    *,
    generation_id: str,
    old_completeness: str,
    new_completeness: str,
    authorized_scope_keys: Iterable[str],
    expected_changes: Mapping[tuple[str, str], Iterable[str]] | None = None,
    policy: ExposureReconciliationPolicy | None = None,
    metrics: ExposureMetrics | None = None,
    checkpoint: str = "post_publication",
) -> ExposureReconciliationReport:
    """Compare bounded scoped old/new semantics without choosing a truth arm."""

    selected_policy = policy or ExposureReconciliationPolicy()
    generation = str(generation_id or "").strip()
    if not generation:
        raise ValueError("Exposure reconciliation requires a generation_id")
    if checkpoint not in {"post_publication", "representative_read"}:
        raise ValueError("Unsupported Exposure reconciliation checkpoint")
    old = tuple(dict(row) for row in old_rows)
    new = tuple(dict(row) for row in new_rows)
    if (
        len(old) > selected_policy.max_rows_per_arm
        or len(new) > selected_policy.max_rows_per_arm
    ):
        raise ValueError("Exposure reconciliation row bound exceeded")
    for row in (*old, *new):
        if str(row.get("read_model_generation_id") or "") != generation:
            raise ValueError(
                "Exposure reconciliation rows must share one generation"
            )

    authorized = {
        str(value).strip() for value in authorized_scope_keys if str(value).strip()
    }
    if not authorized:
        raise ValueError(
            "Exposure reconciliation requires authorized scope keys"
        )
    expected = _expected_change_map(
        expected_changes,
        selected_policy=selected_policy,
    )
    counts = {name: 0 for name in RECONCILIATION_MISMATCH_CLASSES}
    expected_counts: Counter[str] = Counter()
    samples: list[dict[str, str]] = []

    old_keys = [_stable_reconciliation_key(row) for row in old]
    new_keys = [_stable_reconciliation_key(row) for row in new]
    old_counter = Counter(old_keys)
    new_counter = Counter(new_keys)
    duplicate_count = sum(
        max(0, count - 1)
        for count in (*old_counter.values(), *new_counter.values())
    )
    counts["cursor_duplicate"] = duplicate_count
    for key, count in sorted(old_counter.items()):
        if count > 1:
            _sample(samples, "cursor_duplicate", key, "old", selected_policy)
    for key, count in sorted(new_counter.items()):
        if count > 1:
            _sample(samples, "cursor_duplicate", key, "new", selected_policy)

    old_by_key = {key: row for key, row in zip(old_keys, old, strict=True)}
    new_by_key = {key: row for key, row in zip(new_keys, new, strict=True)}
    old_set = set(old_by_key)
    new_set = set(new_by_key)
    old_only = sorted(old_set - new_set)
    new_only = sorted(new_set - old_set)
    counts["stable_key"] = len(old_only) + len(new_only)
    counts["cursor_omission"] = len(old_only) + len(new_only)
    counts["count"] = abs(len(old) - len(new))
    for key in old_only:
        _sample(samples, "stable_key", key, "old_only", selected_policy)
    for key in new_only:
        _sample(samples, "stable_key", key, "new_only", selected_policy)

    unauthorized = [
        (key, side)
        for side, rows in (("old", old_by_key), ("new", new_by_key))
        for key in rows
        if key[0] not in authorized
    ]
    counts["scope_widening"] = len(unauthorized)
    for key, side in unauthorized:
        _sample(samples, "scope_widening", key, side, selected_policy)

    if len(old_keys) == len(new_keys) and old_keys != new_keys:
        counts["order"] = 1
        _sample(
            samples,
            "order",
            old_keys[0] if old_keys else ("empty", "empty"),
            "both",
            selected_policy,
        )
    if old_completeness != new_completeness:
        counts["completeness"] = 1
        _sample(
            samples,
            "completeness",
            ("aggregate", "aggregate"),
            "both",
            selected_policy,
        )
    if (
        not old
        and new
        and old_completeness == "healthy-empty"
    ) or (
        not new
        and old
        and new_completeness == "healthy-empty"
    ):
        counts["false_healthy_empty"] = 1
        _sample(
            samples,
            "false_healthy_empty",
            ("aggregate", "aggregate"),
            "both",
            selected_policy,
        )

    for key in sorted(old_set & new_set):
        old_row = old_by_key[key]
        new_row = new_by_key[key]
        _compare_field(
            counts,
            samples,
            key,
            "state",
            old_row,
            new_row,
            selected_policy,
        )
        if _is_false_clear(old_row.get("state"), new_row.get("state")):
            counts["false_clear"] += 1
            _sample(samples, "false_clear", key, "both", selected_policy)
        for field_name in (
            "completeness",
            "freshness",
            "recommendation",
            "target_kind",
        ):
            _compare_field(
                counts,
                samples,
                key,
                field_name,
                old_row,
                new_row,
                selected_policy,
            )
        old_sources = _canonical_string_set(
            old_row.get("source_families")
            or old_row.get("active_source_families")
            or (old_row.get("source_family") or (),)
        )
        new_sources = _canonical_string_set(
            new_row.get("source_families")
            or new_row.get("active_source_families")
            or (new_row.get("source_family") or (),)
        )
        if old_sources != new_sources:
            counts["source_class_disappearance"] += 1
            _sample(
                samples,
                "source_class_disappearance",
                key,
                "both",
                selected_policy,
            )
        if (
            str(old_row.get("target_kind") or "") == "container_image"
            or str(new_row.get("target_kind") or "") == "container_image"
        ) and _canonical_string_set(
            old_row.get("deployment_ids") or ()
        ) != _canonical_string_set(new_row.get("deployment_ids") or ()):
            counts["missing_image_relationship"] += 1
            _sample(
                samples,
                "missing_image_relationship",
                key,
                "both",
                selected_policy,
            )
        if old_row.get("enrichment_score") != new_row.get("enrichment_score"):
            change_class = "time_varying_enrichment_score"
            if change_class in expected.get(key, frozenset()):
                expected_counts[change_class] += 1
                counts[change_class] += 1
                _sample(
                    samples,
                    change_class,
                    key,
                    "expected",
                    selected_policy,
                )
            else:
                counts["enrichment_score"] += 1
                _sample(
                    samples,
                    "enrichment_score",
                    key,
                    "both",
                    selected_policy,
                )

    expected_total = sum(expected_counts.values())
    unexpected_count = max(0, sum(counts.values()) - expected_total)
    compared_count = len(old_set | new_set)
    mismatch_ratio = min(
        1.0,
        unexpected_count / compared_count if compared_count else (
            1.0 if unexpected_count else 0.0
        ),
    )
    hard_failures = tuple(
        sorted(
            name
            for name in selected_policy.hard_failure_classes
            if counts.get(name, 0) > 0
        )
    )
    passed = (
        not hard_failures
        and unexpected_count
        <= selected_policy.max_unexpected_mismatch_count
        and mismatch_ratio
        <= selected_policy.max_unexpected_mismatch_ratio
    )
    report = ExposureReconciliationReport(
        generation_id=generation,
        checkpoint=checkpoint,
        old_count=len(old),
        new_count=len(new),
        compared_count=compared_count,
        mismatch_counts=counts,
        expected_change_counts=dict(sorted(expected_counts.items())),
        unexpected_mismatch_count=unexpected_count,
        mismatch_ratio=mismatch_ratio,
        hard_failure_classes=hard_failures,
        passed=passed,
        blocks_cutover=not passed,
        policy=selected_policy.to_dict(),
        redacted_samples=tuple(samples),
    )
    if metrics is not None:
        completeness = (
            old_completeness
            if old_completeness == new_completeness
            else "partial"
        )
        for mismatch_class in RECONCILIATION_MISMATCH_CLASSES:
            mismatch_count = counts[mismatch_class]
            outcome = (
                "expected_change"
                if mismatch_class in expected_counts
                else "unexpected_drift"
                if mismatch_count
                else "ok"
            )
            metrics.record_reconciliation(
                mismatch_class=mismatch_class,
                mismatch_count=mismatch_count,
                compared_count=compared_count,
                outcome=outcome,
                completeness=completeness,
            )
    return report


def _expected_change_map(
    value: Mapping[tuple[str, str], Iterable[str]] | None,
    *,
    selected_policy: ExposureReconciliationPolicy,
) -> dict[tuple[str, str], frozenset[str]]:
    result: dict[tuple[str, str], frozenset[str]] = {}
    for raw_key, raw_classes in (value or {}).items():
        if not isinstance(raw_key, tuple) or len(raw_key) != 2:
            raise ValueError("Expected changes require scoped stable keys")
        key = (str(raw_key[0]).strip(), str(raw_key[1]).strip())
        classes = frozenset(str(item).strip() for item in raw_classes)
        if not classes <= selected_policy.expected_change_classes:
            raise ValueError("Expected change class is not policy-approved")
        result[key] = classes
    return result


def _stable_reconciliation_key(row: Mapping[str, Any]) -> tuple[str, str]:
    scope_key = str(row.get("scope_key") or "").strip()
    exposure_id = str(
        row.get("exposure_id")
        or row.get("current_key")
        or row.get("resource_id")
        or ""
    ).strip()
    if not scope_key or not exposure_id:
        raise ValueError(
            "Exposure reconciliation requires scope_key and stable exposure_id"
        )
    return scope_key, exposure_id


def _compare_field(
    counts: dict[str, int],
    samples: list[dict[str, str]],
    key: tuple[str, str],
    field_name: str,
    old_row: Mapping[str, Any],
    new_row: Mapping[str, Any],
    policy: ExposureReconciliationPolicy,
) -> None:
    if old_row.get(field_name) == new_row.get(field_name):
        return
    counts[field_name] += 1
    _sample(samples, field_name, key, "both", policy)


def _is_false_clear(old_state: Any, new_state: Any) -> bool:
    inactive = {"resolved", "clear", "not_affected"}
    active = {"missing", "active", "vulnerable", "reintroduced"}
    values = {str(old_state or "").casefold(), str(new_state or "").casefold()}
    return bool(values & inactive and values & active)


def _canonical_string_set(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        values = (value,)
    else:
        values = value or ()
    return frozenset(
        str(item).strip().casefold()
        for item in values
        if str(item).strip()
    )


def _sample(
    samples: list[dict[str, str]],
    mismatch_class: str,
    key: tuple[str, str],
    side: str,
    policy: ExposureReconciliationPolicy,
) -> None:
    if len(samples) >= policy.max_redacted_samples:
        return
    token = hashlib.sha256(
        f"{key[0]}\x1f{key[1]}".encode()
    ).hexdigest()[:16]
    sample = {
        "mismatch_class": mismatch_class,
        "side": side,
        "sample_token": f"redacted:{token}",
    }
    if sample not in samples:
        samples.append(sample)


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
    "EXPECTED_RECONCILIATION_CHANGE_CLASSES",
    "EXPOSURE_METRIC_SPECS",
    "HARD_RECONCILIATION_FAILURE_CLASSES",
    "RECONCILIATION_MISMATCH_CLASSES",
    "ExposureMetricSpec",
    "ExposureMetrics",
    "ExposureReconciliationPolicy",
    "ExposureReconciliationReport",
    "build_exposure_dimensions",
    "reconcile_exposure_arms",
]
