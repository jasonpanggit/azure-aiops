from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fabric.medallion_health import FreshnessSloConfig, dataset_status

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
POLICY = FreshnessSloConfig(default_cadence_minutes=10, default_slo_multiplier=3)


def row(connection="one", timestamp="2026-10-17T11:50:00Z", **changes):
    return {
        "source_family": "silver_incidents", "subscription_id": "sub-a", "subscription_connection": connection,
        "status": "succeeded", "quality": "complete", "observed_at": timestamp, "row_count": 5, **changes,
    }


def status(rows):
    return dataset_status("silver_incidents", source_status=rows, freshness_slo=POLICY, clock=lambda: NOW)


def test_one_fresh_connection_does_not_mask_stale_connection_or_collapse_registry_identity():
    result = status([row(timestamp="2026-10-17T11:00:00Z"), row("two")])
    assert result["freshness"] == "stale" and result["availability"] == "stale"
    assert result["row_count"] == 10
    budget = result["freshness_budget"]
    assert budget["source_count"] == budget["known_clock_count"] == 2
    assert budget["evaluated_at"] == NOW.isoformat()
    assert budget["threshold_seconds"] == 1800
    assert budget["worst_known_age_seconds"] == 3600
    assert budget["remaining_seconds"] == -1800
    assert [item["scope"]["subscription_connection"] for item in budget["sources"]] == [["one"], ["two"]]


def test_latest_within_one_authoritative_connection_replaces_its_old_status_not_other_connections():
    result = status([
        row(timestamp="2026-10-17T10:00:00Z", requested_scope={"subscription_connection": ["obsolete"]}),
        row(timestamp="2026-10-17T11:50:00Z", requested_scope={"subscription_connection": ["obsolete"]}),
        row("two", timestamp="2026-10-17T11:40:00Z"),
    ])
    assert result["freshness"] == "fresh" and result["row_count"] == 10
    assert result["freshness_budget"]["source_count"] == 2
    assert result["freshness_budget"]["remaining_seconds"] == 600
    assert result["freshness_budget"]["sources"][0]["scope"]["subscription_connection"] == ["one"]


def test_latest_clock_is_chronological_not_iso_lexicographic():
    result = status([
        row(timestamp="2026-10-17T13:00:00+02:00"),
        row(timestamp="2026-10-17T11:50:00Z", row_count=12),
    ])
    assert result["freshness"] == "fresh" and result["row_count"] == 12


@pytest.mark.parametrize("reverse", [False, True])
def test_unorderable_same_identity_clock_cannot_be_dismissed_as_old(reverse):
    rows = [row(timestamp=""), row()]
    result = status(list(reversed(rows)) if reverse else rows)
    assert result["freshness"] == "unknown"


@pytest.mark.parametrize("timestamp", ["", "invalid", "2026-10-17T12:01:00Z", "2026-10-17T11:50:00"])
def test_unreported_invalid_future_or_unzoned_clock_is_unknown_never_full_headroom(timestamp):
    result = status([row(timestamp=timestamp), row("two")])
    assert result["freshness"] == "unknown" and result["availability"] == "degraded"
    budget = result["freshness_budget"]
    assert budget["source_count"] == 2 and budget["known_clock_count"] == 1
    assert budget["remaining_seconds"] is None
    assert budget["sources"][0]["state"] == "unknown"
    assert budget["sources"][0]["age_seconds"] is None


@pytest.mark.parametrize("timestamp,state,remaining", [
    ("2026-10-17T11:30:00Z", "fresh", 0),
    ("2026-10-17T11:29:59Z", "stale", -1),
    ("2026-10-17T11:30:01Z", "fresh", 1),
    ("2026-10-17T13:30:00+02:00", "fresh", 0),
])
def test_exact_threshold_and_offset_clock_boundaries(timestamp, state, remaining):
    budget = status([row(timestamp=timestamp)])["freshness_budget"]
    assert budget["state"] == state and budget["remaining_seconds"] == remaining


def test_ingestion_clock_precedence_is_explicit_not_mislabeled_as_resource_observation():
    budget = status([row(timestamp="2026-10-17T10:00:00Z", ingested_at="2026-10-17T11:50:00Z")])["freshness_budget"]
    assert budget["clock"] == "metadata_status_ingested_then_observed_then_timestamp"
    assert budget["sources"][0]["status_at"] == "2026-10-17T11:50:00Z"
    assert budget["sources"][0]["age_seconds"] == 600


def test_no_status_rows_cannot_establish_budget_or_observed_freshness():
    result = status([])
    budget = result["freshness_budget"]
    assert result["availability"] == "unavailable"
    assert budget["state"] == "unknown" and budget["source_count"] == 0
    assert budget["remaining_seconds"] is None


def test_slo_uses_selected_config_path_and_discloses_default_or_table_policy(tmp_path, monkeypatch):
    path = tmp_path / "fabric.yaml"
    path.write_text("fabric:\n  medallion_health:\n    freshness_slo:\n      default_cadence_minutes: 30\n      tables:\n        silver_incidents:\n          cadence_minutes: 2\n          slo_multiplier: 2\n")
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(path))
    result = dataset_status("silver_incidents", source_status=[row()], clock=lambda: NOW)
    budget = result["freshness_budget"]
    assert budget["threshold_seconds"] == 240
    assert budget["policy"] == "table_override"
    assert budget["cadence_minutes"] == budget["slo_multiplier"] == 2
    assert status([row()])["freshness_budget"]["policy"] == "defaults"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, None, "not-a-number"])
def test_invalid_policy_cannot_produce_success_shaped_budget(value):
    with pytest.raises((ValueError, TypeError)):
        FreshnessSloConfig(default_cadence_minutes=value)
    with pytest.raises((ValueError, TypeError)):
        FreshnessSloConfig(tables={"silver_incidents": {"slo_multiplier": value}})


@pytest.mark.parametrize("content", [
    "fabric: [", "fabric: []", "fabric:\n  medallion_health: false",
    "fabric:\n  medallion_health:\n    freshness_slo: []",
    "fabric:\n  medallion_health:\n    freshness_slo:\n      tables:\n        silver_incidents: false",
])
def test_malformed_policy_does_not_silently_fall_back(tmp_path, content):
    path = tmp_path / "fabric.yaml"
    path.write_text(content)
    with pytest.raises((ValueError, TypeError)):
        FreshnessSloConfig.from_config(path)
