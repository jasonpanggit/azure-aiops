"""Immutable promotion audit boundaries must survive identical replay."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

from datetime import timedelta

import pytest

from ontology_discovery.publisher import PublicationSafetyError
from tests.test_ontology_generation_publication import _candidate, _publish, _publisher
from tests.test_ontology_maintenance_admission import NOW, authority  # noqa: F401
from tests.test_ontology_maintenance_materialization import Real
from tests.test_ontology_maintenance_publication import active, dispatched


class ProcessDeath(BaseException):
    """Model process termination without in-process failure recovery."""


def test_identical_promotion_audit_replays_after_process_death(tmp_path, monkeypatch):
    _store, storage, publisher = _publisher(tmp_path)
    persist = storage.persist_generation_audit

    def die_after_audit(generation_id, audit):
        persist(generation_id, audit)
        raise ProcessDeath

    monkeypatch.setattr(storage, "persist_generation_audit", die_after_audit)
    with pytest.raises(ProcessDeath):
        _publish(publisher, _candidate())
    assert storage.read_pointer().pointer is None
    monkeypatch.setattr(storage, "persist_generation_audit", persist)
    promoted = _publish(publisher, _candidate())
    assert promoted.pointer.active_generation == "generation-1"


def test_different_promotion_audit_never_replays(tmp_path):
    _store, storage, publisher = _publisher(tmp_path)
    persist = storage.persist_generation_audit

    def changed_audit(generation_id, audit):
        persist(generation_id, {**audit, "publisher_identity": "different-publisher"})
        raise ProcessDeath

    storage.persist_generation_audit = changed_audit
    with pytest.raises(ProcessDeath):
        _publish(publisher, _candidate())
    storage.persist_generation_audit = persist
    with pytest.raises(PublicationSafetyError, match="conflicts"):
        _publish(publisher, _candidate())
    assert storage.read_pointer().pointer is None


def test_actual_products_resume_after_promotion_audit_process_death(
    tmp_path, monkeypatch, authority,
):
    env = dispatched(tmp_path, monkeypatch, authority)
    dead = Real(tmp_path, env, authority)
    persist = dead.storage.persist_generation_audit

    def die_after_audit(generation_id, audit):
        persist(generation_id, audit)
        raise ProcessDeath

    monkeypatch.setattr(dead.storage, "persist_generation_audit", die_after_audit)
    with pytest.raises(ProcessDeath):
        dead.worker.run_once(now=NOW, limit=1)
    assert active(dead.storage) is None
    assert any(r["source"] == "model" for r in dead.table("ontology_relationships"))

    later = NOW + timedelta(hours=1)
    fresh = Real(tmp_path, env, authority, worker_now=later)
    result = fresh.worker.run_once(now=later, limit=1)
    assert result["succeeded"] == 1, fresh.worker._dispatches.get_publish(
        env.published()[0]["dispatch_id"]
    )
    generation_id, receipt = fresh.materializer.reader.active()
    assert generation_id == active(fresh.storage)
    assert fresh.materializer.reader.verify(receipt)
    assert any(r["source"] == "model" for r in fresh.table("ontology_relationships"))
