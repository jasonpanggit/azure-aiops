"""Deterministic source-run lease lifetime, publication and cleanup regressions."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from storage import renewing_run
from storage.datasets import DatasetStore
from storage.locking import LeaseLostError


class ClockEvent:
    """Advance renewal ticks without sleeping for real lease intervals."""

    def __init__(self):
        self.condition = threading.Condition()
        self.ticks = 0
        self.stopped = False
        self.waiting = threading.Event()
        self.stop_requested = threading.Event()

    def wait(self, interval):
        assert interval == 20
        with self.condition:
            self.waiting.set()
            self.condition.wait_for(lambda: self.stopped or self.ticks > 0)
            if self.stopped:
                return True
            self.ticks -= 1
            return False

    def tick(self):
        with self.condition:
            self.ticks += 1
            self.condition.notify_all()

    def set(self):
        with self.condition:
            self.stopped = True
            self.stop_requested.set()
            self.condition.notify_all()


class Lease:
    is_remote = True

    def __init__(self, backend=None):
        self.backend = backend if backend is not None else {"now": 0, "expires": 0}
        self.lost = False
        self.released = False
        self.renewed = threading.Event()
        self.fail_renewal = False
        self.renew_count = 0

    def __enter__(self):
        if self.backend["expires"] > self.backend["now"]:
            raise RuntimeError("busy")
        self.backend["expires"] = self.backend["now"] + 60
        return self

    def renew(self):
        self.renew_count += 1
        if self.fail_renewal:
            self.lost = True
        else:
            self.backend["expires"] = self.backend["now"] + 60
        self.renewed.set()
        self.assert_held()

    def assert_held(self):
        if self.lost:
            raise LeaseLostError("test_lease_lost")

    def __exit__(self, *args):
        self.released = True
        if not self.lost:
            self.backend["expires"] = 0


def test_long_run_renews_and_keeps_other_execution_out(monkeypatch):
    clock = ClockEvent()
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    lease = Lease()
    with renewing_run.renewing_run_lock(lease):
        assert clock.waiting.wait(2)
        for now in (20, 40, 60, 80, 100, 120):
            lease.backend["now"] = now
            lease.renewed.clear()
            clock.tick()
            assert lease.renewed.wait(2)
            with pytest.raises(RuntimeError, match="busy"), Lease(lease.backend):
                pytest.fail("overlapping writer entered")
    assert lease.renew_count == 6
    assert clock.stopped and lease.released


def test_lease_loss_is_propagated_even_if_body_returns_normally(monkeypatch):
    clock = ClockEvent()
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    lease = Lease()
    lease.fail_renewal = True
    with pytest.raises(LeaseLostError, match="test_lease_lost"), renewing_run.renewing_run_lock(lease):
        clock.tick()
        assert lease.renewed.wait(2)
    assert clock.stopped and lease.released


def test_body_failure_stops_renewal_before_release(monkeypatch):
    clock = ClockEvent()
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    lease = Lease()
    with pytest.raises(ValueError, match="work_failed"), renewing_run.renewing_run_lock(lease):
        raise ValueError("work_failed")
    assert clock.stopped and lease.released
    count = lease.renew_count
    clock.tick()
    assert lease.renew_count == count


def test_local_lock_does_not_start_renewal_thread(monkeypatch):
    lease = Lease()
    lease.is_remote = False
    monkeypatch.setattr(renewing_run, "Thread", lambda **kwargs: pytest.fail("local renewal thread"))
    with renewing_run.renewing_run_lock(lease):
        pass
    assert lease.released


@pytest.mark.parametrize("late_renewal_success", [True, False])
def test_stalled_renewal_cannot_publish_after_expiry_or_revive_owner(
    tmp_path, monkeypatch, late_renewal_success,
):
    clock = ClockEvent()
    backend = {"now": 0, "expires": 0}
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    monkeypatch.setattr(renewing_run, "monotonic", lambda: backend["now"])
    renewal_started = threading.Event()
    finish_renewal = threading.Event()

    class StalledLease(Lease):
        def renew(self):
            renewal_started.set()
            assert finish_renewal.wait(2)
            if not late_renewal_success:
                self.lost = True
                self.assert_held()

    lease = StalledLease(backend)
    store = DatasetStore(tmp_path)
    store.publish({"entities/VirtualMachine": [{"id": "old"}]}, {}, {"runId": "old"})
    generation = store.current_generation()
    hashes = store.hash_path.read_bytes()

    def complete_after_owner_stops():
        assert clock.stop_requested.wait(2)
        assert not lease.released
        finish_renewal.set()

    completion = threading.Thread(target=complete_after_owner_stops)
    completion.start()
    try:
        with (
            pytest.raises(LeaseLostError, match="validity expired"),
            renewing_run.renewing_run_lock(lease) as guard,
        ):
            backend["now"] = 20
            clock.tick()
            assert renewal_started.wait(2)
            backend["now"] = 61
            assert lease.lost is False
            # The service lease has expired; a second execution can now acquire it.
            with Lease(backend), pytest.raises(LeaseLostError, match="validity expired"):
                store.publish(
                    {"entities/VirtualMachine": [{"id": "unsafe"}]}, {}, {"runId": "unsafe"},
                    assert_lock_held=guard.assert_held,
                )
    finally:
        finish_renewal.set()
        completion.join(2)
    assert not completion.is_alive()
    assert lease.released
    assert store.current_generation() == generation
    assert store.hash_path.read_bytes() == hashes
    assert store.read_dataset("entities/VirtualMachine") == [{"id": "old"}]


def test_renewal_latency_is_not_added_to_confirmed_validity(monkeypatch):
    clock = ClockEvent()
    backend = {"now": 0, "expires": 0}
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    monkeypatch.setattr(renewing_run, "monotonic", lambda: backend["now"])

    class SlowLease(Lease):
        def renew(self):
            backend["now"] = 50
            super().renew()

    lease = SlowLease(backend)
    with (
        pytest.raises(LeaseLostError, match="validity expired"),
        renewing_run.renewing_run_lock(lease) as guard,
    ):
        assert clock.waiting.wait(2)
        clock.waiting.clear()
        backend["now"] = 20
        clock.tick()
        assert lease.renewed.wait(2)
        # Join confirmation processing before testing the next deadline.
        assert clock.waiting.wait(2)
        backend["now"] = 81
        guard.assert_held()


def test_acquisition_latency_cannot_overstate_remaining_validity(monkeypatch):
    backend = {"now": 0, "expires": 0}
    monkeypatch.setattr(renewing_run, "monotonic", lambda: backend["now"])
    monkeypatch.setattr(renewing_run, "Thread", lambda **kwargs: pytest.fail("expired acquisition"))

    class DelayedLease(Lease):
        def __enter__(self):
            result = super().__enter__()
            backend["now"] = 61
            return result

    lease = DelayedLease(backend)
    with pytest.raises(LeaseLostError, match="validity expired"), renewing_run.renewing_run_lock(lease):
        pytest.fail("expired acquisition admitted work")
    assert lease.released


def test_shutdown_joins_inflight_renewal_and_propagates_its_loss_before_release(monkeypatch):
    clock = ClockEvent()
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    renewal_started = threading.Event()
    finish_renewal = threading.Event()
    failures = []

    class BlockingLease(Lease):
        def renew(self):
            renewal_started.set()
            assert finish_renewal.wait(2)
            self.lost = True
            self.assert_held()

    lease = BlockingLease()

    def run():
        try:
            with renewing_run.renewing_run_lock(lease):
                clock.tick()
                assert renewal_started.wait(2)
        except LeaseLostError as error:
            failures.append(error)

    owner = threading.Thread(target=run)
    owner.start()
    try:
        assert clock.stop_requested.wait(2)
        assert not lease.released
    finally:
        finish_renewal.set()
        owner.join(2)
    assert not owner.is_alive()
    assert lease.released
    assert len(failures) == 1


def test_loss_during_source_staging_preserves_active_pointer_and_hashes(tmp_path, monkeypatch):
    store = DatasetStore(tmp_path)
    store.publish({"entities/VirtualMachine": [{"id": "old"}]}, {}, {"runId": "old"}, ontology={})
    original_generation = store.current_generation()
    original_hashes = store.hash_path.read_bytes()
    write = store._write_generation
    lease = Lease()

    def lose_after_stage(*args, **kwargs):
        result = write(*args, **kwargs)
        lease.lost = True
        return result

    monkeypatch.setattr(store, "_write_generation", lose_after_stage)
    with pytest.raises(LeaseLostError):
        store.publish(
            {"entities/VirtualMachine": [{"id": "new"}]}, {}, {"runId": "new"},
            ontology={}, assert_lock_held=lease.assert_held,
        )
    assert store.current_generation() == original_generation
    assert store.hash_path.read_bytes() == original_hashes
    assert store.read_dataset("entities/VirtualMachine") == [{"id": "old"}]


@pytest.mark.parametrize("caller", ["inventory", "ingestion"])
def test_source_callers_refuse_publication_after_acquisition_lease_loss(tmp_path, monkeypatch, caller):
    from intelligence.inventory import pipeline
    from onboarding import ingestion_service
    from onboarding.config import ConnectorConfig

    clock = ClockEvent()
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    lease = Lease()
    module = pipeline if caller == "inventory" else ingestion_service
    monkeypatch.setattr(module, "RunLock", lambda root: lease)
    fixture = Path(__file__).parent / "fixtures" / (
        "mock_inventory_arg.json" if caller == "inventory" else "mock_arg_responses.json"
    )
    rows = json.loads(fixture.read_text())

    class Source:
        def fetch(self, specs, subscriptions):
            lease.lost = True
            return {spec.name: list(rows.get(spec.name, [])) for spec in specs}

    config = ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-a",), cost_management_enabled=False)
    service = (
        pipeline.InventoryPipeline(config, source=Source()) if caller == "inventory"
        else ingestion_service.IngestionService(config, source=Source())
    )
    with pytest.raises(LeaseLostError):
        service.refresh() if caller == "inventory" else service.run()
    assert DatasetStore(tmp_path).current_generation() is None
    assert not (tmp_path / "state/state.json").exists()
    assert lease.released and clock.stopped


def test_ingestion_does_not_advance_watermark_after_publication_lease_loss(tmp_path, monkeypatch):
    from onboarding import ingestion_service
    from onboarding.config import ConnectorConfig

    clock = ClockEvent()
    monkeypatch.setattr(renewing_run, "Event", lambda: clock)
    lease = Lease()
    monkeypatch.setattr(ingestion_service, "RunLock", lambda root: lease)
    rows = json.loads((Path(__file__).parent / "fixtures/mock_arg_responses.json").read_text())

    class Source:
        def fetch(self, specs, subscriptions):
            return {spec.name: list(rows.get(spec.name, [])) for spec in specs}

    service = ingestion_service.IngestionService(
        ConnectorConfig(output_dir=tmp_path, subscriptions=("sub-1",), cost_management_enabled=False),
        source=Source(),
    )
    publish = service._publish_generation

    def publish_then_lose(*args, **kwargs):
        manifest = publish(*args, **kwargs)
        lease.lost = True
        return manifest

    monkeypatch.setattr(service, "_publish_generation", publish_then_lose)
    with pytest.raises(LeaseLostError):
        service.run()
    assert not (tmp_path / "state/state.json").exists()
    assert lease.released and clock.stopped
