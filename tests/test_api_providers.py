"""Provider lifecycle, safe refresh, and health contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import (
    _REMEDIATION_PLANNER_REFRESH_INTERVAL_SECONDS,
    _refresh_remediation_planner,
    _start_background_refresh,
    _start_remediation_planner_refresh,
)
from api.providers import (
    DEFERRED,
    DEGRADED,
    READY,
    STALE,
    UNAVAILABLE,
    ProviderRuntime,
    ProviderSpec,
    ProviderUnavailableError,
)


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


def test_forced_refresh_skips_deferred_provider_io() -> None:
    calls: list[str] = []

    def load_exposure() -> SnapshotProvider:
        calls.append("exposure-loader")
        return SnapshotProvider(
            version="exposure-v1",
            freshness="2026-09-10T00:00:00Z",
        )

    def semantic_cache_key() -> tuple[str, int]:
        calls.append("semantic-cache-key")
        return ("semantic-generation", 7)

    def load_semantic() -> SnapshotProvider:
        calls.append("semantic-loader")
        return SnapshotProvider(
            version="ontology-v7",
            freshness="2026-09-10T00:00:00Z",
        )

    runtime = ProviderRuntime(
        {
            "exposure_query": ProviderSpec(load_exposure),
            "semantic": ProviderSpec(
                load_semantic,
                required=False,
                cache_key=semantic_cache_key,
                scheduled=False,
            ),
        },
        clock=lambda: datetime(2026, 9, 10, 0, 30, tzinfo=UTC),
    )

    health = runtime.refresh(force=True)

    assert calls == ["exposure-loader"]
    assert health["readiness"] == READY
    assert health["providers"]["exposure_query"]["loaded"] is True
    assert health["providers"]["semantic"]["loaded"] is False
    assert health["providers"]["semantic"]["state"] == DEFERRED
    assert health["providers"]["semantic"]["last_attempt_at"] == ""
    assert health["providers"]["semantic"]["retry"]["attempts"] == 0


def test_scheduled_required_providers_publish_before_optional_blocker() -> None:
    calls: list[str] = []
    optional_started = Event()
    release_optional = Event()

    def load(name: str) -> SnapshotProvider:
        calls.append(name)
        return SnapshotProvider(
            version=f"{name}-v1",
            freshness="2026-09-20T00:00:00Z",
        )

    def load_optional_blocker() -> SnapshotProvider:
        calls.append("optional_blocker")
        optional_started.set()
        assert release_optional.wait(timeout=2)
        return SnapshotProvider(
            version="optional-blocker-v1",
            freshness="2026-09-20T00:00:00Z",
        )

    runtime = ProviderRuntime(
        {
            "optional_blocker": ProviderSpec(
                load_optional_blocker,
                required=False,
            ),
            "exposure_query": ProviderSpec(lambda: load("exposure_query")),
            "optional_follower": ProviderSpec(
                lambda: load("optional_follower"),
                required=False,
            ),
            "copilot": ProviderSpec(lambda: load("copilot")),
            "deferred": ProviderSpec(
                lambda: load("deferred"),
                required=False,
                scheduled=False,
            ),
        },
        clock=lambda: datetime(2026, 9, 20, 0, 30, tzinfo=UTC),
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        refresh = pool.submit(runtime.refresh, force=True)
        assert optional_started.wait(timeout=1)
        try:
            assert calls == ["exposure_query", "copilot", "optional_blocker"]
            assert runtime.get("exposure_query").knowledge_version == "exposure_query-v1"
            assert runtime.get("copilot").knowledge_version == "copilot-v1"
            assert runtime.health(refresh=False)["readiness"] == READY
        finally:
            release_optional.set()
        health = refresh.result(timeout=1)

    assert calls == [
        "exposure_query",
        "copilot",
        "optional_blocker",
        "optional_follower",
    ]
    assert health["providers"]["deferred"]["state"] == DEFERRED
    assert health["providers"]["deferred"]["last_attempt_at"] == ""


def test_required_provider_failure_remains_fail_closed_after_priority() -> None:
    calls: list[str] = []

    def fail_required() -> SnapshotProvider:
        calls.append("required_failure")
        raise ConnectionError("required provider unavailable")

    runtime = ProviderRuntime(
        {
            "optional": ProviderSpec(
                lambda: calls.append("optional") or object(),
                required=False,
            ),
            "required_failure": ProviderSpec(fail_required),
            "required_success": ProviderSpec(
                lambda: calls.append("required_success") or object()
            ),
        },
        clock=lambda: datetime(2026, 9, 20, 0, 30, tzinfo=UTC),
    )

    health = runtime.refresh(force=True)

    assert calls == ["required_failure", "required_success", "optional"]
    assert health["readiness"] == DEGRADED
    failed = health["providers"]["required_failure"]
    assert failed["state"] == UNAVAILABLE
    assert failed["loaded"] is False
    assert failed["retry"]["attempts"] == 1
    assert failed["retry"]["next_retry_at"]
    with pytest.raises(ProviderUnavailableError):
        runtime.get("required_failure")


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


def test_get_is_a_strict_last_known_good_read_without_refresh_io() -> None:
    revision = 7
    io_calls: list[str] = []
    first = SnapshotProvider(
        version="policy-v7",
        freshness="2026-08-22T00:00:00Z",
    )

    def cache_key() -> tuple[str, int]:
        io_calls.append("cache-key")
        return ("network-policy", revision)

    def load() -> SnapshotProvider:
        io_calls.append("loader")
        return first

    runtime = ProviderRuntime(
        {"network": ProviderSpec(load, cache_key=cache_key)},
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    runtime.refresh(force=True)
    io_calls.clear()
    revision = 8

    assert runtime.get("network") is first
    assert io_calls == []


def test_concurrent_gets_do_no_io_during_background_refresh() -> None:
    revision = 7
    io_calls: list[str] = []
    refresh_started = Event()
    release_refresh = Event()
    first = SnapshotProvider(
        version="policy-v7",
        freshness="2026-08-22T00:00:00Z",
    )
    replacement = SnapshotProvider(
        version="policy-v8",
        freshness="2026-08-22T00:01:00Z",
    )

    def cache_key() -> tuple[str, int]:
        io_calls.append("cache-key")
        return ("network-policy", revision)

    def load() -> SnapshotProvider:
        io_calls.append("loader")
        if revision == 8:
            refresh_started.set()
            assert release_refresh.wait(timeout=2)
            return replacement
        return first

    runtime = ProviderRuntime(
        {"network": ProviderSpec(load, cache_key=cache_key)},
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )
    runtime.refresh(force=True)
    revision = 8

    with ThreadPoolExecutor(max_workers=5) as pool:
        refresh = pool.submit(runtime.refresh, force=True)
        assert refresh_started.wait(timeout=1)
        calls_before_reads = len(io_calls)
        try:
            readers = [pool.submit(runtime.get, "network") for _ in range(4)]
            assert [reader.result(timeout=0.5) for reader in readers] == [
                first,
                first,
                first,
                first,
            ]
            assert len(io_calls) == calls_before_reads
        finally:
            release_refresh.set()
        refresh.result(timeout=1)

    assert runtime.get("network") is replacement


def test_initial_get_during_background_startup_does_not_duplicate_io() -> None:
    io_calls: list[str] = []
    startup_refresh_started = Event()
    release_startup_refresh = Event()
    provider = SnapshotProvider(
        version="ontology-v1",
        freshness="2026-08-22T00:00:00Z",
    )

    def cache_key() -> tuple[str, int]:
        io_calls.append("cache-key")
        return ("fabric-generation", 1)

    def load() -> SnapshotProvider:
        io_calls.append("loader")
        startup_refresh_started.set()
        assert release_startup_refresh.wait(timeout=2)
        return provider

    runtime = ProviderRuntime(
        {"network": ProviderSpec(load, cache_key=cache_key)},
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
        monotonic=lambda: 0.0,
    )

    app = FastAPI()
    _start_background_refresh(
        app,
        SimpleNamespace(provider_runtime=runtime),
    )
    assert startup_refresh_started.wait(timeout=1)
    calls_before_get = len(io_calls)
    try:
        assert runtime.get("network", optional=True) is None
        assert len(io_calls) == calls_before_get
    finally:
        app.state.provider_refresh_stop.set()
        release_startup_refresh.set()
        app.state.provider_refresh_thread.join(timeout=1)

    assert not app.state.provider_refresh_thread.is_alive()
    assert runtime.get("network") is provider


def test_remediation_planner_is_warmed_before_requests() -> None:
    calls: list[list[str]] = []
    app = FastAPI()
    context = SimpleNamespace(
        onboarding=SimpleNamespace(
            registry=SimpleNamespace(
                list=lambda *, include_disabled: [
                    SimpleNamespace(subscription_id="sub-b"),
                    SimpleNamespace(subscription_id="sub-a"),
                    SimpleNamespace(subscription_id="sub-a"),
                ]
            )
        ),
        hybrid_remediation_provider=lambda subscriptions: calls.append(subscriptions),
    )

    _start_remediation_planner_refresh(app, context)

    with TestClient(app):
        assert calls == [["sub-a", "sub-b"]]
        assert _REMEDIATION_PLANNER_REFRESH_INTERVAL_SECONDS == 30
        assert app.state.remediation_planner_refresh_thread.is_alive()

    assert not app.state.remediation_planner_refresh_thread.is_alive()


def test_remediation_planner_refresh_reuses_the_warmed_subscription_scope() -> None:
    calls: list[list[str]] = []
    context = SimpleNamespace(
        onboarding=SimpleNamespace(
            registry=SimpleNamespace(
                list=lambda *, include_disabled: [
                    SimpleNamespace(subscription_id="sub-b"),
                    SimpleNamespace(subscription_id="sub-a"),
                    SimpleNamespace(subscription_id="sub-a"),
                ]
            )
        ),
        hybrid_remediation_provider=lambda subscriptions: calls.append(subscriptions),
    )

    _refresh_remediation_planner(context)
    _refresh_remediation_planner(context)

    assert calls == [["sub-a", "sub-b"], ["sub-a", "sub-b"]]


def test_unchanged_cache_key_skips_periodic_provider_rebuild() -> None:
    attempts = 0
    revision = 7
    elapsed = [0.0]

    def load() -> SnapshotProvider:
        nonlocal attempts
        attempts += 1
        return SnapshotProvider(
            version=f"policy-v{revision}",
            freshness="2026-08-22T00:00:00Z",
        )

    runtime = ProviderRuntime(
        {
            "network": ProviderSpec(
                load,
                cache_key=lambda: ("network-policy", revision),
            )
        },
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
        monotonic=lambda: elapsed[0],
    )

    runtime.refresh(force=True)
    elapsed[0] = 31.0
    runtime.refresh()

    assert attempts == 1
    assert runtime.get("network").knowledge_version == "policy-v7"


def test_changed_cache_key_rebuilds_once_and_force_overrides_key() -> None:
    attempts = 0
    revision = 7
    elapsed = [0.0]

    def load() -> SnapshotProvider:
        nonlocal attempts
        attempts += 1
        return SnapshotProvider(
            version=f"policy-v{revision}",
            freshness="2026-08-22T00:00:00Z",
        )

    runtime = ProviderRuntime(
        {
            "network": ProviderSpec(
                load,
                cache_key=lambda: ("network-policy", revision),
            )
        },
        clock=lambda: datetime(2026, 8, 22, 0, 30, tzinfo=UTC),
        monotonic=lambda: elapsed[0],
    )
    runtime.refresh(force=True)

    revision = 8
    elapsed[0] = 31.0
    runtime.refresh()
    elapsed[0] = 62.0
    runtime.refresh()
    runtime.refresh(force=True)

    assert attempts == 3
    assert runtime.get("network").knowledge_version == "policy-v8"


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

    runtime.refresh(force=True)
    assert runtime.get("network") is first

    health = runtime.health(refresh=False)["providers"]["network"]
    assert attempts == 2
    assert health["state"] == DEGRADED
    assert health["loaded"] is True
    assert health["cache_key_stale"] is True
    assert health["retry"]["attempts"] == 1


def test_concurrent_changed_key_failure_has_one_background_refresh_owner():
    attempts = 0
    revision = 7
    body_available = True
    failed_load_started = Event()
    release_failed_load = Event()
    first = SnapshotProvider(
        version="policy-v7",
        freshness="2026-08-22T00:00:00Z",
    )

    def load():
        nonlocal attempts
        attempts += 1
        if body_available:
            return first
        failed_load_started.set()
        assert release_failed_load.wait(timeout=2)
        raise OSError("policy body unavailable")

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

    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh_owner = pool.submit(runtime.refresh, force=True)
        assert failed_load_started.wait(timeout=1)
        concurrent_reader = pool.submit(runtime.get, "network")
        try:
            retained = concurrent_reader.result(timeout=0.5)
        finally:
            release_failed_load.set()
        refresh_owner.result(timeout=1)

    health = runtime.health(refresh=False)["providers"]["network"]
    assert retained is first
    assert runtime.get("network") is first
    assert attempts == 2
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
