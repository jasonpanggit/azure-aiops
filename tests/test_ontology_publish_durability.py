"""Durability and telemetry regression tests for ontology publish (MED-01).

Covers the remaining "durable state and telemetry" half of MED-01 -- the
preflight-validation half (`OntologyPublisher.build_definition()` running
before any Fabric network call) was already proven in Plan 10-01. This file
proves:

- Every publish outcome (preflight-rejected, retryable-failed, succeeded)
  produces a durable `PublicationAttemptRecord` via
  `ontology.publication_state.PublicationStateStore`
  (`ConnectionSyncCoordinator._record_publication_attempt`).
- Those records survive a fresh `PublicationStateStore` instance reading the
  same backing store (not merely in-memory).
- `FabricMetrics.publish_preflight_rejected`/`publish_retry` increment on the
  matching code paths, with no PII/payload attributes recorded.
- `manager.resolve()` is never invoked when `build_definition()` raises --
  the same preflight-ordering invariant
  `tests/test_relationship_vocabulary_consistency.py` asserts directly
  against `OntologyPublisher`, re-asserted here end-to-end through
  `ConnectionSyncCoordinator`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from onboarding.sync import ConnectionSyncCoordinator
from ontology.ontology_publisher import OntologyPublisher
from ontology.publication_state import DEFAULT_ONTOLOGY_NAME, PublicationStateStore
from ontology.subscription_connection import SubscriptionConnection

_MANIFEST: dict = {
    "queryVersion": "1.0.0",
    "datasets": {"entities/resource": {"rowCount": 1}},
}


def _connection() -> SubscriptionConnection:
    return SubscriptionConnection(
        connection_id="conn-1",
        name="Connection One",
        tenant_id="tenant-1",
        subscription_id="sub-1",
    )


class _FakeIngestion:
    def __init__(self, manifest: dict) -> None:
        self.manifest = manifest

    def run(self) -> dict:
        return self.manifest


class _FakePublish:
    """A `publish_factory(connection)` result: `.run()` succeeds or raises."""

    def __init__(self, *, exc: Exception | None = None) -> None:
        self.exc = exc
        self.called = False

    def run(self) -> None:
        self.called = True
        if self.exc is not None:
            raise self.exc


class _NeverCalledManager:
    """An `OntologyManager` double that fails loudly if `resolve()` is reached.

    Used for the preflight-rejection tests, where `build_definition()` must
    raise before `publish()` ever calls `manager.resolve()`.
    """

    def resolve(self, **kwargs: object) -> dict[str, object] | None:
        raise AssertionError("manager.resolve() must not be called when build_definition() raises")


class _FakeMetrics:
    """A `FabricMetrics` double recording calls without touching OpenTelemetry."""

    def __init__(self) -> None:
        self.preflight_rejected_calls = 0
        self.retry_calls: list[int | None] = []

    def record_publish_preflight_rejected(self) -> None:
        self.preflight_rejected_calls += 1

    def record_publish_retry(self, status_code: int | None) -> None:
        self.retry_calls.append(status_code)


class _RejectingPublish:
    """Runs a real `OntologyPublisher.publish()` with an invalid relationship
    mapping so `build_definition()` raises its "endpoint type is not defined"
    `ValueError` before any Fabric manager call."""

    def __init__(self, manager: object | None = None) -> None:
        self.manager = manager or _NeverCalledManager()

    def run(self) -> None:
        publisher = OntologyPublisher(self.manager, workspace_id="ws-1", lakehouse_id="lh-1")
        publisher.publish(
            ontology_id="ontology-1",
            ontology_name="AIOps Operational Context Graph",
            entity_types={"VM": "table_vm"},
            relationships={("VM", "runsOn", "MissingType"): "table_rel"},
        )


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.fabric.microsoft.com/v1/items")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"Server error '{status_code}' for url", request=request, response=response
    )


def _coordinator(
    tmp_path: Path,
    *,
    publish_factory,
    metrics: object | None = None,
    publication_state_store: PublicationStateStore | None = None,
) -> ConnectionSyncCoordinator:
    return ConnectionSyncCoordinator(
        str(tmp_path),
        ingestion_factory=lambda _connection: _FakeIngestion(_MANIFEST),
        publish_factory=publish_factory,
        publication_state_store=publication_state_store,
        metrics=metrics,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )


# --- Task 1: durable per-publication-attempt terminal-state record --------


def test_preflight_rejection_records_durable_state(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path, publish_factory=lambda _c: _RejectingPublish())

    coordinator.run(_connection(), mode="initial")

    record = coordinator.publication_state_store.get(coordinator.ontology_name)
    assert record is not None
    assert record.outcome == "rejected"
    assert record.retryable is False
    assert "endpoint type is not defined" in record.error
    assert "MissingType" in record.error


def test_transient_failure_records_durable_state(tmp_path: Path) -> None:
    exc = _http_status_error(503)
    coordinator = _coordinator(tmp_path, publish_factory=lambda _c: _FakePublish(exc=exc))

    coordinator.run(_connection(), mode="initial")

    record = coordinator.publication_state_store.get(coordinator.ontology_name)
    assert record is not None
    assert record.outcome == "failed"
    assert record.retryable is True
    assert "503" in record.error


def test_successful_publish_records_durable_state(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path, publish_factory=lambda _c: _FakePublish())

    coordinator.run(_connection(), mode="initial")

    record = coordinator.publication_state_store.get(coordinator.ontology_name)
    assert record is not None
    assert record.outcome == "succeeded"
    assert record.retryable is False
    assert record.error == ""


def test_publication_state_persists_across_fresh_store_instance(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path, publish_factory=lambda _c: _FakePublish())
    coordinator.run(_connection(), mode="initial")

    # A brand new store instance, pointed at the same backing root, must see
    # the same record -- this is the durability assertion (not in-memory
    # only): a fresh process reading the same store sees prior attempts.
    fresh_store = PublicationStateStore(coordinator.output_dir)
    record = fresh_store.get(DEFAULT_ONTOLOGY_NAME)
    assert record is not None
    assert record.outcome == "succeeded"


def test_publication_attempt_count_increments_across_repeated_attempts(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path, publish_factory=lambda _c: _FakePublish())

    coordinator.run(_connection(), mode="initial")
    coordinator.run(_connection(), mode="scheduled")

    record = coordinator.publication_state_store.get(coordinator.ontology_name)
    assert record is not None
    assert record.attempt_count == 2


# --- Task 2: telemetry for publish preflight rejections and retries -------


def test_preflight_rejection_increments_telemetry_counter(tmp_path: Path) -> None:
    metrics = _FakeMetrics()
    coordinator = _coordinator(
        tmp_path, publish_factory=lambda _c: _RejectingPublish(), metrics=metrics
    )

    coordinator.run(_connection(), mode="initial")

    assert metrics.preflight_rejected_calls == 1
    assert metrics.retry_calls == []


def test_transient_failure_increments_telemetry_counter(tmp_path: Path) -> None:
    metrics = _FakeMetrics()
    exc = _http_status_error(503)
    coordinator = _coordinator(
        tmp_path, publish_factory=lambda _c: _FakePublish(exc=exc), metrics=metrics
    )

    coordinator.run(_connection(), mode="initial")

    assert metrics.retry_calls == [503]
    assert metrics.preflight_rejected_calls == 0


def test_successful_publish_does_not_increment_telemetry_counters(tmp_path: Path) -> None:
    metrics = _FakeMetrics()
    coordinator = _coordinator(
        tmp_path, publish_factory=lambda _c: _FakePublish(), metrics=metrics
    )

    coordinator.run(_connection(), mode="initial")

    assert metrics.preflight_rejected_calls == 0
    assert metrics.retry_calls == []


def test_non_transient_failure_does_not_increment_retry_telemetry_counter(tmp_path: Path) -> None:
    """A non-transient (e.g. 400) or non-HTTP exception is `failed` but not
    `retryable` -- it must not be counted as a retry, since `fabric_client.py`
    never retries it either."""
    metrics = _FakeMetrics()
    exc = _http_status_error(400)
    coordinator = _coordinator(
        tmp_path, publish_factory=lambda _c: _FakePublish(exc=exc), metrics=metrics
    )

    coordinator.run(_connection(), mode="initial")

    record = coordinator.publication_state_store.get(coordinator.ontology_name)
    assert record is not None
    assert record.outcome == "failed"
    assert record.retryable is False
    assert metrics.retry_calls == []
    assert metrics.preflight_rejected_calls == 0


# --- Task 3: call-ordering regression --------------------------------------


def test_manager_resolve_never_invoked_when_build_definition_raises(tmp_path: Path) -> None:
    """End-to-end preflight-ordering regression through the sync coordinator.

    Completes the assertion noted but not filed as its own test in Plan
    10-01 Task 1: `manager.resolve()` must never be reached when
    `build_definition()` raises, exercised here through the full
    `ConnectionSyncCoordinator.run()` -> `publish_factory` ->
    `OntologyPublisher.publish()` path (not just a direct
    `OntologyPublisher.publish()` call, as
    `tests/test_relationship_vocabulary_consistency.py` already covers).
    """
    manager = _NeverCalledManager()
    coordinator = _coordinator(
        tmp_path, publish_factory=lambda _c: _RejectingPublish(manager=manager)
    )

    result, _state = coordinator.run(_connection(), mode="initial")

    assert result.status == "failed"
    record = coordinator.publication_state_store.get(coordinator.ontology_name)
    assert record is not None
    assert record.outcome == "rejected"
