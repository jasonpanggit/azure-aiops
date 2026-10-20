"""Offline Phase 14 publisher-stage authorization tests (real stores/validator)."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

from datetime import timedelta

import pytest

from ontology.ontology_validator import OntologyValidator
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.maintenance_admission import (
    MaintenanceAuthorizer,
    vocabulary_fingerprint,
)
from ontology_discovery.maintenance_consumers import (
    CONSUMER_FAMILIES,
    ConsumerObservation,
    MaintenanceConsumerCheck,
)
from ontology_discovery.maintenance_relationships import FirstAdmissionLedger
from ontology_discovery.maintenance_release import MaintenanceDenied
from ontology_discovery.publisher import OntologyGenerationPublisher
from ontology_discovery.publisher_worker import PublisherWorker
from storage.datasets import DatasetStore
from storage.locking import MonotonicFenceAllocator
from storage.onelake_documents import OneLakeDocumentStore
from tests.test_ontology_maintenance_admission import (  # noqa: F401
    NOW,
    Authority,
    Env,
    authority,
    maintenance_for,
    model_rows,
    patch_inventory,
    seed_reviewed_proposals,
)


class Ports:
    def __init__(self) -> None:
        self.n = 0

    def make(self, family):
        outer = self

        class Port:
            def observe(self, fam, generation_id, stage):
                outer.n += 1
                return ConsumerObservation(
                    family=fam, observer_id=f"obs-{fam}", source_id=f"src-{fam}",
                    capture_id=f"cap-{fam}-{outer.n}", result_hash=f"h-{fam}-{outer.n}",
                    generation_id=generation_id, stage=stage,
                    definition_fingerprint=vocabulary_fingerprint(),
                    product_fingerprint="" if stage == "staged" else f"p-{fam}",
                    observed_at=NOW, status="pass",
                )

        return Port()


def build(tmp_path, env, authority, *, with_authorizer=True):
    dataset = DatasetStore(str(tmp_path / "publication"))
    storage = dataset.authoritative_publisher(
        publisher_identity="publisher-uai", approved_publisher_identity="publisher-uai"
    )
    publisher = OntologyGenerationPublisher(
        storage, validator=OntologyValidator(),
        approved_publisher_identity="publisher-uai",
    )
    ports = Ports()
    check = MaintenanceConsumerCheck(
        ports={f: ports.make(f) for f in CONSUMER_FAMILIES},
        definition_fingerprint=vocabulary_fingerprint, clock=lambda: NOW,
    )
    materialized = []

    def materialize(candidate):
        materialized.append(candidate.generation_id)
        return {"status": "completed"}

    authorizer = (
        MaintenanceAuthorizer(
            reader=authority.reader(), store=env.store,
            trusted_records=FirstAdmissionLedger(env.tmp / "ledger.json").reader(),
        ) if with_authorizer else None
    )
    worker = PublisherWorker(
        dispatches=PublisherDispatchStore(str(env.dispatch_path)).publisher(),
        publisher=publisher, publisher_identity="publisher-uai",
        owner_id="worker-1",
        fence_allocator=MonotonicFenceAllocator(OneLakeDocumentStore(str(env.dispatch_path))),
        materialize=materialize, consumer_check=check, now=lambda: NOW,
        maintenance_authorizer=authorizer,
    )
    return storage, worker, materialized


def dispatched(tmp_path, monkeypatch, authority):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "pub")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "ledger.json"),
    ))
    env.tmp = tmp_path
    return env


def active(storage):
    pointer = storage.read_pointer()
    return getattr(getattr(pointer, 'pointer', None), 'active_generation', None)


def final(env):
    rows = PublisherDispatchStore(str(env.dispatch_path)).publisher()
    return rows


def test_maintenance_dispatch_reauthorizes_to_immutable_stage(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    storage, worker, materialized = build(tmp_path, env, authority)
    before = active(storage)
    result = worker.run_once(now=NOW, limit=1)
    # Stage is authorized and persisted, but no Plan 06 qualified materializer exists.
    assert result["failed"] == 1 and result["succeeded"] == 0
    assert materialized == []
    assert active(storage) == before
    gen_id = env.published()[0]["candidate"]["generation_id"]
    staged = storage.read_generation(gen_id)
    assert [r for r in staged["relationships"] if r["source"] == "model"]
    # Receipts show independent stage authorization and no materialization.
    view = PublisherDispatchStore(str(env.dispatch_path)).publisher()
    row = view.list_due_publish(now=NOW + timedelta(days=2), limit=5)[0]
    steps = [r["step"] for r in row["receipts"]]
    assert "maintenance_stage_authorization" in steps
    assert "fabric_materialization" not in steps and "pointer_cas" not in steps
    assert row["status"] != "succeeded"


def test_missing_authorizer_denies_model_rows_before_pointer(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    storage, worker, materialized = build(tmp_path, env, authority, with_authorizer=False)
    before = active(storage)
    assert worker.run_once(now=NOW, limit=1)["succeeded"] == 0
    assert materialized == []
    assert active(storage) == before


def test_revocation_between_dispatch_and_publish_denies(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    storage, worker, materialized = build(tmp_path, env, authority)
    authority.control["kill"] = True
    before = active(storage)
    assert worker.run_once(now=NOW, limit=1)["succeeded"] == 0
    assert materialized == []
    assert active(storage) == before


def test_authorizer_rejects_added_unreviewed_edge_and_forged_row(tmp_path, monkeypatch, authority):
    from ontology_discovery.publisher import OntologyGenerationCandidate

    env = dispatched(tmp_path, monkeypatch, authority)
    row = env.published()[0]
    raw = row["candidate"]
    authorizer = MaintenanceAuthorizer(
            reader=authority.reader(), store=env.store,
            trusted_records=FirstAdmissionLedger(env.tmp / "ledger.json").reader(),
        )

    def candidate(relationships):
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

    good = authorizer.model_rows(raw["relationships"])
    assert len(good) == 1
    assert authorizer.authorize(candidate(raw["relationships"]))["model_rows"]
    # Forged identity, tampered scope and an added second (unreviewed) edge all deny.
    base = list(raw["relationships"])
    forged = {**good[0], "resource_id": "maintenance-rel://forged"}
    tampered = {**good[0], "scope": "tenant-2:sub-9:other"}
    for variant in (
        [r for r in base if r is not good[0]] + [forged],
        [r for r in base if r is not good[0]] + [tampered],
        [*base, forged],
        [r for r in base if r is not good[0]] + [{**good[0], "confidence": 0.1}],
    ):
        with pytest.raises(MaintenanceDenied):
            authorizer.authorize(candidate(variant))


def test_worker_requires_maintenance_observer_consumer_check(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    with pytest.raises(ValueError, match="independent_consumer_observers"):
        PublisherWorker(
            dispatches=PublisherDispatchStore(str(env.dispatch_path)).publisher(),
            publisher=object(), publisher_identity="p", owner_id="o",
            fence_allocator=object(), materialize=lambda c: {}, now=lambda: NOW,
            consumer_check=lambda s, g: {f: True for f in CONSUMER_FAMILIES},
            maintenance_authorizer=MaintenanceAuthorizer(
            reader=authority.reader(), store=env.store,
            trusted_records=FirstAdmissionLedger(env.tmp / "ledger.json").reader(),
        ),
        )
