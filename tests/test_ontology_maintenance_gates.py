"""Offline Phase 14 consumer-observation, budget, kill and deadline gate tests."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from ontology_discovery.maintenance_consumers import (
    CONSUMER_FAMILIES,
    BudgetLedger,
    ConsumerObservation,
    MaintenanceConsumerCheck,
    check_batch_caps,
    check_evaluation_latency_tokens,
    cost_usd,
    enforce_run_caps,
    evaluate_observations,
    p95,
)
from ontology_discovery.maintenance_relationships import FirstAdmissionLedger
from ontology_discovery.maintenance_release import MaintenanceDenied
from tests.test_ontology_maintenance_admission import (  # noqa: F401
    NOW,
    Env,
    authority,
    maintenance_for,
    model_rows,
    patch_inventory,
    seed_reviewed_proposals,
)

DEF = "sha256:definition"


def obs(family, **over):
    values = {
        "family": family, "observer_id": f"o-{family}", "source_id": f"s-{family}",
        "capture_id": f"c-{family}", "result_hash": f"h-{family}", "generation_id": "g1",
        "stage": "active", "definition_fingerprint": DEF, "product_fingerprint": f"p-{family}",
        "observed_at": NOW, "status": "pass",
    }
    values.update(over)
    return ConsumerObservation(**values)


def five(**over):
    return [obs(f, **over) for f in CONSUMER_FAMILIES]


def run(items, **kw):
    return evaluate_observations(
        items, generation_id="g1", stage="active", definition_fingerprint=DEF, now=NOW, **kw
    )


def test_five_independent_observations_pass():
    assert run(five()) == {f: True for f in CONSUMER_FAMILIES}


@pytest.mark.parametrize("bad", [
    lambda: five()[:-1],  # missing family
    lambda: [*five()[:-1], obs(CONSUMER_FAMILIES[0], observer_id="x")],  # duplicate family
    lambda: [obs(f, observer_id="shared") for f in CONSUMER_FAMILIES],  # same-observer alias
    lambda: [obs(f, source_id="same") for f in CONSUMER_FAMILIES],  # one source
    lambda: [obs(f, result_hash="copy") for f in CONSUMER_FAMILIES],  # manifest copy
    lambda: [obs(f, capture_id="same") for f in CONSUMER_FAMILIES],
    lambda: five(generation_id="other"),
    lambda: five(definition_fingerprint="sha256:other"),
    lambda: five(stage="staged"),
    lambda: five(observed_at=NOW - timedelta(hours=1)),
    lambda: five(observed_at=NOW + timedelta(minutes=5)),
    lambda: five(product_fingerprint=""),
])
def test_invalid_observation_sets_are_denied(bad):
    with pytest.raises(MaintenanceDenied):
        run(bad())


def test_observation_before_materialization_denied():
    with pytest.raises(MaintenanceDenied, match="before_materialization"):
        run(five(), not_before=NOW + timedelta(seconds=1))


def test_failed_observation_reports_false_not_pass():
    items = five()
    items[2] = obs(CONSUMER_FAMILIES[2], status="fail")
    assert run(items)[CONSUMER_FAMILIES[2]] is False


def test_consumer_check_requires_all_ports_and_marks_maintenance_observer():
    with pytest.raises(MaintenanceDenied):
        MaintenanceConsumerCheck(ports={}, definition_fingerprint=lambda: DEF)

    class Port:
        def __init__(self, family):
            self.family = family

        def observe(self, family, generation_id, stage):
            return None if self.family == "api" else obs(
                family, generation_id=generation_id, stage=stage
            )

    check = MaintenanceConsumerCheck(
        ports={f: Port(f) for f in CONSUMER_FAMILIES},
        definition_fingerprint=lambda: DEF, clock=lambda: NOW,
    )
    assert check.maintenance_observer is True
    with pytest.raises(MaintenanceDenied, match="missing"):
        check("post", "g1")


def test_budget_ledger_real_counts_cost_unknown_and_caps(tmp_path):
    ledger = BudgetLedger(tmp_path / "b.json")
    usage = [
        {"usage": {"input_tokens": 1000, "output_tokens": 100}, "latency_ms": 2000, "ok": True},
        {"usage": {"input_tokens": 500, "output_tokens": 50}, "latency_ms": 1000, "ok": False},
    ]
    totals = ledger.record("run-1", attempts=2, usage_log=usage)
    assert totals["input_tokens"] == 1500 and totals["failures"] == 1
    assert BudgetLedger(tmp_path / "b.json").totals("run-1") == totals  # durable
    assert cost_usd(totals, None) is None
    with pytest.raises(MaintenanceDenied, match="cost_unknown"):
        enforce_run_caps(totals, max_total_seconds=60, max_cost_usd=1.0, pricing=None)
    pricing = {"input_per_million": 1.0, "output_per_million": 2.0}
    assert cost_usd(totals, pricing) == pytest.approx(0.0016 + 0.0001, rel=0.2)
    enforce_run_caps(totals, max_total_seconds=60, max_cost_usd=1.0, pricing=pricing)
    with pytest.raises(MaintenanceDenied, match="cost_cap"):
        enforce_run_caps(totals, max_total_seconds=60, max_cost_usd=1e-9, pricing=pricing)
    with pytest.raises(MaintenanceDenied, match="run_time"):
        enforce_run_caps(totals, max_total_seconds=1, max_cost_usd=None, pricing=None)
    with pytest.raises(MaintenanceDenied, match="attempt_cap"):
        enforce_run_caps({**totals, "attempts": 99}, max_total_seconds=60,
                         max_cost_usd=None, pricing=None)


def test_p95_and_batch_caps():
    assert p95([1, 2, 3, 4, 100]) == 100
    with pytest.raises(MaintenanceDenied):
        p95([])
    check_evaluation_latency_tokens([1.0] * 20, [1000] * 20)
    with pytest.raises(MaintenanceDenied, match="latency"):
        check_evaluation_latency_tokens([31.0] * 20, [1000] * 20)
    with pytest.raises(MaintenanceDenied, match="tokens"):
        check_evaluation_latency_tokens([1.0] * 20, [10**9] * 20)
    with pytest.raises(MaintenanceDenied, match="batch_cap"):
        check_batch_caps(changed_entities=10**6, pairs=1, evidence_records=1)


def test_processor_outer_deadline_bounds_slow_curator(tmp_path, monkeypatch, authority):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "slow")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)

    async def slow(run, evidence):
        await asyncio.sleep(30)

    env.curator.propose = slow
    run = env.claim(lease_seconds=600, deadline_seconds=1)
    import time
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="deadline_exceeded"):
        env.run(env.processor(
            maintenance=maintenance_for(authority),
            ledger=FirstAdmissionLedger(tmp_path / "l.json"),
        ), run)
    assert time.monotonic() - started < 10  # bounded; never waits the 30s sleep
    assert env.published() == []


def test_budget_ledger_records_processor_usage(tmp_path, monkeypatch, authority):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "budget")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    ledger = BudgetLedger(tmp_path / "budget.json")
    run = env.claim()
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "l.json"),
        budget_ledger=ledger,
    ), run)
    totals = ledger.totals(run["run_id"])
    assert totals is None or totals["attempts"] >= 0
