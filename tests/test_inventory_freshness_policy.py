"""Approved daily inventory freshness policy, independent of publication readiness."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fabric.medallion_health import FreshnessSloConfig, dataset_status

CONFIG = Path(__file__).resolve().parents[1] / "fabric.config.deploy.yaml"
TABLES = ("bronze_resources", "silver_vm_inventory")
NOW = datetime(2026, 10, 28, 14, 30, tzinfo=UTC)


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    ("age_seconds", "freshness"),
    [(24 * 3600, "fresh"), (26 * 3600, "fresh"), (26 * 3600 + 1, "stale")],
)
def test_daily_inventory_freshness_boundary(table, age_seconds, freshness):
    config = FreshnessSloConfig.from_config(CONFIG)
    observed = (NOW - timedelta(seconds=age_seconds)).isoformat()
    result = dataset_status(
        table,
        source_status=[
            {
                "source_family": table,
                "status": "succeeded",
                "availability": "available",
                "quality": "complete",
                "observed_at": observed,
                "ingested_at": observed,
                "row_count": 1,
            }
        ],
        freshness_slo=config,
        clock=lambda: NOW,
    )
    assert config.slo_seconds(table) == 93600
    assert result["freshness"] == freshness


def test_inventory_policy_does_not_relax_other_producers():
    config = FreshnessSloConfig.from_config(CONFIG)
    assert set(config.tables) == set(TABLES)
    for table in ("gold_exposure_current", "silver_incidents", "unknown_product"):
        assert config.slo_seconds(table) == 10800


@pytest.mark.parametrize("table", TABLES)
def test_daily_policy_does_not_turn_missing_evidence_into_success(table):
    result = dataset_status(
        table,
        freshness_slo=FreshnessSloConfig.from_config(CONFIG),
        clock=lambda: NOW,
    )
    assert result["freshness"] == "unknown"
    assert result["availability"] != "healthy"


@pytest.mark.parametrize("table", TABLES)
def test_daily_policy_preserves_failed_publication_status(table):
    result = dataset_status(
        table,
        source_status=[
            {
                "source_family": table,
                "status": "failed",
                "availability": "failed",
                "quality": "incomplete",
                "observed_at": NOW.isoformat(),
                "row_count": 1,
            }
        ],
        freshness_slo=FreshnessSloConfig.from_config(CONFIG),
        clock=lambda: NOW,
    )
    assert result["availability"] == "failed"
