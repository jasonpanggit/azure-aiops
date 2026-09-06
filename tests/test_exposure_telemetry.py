"""Low-cardinality Exposure telemetry and alert coverage contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from api.exposure_query import (
    ExposureAuthorization,
    ExposureQuery,
    ExposureQueryService,
)
from intelligence.vulnerability.acquisition import AcquisitionSuccess, PagingProof
from onboarding.ingestion_service import activate_source_partitions
from operations.exposure_metrics import (
    EXPOSURE_METRIC_SPECS,
    ExposureMetrics,
    build_exposure_dimensions,
)


class _Instrument:
    def __init__(self, name: str, unit: str = "") -> None:
        self.name = name
        self.unit = unit
        self.records: list[tuple[float, dict[str, str]]] = []

    def add(self, value: float, attributes: dict[str, str] | None = None) -> None:
        self.records.append((float(value), dict(attributes or {})))

    def record(
        self,
        value: float,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.records.append((float(value), dict(attributes or {})))


class _Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, _Instrument] = {}

    def create_counter(self, name: str, *, unit: str = "", **_kwargs: Any) -> _Instrument:
        instrument = _Instrument(name, unit)
        self.instruments[name] = instrument
        return instrument

    def create_histogram(self, name: str, *, unit: str = "", **_kwargs: Any) -> _Instrument:
        instrument = _Instrument(name, unit)
        self.instruments[name] = instrument
        return instrument


def _records(
    meter: _Meter,
    name: str,
) -> list[tuple[float, dict[str, str]]]:
    return meter.instruments[name].records


def test_metric_schema_is_explicit_and_emits_zero_outcomes() -> None:
    meter = _Meter()
    exposure = ExposureMetrics(meter=meter, environment="prod")

    exposure.record_ingestion_cycle(
        source_family="defender_subassessment",
        target_kind="server",
        attempted_rows=0,
        effective_rows=8,
        previous_effective_rows=8,
        source_age_seconds=61,
        outcome="partial",
        completeness="stale",
    )
    exposure.record_merge(
        {"insert": 3, "update": 0, "noop": 5, "conflict": 0},
        target_kind="server",
    )
    exposure.record_enrichment(
        attempted=8,
        succeeded=6,
        target_kind="server",
        completeness="partial",
    )
    exposure.record_coverage(
        represented=6,
        total=8,
        unknown=2,
        target_kind="server",
        completeness="partial",
    )

    assert {
        name: instrument.unit for name, instrument in meter.instruments.items()
    } == {
        name: spec.unit for name, spec in EXPOSURE_METRIC_SPECS.items()
    }
    assert _records(meter, "aiops.exposure.ingestion.rows") == [
        (
            0.0,
            {
                "environment": "prod",
                "source_family": "defender_subassessment",
                "target_kind": "server",
                "outcome": "attempted",
                "completeness": "stale",
                "operation": "ingestion",
            },
        ),
        (
            8.0,
            {
                "environment": "prod",
                "source_family": "defender_subassessment",
                "target_kind": "server",
                "outcome": "effective",
                "completeness": "stale",
                "operation": "ingestion",
            },
        ),
    ]
    assert _records(meter, "aiops.exposure.ingestion.drop.rows")[-1][0] == 0
    assert _records(meter, "aiops.exposure.ingestion.drop.ratio")[-1][0] == 0
    assert {
        attributes["outcome"]: value
        for value, attributes in _records(meter, "aiops.exposure.merge.rows")
    } == {"insert": 3, "update": 0, "noop": 5, "conflict": 0}
    assert {
        attributes["outcome"]: value
        for value, attributes in _records(meter, "aiops.exposure.enrichment.items")
    } == {"attempted": 8, "succeeded": 6, "failed": 2}
    assert _records(meter, "aiops.exposure.enrichment.quality")[-1][0] == 0.75
    assert {
        attributes["outcome"]: value
        for value, attributes in _records(meter, "aiops.exposure.coverage.resources")
    } == {"represented": 6, "total": 8, "unknown": 2}
    assert _records(meter, "aiops.exposure.coverage.ratio")[-1][0] == 0.75


@pytest.mark.parametrize(
    ("dimension", "value"),
    [
        ("tenant_id", "tenant-secret"),
        ("subscription_id", "subscription-secret"),
        ("resource_id", "/subscriptions/secret"),
        ("connection_id", "connection-secret"),
        ("query", "select * from secrets"),
        ("cve", "CVE-2026-9999"),
        ("url", "https://secret.example"),
        ("cursor", "signed-secret"),
        ("error", "raw provider exception"),
    ],
)
def test_dimension_builder_rejects_scoped_and_raw_values(
    dimension: str,
    value: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match="dimension|attribute"):
        build_exposure_dimensions(environment="prod", **{dimension: value})


@pytest.mark.parametrize(
    ("dimension", "value"),
    [
        ("source_family", "subscription-123"),
        ("target_kind", "/subscriptions/secret"),
        ("outcome", "raw database exception"),
        ("completeness", "customer-a"),
        ("adapter", "https://fabric.example"),
        ("operation", "select tenant_id from gold"),
    ],
)
def test_dimension_builder_rejects_unbounded_allowlisted_values(
    dimension: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=dimension):
        build_exposure_dimensions(environment="prod", **{dimension: value})


def test_source_activation_emits_attempted_effective_drop_and_source_quality() -> None:
    meter = _Meter()
    exposure = ExposureMetrics(meter=meter, environment="test")
    attempted_at = datetime(2026, 9, 5, tzinfo=UTC)
    outcome = AcquisitionSuccess(
        connection_id="connection-sensitive",
        query_name="defender_subassessments",
        source_family="defender_subassessment",
        scope=("subscription-sensitive",),
        attempted_at=attempted_at,
        completed_at=attempted_at,
        paging=PagingProof(
            pages_fetched=1,
            page_size=100,
            max_pages=10,
            row_count=0,
            complete=True,
        ),
        watermark=None,
        sequence="1.0.0:1:0",
        rows=(),
    )

    activate_source_partitions(
        outcomes={"defender_subassessments": outcome},
        attempted_generation="generation-2",
        completed_at="2026-09-05T00:00:00Z",
        previous_partition_rows=(
            {
                "partition_key": (
                    "exposure-source-v1:"
                    "e67fc72ee394481faf78ba95"
                ),
                "query_name": "defender_subassessments",
                "row_key": "previous-row",
                "payload_json": '{"id":"old"}',
                "effective_generation": "generation-1",
            },
        ),
        previous_statuses=(
            {
                "partition_key": (
                    "exposure-source-v1:"
                    "e67fc72ee394481faf78ba95"
                ),
                "source_family": "defender_subassessment",
                "effective_generation": "generation-1",
                "completeness": "complete",
                "row_count": 1,
            },
        ),
        metrics=exposure,
    )

    all_attributes = [
        attributes
        for instrument in meter.instruments.values()
        for _value, attributes in instrument.records
    ]
    assert all(
        "connection_id" not in attributes
        and "subscription_id" not in attributes
        and "query" not in attributes
        for attributes in all_attributes
    )
    assert _records(meter, "aiops.exposure.ingestion.rows")
    assert _records(meter, "aiops.exposure.source.age")
    assert _records(meter, "aiops.exposure.source.cycles")


class _Reader:
    def query(
        self,
        sql: str,
        _parameters: tuple[Any, ...] = (),
        *,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        if "COUNT_BIG" in sql:
            return [
                {
                    "total_count": 2,
                    "freshest_at": "2026-09-05T00:00:00Z",
                    "all_complete": 1,
                }
            ]
        return [
            {"exposure_id": "one", "priority_score": 10},
            {"exposure_id": "two", "priority_score": 9},
        ][: int(max_rows or 0)]


def test_query_service_emits_count_page_latency_and_rows_without_identity() -> None:
    meter = _Meter()
    exposure = ExposureMetrics(meter=meter, environment="prod")
    clock_values = iter((1.0, 1.004, 2.0, 2.006))
    service = ExposureQueryService(
        _Reader(),
        metrics=exposure,
        clock=lambda: next(clock_values),
    )
    authorization = ExposureAuthorization(
        subject="operator@example.com",
        tenant_id="tenant-secret",
        connection_ids=("connection-secret",),
        scope={"subscription": ("subscription-secret",)},
    )

    page = service.list_page(
        authorization,
        generation_id="generation-secret",
        query=ExposureQuery(page_size=2),
    )

    assert len(page.items) == 2
    duration_records = _records(meter, "aiops.exposure.query.duration")
    assert [attributes["operation"] for _, attributes in duration_records] == [
        "count",
        "page",
    ]
    assert [value for value, _ in duration_records] == pytest.approx([4.0, 6.0])
    assert {
        attributes["operation"]: value
        for value, attributes in _records(meter, "aiops.exposure.query.rows")
    } == {"count": 2, "page": 2}
    serialized_attributes = repr(
        [attributes for _, attributes in duration_records]
    )
    for forbidden in (
        "tenant-secret",
        "connection-secret",
        "subscription-secret",
        "operator@example.com",
        "generation-secret",
    ):
        assert forbidden not in serialized_attributes


def test_query_error_emits_only_bounded_outcome() -> None:
    class FailingReader:
        def query(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            raise RuntimeError("raw query error with tenant-secret")

    meter = _Meter()
    exposure = ExposureMetrics(meter=meter, environment="prod")
    clock_values = iter((1.0, 1.001))
    service = ExposureQueryService(
        FailingReader(),
        metrics=exposure,
        clock=lambda: next(clock_values),
    )

    with pytest.raises(RuntimeError, match="raw query error"):
        service.list_page(
            ExposureAuthorization(
                subject="operator@example.com",
                tenant_id="tenant-secret",
                connection_ids=("connection-secret",),
                scope={"subscription": ("subscription-secret",)},
            ),
            generation_id="generation-secret",
            query=ExposureQuery(),
        )

    assert _records(meter, "aiops.exposure.query.events") == [
        (
            1.0,
            {
                "environment": "prod",
                "adapter": "fabric_sql",
                "operation": "count",
                "outcome": "error",
            },
        )
    ]
    assert "tenant-secret" not in repr(
        [
            record
            for instrument in meter.instruments.values()
            for record in instrument.records
        ]
    )


def test_reconciliation_metric_emits_safe_class_count_and_ratio() -> None:
    meter = _Meter()
    exposure = ExposureMetrics(meter=meter, environment="prod")

    exposure.record_reconciliation(
        mismatch_class="state",
        mismatch_count=2,
        compared_count=8,
        outcome="unexpected_drift",
        completeness="partial",
    )

    assert _records(
        meter,
        "aiops.exposure.reconciliation.mismatches",
    ) == [
        (
            2.0,
            {
                "environment": "prod",
                "adapter": "shadow",
                "operation": "reconcile",
                "outcome": "unexpected_drift",
                "completeness": "partial",
                "mismatch_class": "state",
            },
        )
    ]
    assert _records(
        meter,
        "aiops.exposure.reconciliation.drift.ratio",
    )[0][0] == 0.25


def _terraform_alert_blocks(source: str) -> dict[str, str]:
    marker = (
        'resource "azurerm_monitor_scheduled_query_rules_alert_v2" '
        '"'
    )
    chunks = source.split(marker)[1:]
    return {
        chunk.split('"', 1)[0]: chunk
        for chunk in chunks
    }


def test_every_required_metric_is_linked_to_an_exposure_alert() -> None:
    alerting = Path("infra/terraform/alerting.tf").read_text(encoding="utf-8")
    blocks = _terraform_alert_blocks(alerting)
    required = {
        "exposure_row_zero": {"aiops.exposure.ingestion.rows"},
        "exposure_row_drop": {"aiops.exposure.ingestion.drop.ratio"},
        "exposure_source_health": {
            "aiops.exposure.source.cycles",
            "aiops.exposure.source.age",
        },
        "exposure_merge_conflict": {"aiops.exposure.merge.rows"},
        "exposure_enrichment_quality": {
            "aiops.exposure.enrichment.quality"
        },
        "exposure_coverage_ratio": {"aiops.exposure.coverage.ratio"},
        "exposure_reconciliation_drift": {
            "aiops.exposure.reconciliation.mismatches",
            "aiops.exposure.reconciliation.drift.ratio",
        },
        "exposure_query_slo": {
            "aiops.exposure.query.duration",
            "aiops.exposure.query.events",
        },
    }

    assert required.keys() <= blocks.keys()
    for resource_name, metric_names in required.items():
        block = blocks[resource_name]
        assert metric_names <= set(EXPOSURE_METRIC_SPECS)
        assert all(metric_name in block for metric_name in metric_names)
        assert (
            "evaluation_frequency = "
            "local.exposure_alert_evaluation_frequency"
        ) in block
        assert (
            "window_duration      = "
            "local.exposure_ingestion_cycle_window"
        ) in block
        assert "minimum_failing_periods_to_trigger_alert = 1" in block
        assert "number_of_evaluation_periods             = 1" in block
        assert (
            "action_groups = [azurerm_monitor_action_group.ops[0].id]"
        ) in block
        assert "severity" in block


def test_alert_windows_are_exactly_one_cycle_and_evaluate_no_slower() -> None:
    alerting = Path("infra/terraform/alerting.tf").read_text(encoding="utf-8")
    variables = Path("infra/terraform/variables.tf").read_text(
        encoding="utf-8"
    )
    compact_alerting = " ".join(alerting.split())
    compact_variables = " ".join(variables.split())

    assert "exposure_ingestion_cadence_minutes" in variables
    assert "exposure_alert_evaluation_minutes" in variables
    assert (
        "var.exposure_alert_evaluation_minutes <= "
        "var.exposure_ingestion_cadence_minutes"
    ) in compact_variables
    assert (
        "exposure_ingestion_cycle_window = "
        'local.exposure_alert_iso8601_minutes[ '
        "tostring(var.exposure_ingestion_cadence_minutes) ]"
    ) in compact_alerting
    assert (
        "exposure_alert_evaluation_frequency = "
        'local.exposure_alert_iso8601_minutes[ '
        "tostring(var.exposure_alert_evaluation_minutes) ]"
    ) in compact_alerting
    assert "minimum_failing_periods_to_trigger_alert = 2" not in alerting
    assert "number_of_evaluation_periods             = 2" not in alerting


def test_alert_queries_use_only_safe_dimensions_and_configured_thresholds() -> None:
    alerting = Path("infra/terraform/alerting.tf").read_text(encoding="utf-8")
    exposure_alerts = alerting.split("# Exposure one-cycle alerts", 1)[1]

    for forbidden in (
        "tenant_id",
        "subscription_id",
        "resource_id",
        "connection_id",
        "weakness_id",
        "cve_id",
        "query_text",
        "raw_error",
        "cursor_value",
    ):
        assert forbidden not in exposure_alerts
    for required_threshold in (
        "var.exposure_alert_min_effective_rows",
        "var.exposure_alert_max_drop_ratio",
        "var.exposure_alert_source_max_age_seconds",
        "var.exposure_alert_min_enrichment_quality",
        "var.exposure_alert_min_represented_ratio",
        "var.exposure_alert_max_reconciliation_mismatches",
        "var.exposure_alert_max_reconciliation_ratio",
        "var.exposure_alert_query_p95_ms",
        "var.exposure_alert_max_query_errors",
    ):
        assert required_threshold in exposure_alerts
    assert "Properties" in exposure_alerts
    assert "environment" in exposure_alerts
