"""Isolated offline regression for durable pre-transport maintenance charges."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from test_ontology_agent_maintenance import (
    NOW,
    Collected,
    ScriptedResponses,
    _curator,
    _sources,
)
from test_ontology_maintenance_admission import (
    Authority,
    Env,
    FirstAdmissionLedger,
    maintenance_for,
    patch_inventory,
)

from ontology_discovery.contracts import RunProcessingFailure
from ontology_discovery.coordinator import BoundedEvidenceProcessor
from ontology_discovery.curator import OntologyCurator, RetryableCuratorTransportError
from ontology_discovery.maintenance_consumers import BudgetLedger, cost_usd
from ontology_discovery.maintenance_release import (
    MaintenanceConfigError,
    MaintenanceDenied,
)
from ontology_discovery.planner_capabilities import select_planner
from ontology_discovery.runtime import (
    ProductionConnectionProcessor,
    build_production_runtime,
)
from ontology_discovery.store import OntologyRunStore

PRICING = {
    "version": "isolated-offline/v1",
    "input_per_million": 1.0,
    "output_per_million": 2.0,
}
CAPS = {
    "pricing": PRICING, "max_cost_usd": 1.0, "max_total_seconds": 1800.0,
    "input_overhead_tokens": 0,  # explicit isolated scripted-transport bound
}


def reserve(ledger, run="run-a", **overrides):
    caps = {key: value for key, value in CAPS.items() if key != "input_overhead_tokens"}
    return ledger.reserve(
        run, **{
            "input_tokens": 100, "output_tokens": 20, "timeout_seconds": 1,
            **caps, **overrides,
        },
    )


def test_unique_charges_survive_restart_replay_and_other_run(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path)
    ids = [reserve(ledger) for _ in range(4)]
    before = ledger.totals("run-a")
    assert before["attempts"] == 4 and before["input_tokens"] == 400
    restarted = BudgetLedger(path)
    settled = restarted.settle(
        "run-a", ids[0], usage={"input_tokens": 10, "output_tokens": 2},
        elapsed_ms=1, ok=True,
    )
    assert settled == before  # no refunds; actual usage is retained separately
    assert restarted.settle(
        "run-a", ids[0], usage={"input_tokens": 99999},
        elapsed_ms=99999, ok=False,
    ) == settled
    reserve(restarted, "run-b")
    assert restarted.totals("run-b")["attempts"] == 1
    assert restarted.totals("run-a") == settled
    fifth = reserve(restarted)
    assert fifth not in ids
    assert BudgetLedger(path).totals("run-a")["attempts"] == 5


def test_legacy_snapshot_can_never_decrease_or_qualify(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json")
    ledger.record("run-a", attempts=4, usage_log=[
        {"usage": {"input_tokens": 400}, "latency_ms": 400, "ok": False},
    ])
    ledger = BudgetLedger(tmp_path / "budget.json")
    totals = ledger.record("run-a", attempts=1, usage_log=[
        {"usage": {"input_tokens": 100}, "latency_ms": 100, "ok": True},
    ])
    assert totals["attempts"] == 4 and totals["input_tokens"] == 400
    with pytest.raises(MaintenanceDenied, match="budget_legacy_unqualified"):
        reserve(ledger)


@pytest.mark.parametrize("override,reason", [
    ({"max_cost_usd": 0.00001}, "cost_cap_exceeded"),
    ({"max_input_tokens": 99}, "run_token_cap_exceeded"),
    ({"max_output_tokens": 19}, "run_token_cap_exceeded"),
    ({"max_total_seconds": 0.5}, "run_time_cap_exceeded"),
    ({"pricing": {}}, "cost_unknown"),
    ({"pricing": {"input_per_million": float("nan"), "output_per_million": 2}}, "cost_unknown"),
    ({"pricing": {"input_per_million": -1, "output_per_million": 2}}, "cost_unknown"),
])
def test_atomic_admission_denies_without_charge(tmp_path, override, reason):
    ledger = BudgetLedger(tmp_path / "budget.json")
    with pytest.raises(MaintenanceDenied, match=reason):
        reserve(ledger, **override)
    assert ledger.totals("run-a") is None


def test_concurrent_ledger_handles_enforce_one_remaining_slot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "budget.json"
    for _ in range(8):
        reserve(BudgetLedger(path))

    def try_reserve(_):
        try:
            reserve(BudgetLedger(path))
            return True
        except MaintenanceDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(try_reserve, range(2))) == [False, True]
    assert BudgetLedger(path).totals("run-a")["attempts"] == 9


def test_cost_charges_pin_attempt_pricing_across_restart(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json")
    reserve(ledger)
    before = ledger.totals("run-a")["charged_cost_usd"]
    cheap = {"version": "cheaper/v2", "input_per_million": 0.1, "output_per_million": 0.2}
    reserve(BudgetLedger(tmp_path / "budget.json"), pricing=cheap)
    totals = ledger.totals("run-a")
    assert totals["charged_cost_usd"] > before
    assert cost_usd(totals, cheap) == totals["charged_cost_usd"]


def test_provider_bound_violation_is_durably_charged_and_poisoned(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path)
    attempt_id = reserve(ledger)
    reserved_cost = ledger.totals("run-a")["charged_cost_usd"]
    with pytest.raises(MaintenanceDenied, match="attempt_usage_bound_exceeded"):
        ledger.settle(
            "run-a", attempt_id, usage={"input_tokens": 101, "output_tokens": 21},
            elapsed_ms=1, ok=True,
        )
    assert BudgetLedger(path).totals("run-a")["input_tokens"] == 101
    assert BudgetLedger(path).totals("run-a")["failures"] == 1
    assert BudgetLedger(path).totals("run-a")["charged_cost_usd"] > reserved_cost
    with pytest.raises(MaintenanceDenied, match="attempt_usage_bound_exceeded"):
        reserve(BudgetLedger(path))


def claim(store, connection, generation):
    queued, _ = store.get_or_create_run(
        connection_id=connection, source_generation_id=generation,
        trigger="manual", requested_by="offline", now=NOW,
        deadline_at=NOW + timedelta(minutes=10),
    )
    return store.claim(
        queued["run_id"], expected_revision=queued["revision"],
        owner="offline", lease_seconds=600, now=NOW,
    )


def processor(store, curator, generation="offline-source-1"):
    evidence = _sources()
    evidence["source_generation_id"] = generation
    for record in evidence["evidence_records"]:
        record["source_generation_id"] = generation
    return BoundedEvidenceProcessor(
        store=store, evidence_provider=Collected(evidence), curator=curator,
        now=lambda: NOW, planner_selection=select_planner(execution_class="simulated"),
    )


def test_actual_processor_retry_two_connections_restart_and_replay(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json")
    store = OntologyRunStore(tmp_path / "runs")
    transport = ScriptedResponses(failures=2)
    curator = _curator(transport)
    first = claim(store, "connection-a", "offline-source-1")

    async def advance(run):
        with curator.budget_scope(run["run_id"], ledger, **CAPS):
            return await processor(store, curator, run["source_generation_id"]).advance(run)

    assert asyncio.run(advance(first)).complete
    totals = ledger.totals(first["run_id"])
    assert totals["attempts"] == 3 and totals["failures"] == 2
    assert len(transport.calls) == 3
    assert totals["input_tokens"] > 0 and totals["charged_cost_usd"] > 0
    store = OntologyRunStore(tmp_path / "runs")
    ledger = BudgetLedger(tmp_path / "budget.json")
    assert asyncio.run(advance(first)).complete
    assert len(transport.calls) == 3
    assert ledger.totals(first["run_id"]) == totals
    second = claim(store, "connection-b", "offline-source-2")
    assert asyncio.run(advance(second)).complete
    assert ledger.totals(second["run_id"])["attempts"] == 1
    assert ledger.totals(first["run_id"]) == totals


def test_actual_processor_denies_retry_before_second_call(tmp_path, caplog):
    ledger = BudgetLedger(tmp_path / "budget.json")
    store = OntologyRunStore(tmp_path / "runs")
    run = claim(store, "connection-a", "offline-source-1")
    calls = []

    async def failing(payload, *, timeout_seconds):
        assert ledger.totals(run["run_id"])["attempts"] == 9
        calls.append(payload)
        raise RetryableCuratorTransportError("secret-not-for-logs")

    curator = OntologyCurator(
        project_endpoint="https://offline.invalid", agent_name="offline",
        transport=failing, retry_backoff_seconds=0,
    )
    for _ in range(8):
        reserve(ledger, run["run_id"])

    async def execute():
        with curator.budget_scope(run["run_id"], ledger, **CAPS):
            await processor(store, curator).advance(run)

    with pytest.raises(RunProcessingFailure, match="curator_provider_failed"):
        asyncio.run(execute())
    totals = BudgetLedger(tmp_path / "budget.json").totals(run["run_id"])
    assert len(calls) == 1 and totals["attempts"] == 9
    assert totals["failures"] == 1 and totals["input_tokens"] > 800
    assert "secret-not-for-logs" not in caplog.text
    assert "ontology_curator_attempt_failed" in caplog.text


def test_schema_repairs_charge_each_actual_attempt(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json")
    store = OntologyRunStore(tmp_path / "runs")
    run = claim(store, "connection-a", "offline-source-1")

    def invalid(document):
        document["unexpected"] = "not a valid whole document"

    transport = ScriptedResponses(mutate=invalid)
    curator = _curator(transport)

    async def execute():
        with curator.budget_scope(run["run_id"], ledger, **CAPS):
            await processor(store, curator).advance(run)

    with pytest.raises(RunProcessingFailure, match="curator_output_invalid"):
        asyncio.run(execute())
    assert len(transport.calls) == 3
    assert ledger.totals(run["run_id"])["attempts"] == 3
    assert ledger.totals(run["run_id"])["charged_cost_usd"] > 0


def test_exhausted_transport_retries_all_remain_charged(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json")
    store = OntologyRunStore(tmp_path / "runs")
    run = claim(store, "connection-a", "offline-source-1")
    transport = ScriptedResponses(failures=3)
    curator = _curator(transport)

    async def execute():
        with curator.budget_scope(run["run_id"], ledger, **CAPS):
            await processor(store, curator).advance(run)

    with pytest.raises(RunProcessingFailure, match="curator_provider_failed"):
        asyncio.run(execute())
    totals = BudgetLedger(tmp_path / "budget.json").totals(run["run_id"])
    assert len(transport.calls) == 3
    assert totals["attempts"] == totals["failures"] == 3
    assert totals["charged_cost_usd"] > 0


@pytest.mark.parametrize("caps", [
    {"max_cost_usd": 0.000001},
    {"max_input_tokens": 1},
    {"max_output_tokens": 1999},
    {"max_total_seconds": 0.01},
    {"pricing": {}},
])
def test_actual_curator_pre_call_caps_never_allow_unaccounted_calls(tmp_path, caps):
    ledger = BudgetLedger(tmp_path / "budget.json")
    transport = ScriptedResponses()
    curator = _curator(transport)

    async def execute():
        with curator.budget_scope("run-a", ledger, **{**CAPS, **caps}):
            await curator._request(curator._payload("bounded request"))

    with pytest.raises(MaintenanceDenied):
        asyncio.run(execute())
    assert transport.calls == []
    assert ledger.totals("run-a") is None


def test_unsettled_crash_reservation_blocks_after_restart(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path)
    for _ in range(9):
        reserve(ledger)
    # Simulate process death before all settlements. Reserved charges remain.
    with pytest.raises(MaintenanceDenied, match="attempt_cap_exceeded"):
        reserve(BudgetLedger(path))
    assert BudgetLedger(path).totals("run-a")["attempts"] == 9


def test_diagnostic_history_truncation_cannot_erase_run_accounting(tmp_path):
    path = tmp_path / "budget.json"
    ledger = BudgetLedger(path)

    async def transport(payload, *, timeout_seconds):
        return {}  # unknown usage must retain the charged request bound

    curator = OntologyCurator(
        project_endpoint="https://offline.invalid", agent_name="offline",
        transport=transport,
    )

    async def execute():
        for index in range(70):
            with curator.budget_scope(f"run-{index}", ledger, **CAPS):
                await curator._request(curator._payload("bounded request"))

    asyncio.run(execute())
    assert len(curator.usage_log) == 64 and curator.transport_attempts == 70
    first = BudgetLedger(path).totals("run-0")
    assert first["attempts"] == 1 and first["charged_cost_usd"] > 0
    assert not any(entry["run_id"] == "run-0" for entry in curator.usage_log)
    assert BudgetLedger(path).totals("run-69") == first


def test_concurrent_curator_scopes_do_not_cross_charge_runs(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.json")

    async def transport(payload, *, timeout_seconds):
        await asyncio.sleep(0)
        return {}

    curator = OntologyCurator(
        project_endpoint="https://offline.invalid", agent_name="offline",
        transport=transport,
    )

    async def execute(run_id, prompt):
        with curator.budget_scope(run_id, ledger, **CAPS):
            await curator._request(curator._payload(prompt))

    async def together():
        await asyncio.gather(execute("run-a", "left"), execute("run-b", "right"))

    asyncio.run(together())
    assert ledger.totals("run-a")["attempts"] == ledger.totals("run-b")["attempts"] == 1
    assert ledger.totals("run-a")["input_tokens"] == 4
    assert ledger.totals("run-b")["input_tokens"] == 5


@pytest.mark.parametrize("mode", ["unknown", "raise", "timeout", "cancel"])
def test_transport_finally_charges_every_outcome(tmp_path, mode):
    ledger = BudgetLedger(tmp_path / "budget.json")

    async def transport(payload, *, timeout_seconds):
        assert ledger.totals("run-a")["attempts"] == 1
        if mode == "raise":
            raise ValueError("secret")
        if mode == "timeout":
            await asyncio.sleep(30)
        if mode == "cancel":
            raise asyncio.CancelledError
        return {"usage": None}

    curator = OntologyCurator(
        project_endpoint="https://offline.invalid", agent_name="offline",
        transport=transport, max_transport_retries=0, timeout_seconds=0.01,
    )

    async def execute():
        with curator.budget_scope("run-a", ledger, **CAPS):
            await curator._request(curator._payload("bounded request"))

    if mode == "unknown":
        asyncio.run(execute())
    else:
        with pytest.raises((Exception, asyncio.CancelledError)):
            asyncio.run(execute())
    totals = BudgetLedger(tmp_path / "budget.json").totals("run-a")
    assert totals["attempts"] == 1 and totals["input_tokens"] == len("bounded request")
    assert totals["output_tokens"] == 2000 and totals["charged_cost_usd"] > 0
    row = json.loads((tmp_path / "budget.json").read_text())["run-a"]["records"]
    assert next(iter(row.values()))["status"] != "reserved"
    assert "secret" not in (tmp_path / "budget.json").read_text()


def test_actual_production_processor_uses_qualified_fixture_budget(
    tmp_path, monkeypatch,
):
    authority = Authority(tmp_path)
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "durable-processor")
    ledger = BudgetLedger(tmp_path / "durable.json")
    run = env.claim()
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "first.json"),
        budget_ledger=ledger,
    ), run)
    assert ledger.totals(run["run_id"])["attempts"] == 1
    assert ledger.totals(run["run_id"])["charged_cost_usd"] > 0


def test_unqualified_external_curator_cannot_admit_maintenance(tmp_path):
    env = Env(tmp_path, "unqualified")
    with pytest.raises(MaintenanceConfigError, match="maintenance_budget_unqualified"):
        ProductionConnectionProcessor(
            store=env.store, dispatch=env.dispatch, connector_config=object(),
            curator=env.curator, resolver=object(), maintenance=object(),
            first_admission_ledger=FirstAdmissionLedger(tmp_path / "first.json"),
            budget_ledger=BudgetLedger(tmp_path / "budget.json"), **CAPS,
        )
    # Same externally injected protocol-only curator remains usable in shadow.
    assert ProductionConnectionProcessor(
        store=env.store, dispatch=env.dispatch, connector_config=object(),
        curator=env.curator, resolver=object(),
    ).maintenance is None


def production_bindings(tmp_path):
    return {
        "AIOPS_ONTOLOGY_ENVIRONMENT": "validation",
        "AIOPS_CONNECTION_HOME": str(tmp_path / "connections"),
        "AIOPS_ONTOLOGY_COMMAND_HOME": str(tmp_path / "commands"),
        "AIOPS_ONTOLOGY_STATE_HOME": str(tmp_path / "runs"),
        "AIOPS_ONTOLOGY_DISPATCH_HOME": str(tmp_path / "dispatch"),
        "FOUNDRY_PROJECT_ENDPOINT": "https://offline.services.ai.azure.com/api/projects/offline",
        "FOUNDRY_ONTOLOGY_AGENT_NAME": "offline",
        "FOUNDRY_ONTOLOGY_AGENT_VERSION": "1",
        "AIOPS_CONFIG_PATH": str(tmp_path / "offline-config.yaml"),
        "ONTOLOGY_MAINTENANCE_LEDGER_PATH": str(tmp_path / "first.json"),
        "ONTOLOGY_MAINTENANCE_BUDGET_PATH": str(tmp_path / "budget.json"),
        "ONTOLOGY_MAINTENANCE_PRICING_JSON": json.dumps(PRICING),
        "ONTOLOGY_MAINTENANCE_MAX_COST_USD": "1.0",
        "ONTOLOGY_MAINTENANCE_INPUT_OVERHEAD_TOKENS": "0",
    }


@pytest.mark.parametrize("missing", [
    "ONTOLOGY_MAINTENANCE_BUDGET_PATH",
    "ONTOLOGY_MAINTENANCE_PRICING_JSON",
    "ONTOLOGY_MAINTENANCE_MAX_COST_USD",
    "ONTOLOGY_MAINTENANCE_INPUT_OVERHEAD_TOKENS",
])
def test_production_composition_denies_missing_server_budget_bindings(
    tmp_path, monkeypatch, missing,
):
    from ontology_discovery import runtime

    # Only acquisition is isolated; run the actual production builder.
    monkeypatch.setattr(runtime, "build_production_reader", lambda _env: object())
    monkeypatch.setattr(runtime.ConnectorConfig, "load", lambda _path: object())
    bindings = production_bindings(tmp_path)
    del bindings[missing]
    transport = ScriptedResponses()
    with pytest.raises(MaintenanceConfigError, match="maintenance_budget_unqualified"):
        build_production_runtime(
            environ=bindings, curator=_curator(transport), owner="offline",
        )
    assert transport.calls == []


def test_production_composition_wires_server_budget_without_invocation(
    tmp_path, monkeypatch,
):
    from ontology_discovery import runtime

    monkeypatch.setattr(runtime, "build_production_reader", lambda _env: object())
    monkeypatch.setattr(runtime.ConnectorConfig, "load", lambda _path: object())
    bindings = production_bindings(tmp_path)
    transport = ScriptedResponses()
    built = build_production_runtime(
        environ=bindings, curator=_curator(transport), owner="offline",
    )
    assert built.processor.budget_ledger is not None
    assert built.processor.pricing == PRICING
    assert built.processor.input_overhead_tokens == 0
    assert built.processor.max_cost_usd == 1.0 and transport.calls == []
