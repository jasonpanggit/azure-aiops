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


def test_cache_key_read_failure_retains_last_good_provider():
    attempts = 0
    revision_read_fails = False
    first = SnapshotProvider(
        version="ontology-v1", freshness="2026-08-22T00:00:00Z"
    )

    def load():
        nonlocal attempts
        attempts += 1
        return first

    def cache_key():
        if revision_read_fails:
            raise OSError("revision store unavailable")
        return ("policy", 7)

    runtime = ProviderRuntime(
        {"network": ProviderSpec(load, cache_key=cache_key)},
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
    )
    runtime.refresh(force=True)
    revision_read_fails = True

    assert runtime.get("network") is first
    assert attempts == 1


def test_known_newer_key_with_failed_body_serves_last_good_once():
    attempts = 0
    revision = 7
    body_available = True
    first = SnapshotProvider(
        version="policy-v7",
        freshness="2026-08-22T00:00:00Z",
    )

    def load():
        nonlocal attempts
        attempts += 1
        if not body_available:
            raise OSError("policy body unavailable")
        return first

    runtime = ProviderRuntime(
        {
            "network": ProviderSpec(
                load,
                cache_key=lambda: ("network-policy", revision),
            )
        },
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    runtime.refresh(force=True)
    revision = 8
    body_available = False

    assert runtime.get("network") is first

    health = runtime.health(refresh=False)["providers"]["network"]
    assert attempts == 2
    assert health["state"] == DEGRADED
    assert health["loaded"] is True
    assert health["cache_key_stale"] is True
    assert health["retry"]["attempts"] == 1


def test_cache_key_is_never_resolved_while_state_lock_is_held():
    lock_observations: list[bool] = []
    runtime_holder: dict[str, ProviderRuntime] = {}

    def cache_key():
        runtime = runtime_holder["runtime"]
        lock_observations.append(runtime._state_lock._is_owned())
        return ("policy", 1)

    runtime = ProviderRuntime(
        {
            "network": ProviderSpec(
                lambda: SnapshotProvider(
                    version="ontology-v1",
                    freshness="2026-08-22T00:00:00Z",
                ),
                cache_key=cache_key,
            )
        },
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
    )
    runtime_holder["runtime"] = runtime

    runtime.refresh(force=True)
    runtime.get("network")

    assert lock_observations
    assert not any(lock_observations)


def test_optional_provider_failure_does_not_block_readiness():
    runtime = ProviderRuntime(
        {
            "semantic": ProviderSpec(
                lambda: SnapshotProvider(
                    version="ontology-v1",
                    freshness="2026-08-22T00:00:00Z",
                )
            ),
            "inventory": ProviderSpec(
                lambda: (_ for _ in ()).throw(ConnectionError("OneLake busy")),
                required=False,
            ),
        },
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
    )

    health = runtime.refresh(force=True)

    assert health["readiness"] == READY
    assert health["providers"]["inventory"]["state"] == "unavailable"
    assert "ConnectionError" in health["providers"]["inventory"]["degraded_reason"]


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
