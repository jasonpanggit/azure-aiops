"""Plan 14-04 corrective tests: trusted records, mandatory model, stage audit."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from ontology_discovery.maintenance_admission import MaintenanceAuthorizer
from ontology_discovery.maintenance_relationships import FirstAdmissionLedger
from ontology_discovery.maintenance_release import MaintenanceDenied
from ontology_discovery.publisher import OntologyGenerationCandidate
from storage.onelake_documents import DocumentConflictError
from tests.test_ontology_maintenance_admission import (  # noqa: F401
    NOW,
    Env,
    authority,
    maintenance_for,
    model_rows,
    patch_inventory,
    seed_reviewed_proposals,
)
from tests.test_ontology_maintenance_publication import build, dispatched


def _candidate(env):
    row = env.published()[0]
    raw = row["candidate"]

    def make(relationships):
        return OntologyGenerationCandidate(
            generation_id=raw["generation_id"],
            source_generation=row["source_generation_id"],
            entities=tuple(raw["entities"]),
            relationships=tuple(relationships),
            proposal_lineage=tuple(raw["proposal_lineage"]),
            decision_lineage=tuple(raw["decision_lineage"]),
            policy_version=raw["policy_version"],
            schema_version=raw["schema_version"],
        )

    return raw, make


def _authorizer(env, authority, reader):
    return MaintenanceAuthorizer(
        reader=authority.reader(), store=env.store, trusted_records=reader
    )


# ---------------------------------------------------------------- (1) lineage
def test_candidate_supplied_time_run_and_valid_from_are_rejected(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    raw, make = _candidate(env)
    auth = _authorizer(env, authority, FirstAdmissionLedger(tmp_path / "ledger.json").reader())
    assert auth.authorize(make(raw["relationships"]))["model_rows"] == 1
    good = model_rows(raw)[0]
    for change in (
        {"timestamp": (datetime.fromisoformat(good["timestamp"]) + timedelta(days=1)).isoformat()},
        {"ingestion_run_id": "forged-run"},
        {"valid_from": "2001-01-01T00:00:00+00:00"},
    ):
        tampered = [r if r is not good else {**good, **change} for r in raw["relationships"]]
        with pytest.raises(MaintenanceDenied, match="model_edge_not_canonical"):
            auth.authorize(make(tampered))


def test_missing_or_changed_trusted_records_deny(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    raw, make = _candidate(env)
    candidate = make(raw["relationships"])
    with pytest.raises(MaintenanceDenied, match="trusted_records_unavailable"):
        _authorizer(env, authority, None).authorize(candidate)
    empty = FirstAdmissionLedger(tmp_path / "other.json").reader()
    with pytest.raises(MaintenanceDenied, match="trusted_records_missing"):
        _authorizer(env, authority, empty).authorize(candidate)
    path = tmp_path / "ledger.json"
    stored = json.loads(path.read_text())
    key = next(k for k in stored if k.startswith("source-observation://"))
    stored[key]["source_observed_at"] = "2001-01-01T00:00:00+00:00"
    path.write_text(json.dumps(stored))
    with pytest.raises(MaintenanceDenied, match="model_edge_not_canonical"):
        _authorizer(env, authority, FirstAdmissionLedger(path).reader()).authorize(candidate)
    # Changed first-admission record (value diverges from legacy ledger entry).
    stored = json.loads(path.read_text())
    fkey = next(k for k in stored if k.startswith("first-admission://"))
    stored[fkey]["first_admitted_at"] = "2001-01-01T00:00:00+00:00"
    path.write_text(json.dumps(stored))
    with pytest.raises(MaintenanceDenied, match="trusted_records_missing"):
        _authorizer(env, authority, FirstAdmissionLedger(path).reader()).authorize(candidate)


def test_ledger_is_create_only_and_survives_restart(tmp_path):
    path = tmp_path / "l.json"
    first = FirstAdmissionLedger(path).record_source_observation(
        "sg", observed_at=NOW, ingestion_run_id="run-1", manifest_digest="d1"
    )
    again = FirstAdmissionLedger(path).record_source_observation(  # restart
        "sg", observed_at=NOW, ingestion_run_id="run-1", manifest_digest="d1"
    )
    assert first == again == FirstAdmissionLedger(path).reader().source_observation("sg")
    for drift in (
        {"observed_at": NOW + timedelta(seconds=1), "ingestion_run_id": "run-1", "manifest_digest": "d1"},
        {"observed_at": NOW, "ingestion_run_id": "run-2", "manifest_digest": "d1"},
        {"observed_at": NOW, "ingestion_run_id": "run-1", "manifest_digest": "d2"},
    ):
        with pytest.raises(MaintenanceDenied, match="trusted_record_conflict"):
            FirstAdmissionLedger(path).record_source_observation("sg", **drift)
    ledger = FirstAdmissionLedger(path)
    ledger.get_or_record("rid", NOW, provenance={"source_generation_id": "sg", "ingestion_run_id": "r"})
    with pytest.raises(MaintenanceDenied, match="trusted_record_conflict"):
        ledger.get_or_record("rid", NOW, provenance={"source_generation_id": "other", "ingestion_run_id": "r"})
    assert ledger.reader().first_admission("rid")["first_admitted_at"] == NOW.isoformat()


# ------------------------------------------------------------------ (2) model
def _run_with_attempt(tmp_path, monkeypatch, authority, mutate, name):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, name)
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    original = env.curator.propose

    async def propose(run, evidence):
        out = await original(run, evidence)
        mutate(env.curator)
        return out

    env.curator.propose = propose
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / f"{name}.json"),
    ))
    return env


@pytest.mark.parametrize("name,mutate", [
    ("absent", lambda c: setattr(c, "last_attempt", None)),
    ("empty", lambda c: c.last_attempt.update(model="")),
    ("missing", lambda c: c.last_attempt.pop("model")),
    ("changed", lambda c: c.last_attempt.update(model="gpt-other")),
])
def test_exact_model_metadata_is_obligatory(tmp_path, monkeypatch, authority, name, mutate):
    env = _run_with_attempt(tmp_path, monkeypatch, authority, mutate, name)
    assert model_rows(env.published()[0]["candidate"]) == []


def test_matching_model_still_admits_and_release_without_model_is_denied(
    tmp_path, monkeypatch, authority
):
    env = _run_with_attempt(tmp_path, monkeypatch, authority, lambda c: None, "same")
    assert len(model_rows(env.published()[0]["candidate"])) == 1
    payload = authority.payload()
    del payload["release"]["lineage"]["model"]
    payload["evaluation"]["bound_lineage"].pop("model", None)
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == "release_model_lineage_required"


# ---------------------------------------------------------------- (3) audit
def _audit_files(tmp_path):
    return sorted((tmp_path / "publication" / "generations").glob("*/stage-authorization-*.json"))


def test_stage_authorization_audit_precedes_materializer_and_is_immutable(
    tmp_path, monkeypatch, authority
):
    env = dispatched(tmp_path, monkeypatch, authority)
    storage, worker, _materialized = build(tmp_path, env, authority)
    gen = env.published()[0]["candidate"]["generation_id"]
    seen = []

    def materialize(candidate):
        seen.append([p.name for p in _audit_files(tmp_path)])
        return {"status": "completed"}

    materialize.maintenance_candidate_bound = True
    worker._materialize = materialize
    worker.run_once(now=NOW, limit=1)
    files = _audit_files(tmp_path)
    assert len(files) == 1 and seen and seen[0] == [files[0].name]  # audit before materializer
    record = json.loads(files[0].read_text())
    staged = storage.read_generation(gen)
    assert record["event"] == "maintenance_stage_authorization"
    assert record["generation_id"] == gen
    assert record["content_hash"] == staged["manifest"]["content_hash"]
    assert record["attestation_digest"] == authority.reader().read().attestation_digest
    assert record["release_id"] == "release-1" and record["model_rows"] == 1
    assert record["authorization_digest"]
    # Duplicate/conflicting write of the same authorization is refused.
    with pytest.raises(DocumentConflictError):
        storage.persist_stage_authorization(
            target_generation_id=gen, owner_id=record["owner_id"],
            fence=record["fence"], audit={**record, "model_rows": 9},
        )


def test_no_audit_and_no_materializer_when_authorization_denied(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    _storage, worker, materialized = build(tmp_path, env, authority)
    authority.control["kill"] = True
    worker.run_once(now=NOW, limit=1)
    assert materialized == [] and _audit_files(tmp_path) == []
