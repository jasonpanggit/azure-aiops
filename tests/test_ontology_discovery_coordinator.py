"""Finite, restart-safe ontology discovery coordinator contracts."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

from ontology_discovery.contracts import CheckpointResult
from ontology_discovery.coordinator import OntologyDiscoveryCoordinator
from ontology_discovery.store import OntologyRunStore

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _enqueue(store: OntologyRunStore, generation: str = "inventory-generation-7") -> dict:
    record, _ = store.get_or_create_run(
        connection_id="prod-core",
        source_generation_id=generation,
        trigger="scheduled",
        requested_by="scheduler",
        now=NOW,
    )
    return record


class _CompletingProcessor:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    async def advance(self, run: dict) -> CheckpointResult:
        self.seen.append((run["run_id"], run["checkpoint"]["name"]))
        return CheckpointResult(
            checkpoint="work_recorded",
            payload={"proposal_count": 0},
            complete=True,
        )


def test_run_once_is_finite_bounded_and_isolates_each_record(tmp_path):
    store = OntologyRunStore(tmp_path / "ontology-runs.json")
    first = _enqueue(store, "generation-1")
    second = _enqueue(store, "generation-2")
    _enqueue(store, "generation-3")

    class Processor:
        async def advance(self, run: dict) -> CheckpointResult:
            if run["run_id"] == first["run_id"]:
                raise RuntimeError("one bad source")
            return CheckpointResult(checkpoint="work_recorded", complete=True)

    coordinator = OntologyDiscoveryCoordinator(
        store=store,
        processor=Processor(),
        owner="job-1",
        now=lambda: NOW,
    )

    result = asyncio.run(coordinator.run_once(now=NOW, limit=2))

    assert result == {
        "selected": 2,
        "processed": 1,
        "retrying": 1,
        "failed": 0,
        "timed_out": 0,
        "cancelled": 0,
        "skipped_contended": 0,
        "lease_lost": 0,
        "errored": 0,
    }
    assert store.get(first["run_id"])["status"] == "retrying"
    assert store.get(second["run_id"])["status"] == "succeeded"
    assert store.get(_enqueue(store, "generation-3")["run_id"])["status"] == "queued"


def test_restart_dispatches_from_durable_checkpoint_with_no_process_memory(tmp_path):
    path = tmp_path / "ontology-runs.json"
    first_store = OntologyRunStore(path, retry_base_seconds=1)
    created = _enqueue(first_store)
    claimed = first_store.claim(
        created["run_id"],
        expected_revision=created["revision"],
        owner="worker-before-restart",
        lease_seconds=2,
        now=NOW,
    )
    checkpointed = first_store.checkpoint(
        claimed["run_id"],
        expected_revision=claimed["revision"],
        owner="worker-before-restart",
        fencing_token=claimed["fencing_token"],
        name="evidence_collected",
        payload={"evidence_snapshot_id": "EV-7"},
        now=NOW + timedelta(seconds=1),
    )
    assert checkpointed["status"] == "running"

    processor = _CompletingProcessor()
    restarted = OntologyDiscoveryCoordinator(
        store=OntologyRunStore(path),
        processor=processor,
        owner="worker-after-restart",
        now=lambda: NOW + timedelta(seconds=3),
    )

    result = asyncio.run(restarted.run_once(limit=5))

    assert result["processed"] == 1
    assert processor.seen == [(created["run_id"], "evidence_collected")]
    final = OntologyRunStore(path).get(created["run_id"])
    assert final["status"] == "succeeded"
    assert final["checkpoint"]["name"] == "work_recorded"


def test_deadline_expires_without_invoking_processor(tmp_path):
    store = OntologyRunStore(
        tmp_path / "ontology-runs.json",
        default_deadline_seconds=10,
    )
    created = _enqueue(store)
    processor = _CompletingProcessor()
    coordinator = OntologyDiscoveryCoordinator(
        store=store,
        processor=processor,
        owner="job-timeout",
        now=lambda: NOW + timedelta(seconds=11),
    )

    result = asyncio.run(coordinator.run_once(limit=1))

    assert result["timed_out"] == 1
    assert processor.seen == []
    final = store.get(created["run_id"])
    assert final["status"] == "failed"
    assert final["failure_class"] == "deadline_exceeded"


def test_coordinator_exposes_no_authoritative_stage_or_pointer_primitive():
    source = inspect.getsource(OntologyDiscoveryCoordinator)
    signature = inspect.signature(OntologyDiscoveryCoordinator)

    assert "publisher" not in signature.parameters
    assert "promote" not in source
    assert "active_pointer" not in source
    assert "stage_generation" not in source
