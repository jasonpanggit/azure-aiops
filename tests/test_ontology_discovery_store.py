"""Durable lifecycle contracts for autonomous ontology discovery."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from ontology_discovery.store import (
    OntologyRunStore,
    RunClaimConflict,
    RunLeaseLost,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def _create(
    store: OntologyRunStore,
    *,
    trigger: str = "scheduled",
    source_generation_id: str = "inventory-generation-7",
) -> tuple[dict, bool]:
    return store.get_or_create_run(
        connection_id="prod-core",
        source_generation_id=source_generation_id,
        trigger=trigger,
        requested_by="scheduler" if trigger == "scheduled" else "operator@example.com",
        now=NOW,
    )


def test_independent_stores_converge_duplicate_triggers_and_cas_claim_once(tmp_path):
    path = tmp_path / "ontology-runs.json"
    scheduled_store = OntologyRunStore(path)
    manual_store = OntologyRunStore(path)

    scheduled, scheduled_created = _create(scheduled_store)
    manual, manual_created = _create(manual_store, trigger="manual")

    assert scheduled_created is True
    assert manual_created is False
    assert manual["run_id"] == scheduled["run_id"]
    assert manual["run_identity"] == scheduled["run_identity"]

    def claim(store: OntologyRunStore, owner: str):
        try:
            return store.claim(
                scheduled["run_id"],
                expected_revision=scheduled["revision"],
                owner=owner,
                lease_seconds=30,
                now=NOW,
            )
        except RunClaimConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(
            pool.map(
                lambda pair: claim(*pair),
                ((scheduled_store, "worker-a"), (manual_store, "worker-b")),
            )
        )

    winners = [record for record in claimed if record is not None]
    assert len(winners) == 1
    assert winners[0]["attempt_count"] == 1
    assert winners[0]["fencing_token"] == 1


def test_reads_are_deep_copies_and_legacy_records_gain_fail_closed_defaults(tmp_path):
    path = tmp_path / "ontology-runs.json"
    path.write_text(
        """
        {
          "revision": 1,
          "runs": [{
            "run_id": "ODR-LEGACY",
            "connection_id": "prod-core",
            "source_generation_id": "generation-legacy",
            "status": "queued"
          }]
        }
        """,
        encoding="utf-8",
    )
    store = OntologyRunStore(path)

    record = store.get("ODR-LEGACY")
    assert record is not None
    assert record["revision"] == 0
    assert record["checkpoint"] == {"name": "queued", "payload": {}}
    assert record["cancel_requested"] is False
    assert record["attempt_count"] == 0
    assert record["max_attempts"] > 0
    assert record["history"] == []

    record["checkpoint"]["payload"]["tampered"] = True
    assert store.get("ODR-LEGACY")["checkpoint"]["payload"] == {}


def test_retry_backoff_and_deadline_are_durable_and_bounded(tmp_path):
    store = OntologyRunStore(
        tmp_path / "ontology-runs.json",
        max_attempts=2,
        retry_base_seconds=5,
        retry_max_seconds=30,
        default_deadline_seconds=60,
    )
    created, _ = _create(store)
    first = store.claim(
        created["run_id"],
        expected_revision=created["revision"],
        owner="worker-a",
        lease_seconds=10,
        now=NOW,
    )
    retrying = store.fail(
        first["run_id"],
        expected_revision=first["revision"],
        owner="worker-a",
        fencing_token=first["fencing_token"],
        failure_class="transient_provider",
        message="temporary outage",
        now=NOW,
    )

    assert retrying["status"] == "retrying"
    assert retrying["next_attempt_at"] == (NOW + timedelta(seconds=5)).isoformat()
    assert OntologyRunStore(store.path).list_due(now=NOW + timedelta(seconds=4)) == []

    due = OntologyRunStore(store.path).list_due(now=NOW + timedelta(seconds=5))
    assert [row["run_id"] for row in due] == [created["run_id"]]
    second = store.claim(
        created["run_id"],
        expected_revision=due[0]["revision"],
        owner="worker-b",
        lease_seconds=10,
        now=NOW + timedelta(seconds=5),
    )
    failed = store.fail(
        second["run_id"],
        expected_revision=second["revision"],
        owner="worker-b",
        fencing_token=second["fencing_token"],
        failure_class="transient_provider",
        message="still unavailable",
        now=NOW + timedelta(seconds=5),
    )

    assert failed["status"] == "failed"
    assert failed["failure_class"] == "attempts_exhausted"
    assert failed["next_attempt_at"] == ""
    assert OntologyRunStore(store.path).list_due(now=NOW + timedelta(minutes=5)) == []


def test_cancel_is_durable_and_invalidates_the_active_owner(tmp_path):
    store = OntologyRunStore(tmp_path / "ontology-runs.json")
    created, _ = _create(store)
    claimed = store.claim(
        created["run_id"],
        expected_revision=created["revision"],
        owner="worker-a",
        lease_seconds=30,
        now=NOW,
    )

    cancelled = OntologyRunStore(store.path).request_cancel(
        claimed["run_id"],
        expected_revision=claimed["revision"],
        actor="operator@example.com",
        reason="source was disabled",
        now=NOW + timedelta(seconds=1),
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True
    assert cancelled["lease_owner"] == ""
    assert cancelled["history"][-1]["status"] == "cancelled"
    with pytest.raises(RunLeaseLost):
        store.checkpoint(
            claimed["run_id"],
            expected_revision=cancelled["revision"],
            owner="worker-a",
            fencing_token=claimed["fencing_token"],
            name="evidence_collected",
            payload={"count": 12},
            now=NOW + timedelta(seconds=2),
        )
    assert store.get(claimed["run_id"])["checkpoint"]["name"] == "queued"


def test_expired_owner_cannot_checkpoint_after_new_fenced_claim(tmp_path):
    path = tmp_path / "ontology-runs.json"
    stale_store = OntologyRunStore(path)
    new_store = OntologyRunStore(path)
    created, _ = _create(stale_store)
    stale = stale_store.claim(
        created["run_id"],
        expected_revision=created["revision"],
        owner="worker-stale",
        lease_seconds=5,
        now=NOW,
    )
    due = new_store.list_due(now=NOW + timedelta(seconds=6))
    fresh = new_store.claim(
        created["run_id"],
        expected_revision=due[0]["revision"],
        owner="worker-fresh",
        lease_seconds=30,
        now=NOW + timedelta(seconds=6),
    )

    with pytest.raises(RunLeaseLost):
        stale_store.checkpoint(
            stale["run_id"],
            expected_revision=fresh["revision"],
            owner="worker-stale",
            fencing_token=stale["fencing_token"],
            name="evidence_collected",
            payload={"should_not_persist": True},
            now=NOW + timedelta(seconds=7),
        )

    final = new_store.get(created["run_id"])
    assert final["status"] == "running"
    assert final["lease_owner"] == "worker-fresh"
    assert final["fencing_token"] > stale["fencing_token"]
    assert final["checkpoint"]["name"] == "queued"
    assert final["history"][-1]["failure_class"] == "lease_lost"
    assert final["history"][-1]["consequential"] is False


def test_lease_renewal_is_durable_and_delays_restart_claim(tmp_path):
    path = tmp_path / "ontology-runs.json"
    store = OntologyRunStore(path)
    created, _ = _create(store)
    claimed = store.claim(
        created["run_id"],
        expected_revision=created["revision"],
        owner="worker-a",
        lease_seconds=5,
        now=NOW,
    )

    renewed = store.renew_lease(
        claimed["run_id"],
        expected_revision=claimed["revision"],
        owner="worker-a",
        fencing_token=claimed["fencing_token"],
        lease_seconds=10,
        now=NOW + timedelta(seconds=4),
    )

    restarted = OntologyRunStore(path)
    assert restarted.list_due(now=NOW + timedelta(seconds=6)) == []
    assert [row["run_id"] for row in restarted.list_due(now=NOW + timedelta(seconds=15))] == [
        created["run_id"]
    ]
    assert renewed["history"][-1]["message"] == "Lease renewed"
