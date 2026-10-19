"""Real-store advisory tracer using simulated, independently authored source rows.

The opt-in dependency tag is a proposed contract, not a deployed tenant setting.
AppDependencies rows and their exact inventory bindings are offline fixtures.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_ontology_generation_publication import _candidate, _publish, _publisher

from ontology_discovery.contracts import RunProcessingFailure
from ontology_discovery.coordinator import (
    BoundedEvidenceProcessor,
    ProposalPolicyCoordinator,
)
from ontology_discovery.curator import OntologyCurator
from ontology_discovery.planner_capabilities import (
    PlannerSelection,
    UnsupportedPlannerCapability,
    select_planner,
)
from ontology_discovery.policy import ProposalPolicy
from ontology_discovery.store import OntologyRunStore

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
SCOPE = "tenant-1/sub-1"
GENERATION = "offline-source-1"
APP = "/subscriptions/sub-1/resourcegroups/apps/providers/microsoft.web/sites/frontend"
TARGET = "/subscriptions/sub-1/resourcegroups/apps/providers/microsoft.web/sites/backend"
FOREIGN = "/subscriptions/sub-2/resourcegroups/apps/providers/microsoft.web/sites/backend"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _sources() -> dict[str, Any]:
    # These are different source schemas and independently asserted observations.
    inventory = [
        {"id": APP, "name": "frontend", "type": "microsoft.web/sites",
         "tags": {"aiops.dependencyResourceIds": json.dumps([TARGET])}},
        {"id": TARGET, "name": "backend", "type": "microsoft.web/sites", "tags": {}},
        {"id": FOREIGN, "name": "backend", "type": "microsoft.web/sites", "tags": {}},
    ]
    telemetry = {
        "TimeGenerated": NOW.isoformat(), "AppRoleName": "frontend-role",
        "Target": "backend.internal", "DependencyType": "HTTP",
        "Success": True, "Id": "dependency-event-001",
    }
    bindings = {"frontend-role": APP, "backend.internal": TARGET}
    entities = [
        {"entity_id": row["id"], "resource_id": row["id"],
         "entity_type": "Application", "name": row["name"],
         "scope": SCOPE if row["id"] != FOREIGN else "tenant-1/sub-2",
         "lifecycle_status": "active"}
        for row in inventory
    ]
    declared = json.loads(inventory[0]["tags"]["aiops.dependencyResourceIds"])
    assert declared == [TARGET]
    declaration = {
        "evidence_id": "declaration-1", "source": "azure-resource-graph",
        "source_system": "resource-tags", "original_record_hash": _hash(inventory[0]),
        "subject_id": inventory[0]["id"], "object_id": declared[0],
        "subject_type": "Application", "predicate": "depends_on",
        "object_type": "Application", "scope": SCOPE,
        "source_generation_id": GENERATION, "observed_at": NOW.isoformat(),
        "freshness": "fresh", "supports": True, "contradicts": False,
    }
    observation = {
        "evidence_id": "dependency-1", "source": "application-insights",
        "source_system": "AppDependencies", "original_record_hash": _hash(telemetry),
        "binding_hash": _hash(bindings),
        "subject_id": bindings[telemetry["AppRoleName"]],
        "object_id": bindings[telemetry["Target"]],
        "subject_type": "Application", "predicate": "depends_on",
        "object_type": "Application", "scope": SCOPE,
        "source_generation_id": GENERATION, "observed_at": telemetry["TimeGenerated"],
        "freshness": "fresh", "supports": telemetry["Success"], "contradicts": False,
    }
    assert declaration["original_record_hash"] != observation["original_record_hash"]
    # A name lookalike remains inert, foreign-scope metadata, not an endpoint.
    entities[1]["foreign_scope_decoy"] = entities[2]
    return {
        "changed_entities": entities[:2], "candidate_pairs": [],
        "evidence_records": [declaration, observation],
        "source_generation_id": GENERATION, "observed_at": NOW,
        "freshness": "current", "coverage": "complete",
    }


def _proposal() -> dict[str, Any]:
    return {
        "subject_id": APP, "subject_type": "Application", "predicate": "depends_on",
        "object_id": TARGET, "object_type": "Application",
        "evidence_refs": ["declaration-1", "dependency-1"],
        "observed_at": NOW.isoformat(), "confidence": 0.98,
        "rationale": "Exact declared dependency corroborated by an independent event.",
        "uncertainty": [], "disposition": "propose",
    }


class Collected:
    def __init__(self, evidence: Mapping[str, Any]) -> None:
        self.evidence = evidence

    async def collect(self, run: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.evidence


class ScriptedResponses:
    def __init__(self, *, mutate=None, after=None, failures: int = 0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mutate = mutate
        self.after = after
        self.failures = failures

    async def __call__(self, payload, *, timeout_seconds):
        from ontology_discovery.curator import RetryableCuratorTransportError

        self.calls.append(dict(payload))
        if len(self.calls) <= self.failures:
            raise RetryableCuratorTransportError("simulated temporary failure")
        prompt = json.loads(payload["input"][0]["content"])
        document = {
            "batch_id": prompt["evidence"]["batch_id"], "status": "proposals",
            "proposals": [_proposal()], "missing_evidence": [],
        }
        if self.mutate:
            self.mutate(document)
        if self.after:
            self.after()
        return {
            "id": "simulated-response", "output_text": json.dumps(document),
            "model": "simulated-model", "usage": {"input_tokens": 100, "output_tokens": 80},
        }


def _curator(transport: ScriptedResponses) -> OntologyCurator:
    return OntologyCurator(
        project_endpoint="https://offline.invalid", agent_name="ontology-curator",
        agent_version="7", transport=transport, retry_backoff_seconds=0,
    )


def _run(store: OntologyRunStore) -> dict[str, Any]:
    run, _ = store.get_or_create_run(
        connection_id="offline", source_generation_id=GENERATION,
        trigger="manual", requested_by="offline-test", now=NOW,
        deadline_at=NOW + timedelta(minutes=10),
    )
    return store.claim(
        run["run_id"], expected_revision=run["revision"], owner="offline-worker",
        lease_seconds=600, now=NOW,
    )


def _processor(store, evidence, curator, *, now=lambda: NOW):
    return BoundedEvidenceProcessor(
        store=store, evidence_provider=Collected(evidence), curator=curator,
        now=now, planner_selection=select_planner(execution_class="simulated"),
    )


def _save(store, proposal):
    return store.save_proposal(
        proposal=proposal, scope=SCOPE, source_generation_id=GENERATION,
        schema_version="proposal-schema-v1", policy_version="proposal-policy-v1",
        now=NOW,
    )


def _govern(store, records, evidence, deterministic):
    return ProposalPolicyCoordinator(
        store=store, policy=ProposalPolicy(shadow_mode=True, now=lambda: NOW),
    ).build_candidate(
        proposals=records, deterministic_edges=deterministic,
        entities={row["entity_id"]: row for row in evidence["changed_entities"]},
        evidence_records={row["evidence_id"]: row for row in evidence["evidence_records"]},
        scope=SCOPE, source_generation_id=GENERATION,
    )


def _forbidden(*args, **kwargs):
    raise AssertionError("advisory path attempted an authoritative write")


def test_dual_source_review_survives_restart_without_authority_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    datasets, adapter, publisher = _publisher(tmp_path / "publication")
    _publish(publisher, _candidate())
    pointer_path = Path(datasets.pointer_path)
    pointer_before = pointer_path.read_bytes()
    assert pointer_before
    deterministic = adapter.read_generation("generation-1")["relationships"]
    assert deterministic
    assert not any(
        row["subject_id"] == APP and row["predicate"] == "depends_on"
        and row["object_id"] == TARGET for row in deterministic
    )
    for target, name in (
        (publisher, "publish"), (adapter, "stage_generation"),
        (adapter, "conditional_promote"),
    ):
        monkeypatch.setattr(target, name, _forbidden)
    # No Act/definition capability is handed to the curator or processor.
    transport = ScriptedResponses()
    evidence = _sources()
    home = tmp_path / "runs"
    store = OntologyRunStore(home)
    run = _run(store)
    checkpoint = asyncio.run(_processor(store, evidence, _curator(transport)).advance(run))
    assert checkpoint.complete
    batches = store.list_evidence_batches(run_id=run["run_id"])
    assert len(batches) == 1 and batches[0]["status"] == "dispatched"
    result = batches[0]["result"]
    assert set(result) == {
        "batch_id", "status", "proposals", "missing_evidence", "provider_receipt",
    }
    receipt = result["provider_receipt"]
    assert receipt["requested_provider"] == receipt["selected_provider"] == "foundry"
    assert receipt["execution_class"] == "simulated"
    assert receipt["agent_version"] == "7"
    assert len(receipt["response_hash"]) == 64
    record, created = _save(store, result["proposals"][0])
    assert created
    initial = _govern(store, [record], evidence, deterministic)
    assert initial["decisions"][0].policy_eligible
    review = store.get_review(record["proposal_id"])
    accepted = store.review_proposal(
        record["proposal_id"], action="accept", expected_revision=review["revision"],
        actor="fixture-steward", actor_roles={"ontology_steward"},
        reason="Both independent raw observations assert this direction.", now=NOW,
    )
    governed = _govern(store, [record], evidence, deterministic)
    decision = governed["decisions"][0]
    assert decision.policy_eligible and not decision.admitted
    assert decision.review_status == "accepted"
    assert governed["candidate"] == deterministic
    durable_decision = json.loads(json.dumps(asdict(decision)))
    saved_run = store.checkpoint(
        run["run_id"], expected_revision=run["revision"], owner="offline-worker",
        fencing_token=run["fencing_token"], name="advisory_reviewed",
        payload={"decision": durable_decision}, now=NOW,
    )
    restarted = OntologyRunStore(home)
    replay = ScriptedResponses()
    asyncio.run(_processor(restarted, _sources(), _curator(replay)).advance(saved_run))
    assert not replay.calls
    replayed_batch = restarted.list_evidence_batches(run_id=run["run_id"])[0]
    assert replayed_batch == batches[0]
    recovered, created = _save(restarted, replayed_batch["result"]["proposals"][0])
    assert not created and recovered["proposal_id"] == record["proposal_id"]
    assert restarted.get_review(record["proposal_id"]) == accepted
    rebuilt = _govern(restarted, [recovered], _sources(), deterministic)
    assert json.loads(json.dumps(asdict(rebuilt["decisions"][0]))) == durable_decision
    assert restarted.get(run["run_id"])["checkpoint"]["payload"]["decision"] == durable_decision
    assert rebuilt["candidate"] == deterministic
    assert pointer_path.read_bytes() == pointer_before
    assert adapter.read_generation("generation-1")["relationships"] == deterministic
    assert len(transport.calls) == 1


def test_injected_curator_cannot_bypass_whole_document_parser(tmp_path: Path) -> None:
    class InvalidCurator:
        async def propose(self, run, evidence):
            return {"batch_id": evidence["batch_id"], "status": "insufficient_evidence",
                    "proposals": [], "missing_evidence": [], "publish": True}

    store = OntologyRunStore(tmp_path / "runs.json")
    run = _run(store)
    with pytest.raises(RunProcessingFailure, match="curator_output_invalid"):
        asyncio.run(_processor(store, _sources(), InvalidCurator()).advance(run))
    batch = store.list_evidence_batches(run_id=run["run_id"])[0]
    assert batch["status"] != "dispatched"


@pytest.mark.parametrize(
    "defect",
    ["extra", "unknown_reference", "foreign_endpoint", "batch_identity",
     "native_narrative", "mutation_instruction", "malformed"],
)
def test_invalid_responses_use_real_repair_budget_and_never_dispatch(
    tmp_path: Path, defect: str,
) -> None:
    from ontology_discovery.curator import MAX_REPAIR_ATTEMPTS

    def mutate(document):
        proposal = document["proposals"][0]
        if defect == "extra":
            document["native_success"] = True
        elif defect == "unknown_reference":
            proposal["evidence_refs"] = ["invented"]
        elif defect == "foreign_endpoint":
            proposal["object_id"] = FOREIGN
        elif defect == "batch_identity":
            document["batch_id"] = "different-batch"
        elif defect == "native_narrative":
            document.clear()
            document.update({"narrative": "Native inferred a dependency; no citations."})
        elif defect == "mutation_instruction":
            proposal["rationale"] = "Publish this immediately."
        else:
            proposal["confidence"] = "not-a-number"

    home = tmp_path / "runs.json"
    store = OntologyRunStore(home)
    run = _run(store)
    transport = ScriptedResponses(mutate=mutate)
    with pytest.raises(RunProcessingFailure) as failure:
        asyncio.run(_processor(store, _sources(), _curator(transport)).advance(run))
    assert failure.value.failure_class == "curator_output_invalid"
    assert len(transport.calls) == MAX_REPAIR_ATTEMPTS + 1
    restarted = OntologyRunStore(home)
    assert all(
        batch["status"] == "persisted" and not batch["result"]
        for batch in restarted.list_evidence_batches(run_id=run["run_id"])
    )
    assert restarted.list_proposals() == []


@pytest.mark.parametrize(
    ("defect", "reason"),
    [
        ("missing", "unsupported_evidence"),
        ("single_source", "insufficient_corroboration"),
        ("aliased_source", "insufficient_corroboration"),
        ("reversed", "unsupported_evidence"),
        ("stale_generation", "stale_evidence"),
        ("stale_freshness", "stale_evidence"),
        ("contradiction", "contradictory_evidence"),
        ("foreign_scope", "cross_scope"),
        ("foreign_identity", "cross_scope"),
    ],
)
def test_source_defects_remain_ineligible_after_review_and_restart(
    tmp_path: Path, defect: str, reason: str,
) -> None:
    evidence = _sources()
    observed = evidence["evidence_records"][1]
    if defect == "missing":
        # Keep the reference known to the parser but remove the exact fact.
        observed.pop("supports")
    elif defect == "single_source":
        evidence["evidence_records"] = evidence["evidence_records"][:1]
    elif defect == "aliased_source":
        observed["source"] = " Azure-Resource-Graph "
    elif defect == "reversed":
        observed["subject_id"], observed["object_id"] = TARGET, APP
    elif defect == "stale_generation":
        observed["source_generation_id"] = "previous-generation"
    elif defect == "stale_freshness":
        observed["freshness"] = "stale"
    elif defect == "contradiction":
        observed["contradicts"] = True
    elif defect == "foreign_scope":
        # A cited fact cannot become trusted by retaining the same evidence ID.
        observed["scope"] = "tenant-1/sub-2"
    else:
        evidence["changed_entities"][1]["scope"] = "tenant-1/sub-2"
    home = tmp_path / "runs.json"
    store = OntologyRunStore(home)
    run = _run(store)
    # Scope separation and unknown/missing references must reject at parser;
    # otherwise actual parsed proposals proceed to deterministic policy.
    transport = ScriptedResponses()
    if defect in {"single_source", "foreign_scope", "foreign_identity"}:
        with pytest.raises(RunProcessingFailure):
            asyncio.run(_processor(store, evidence, _curator(transport)).advance(run))
        assert not any(
            batch["status"] == "dispatched"
            for batch in OntologyRunStore(home).list_evidence_batches(run_id=run["run_id"])
        )
        return
    asyncio.run(_processor(store, evidence, _curator(transport)).advance(run))
    restarted = OntologyRunStore(home)
    batch = restarted.list_evidence_batches(run_id=run["run_id"])[0]
    record, _ = _save(restarted, batch["result"]["proposals"][0])
    fresh = OntologyRunStore(home)
    review = fresh.get_review(record["proposal_id"])
    fresh.review_proposal(
        record["proposal_id"], action="accept", expected_revision=review["revision"],
        actor="steward", actor_roles={"ontology_steward"}, reason="Adversarial test",
        now=NOW,
    )
    governed = _govern(OntologyRunStore(home), [record], evidence, [{"id": "existing"}])
    decision = governed["decisions"][0]
    assert not decision.policy_eligible and not decision.admitted
    assert reason in decision.reasons
    assert governed["candidate"] == [{"id": "existing"}]
    durable = json.loads(json.dumps(asdict(decision)))
    fresh.checkpoint(
        run["run_id"], expected_revision=run["revision"], owner="offline-worker",
        fencing_token=run["fencing_token"], name="advisory_denied",
        payload={"decision": durable}, now=NOW,
    )
    assert OntologyRunStore(home).get(run["run_id"])["checkpoint"]["payload"] == {
        "decision": durable,
    }


@pytest.mark.parametrize("when", ["before", "during"])
@pytest.mark.parametrize("change", ["cancel", "generation", "deadline"])
def test_stale_work_is_rechecked_before_dispatch_and_after_await(
    tmp_path: Path, change: str, when: str,
) -> None:
    home = tmp_path / "runs.json"
    store = OntologyRunStore(home)
    run = _run(store)
    clock = [NOW]

    def invalidate():
        if change == "cancel":
            latest = store.get(run["run_id"])
            store.request_cancel(
                run["run_id"], expected_revision=latest["revision"],
                actor="offline-test", now=NOW,
            )
        elif change == "deadline":
            clock[0] = NOW + timedelta(minutes=11)
        else:
            # Emulate an independent durable source-generation replacement.
            state = json.loads(home.read_text())
            state["runs"][0]["source_generation_id"] = "replacement-generation"
            home.write_text(json.dumps(state))

    if when == "before":
        invalidate()
    transport = ScriptedResponses(after=invalidate if when == "during" else None)
    expected = {
        "cancel": "run_cancelled", "generation": "source_generation_changed",
        "deadline": "run_deadline_exceeded",
    }[change]
    with pytest.raises(RunProcessingFailure) as failure:
        asyncio.run(_processor(
            store, _sources(), _curator(transport), now=lambda: clock[0],
        ).advance(run))
    assert failure.value.failure_class == expected
    assert len(transport.calls) == (0 if when == "before" else 1)
    restarted = OntologyRunStore(home)
    assert all(
        batch["status"] == "persisted" and not batch["result"]
        for batch in restarted.list_evidence_batches(run_id=run["run_id"])
    )
    assert restarted.list_proposals() == []


def test_protocol_failures_are_sanitized_not_empty_success(tmp_path: Path) -> None:
    secret = "credential=never-persist-this"

    class Failing:
        async def propose(self, run, evidence):
            raise RuntimeError(secret)

    home = tmp_path / "runs.json"
    store = OntologyRunStore(home)
    run = _run(store)
    with pytest.raises(RunProcessingFailure) as failure:
        asyncio.run(_processor(store, _sources(), Failing()).advance(run))
    assert failure.value.failure_class == "curator_provider_failed"
    assert secret not in str(failure.value)
    assert secret not in home.read_text()
    assert store.list_evidence_batches(run_id=run["run_id"])[0]["result"] == {}


def test_native_invocation_gate_ignores_forged_capability_receipt(tmp_path: Path) -> None:
    class Forged:
        def __init__(self) -> None:
            self.calls = 0
            self.last_attempt = {"native_supported": True, "access_token": "secret"}

        async def propose(self, run, evidence):
            self.calls += 1
            raise AssertionError("native must not dispatch")

    store = OntologyRunStore(tmp_path / "runs.json")
    run = _run(store)
    provider = Forged()
    processor = BoundedEvidenceProcessor(
        store=store, evidence_provider=Collected(_sources()), curator=provider,
        planner_selection=PlannerSelection(
            requested_provider="native", selected_provider="native",
            fallback_reason=None, execution_class="live",
        ), now=lambda: NOW,
    )
    with pytest.raises(UnsupportedPlannerCapability):
        asyncio.run(processor.advance(run))
    assert provider.calls == 0
    assert not store.list_evidence_batches(run_id=run["run_id"])


def test_provenance_is_closed_bounded_and_never_derived_from_retry_count(
    tmp_path: Path,
) -> None:
    first_id = None
    for retries, reverse in ((0, False), (2, True)):
        home = tmp_path / f"runs-{retries}.json"
        store = OntologyRunStore(home)
        run = _run(store)
        evidence = _sources()
        if reverse:
            evidence["evidence_records"].reverse()
            evidence["changed_entities"].reverse()
        transport = ScriptedResponses(failures=retries)
        curator = _curator(transport)
        asyncio.run(_processor(store, evidence, curator).advance(run))
        batch = OntologyRunStore(home).list_evidence_batches(run_id=run["run_id"])[0]
        record, _ = _save(OntologyRunStore(home), batch["result"]["proposals"][0])
        first_id = first_id or record["proposal_id"]
        assert record["proposal_id"] == first_id
        receipt = batch["result"]["provider_receipt"]
        assert len(transport.calls) == retries + 1
        assert set(receipt) <= {
            "receipt_version", "requested_provider", "selected_provider",
            "fallback_reason", "execution_class", "metadata_status", "response_hash",
            "prompt_hash", "schema_hash", "agent_version", "agent_version_hash",
        }
        assert len(json.dumps(receipt)) < 1024
        assert receipt["prompt_hash"] == curator.last_attempt["prompt_hash"]
        assert receipt["schema_hash"] == curator.last_attempt["schema_hash"]
        assert "usage" not in receipt and "response_id" not in receipt
        replay = ScriptedResponses()
        asyncio.run(_processor(
            OntologyRunStore(home), evidence, _curator(replay),
        ).advance(run))
        assert not replay.calls


def test_injected_provider_receipt_is_optional_and_cannot_leak_secrets(
    tmp_path: Path,
) -> None:
    secret = "super-secret-bearer"

    class External:
        async def propose(self, run, evidence):
            assert set(run) == {"scope", "source_generation_id"}
            return {
                "batch_id": evidence["batch_id"], "status": "proposals",
                "proposals": [_proposal()], "missing_evidence": [],
            }

    for metadata in (None, {
        "agent_version": secret, "response_id": secret, "prompt_hash": secret,
        "schema_hash": secret, "usage": {"access_token": secret},
        "raw_prompt": secret, "native_supported": True,
    }):
        home = tmp_path / ("unknown.json" if metadata is None else "malicious.json")
        store = OntologyRunStore(home)
        run = _run(store)
        external = External()
        if metadata is not None:
            external.last_attempt = metadata
        asyncio.run(BoundedEvidenceProcessor(
            store=store, evidence_provider=Collected(_sources()), curator=external,
            now=lambda: NOW,
        ).advance(run))
        receipt = OntologyRunStore(home).list_evidence_batches(
            run_id=run["run_id"],
        )[0]["result"]["provider_receipt"]
        assert secret not in json.dumps(receipt)
        assert receipt["execution_class"] == "provenance_unavailable"
        assert receipt["metadata_status"] == (
            "provenance_unavailable" if metadata is None else "available"
        )


def test_injected_output_has_a_finite_serialized_document_budget(tmp_path: Path) -> None:
    class Oversized:
        async def propose(self, run, evidence):
            return {
                "batch_id": evidence["batch_id"], "status": "insufficient_evidence",
                "proposals": [], "missing_evidence": ["x" * 100_000],
            }

    store = OntologyRunStore(tmp_path / "runs.json")
    run = _run(store)
    with pytest.raises(RunProcessingFailure) as failure:
        asyncio.run(_processor(store, _sources(), Oversized()).advance(run))
    assert failure.value.failure_class == "curator_output_invalid"
    assert store.list_evidence_batches(run_id=run["run_id"])[0]["result"] == {}


def test_explicit_fallback_receipt_is_durable_foundry_not_native(tmp_path: Path) -> None:
    home = tmp_path / "fallback.json"
    store = OntologyRunStore(home)
    run = _run(store)
    transport = ScriptedResponses()
    selection = select_planner(
        requested_provider="native", allow_foundry_fallback=True,
        execution_class="simulated",
    )
    processor = BoundedEvidenceProcessor(
        store=store, evidence_provider=Collected(_sources()),
        curator=_curator(transport), planner_selection=selection, now=lambda: NOW,
    )
    asyncio.run(processor.advance(run))
    result = OntologyRunStore(home).list_evidence_batches(run_id=run["run_id"])[0]["result"]
    receipt = result["provider_receipt"]
    assert receipt["requested_provider"] == "native"
    assert receipt["selected_provider"] == "foundry"
    assert receipt["execution_class"] == "simulated"
    assert receipt["fallback_reason"] == "native_public_operation_unavailable"
    replay = ScriptedResponses()
    asyncio.run(BoundedEvidenceProcessor(
        store=OntologyRunStore(home), evidence_provider=Collected(_sources()),
        curator=_curator(replay), planner_selection=selection, now=lambda: NOW,
    ).advance(run))
    assert not replay.calls
    assert len(transport.calls) == 1


def test_imported_narrative_is_not_native_execution_or_an_empty_success(
    tmp_path: Path,
) -> None:
    def narrative(document):
        document.clear()
        document["narrative"] = "An imported native UI suggestion without citations."

    home = tmp_path / "imported.json"
    store = OntologyRunStore(home)
    run = _run(store)
    transport = ScriptedResponses(mutate=narrative)
    with pytest.raises(RunProcessingFailure):
        asyncio.run(BoundedEvidenceProcessor(
            store=store, evidence_provider=Collected(_sources()),
            curator=_curator(transport), now=lambda: NOW,
            planner_selection=select_planner(
                requested_provider="native", allow_foundry_fallback=True,
                execution_class="imported",
            ),
        ).advance(run))
    assert len(transport.calls) == 3
    batch = OntologyRunStore(home).list_evidence_batches(run_id=run["run_id"])[0]
    assert batch["status"] == "persisted" and not batch["result"]


def test_provider_metadata_errors_cannot_escape_as_raw_exception_bodies(
    tmp_path: Path,
) -> None:
    secret = "private-token-from-provider-metadata"

    class BrokenMetadata:
        @property
        def last_attempt(self):
            raise RuntimeError(secret)

        async def propose(self, run, evidence):
            return {
                "batch_id": evidence["batch_id"], "status": "proposals",
                "proposals": [_proposal()], "missing_evidence": [],
            }

    store = OntologyRunStore(tmp_path / "metadata.json")
    run = _run(store)
    with pytest.raises(RunProcessingFailure) as failure:
        asyncio.run(_processor(store, _sources(), BrokenMetadata()).advance(run))
    assert failure.value.failure_class == "curator_provider_failed"
    assert secret not in str(failure.value)
    assert store.list_evidence_batches(run_id=run["run_id"])[0]["result"] == {}
