"""Plan 14-06 Task 2: fenced durable restart recovery and rematerialization."""

# ruff: noqa: F811  (pytest fixture re-import)

from __future__ import annotations

import copy
from datetime import timedelta

import pytest

from tests.test_ontology_maintenance_admission import (
    NOW,
    authority,  # noqa: F401
)
from tests.test_ontology_maintenance_materialization import Real
from tests.test_ontology_maintenance_publication import active, dispatched


class SimulatedProcessDeath(BaseException):
    """Not an Exception: no in-process handler may run, as with a killed worker."""


def _die_at(point):
    def fault(name):
        if name == point:
            raise SimulatedProcessDeath(name)

    return fault


def _bind_exact_restore_grant(real, authority, generation_id):
    """Give this test worker a signed, exact-target restore-only grant."""
    if getattr(real.authorizer, "_explicit_restore_authority", False):
        return
    staged = real.storage.read_generation(generation_id)
    receipt = real.materializer.receipts.latest(generation_id)
    if receipt is None:
        raise AssertionError(f"retained generation has no product receipt: {generation_id}")
    expected = {
        **real.materializer._expected_target,
        "generation_id": generation_id,
        "content_hash": str(staged["manifest"]["content_hash"]),
        "authorization_digest": str(receipt["authorization_digest"]),
    }
    payload = authority.payload()
    payload["release"].update(
        release_id=f"restore-{generation_id}",
        operations=["restore"],
        restore_target=expected,
    )
    holder = getattr(real, "_restore_authority_holder", None)
    if holder is None:
        from ontology_discovery.maintenance_admission import MaintenanceAuthorizer
        from ontology_discovery.maintenance_release import MaintenanceReleaseReader

        base = real.authorizer
        holder = {"envelope": authority.sign(payload), "control": copy.deepcopy(authority.control)}
        restore_reader = MaintenanceReleaseReader(
            trust=authority.trust,
            envelope_source=lambda: copy.deepcopy(holder["envelope"]),
            control_source=lambda: copy.deepcopy(holder["control"]),
            clock=lambda: authority.clock[0],
        )

        class BoundRestoreAuthorizer(MaintenanceAuthorizer):
            def __init__(self):
                super().__init__(
                    reader=base.reader,
                    store=base._store,
                    trusted_records=base._trusted,
                )
                self._restore_reader_authorizer = MaintenanceAuthorizer(
                    reader=restore_reader,
                    store=base._store,
                    trusted_records=base._trusted,
                )

            def authorize_restore(self, *, expected_target=None):
                return self._restore_reader_authorizer.authorize_restore(
                    expected_target=expected_target
                )

        real.authorizer = BoundRestoreAuthorizer()
        real.materializer._authorizer = real.authorizer
        real._restore_authority_holder = holder
    else:
        holder["envelope"] = authority.sign(payload)
        holder["control"] = copy.deepcopy(authority.control)


def _snapshot(real, receipt):
    return {
        t: sorted(map(repr, (sorted(r.items()) for r in real.table(t))))
        for t in ("ontology_entities", "ontology_relationships")
    }


@pytest.mark.parametrize(
    "point",
    [
        "after_intent",
        "before_table_write:1",
        "before_table_write:7",
        "after_materialized",
        "after_pointer_commit",
    ],
)
def test_restart_converges_to_exact_candidate_after_process_death(
    tmp_path, monkeypatch, authority, point
):
    env = dispatched(tmp_path, monkeypatch, authority)
    dead = Real(tmp_path, env, authority, fault=_die_at(point))
    with pytest.raises(SimulatedProcessDeath):
        dead.worker.run_once(now=NOW, limit=1)
    pointer_moved = active(dead.storage) is not None
    assert pointer_moved == (point == "after_pointer_commit")

    later = NOW + timedelta(days=2)
    fresh = Real(tmp_path, env, authority, worker_now=later)  # new stores/service/worker/materializer
    result = fresh.worker.run_once(now=later, limit=1)
    if result["succeeded"] != 1:
        from ontology_discovery.dispatch_store import PublisherDispatchStore as _S

        rows = _S(str(env.dispatch_path)).publisher().list_due_publish(
            now=later + timedelta(days=9), limit=5
        )
        raise AssertionError((point, result, [(r["status"], r.get("reason_code"), r.get("terminal_receipt")) for r in rows]))
    gen = active(fresh.storage)
    generation, receipt = fresh.materializer.reader.active()
    assert generation == gen
    assert fresh.materializer.reader.verify(receipt)
    staged = fresh.storage.read_generation(gen)
    me = next(r for r in staged["relationships"] if r["source"] == "model")
    key = (me["subject_id"], me["predicate"], me["object_id"])
    assert key in {
        (r["subject_id"], r["predicate"], r["object_id"])
        for r in fresh.table("ontology_relationships")
    }
    assert not fresh.materializer.has_open_critical()


def test_rematerialization_restores_exact_old_new_old_bytes(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    assert real.worker.run_once(now=NOW, limit=1)["succeeded"] == 1
    gen, receipt = real.materializer.reader.active()
    old = _snapshot(real, receipt)
    # Corrupt the physical products behind the pointer (new/foreign bytes).
    real.service.materialize_ontology_generation(
        entities=[], relationships=[], generation_id="rogue", source_generation="x",
        content_hash="0" * 64, authorization_digest="", attestation_digest="",
        validation={},
    )
    assert _snapshot(real, receipt) != old
    # Recovery rematerializes the pointer's authoritative generation, not source replay.
    real.materializer.bind(
        owner_id="worker-1", fence=10_000, predecessor=None, pointer_etag=None
    )
    _bind_exact_restore_grant(real, authority, gen)
    outcome = real.materializer.recover_physical(reason="drill")
    real.materializer.release()
    assert outcome["target_generation"] == gen
    _, restored = real.materializer.reader.active()
    assert restored["receipt_digest"] != receipt["receipt_digest"]
    assert _snapshot(real, restored) == old
    assert real.materializer.reader.verify(restored)


def test_stale_owner_cannot_write_after_takeover(tmp_path, monkeypatch, authority):
    from ontology_discovery.publisher import PublicationSafetyError

    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    real.materializer.bind(owner_id="old", fence=5, predecessor=None, pointer_etag=None)
    real.materializer.lease.acquire("old", 5)
    other = Real(tmp_path, env, authority)
    other.materializer.bind(owner_id="old", fence=6, predecessor=None, pointer_etag=None)
    other.materializer.lease.acquire("old", 6)  # restart takeover, token replaced
    with pytest.raises(PublicationSafetyError):
        real.materializer.assert_owned()
    other.materializer.assert_owned()


def _generation_b(real, name="generation-b"):
    from ontology_discovery.publisher import OntologyGenerationCandidate
    from tests.test_ontology_generation_publication import _entity, _relationship

    return OntologyGenerationCandidate(
        generation_id=name,
        source_generation="source-b",
        entities=(_entity("vm-1", "VirtualMachine"), _entity("app-1", "Application")),
        relationships=(_relationship(),),
        proposal_lineage=(),
        decision_lineage=(),
        policy_version="ontology-policy/v1",
        schema_version="ontology-generation/v1",
    )


def _publish_b(real, candidate, *, post=None, pre_cas=None, fence=100):
    from ontology_discovery.publisher import APPROVED_PUBLICATION_CHECKPOINTS
    from storage.datasets import GenerationPointerConditions

    current = active(real.storage)
    if current is not None:
        _bind_exact_restore_grant(real, real.env_authority, current)
    check = real.worker._consumer_check
    return real.worker._publisher.publish(
        candidate,
        publisher_identity="publisher-uai",
        checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
        pointer_conditions=GenerationPointerConditions.from_snapshot(
            real.storage.read_pointer()
        ),
        owner_id="worker-b",
        fence=fence,
        consumer_compatibility=dict.fromkeys(
            ("api", "fabric", "agent", "export", "semantic"), True
        ),
        cancellation_check=lambda: False,
        lease_guard=lambda: None,
        materialize_generation=real.materializer,
        staged_consumer_check=lambda g: check("staged", g),
        post_consumer_check=post or (lambda g: check("post", g)),
        pre_cas_hook=pre_cas,
        rollback_fence_allocator=lambda: fence + 50,
    )


def _published_a(tmp_path, monkeypatch, authority):
    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority)
    assert real.worker.run_once(now=NOW, limit=1)["succeeded"] == 1
    gen_a, receipt_a = real.materializer.reader.active()
    return real, gen_a, receipt_a, _snapshot(real, receipt_a)


def test_post_check_failure_restores_old_new_old_bytes(tmp_path, monkeypatch, authority):
    from ontology_discovery.publisher import PostCheckRollbackError

    real, gen_a, receipt_a, old = _published_a(tmp_path, monkeypatch, authority)
    seen = {}

    def failing_post(generation):
        if generation == "generation-b":
            _, receipt = real.materializer.reader.active()
            seen["new"] = _snapshot(real, receipt)
            return dict.fromkeys(("api", "fabric", "agent", "export", "semantic"), False)
        return real.worker._consumer_check("post", generation)

    with pytest.raises(PostCheckRollbackError):
        _publish_b(real, _generation_b(real), post=failing_post)
    assert seen["new"] != old  # B really was materialized and visible
    assert active(real.storage) == gen_a
    _, restored = real.materializer.reader.active()
    assert restored["generation_id"] == gen_a
    assert restored["receipt_digest"] != receipt_a["receipt_digest"]  # rematerialized
    assert _snapshot(real, restored) == old  # old -> new -> old, real Delta bytes
    assert real.materializer.reader.verify(restored)
    assert not real.materializer.has_open_critical()


def test_cas_not_reached_after_materialization_restores_predecessor(
    tmp_path, monkeypatch, authority
):
    real, gen_a, receipt_a, old = _published_a(tmp_path, monkeypatch, authority)
    seen = {}

    def lose_before_cas():
        seen["head"] = _snapshot(real, receipt_a)  # live Delta head = B
        seen["pinned"] = {
            t: sorted(
                map(repr, (sorted(r.items()) for r in real.materializer.reader.read_table(t, receipt_a)))
            )
            for t in ("ontology_entities", "ontology_relationships")
        }
        raise RuntimeError("pre-cas contention")

    with pytest.raises(RuntimeError):
        _publish_b(real, _generation_b(real, "generation-c"), pre_cas=lose_before_cas)
    assert seen["head"] != old  # B really was physically written
    assert seen["pinned"] == old  # pinned reader never exposes unpromoted B
    assert active(real.storage) == gen_a
    _, restored = real.materializer.reader.active()
    assert _snapshot(real, restored) == old
    assert real.materializer.reader.verify(restored)


# Corrective qualification: OLD is deterministic; the actual processor dispatch
# adds a novel reviewed model edge in NEW. All success paths use real products.
def _deterministic_predecessor(tmp_path, monkeypatch, authority, **kwargs):
    from dataclasses import replace

    from ontology_discovery.publisher_worker import _candidate_from_dispatch

    env = dispatched(tmp_path, monkeypatch, authority)
    real = Real(tmp_path, env, authority, **kwargs)
    candidate = _candidate_from_dispatch(env.published()[0], allow_model_rows=True)
    old = replace(
        candidate, generation_id="deterministic-predecessor",
        relationships=tuple(r for r in candidate.relationships if r.get("source") != "model"),
        proposal_lineage=(), decision_lineage=(),
    )
    _publish_b(real, old, fence=1)
    real.worker._fences.allocate(
        scope=str(env.published()[0]["connection_id"]), owner_id="predecessor"
    )
    return env, real, candidate


def _physical(real, candidate, *, receipt=None):
    from fabric.dataset_mapper import ontology_relationship_table
    from ontology_discovery.maintenance_materialization import _hash, _membership

    model = next(r for r in candidate.relationships if r.get("source") == "model")
    typed = ontology_relationship_table(
        model["subject_type"], model["predicate"], model["object_type"]
    )
    tables = ("ontology_entities", "ontology_relationships", typed)
    rows = {
        t: real.table(t) if receipt is None else real.materializer.reader.read_table(t, receipt)
        for t in tables
    }
    return {
        t: {"membership": _membership(data, t), "hash": _hash(_membership(data, t))}
        for t, data in rows.items()
    }


def _assert_model(real, candidate, present):
    from fabric.dataset_mapper import ontology_relationship_table
    from ontology_discovery.maintenance_materialization import _membership

    model = next(r for r in candidate.relationships if r.get("source") == "model")
    typed = ontology_relationship_table(
        model["subject_type"], model["predicate"], model["object_type"]
    )
    for table in ("ontology_relationships", typed):
        # Full schema membership includes source, evidence and row lineage, not
        # just endpoints/counts. Typed and canonical schemas are independently applied.
        member = _membership([model], table)[0]
        assert (member in _membership(real.table(table), table)) is present


def _fail_real_post(real, candidate, seen):
    original = real.worker._consumer_check

    def check(stage, generation):
        results = dict(original(stage, generation))
        if stage == "post" and generation == candidate.generation_id:
            assert all(results.values())
            _assert_model(real, candidate, True)
            seen["new"] = _physical(real, candidate)
            seen["new_receipt"] = real.materializer.reader.active()[1]
            results["semantic"] = False  # fault only the independently read result
        return results

    real.worker._consumer_check = check


@pytest.mark.parametrize("boundary", ["post", "cas"])
def test_novel_model_new_generation_real_old_new_old(
    tmp_path, monkeypatch, authority, boundary
):
    from storage.onelake_documents import DocumentConflictError

    _env, real, candidate = _deterministic_predecessor(tmp_path, monkeypatch, authority)
    old = _physical(real, candidate)
    old_receipt = real.materializer.reader.active()[1]
    _assert_model(real, candidate, False)
    seen = {}
    if boundary == "post":
        _fail_real_post(real, candidate, seen)
    else:
        promote = real.storage.conditional_promote

        def lose_cas(**kwargs):
            if kwargs["generation_id"] == candidate.generation_id:
                _assert_model(real, candidate, True)
                seen["new"] = _physical(real, candidate)
                seen["new_receipt"] = real.materializer.receipts.latest(candidate.generation_id)
                assert _physical(real, candidate, receipt=old_receipt) == old
                assert active(real.storage) == "deterministic-predecessor"
                # Actual conditional conflict at the pointer storage boundary.
                kwargs["conditions"] = type(kwargs["conditions"])(
                    **{**vars(kwargs["conditions"]), "etag": '"stale-etag"'}
                )
                with pytest.raises(DocumentConflictError):
                    promote(**kwargs)
                raise DocumentConflictError("injected stale CAS")
            return promote(**kwargs)

        monkeypatch.setattr(real.storage, "conditional_promote", lose_cas)
    _bind_exact_restore_grant(real, authority, "deterministic-predecessor")
    result = real.worker.run_once(now=NOW, limit=1)
    assert result["failed"] == 1 and result["succeeded"] == 0, result
    assert seen["new"] != old
    assert active(real.storage) == "deterministic-predecessor"
    assert _physical(real, candidate) == old
    _assert_model(real, candidate, False)
    _, restored = real.materializer.reader.active()
    assert restored["receipt_digest"] != old_receipt["receipt_digest"]
    assert _physical(real, candidate, receipt=restored) == old
    assert all(real.worker._consumer_check("post", active(real.storage)).values())
    for table, data in old.items():
        assert restored["products"][table]["hash"] == data["hash"]
        assert restored["products"][table]["version"] >= seen["new_receipt"]["products"][table]["version"]
    assert not real.materializer.has_open_critical()


@pytest.mark.parametrize("boundary", ["after_restore_physical", "after_restore_pointer"])
def test_restart_after_restore_boundaries_keeps_rejected_model_out(
    tmp_path, monkeypatch, authority, boundary
):
    env, real, candidate = _deterministic_predecessor(tmp_path, monkeypatch, authority)
    old = _physical(real, candidate)
    seen = {}
    _fail_real_post(real, candidate, seen)
    real.materializer._fault = _die_at(boundary)
    _bind_exact_restore_grant(real, authority, "deterministic-predecessor")
    with pytest.raises(SimulatedProcessDeath):
        real.worker.run_once(now=NOW, limit=1)
    assert seen["new"] != old
    assert _physical(real, candidate) == old
    pinned = real.materializer.reader.active()[1]
    if boundary == "after_restore_physical":
        assert active(real.storage) == candidate.generation_id
        assert _physical(real, candidate, receipt=pinned) == seen["new"]
    else:
        assert active(real.storage) == "deterministic-predecessor"
        assert _physical(real, candidate, receipt=pinned) == old
    journal = real.materializer.journal.read()
    assert journal["recovery"]["target_generation"] == "deterministic-predecessor"
    later = NOW + timedelta(days=2)
    fresh = Real(tmp_path, env, authority, worker_now=later)
    _bind_exact_restore_grant(fresh, authority, "deterministic-predecessor")
    # Fresh stores, service, DeltaWriter, materializer, worker and real expired
    # target lease; the rejected generation must not be re-promoted on restart.
    result = fresh.worker.run_once(now=later, limit=1)
    assert result["succeeded"] == 0 and result["failed"] == 1, result
    assert active(fresh.storage) == "deterministic-predecessor"
    assert _physical(fresh, candidate) == old
    _, receipt = fresh.materializer.reader.active()
    assert _physical(fresh, candidate, receipt=receipt) == old
    assert fresh.materializer.reader.verify(receipt)
    assert all(fresh.worker._consumer_check("post", active(fresh.storage)).values())
    journal = fresh.materializer.journal.read()
    assert journal["phase"] == "restored"
    assert all(journal["recovery"][k] for k in ("physical", "pointer", "consumer"))


@pytest.mark.parametrize("boundary", ["before", "during", "lease"])
def test_cancellation_and_expired_lease_stop_physical_writes(
    tmp_path, monkeypatch, authority, boundary
):
    from ontology_discovery.maintenance_materialization import MaterializationCritical
    from ontology_discovery.publisher import PublicationSafetyError

    clock = [NOW]
    env, real, candidate = _deterministic_predecessor(
        tmp_path, monkeypatch, authority, product_clock=lambda: clock[0]
    )
    old = _physical(real, candidate)
    receipt = real.materializer.reader.active()[1]
    cancelled = [boundary == "before"]
    writes = []
    changed = []
    write = real.delta.write

    def counted(*args, **kwargs):
        writes.append(args[0])
        changed_table = str(args[0]).endswith("/ontology_relationships") and not changed
        if boundary == "lease" and changed_table:
            # Expire after the materializer's sink guard, while the real Delta
            # write call is in flight, BEFORE its changed product is committed.
            clock[0] += timedelta(minutes=6)
        result = write(*args, **kwargs)
        if changed_table:
            changed.append(_physical(real, candidate))
            assert changed[0] != old  # interruption follows an actual changed Delta commit
            assert _physical(real, candidate, receipt=receipt) == old
            if boundary != "lease":
                cancelled[0] = True
        return result

    monkeypatch.setattr(real.delta, "write", counted)
    with pytest.raises((PublicationSafetyError, MaterializationCritical)):
        _publish_candidate(real, candidate, cancellation=lambda: cancelled[0])
    assert active(real.storage) == "deterministic-predecessor"
    assert _physical(real, candidate, receipt=receipt) == old
    if boundary == "before":
        assert not writes and _physical(real, candidate) == old
    elif boundary == "during":
        assert changed
        assert _physical(real, candidate) == old
        assert real.materializer.journal.read()["recovery"]["physical"]
    else:
        assert len(writes) == 2  # entities + changed relationships; then holder must stop
        assert changed
        assert real.materializer.has_open_critical()
        # A separately fenced fresh holder reconciles durable uncertainty.
        fresh = Real(tmp_path, env, authority, worker_now=clock[0])
        _bind_exact_restore_grant(fresh, authority, "deterministic-predecessor")
        fresh.materializer.bind(owner_id="reconciler", fence=500, predecessor=None, pointer_etag=None)
        fresh.materializer.reconcile()
        assert _physical(fresh, candidate) == old
        checks = fresh.worker._consumer_check("post", active(fresh.storage))
        assert all(checks.values())
        fresh.materializer.mark_recovery(pointer=True, consumer=all(checks.values()))
        fresh.materializer.release()
        assert fresh.materializer.journal.read()["phase"] == "restored"


def _publish_candidate(real, candidate, *, cancellation=lambda: False, post=None, fence=100):
    from ontology_discovery.publisher import APPROVED_PUBLICATION_CHECKPOINTS
    from storage.datasets import GenerationPointerConditions

    current = active(real.storage)
    if current is not None:
        _bind_exact_restore_grant(real, real.env_authority, current)
    return real.worker._publisher.publish(
        candidate, publisher_identity="publisher-uai",
        checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
        pointer_conditions=GenerationPointerConditions.from_snapshot(real.storage.read_pointer()),
        owner_id="corrective-worker", fence=fence,
        consumer_compatibility=dict.fromkeys(("api", "fabric", "agent", "export", "semantic"), True),
        cancellation_check=cancellation, lease_guard=lambda: None,
        materialize_generation=real.materializer,
        staged_consumer_check=lambda g: real.worker._consumer_check("staged", g),
        post_consumer_check=post or (lambda g: real.worker._consumer_check("post", g)),
        rollback_fence_allocator=lambda: fence + 50,
        maintenance_authorizer=real.authorizer,
    )


@pytest.mark.parametrize("boundary", ["before_restore_write", "restore_cas"])
def test_stale_recovery_cannot_overwrite_real_newer_winner(
    tmp_path, monkeypatch, authority, boundary
):
    from dataclasses import replace

    from ontology_discovery.publisher import PublicationSafetyError
    from storage.onelake_documents import DocumentConflictError

    clock = [NOW]
    env, real, candidate = _deterministic_predecessor(
        tmp_path, monkeypatch, authority, product_clock=lambda: clock[0]
    )
    old = _physical(real, candidate)
    seen = {}
    _fail_real_post(real, candidate, seen)
    winner = {}

    def win():
        clock[0] += timedelta(minutes=6)
        newer = Real(tmp_path, env, authority, worker_now=clock[0])
        # Reconcile the previous incomplete attempt under a genuinely fresh,
        # higher target fence, then publish different physical membership.
        deterministic = replace(
            candidate, generation_id="newer-authoritative-winner",
            relationships=(), proposal_lineage=(), decision_lineage=(),
        )
        _publish_b(newer, deterministic, fence=500)
        _bind_exact_restore_grant(real, authority, "newer-authoritative-winner")
        winner.update(
            real=newer, physical=_physical(newer, candidate),
            receipt=newer.materializer.reader.active()[1],
        )
        assert winner["physical"] != old

    if boundary == "before_restore_write":
        fired = [False]

        def fault(point):
            if point == "restore_write" and not fired[0]:
                fired[0] = True
                win()

        real.materializer._fault = fault
    else:
        promote = real.storage.conditional_promote

        def restore_cas(**kwargs):
            if kwargs["generation_id"] == "deterministic-predecessor":
                win()
                # Exercise the actual failed stale conditional update.
                with pytest.raises(DocumentConflictError):
                    promote(**kwargs)
                raise DocumentConflictError("newer winner owns pointer")
            return promote(**kwargs)

        monkeypatch.setattr(real.storage, "conditional_promote", restore_cas)
    with pytest.raises(PublicationSafetyError):
        _publish_candidate(
            real, candidate, post=lambda g: real.worker._consumer_check("post", g)
        )
    assert seen["new"] != old
    newer = winner["real"]
    assert active(newer.storage) == "newer-authoritative-winner"
    assert _physical(newer, candidate) == winner["physical"]
    assert newer.materializer.reader.active()[1] == winner["receipt"]
    assert newer.materializer.reader.verify(winner["receipt"])
    assert all(newer.worker._consumer_check("post", active(newer.storage)).values())


def test_restore_cas_loss_without_safe_resolution_is_durable_critical(
    tmp_path, monkeypatch, authority
):
    from ontology_discovery.publisher import PostCheckRollbackError
    from storage.onelake_documents import DocumentConflictError

    _env, real, candidate = _deterministic_predecessor(tmp_path, monkeypatch, authority)
    seen = {}
    _fail_real_post(real, candidate, seen)
    promote = real.storage.conditional_promote

    def lose_restore(**kwargs):
        if kwargs["generation_id"] == "deterministic-predecessor":
            raise DocumentConflictError("restore CAS unavailable")
        return promote(**kwargs)

    monkeypatch.setattr(real.storage, "conditional_promote", lose_restore)
    with pytest.raises(PostCheckRollbackError) as error:
        _publish_candidate(real, candidate)
    assert not error.value.rollback_succeeded
    assert real.materializer.has_open_critical()
    assert real.materializer.journal.read()["critical_reason"] == "rollback_pointer_or_consumer_uncertain"
    assert active(real.storage) == candidate.generation_id
    # The separately signed restore grant names only the predecessor. Once its
    # pointer CAS fails, reconciling the still-authoritative candidate would
    # require a different exact restore grant. Fail closed: retain the
    # authorized predecessor bytes, keep the candidate pointer, and quarantine
    # rather than silently writing outside the signed grant.
    assert _physical(real, candidate) != seen["new"]
    retained = real.materializer.receipts.latest("deterministic-predecessor")
    assert retained is not None
    assert retained["generation_id"] == "deterministic-predecessor"
    assert _physical(real, candidate, receipt=retained) == _physical(real, candidate)
    assert real.materializer.reader.verify(retained)
    from ontology_discovery.maintenance_materialization import MaterializationCritical

    # A physical-only reconciliation must not silently reopen promotion.
    with pytest.raises(MaterializationCritical, match="explicit_reconciliation"):
        _publish_b(real, _generation_b(real, "must-stay-closed"), fence=300)
    assert real.materializer.has_open_critical()
    assert _physical(real, candidate) != seen["new"]


@pytest.mark.parametrize("restore_allowed", [True, False])
def test_revoked_admission_requires_separately_signed_restore_authority(
    tmp_path, monkeypatch, authority, restore_allowed
):
    import copy

    from ontology_discovery.maintenance_admission import MaintenanceAuthorizer
    from ontology_discovery.maintenance_release import MaintenanceReleaseReader
    from ontology_discovery.publisher import PublicationSafetyError

    env, real, candidate = _deterministic_predecessor(tmp_path, monkeypatch, authority)
    old = _physical(real, candidate)
    old_receipt = real.materializer.reader.active()[1]
    # Separate signed restore-only envelope with independently read control.
    # No fixed True/False authorization callback; Ed25519, trust, corpus and
    # inherited evaluation floors all run through the real release reader.
    payload = authority.payload()
    payload["release"]["release_id"] = "separate-restore-release"
    payload["release"]["operations"] = ["restore"]
    retained = real.storage.read_generation("deterministic-predecessor")
    retained_receipt = real.materializer.receipts.latest("deterministic-predecessor")
    assert retained_receipt is not None
    payload["release"]["restore_target"] = {
        **real.materializer._expected_target,
        "generation_id": "deterministic-predecessor",
        "content_hash": retained["manifest"]["content_hash"],
        "authorization_digest": retained_receipt["authorization_digest"],
    }
    envelope = authority.sign(payload)
    restore_control = copy.deepcopy(authority.control)
    restore_control["kill"] = not restore_allowed
    restore_reader = MaintenanceReleaseReader(
        trust=authority.trust, envelope_source=lambda: copy.deepcopy(envelope),
        control_source=lambda: copy.deepcopy(restore_control), clock=lambda: NOW,
    )

    class SeparateRestoreAuthorizer(MaintenanceAuthorizer):
        def __init__(self):
            super().__init__(
                reader=authority.reader(),
                store=env.store,
                trusted_records=real.authorizer._trusted,
            )
            self._restore_reader_authorizer = MaintenanceAuthorizer(
                reader=restore_reader,
                store=env.store,
                trusted_records=real.authorizer._trusted,
            )

        def authorize_restore(self, *, expected_target=None):
            return self._restore_reader_authorizer.authorize_restore(
                expected_target=expected_target
            )

    authorizer = SeparateRestoreAuthorizer()
    authorizer._explicit_restore_authority = True
    real.authorizer = authorizer
    real.materializer._authorizer = authorizer
    seen = {}

    def revoke(point):
        if point == "after_materialized":
            _assert_model(real, candidate, True)
            seen["new"] = _physical(real, candidate)
            assert _physical(real, candidate, receipt=old_receipt) == old
            authority.control["kill"] = True

    real.materializer._fault = revoke
    with pytest.raises(PublicationSafetyError):
        _publish_candidate(real, candidate)
    assert seen["new"] != old
    assert active(real.storage) == "deterministic-predecessor"
    assert _physical(real, candidate, receipt=old_receipt) == old
    if restore_allowed:
        assert _physical(real, candidate) == old
        assert not real.materializer.has_open_critical()
        assert all(real.worker._consumer_check("post", active(real.storage)).values())
    else:
        assert real.materializer.has_open_critical()
        assert _physical(real, candidate) == seen["new"]  # denied restore made no writes
