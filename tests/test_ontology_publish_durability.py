"""Durability regression tests for ontology publish attempts (MED-01).

`onboarding.sync.ConnectionSyncCoordinator` previously surfaced a Fabric
publish failure only via `logger.exception(...)` -- a process-log-level
signal that disappears on restart and is invisible to anything outside the
process (notably a future Fabric medallion health API). This file proves
every publish outcome (preflight-rejected, retryable-failed, succeeded)
produces a durable `PublicationAttemptRecord` via
`ontology.publication_state.PublicationStateStore`, and that those records
survive a fresh `PublicationStateStore` instance reading the same backing
store (not merely in-memory).

Telemetry and call-ordering regression tests are added in Plan 10-03 Task 3.
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
    publication_state_store: PublicationStateStore | None = None,
) -> ConnectionSyncCoordinator:
    return ConnectionSyncCoordinator(
        str(tmp_path),
        ingestion_factory=lambda _connection: _FakeIngestion(_MANIFEST),
        publish_factory=publish_factory,
        publication_state_store=publication_state_store,
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )


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
