"""Publisher-side independent receipt and freshness authorization (real stores)."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta

import pytest

from ontology_discovery.maintenance_admission import MaintenanceAuthorizer
from ontology_discovery.maintenance_relationships import FirstAdmissionLedger
from ontology_discovery.maintenance_release import MaintenanceDenied
from ontology_discovery.publisher import OntologyGenerationCandidate
from tests.test_ontology_maintenance_admission import (  # noqa: F401
    Env,
    authority,
    maintenance_for,
    patch_inventory,
    seed_reviewed_proposals,
)


def _setup(tmp_path, monkeypatch, authority):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "wev")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    env.run(
        env.processor(
            maintenance=maintenance_for(authority),
            ledger=FirstAdmissionLedger(tmp_path / "ledger.json"),
        )
    )
    row = env.published()[0]
    raw = row["candidate"]
    candidate = OntologyGenerationCandidate(
        generation_id=raw["generation_id"],
        source_generation=row["source_generation_id"],
        entities=tuple(raw["entities"]),
        relationships=tuple(raw["relationships"]),
        proposal_lineage=tuple(raw["proposal_lineage"]),
        decision_lineage=tuple(raw["decision_lineage"]),
        policy_version=raw["policy_version"],
        schema_version=raw["schema_version"],
    )
    authorizer = MaintenanceAuthorizer(
        reader=authority.reader(),
        store=env.store,
        trusted_records=FirstAdmissionLedger(tmp_path / "ledger.json").reader(),
    )
    return env, candidate, authorizer


def _mutate_results(env, fn):
    """Mutate the durable dispatched result in place (real store file state)."""
    state = env.store._read_state()
    for batch in state["evidence_batches"]:
        if batch.get("result"):
            fn(batch["result"])
    env.store._persist_advanced(state, authority_now())


def authority_now():
    from tests.test_ontology_maintenance_admission import NOW

    return NOW


def _rehash(result):
    body = {k: v for k, v in result.items() if k != "provider_receipt"}
    result["provider_receipt"]["response_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_actual_receipt_authorizes_baseline(tmp_path, monkeypatch, authority):
    _, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)
    assert authorizer.authorize(candidate)["model_rows"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.pop("provider_receipt"),
        lambda r: r["provider_receipt"].update(model="wrong-model"),
        lambda r: r["provider_receipt"].update(selected_provider="native"),
        lambda r: r["provider_receipt"].update(prompt_hash="0" * 64),
        lambda r: r["provider_receipt"].update(response_hash="1" * 64),
        lambda r: r["provider_receipt"].pop("model"),
    ],
)
def test_missing_changed_wrong_receipt_denied(tmp_path, monkeypatch, authority, mutation):
    env, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)
    _mutate_results(env, mutation)
    with pytest.raises(MaintenanceDenied):
        authorizer.authorize(candidate)


def test_rebound_response_denied_even_with_matching_hash(tmp_path, monkeypatch, authority):
    env, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)

    def rebind(result):
        result["proposals"] = []
        _rehash(result)

    _mutate_results(env, rebind)
    with pytest.raises(MaintenanceDenied):
        authorizer.authorize(candidate)


def test_changed_response_with_stale_hash_denied(tmp_path, monkeypatch, authority):
    env, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)

    def tweak(result):
        result["proposals"] = copy.deepcopy(result["proposals"])
        result["proposals"][0]["rationale"] = "changed after receipt"

    _mutate_results(env, tweak)
    with pytest.raises(MaintenanceDenied):
        authorizer.authorize(candidate)


def test_evidence_expiry_between_dispatch_and_publish_denies(tmp_path, monkeypatch, authority):
    _, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)
    assert authorizer.authorize(candidate)["model_rows"] == 1
    authority.clock[0] = authority.clock[0] + timedelta(days=2)
    # Fresh clock at every authorize: same policy that reports stale denies.
    with pytest.raises(MaintenanceDenied):
        authorizer.authorize(candidate)


def _duplicate_delivery(env, receipt_update):
    """Add a second dispatched row for the same batch/result with its own receipt."""
    state = env.store._read_state()
    original = next(b for b in state["evidence_batches"] if b.get("result"))
    clone = copy.deepcopy(original)
    clone["batch_id"] = original["batch_id"] + "-redelivery"
    clone["result"]["provider_receipt"].update(receipt_update)
    state["evidence_batches"].append(clone)
    state["evidence_batches"].sort(key=lambda row: row["batch_id"])
    env.store._persist_advanced(state, authority_now())


def test_duplicate_delivery_with_identical_receipt_authorizes(tmp_path, monkeypatch, authority):
    env, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)
    _duplicate_delivery(env, {})
    assert authorizer.authorize(candidate)["model_rows"] == 1


@pytest.mark.parametrize(
    "conflict",
    [
        {"model": "wrong-model"},
        {"selected_provider": "native"},
        {"agent_version": "9.9.9"},
        {"prompt_hash": "2" * 64},
        {"schema_hash": "3" * 64},
    ],
)
def test_duplicate_delivery_with_conflicting_receipt_denied(
    tmp_path, monkeypatch, authority, conflict
):
    env, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)
    _duplicate_delivery(env, conflict)
    with pytest.raises(MaintenanceDenied):
        authorizer.authorize(candidate)
