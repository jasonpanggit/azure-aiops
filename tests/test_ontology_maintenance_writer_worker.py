"""PublisherWorker-level receipt/freshness denial with the real materialization fixture."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

from datetime import timedelta

import pytest

from ontology_discovery.publisher import PublicationSafetyError
from tests.test_ontology_maintenance_admission import (  # noqa: F401
    NOW,
    authority,
)
from tests.test_ontology_maintenance_materialization import Real
from tests.test_ontology_maintenance_publication import active, dispatched
from tests.test_ontology_maintenance_writer_evidence import (
    _duplicate_delivery,
    _mutate_results,
)


def _pointer_state(real):
    return active(real.storage), real.materializer.reader.active()[0]


def _staged_generations(real, env):
    gen_id = env.published()[0]["candidate"]["generation_id"]
    try:
        real.storage.read_generation(gen_id)
    except FileNotFoundError:
        return False
    return True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.pop("provider_receipt"),
        lambda r: r["provider_receipt"].update(model="wrong-model"),
        lambda r: r["provider_receipt"].update(selected_provider="native"),
    ],
)
def test_worker_denies_wrong_or_missing_receipt_before_stage(
    tmp_path, monkeypatch, authority, mutation
):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    before = _pointer_state(real)
    _mutate_results(env, mutation)
    outcome = real.worker.run_once(now=NOW, limit=1)
    assert outcome["succeeded"] == 0 and outcome["failed"] == 1
    assert not _staged_generations(real, env)
    assert _pointer_state(real) == before


def test_worker_denies_conflicting_duplicate_delivery_before_stage(
    tmp_path, monkeypatch, authority
):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    before = _pointer_state(real)
    _duplicate_delivery(env, {"model": "wrong-model"})
    outcome = real.worker.run_once(now=NOW, limit=1)
    assert outcome["succeeded"] == 0
    assert not _staged_generations(real, env)
    assert _pointer_state(real) == before


def test_worker_denies_evidence_expiry_after_stage_before_cas(
    tmp_path, monkeypatch, authority
):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    before = _pointer_state(real)
    storage = real.storage
    original = storage.persist_generation_audit
    publish = real.worker._publisher.publish
    fired = []
    failures = []

    def capture_publish(*args, **kwargs):
        try:
            return publish(*args, **kwargs)
        except PublicationSafetyError as exc:
            failures.append(str(exc))
            raise

    def audit_then_expire(generation_id, intent):
        result = original(generation_id, intent)
        # Stage and promotion-intent audit are durable; evidence now expires
        # before the final pre-CAS reauthorization.
        authority.clock[0] = authority.clock[0] + timedelta(days=2)
        fired.append(generation_id)
        return result

    monkeypatch.setattr(storage, "persist_generation_audit", audit_then_expire)
    monkeypatch.setattr(real.worker._publisher, "publish", capture_publish)
    outcome = real.worker.run_once(now=NOW, limit=1)
    assert fired, "stage/audit boundary was not reached"
    assert outcome["succeeded"] == 0 and outcome["failed"] == 1
    assert _staged_generations(real, env)  # staged, but never visible
    assert _pointer_state(real) == before
    assert any(
        "at pre_cas: model_edge_evidence_stale" in failure
        for failure in failures
    ), failures


@pytest.mark.parametrize(
    "boundary,mutation",
    [
        ("hook", "kill"),
        ("receipt", "expiry"),
        ("hook", "dispatch_lease"),
        ("receipt", "target_lease"),
    ],
)
def test_worker_rechecks_after_final_callbacks(
    tmp_path, monkeypatch, authority, boundary, mutation,
):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    successor = (
        Real(tmp_path, env, authority) if mutation == "target_lease" else None
    )
    publish = real.worker._publisher.publish
    promote = real.storage.conditional_promote
    promotions = []
    fired = []

    def invalidate():
        fired.append(mutation)
        if mutation == "kill":
            authority.control["kill"] = True
        elif mutation == "expiry":
            authority.clock[0] += timedelta(days=2)
        elif mutation == "dispatch_lease":
            real.worker._now = lambda: NOW + timedelta(hours=1)
        else:
            successor.materializer.lease.acquire("worker-1", 100_000)

    def capture_publish(*args, **kwargs):
        if boundary == "hook":
            kwargs["pre_cas_hook"] = invalidate
        else:
            record = kwargs["step_recorder"]

            def after_record(step, receipt):
                record(step, receipt)
                if step == "final_preconditions":
                    invalidate()

            kwargs["step_recorder"] = after_record
        return publish(*args, **kwargs)

    def capture_promote(**kwargs):
        promotions.append(kwargs)
        return promote(**kwargs)

    monkeypatch.setattr(real.worker._publisher, "publish", capture_publish)
    monkeypatch.setattr(real.storage, "conditional_promote", capture_promote)
    result = real.worker.run_once(now=NOW, limit=1)
    assert fired == [mutation]
    assert result["succeeded"] == 0, result
    assert promotions == []
    assert _pointer_state(real) == (None, None)
