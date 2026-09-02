"""Regression tests for the dataset-agnostic Fabric medallion health
provider (MED-03).

Mirrors the test style of `tests/test_data_quality.py` (config loaded from a
`tmp_path` fabric.config.yaml) and `tests/test_vulnerability_intelligence.py`
(`_coverage_for_family`-style latest-per-scope reduction over raw status
rows), generalized to any Bronze/Silver/Gold/metadata table -- not just the
Defender family.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fabric.medallion_health import (
    FreshnessSloConfig,
    _freshness_slo_seconds,
    dataset_status,
)


def _clock(now: datetime):
    return lambda: now


# ---------------------------------------------------------------------------
# Task 1: per-dataset freshness-SLO configuration and evaluator
# ---------------------------------------------------------------------------


def test_freshness_slo_defaults_to_bounded_multiple_of_pipeline_cadence(tmp_path) -> None:
    """A dataset with no explicit config entry defaults to a bounded
    multiple (e.g. 3x) of its producing pipeline's configured cadence --
    never a single hardcoded global threshold."""
    config_path = tmp_path / "fabric.config.yaml"
    config_path.write_text(
        """
fabric:
  medallion_health:
    freshness_slo:
      default_cadence_minutes: 60
      default_slo_multiplier: 3
"""
    )
    config = FreshnessSloConfig.from_config(config_path)

    assert _freshness_slo_seconds("silver_unconfigured_table", config=config) == 60 * 3 * 60


def test_freshness_slo_explicit_table_override_wins_over_default(tmp_path) -> None:
    """A dataset with an explicit per-table override in config uses that
    value instead of the default multiplier."""
    config_path = tmp_path / "fabric.config.yaml"
    config_path.write_text(
        """
fabric:
  medallion_health:
    freshness_slo:
      default_cadence_minutes: 60
      default_slo_multiplier: 3
      tables:
        silver_incidents:
          cadence_minutes: 15
          slo_multiplier: 2
"""
    )
    config = FreshnessSloConfig.from_config(config_path)

    assert _freshness_slo_seconds("silver_incidents", config=config) == 15 * 2 * 60
    # Unrelated table is untouched by the override.
    assert _freshness_slo_seconds("silver_other", config=config) == 60 * 3 * 60


def test_dataset_status_freshness_fresh_under_threshold(tmp_path) -> None:
    """`observed_at` age under the computed threshold classifies `fresh`."""
    config_path = tmp_path / "fabric.config.yaml"
    config_path.write_text(
        """
fabric:
  medallion_health:
    freshness_slo:
      tables:
        silver_incidents:
          cadence_minutes: 15
"""
    )
    config = FreshnessSloConfig.from_config(config_path)
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    observed_at = "2026-01-01T11:50:00Z"  # 10 minutes old; SLO is 45 min (15*3)

    result = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "row_count": 10,
            }
        ],
        freshness_slo=config,
        clock=_clock(now),
    )

    assert result["freshness"] == "fresh"


def test_dataset_status_freshness_stale_over_threshold(tmp_path) -> None:
    """`observed_at` age over the computed threshold classifies `stale`,
    and the *same raw age* is judged independently per dataset cadence:
    a fast-cadence table goes stale while a slow-cadence table with the
    same raw age stays fresh."""
    config_path = tmp_path / "fabric.config.yaml"
    config_path.write_text(
        """
fabric:
  medallion_health:
    freshness_slo:
      tables:
        silver_incidents:
          cadence_minutes: 15
        silver_cost_trends:
          cadence_minutes: 1440
"""
    )
    config = FreshnessSloConfig.from_config(config_path)
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    # 60 minutes old: over silver_incidents' 45-minute SLO (15*3), well under
    # silver_cost_trends' 4320-minute SLO (1440*3).
    observed_at = "2026-01-01T11:00:00Z"

    fast_cadence = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "row_count": 10,
            }
        ],
        freshness_slo=config,
        clock=_clock(now),
    )
    slow_cadence = dataset_status(
        "silver_cost_trends",
        source_status=[
            {
                "source_family": "silver_cost_trends",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": observed_at,
                "ingested_at": observed_at,
                "row_count": 10,
            }
        ],
        freshness_slo=config,
        clock=_clock(now),
    )

    assert fast_cadence["freshness"] == "stale"
    assert slow_cadence["freshness"] == "fresh"


# ---------------------------------------------------------------------------
# Task 2: dataset-agnostic health provider
# ---------------------------------------------------------------------------


def test_dataset_status_healthy_with_rows(tmp_path) -> None:
    """A dataset with rows and healthy source status returns
    `availability="healthy"`."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": "2026-01-01T11:55:00Z",
                "ingested_at": "2026-01-01T11:55:00Z",
                "row_count": 42,
            }
        ],
        clock=_clock(now),
    )

    assert result["availability"] == "healthy"
    assert result["row_count"] == 42


def test_dataset_status_healthy_empty_never_unavailable_or_failed(tmp_path) -> None:
    """A dataset with zero rows and healthy source status returns
    `availability="healthy-empty"` -- never `"unavailable"` or `"failed"`."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": "2026-01-01T11:55:00Z",
                "ingested_at": "2026-01-01T11:55:00Z",
                "row_count": 0,
            }
        ],
        clock=_clock(now),
    )

    assert result["availability"] == "healthy-empty"
    assert result["availability"] not in ("unavailable", "failed")


def test_dataset_status_failed_sync_attempt(tmp_path) -> None:
    """A dataset whose last sync attempt failed returns
    `availability="failed"` regardless of row count."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "failed",
                "availability": "available",
                "quality": "degraded",
                "observed_at": "2026-01-01T11:55:00Z",
                "ingested_at": "2026-01-01T11:55:00Z",
                "row_count": 500,
                "error": "write to Delta table failed",
            }
        ],
        clock=_clock(now),
    )

    assert result["availability"] == "failed"


def test_dataset_status_unavailable_source_unreachable(tmp_path) -> None:
    """A dataset whose source/provider itself could not be reached returns
    `availability="unavailable"`, distinct from `"failed"`."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "failed",
                "availability": "unavailable",
                "quality": "degraded",
                "observed_at": "2026-01-01T11:55:00Z",
                "ingested_at": "2026-01-01T11:55:00Z",
                "row_count": 0,
                "error": "Snapshot manifest is missing",
            }
        ],
        clock=_clock(now),
    )

    assert result["availability"] == "unavailable"
    assert result["availability"] != "failed"


def test_dataset_status_merges_latest_per_scope(tmp_path) -> None:
    """`dataset_status()` merges multiple raw `source_status` rows (one per
    sync attempt/scope) down to the latest-per-scope verdict, exactly
    mirroring `_coverage_for_family`'s reduction: a stale earlier row for a
    scope is superseded by that same scope's later, healthy row, and two
    different scopes are combined rather than one silently shadowing the
    other."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    result = dataset_status(
        "silver_incidents",
        source_status=[
            # subscription "sub-a": earlier failed attempt, later succeeded.
            {
                "source_family": "silver_incidents",
                "status": "failed",
                "availability": "available",
                "quality": "degraded",
                "observed_at": "2026-01-01T10:00:00Z",
                "ingested_at": "2026-01-01T10:00:00Z",
                "requested_scope": {"subscription": ["sub-a"]},
                "row_count": 5,
            },
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": "2026-01-01T11:55:00Z",
                "ingested_at": "2026-01-01T11:55:00Z",
                "requested_scope": {"subscription": ["sub-a"]},
                "row_count": 20,
            },
            # subscription "sub-b": one healthy attempt.
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": "2026-01-01T11:50:00Z",
                "ingested_at": "2026-01-01T11:50:00Z",
                "requested_scope": {"subscription": ["sub-b"]},
                "row_count": 15,
            },
        ],
        clock=_clock(now),
    )

    # The stale/failed sub-a row is superseded by its own later success --
    # only the latest-per-scope rows drive the verdict.
    assert result["availability"] == "healthy"
    # Row counts from both scopes' latest rows are combined, not shadowed.
    assert result["row_count"] == 20 + 15


# ---------------------------------------------------------------------------
# Dataset contract completeness: watermark and timestamps
# ---------------------------------------------------------------------------


def test_dataset_status_returns_watermark_and_timestamps_from_source_rows() -> None:
    """The published contract carries the upstream checkpoint and both
    timestamps, so operators never see "watermark unknown" for a dataset the
    sync pipeline actually stamped."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    result = dataset_status(
        "bronze_resources",
        source_status=[
            {
                "source_family": "bronze_resources",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": "2026-01-01T11:50:00Z",
                "ingested_at": "2026-01-01T11:55:00Z",
                "watermark": "2026-01-01T11:45:00Z",
                "row_count": 20,
                "lineage_ref": "bronze_resources-table",
            }
        ],
        clock=_clock(now),
    )

    assert result["table_name"] == "bronze_resources"
    assert result["watermark"] == "2026-01-01T11:45:00Z"
    assert result["observed_at"] == "2026-01-01T11:50:00Z"
    assert result["ingested_at"] == "2026-01-01T11:55:00Z"
    assert result["stale_after_seconds"] > 0
    assert result["error"] == ""


def test_dataset_status_falls_back_to_ingestion_timestamp_when_no_watermark_column() -> None:
    """A pipeline that carries no distinct watermark column still reports a
    usable checkpoint rather than an alarming "unknown"."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    result = dataset_status(
        "silver_incidents",
        source_status=[
            {
                "source_family": "silver_incidents",
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": "2026-01-01T11:50:00Z",
                "ingested_at": "2026-01-01T11:50:00Z",
                "row_count": 5,
            }
        ],
        clock=_clock(now),
    )

    assert result["watermark"] == "2026-01-01T11:50:00Z"


def test_dataset_status_reports_empty_watermark_when_never_published() -> None:
    """An unregistered dataset reports an empty watermark, which the UI
    renders as "not yet published" rather than a health problem."""
    result = dataset_status("gold_missing", source_status=[])

    assert result["table_name"] == "gold_missing"
    assert result["watermark"] == ""
    assert result["availability"] == "unavailable"
