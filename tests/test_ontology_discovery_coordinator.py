"""Finite, restart-safe ontology discovery coordinator contracts."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from api.routers.connections import sync_connection
from onboarding.service import SubscriptionOnboardingService
from ontology_discovery.cli import run_once as run_cli_once
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


def _onboarding_service(tmp_path) -> SubscriptionOnboardingService:
    service = SubscriptionOnboardingService(
        tmp_path / "aiops",
        ontology_run_store=OntologyRunStore(tmp_path / "ontology-runs.json"),
    )
    service.add(
        connection_id="prod-core",
        name="Production Core",
        tenant_id="33333333-3333-3333-3333-333333333333",
        subscription_id="11111111-1111-1111-1111-111111111111",
        client_id="44444444-4444-4444-4444-444444444444",
        secret_ref="kv://vault/spn-secret",
    )
    return service


def test_manual_and_scheduled_sync_intake_share_one_durable_run_without_executor(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    service = _onboarding_service(tmp_path)

    def fail_if_executor_is_resolved():
        raise AssertionError("ontology intake must not resolve ThreadPoolExecutor")

    monkeypatch.setattr(service, "_shared_executor", fail_if_executor_is_resolved)

    manual = service.enqueue_ontology_refresh(
        "prod-core",
        mode="manual",
        source_generation_id="inventory-generation-7",
        requested_by="operator@example.com",
    )
    scheduled = service.enqueue_ontology_refresh(
        "prod-core",
        mode="scheduled",
        source_generation_id="inventory-generation-7",
        requested_by="scheduler",
    )

    assert manual["run_id"] == scheduled["run_id"]
    assert manual["status"] == scheduled["status"] == "running"
    assert manual["mode"] == "manual"
    assert scheduled["mode"] == "scheduled"
    assert manual["sync_state"]["stage"] == "queued"
    assert manual["durable_run"]["status"] == "queued"
    assert manual["durable_run"]["source_generation_id"] == "inventory-generation-7"
    assert manual["durable_run"]["created"] is True
    assert scheduled["durable_run"]["created"] is False


def test_manual_sync_route_preserves_authorization_and_uses_durable_intake():
    source = inspect.getsource(sync_connection)
    signature = inspect.signature(sync_connection)

    assert "principal" in signature.parameters
    assert signature.parameters["principal"].annotation == "OperatePrincipal"
    assert "_authorize_action" in source
    assert "ACTION_OPERATE" in source
    assert "enqueue_ontology_refresh" in source
    assert "sync_async" not in source


def test_sync_run_once_cli_delegates_one_finite_bounded_pass():
    class Coordinator:
        def __init__(self) -> None:
            self.calls: list[tuple[datetime | None, int]] = []

        async def run_once(self, *, now=None, limit=10):
            self.calls.append((now, limit))
            return {"selected": 0, "processed": 0}

    coordinator = Coordinator()

    result = asyncio.run(run_cli_once(coordinator, now=NOW, limit=7))

    assert result == {"selected": 0, "processed": 0}
    assert coordinator.calls == [(NOW, 7)]
