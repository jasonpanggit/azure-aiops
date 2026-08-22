"""Provider lifecycle, safe refresh, and health contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from api.providers import DEGRADED, READY, STALE, ProviderRuntime, ProviderSpec


class SnapshotProvider:
    def __init__(self, *, version: str, freshness: str) -> None:
        self.knowledge_version = version
        self.freshness = freshness


def test_refresh_loads_provider_and_reports_version():
    runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: SnapshotProvider(
                    version="ontology-v2", freshness="2026-08-22T00:00:00Z"
                )
            )
        },
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
    )

    health = runtime.refresh(force=True)

    assert runtime.get("semantic").knowledge_version == "ontology-v2"
    assert health["readiness"] == READY
    assert health["ontology_version"] == "ontology-v2"
    assert health["providers"]["semantic"]["loaded"] is True


def test_failed_refresh_retains_last_good_provider():
    attempts = 0
    first = SnapshotProvider(
        version="ontology-v1", freshness="2026-08-22T00:00:00Z"
    )

    def load():
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise ConnectionError("OneLake unavailable")
        return first

    runtime = ProviderRuntime(
        {"semantic": ProviderSpec(load)},
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
    )
    runtime.refresh(force=True)

    health = runtime.refresh(force=True)

    assert runtime.get("semantic") is first
    assert health["readiness"] == DEGRADED
    assert health["providers"]["semantic"]["loaded"] is True
    assert health["providers"]["semantic"]["retry"]["attempts"] == 1
    assert "ConnectionError" in health["providers"]["semantic"]["degraded_reason"]


def test_stale_snapshot_is_explicit():
    runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: SnapshotProvider(
                    version="ontology-v1", freshness="2026-08-20T00:00:00Z"
                )
            )
        },
        stale_after_hours=24,
        clock=lambda: datetime(2026, 8, 22, 0, 0, tzinfo=UTC),
    )

    health = runtime.refresh(force=True)

    assert health["readiness"] == STALE
    assert health["providers"]["semantic"]["state"] == STALE


def test_invalid_provider_timing_is_rejected():
    with pytest.raises(ValueError, match="refresh interval"):
        ProviderRuntime({}, refresh_interval_seconds=0)
