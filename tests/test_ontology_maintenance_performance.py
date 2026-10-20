"""Bounded work with real current artifact/store bytes, never cached approval."""

# ruff: noqa: F811 (pytest fixture re-import)

from __future__ import annotations

import builtins
import copy
import os
from collections import Counter
from datetime import timedelta
from unittest.mock import Mock

import pytest

import ontology_discovery.maintenance_release as releases
from ontology_discovery.maintenance_admission import (
    _proposal_membership_key,
    _validated_receipt_body,
)
from ontology_discovery.maintenance_materialization import (
    CandidateGenerationMaterializer,
)
from tests.test_ontology_maintenance_admission import authority  # noqa: F401
from tests.test_ontology_maintenance_materialization import Real
from tests.test_ontology_maintenance_publication import active, dispatched
from tests.test_ontology_maintenance_recovery import (
    test_cas_not_reached_after_materialization_restores_predecessor as recovery_case,
)
from tests.test_ontology_maintenance_release_evidence import qualified_live_authority
from tests.test_ontology_maintenance_writer_evidence import (
    _mutate_results,
    _rehash,
    _setup,
)


def _change_same_metadata(path):
    stat = path.stat()
    data = path.read_bytes()
    assert b"done" in data
    path.write_bytes(data.replace(b"done", b"evil", 1))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    assert path.stat().st_mtime_ns == stat.st_mtime_ns


def test_corpus_reads_once_per_boundary_and_reuses_only_exact_bytes(monkeypatch, authority):
    reader = authority.reader()
    actual_open = builtins.open
    reads = Counter()

    def counted(path, *args, **kwargs):
        if str(path).startswith(str(authority.root)):
            reads[str(path)] += 1
        return actual_open(path, *args, **kwargs)

    signature = Mock(wraps=releases._verify_signature)
    status = Mock(wraps=releases._status)
    corpus = Mock(wraps=releases.verify_prerequisite_corpus)
    monkeypatch.setattr(builtins, "open", counted)
    monkeypatch.setattr(releases, "_verify_signature", signature)
    monkeypatch.setattr(releases, "_status", status)
    monkeypatch.setattr(releases, "verify_prerequisite_corpus", corpus)
    for _ in range(3):
        reader.read()
    assert corpus.call_count == 3
    assert signature.call_count == 12  # actual Ed25519 on every boundary
    assert set(reads.values()) == {3}  # Phase 13 and ordering not read twice
    assert status.call_count == len(reads)  # parse once per actual revision
    path = authority.root / "phases/07-inventory/07-01-SUMMARY.md"
    _change_same_metadata(path)
    with pytest.raises(releases.MaintenanceDenied, match="manifest_digest_mismatch"):
        reader.read()


@pytest.mark.parametrize("mutation", ["new-plan", "new-verification", "removed-summary"])
def test_current_directory_membership_is_not_cached(authority, mutation):
    reader = authority.reader()
    reader.read()
    root = authority.root / "phases"
    if mutation == "new-plan":
        (root / "03.8-native/03.8-03-PLAN.md").write_text("new")
    elif mutation == "new-verification":
        (root / "13-ontology/extra-VERIFICATION.md").write_text("---\nstatus: passed\n---")
    else:
        (root / "13-ontology/13-22-SUMMARY.md").unlink()
    with pytest.raises(releases.MaintenanceDenied):
        reader.read()


def test_one_store_read_and_one_receipt_parse_per_bytes_revision(
    tmp_path, monkeypatch, authority
):
    env, candidate, authorizer = _setup(tmp_path, monkeypatch, authority)
    _validated_receipt_body.cache_clear()
    batches = Mock(wraps=env.store.list_evidence_batches)
    monkeypatch.setattr(env.store, "list_evidence_batches", batches)
    for _ in range(3):
        assert authorizer.authorize(candidate)["model_rows"] == 1
    assert batches.call_count == 3
    info = _validated_receipt_body.cache_info()
    assert info.misses == 1
    assert info.hits == 2
    assert info.maxsize == 32

    def mutate(result):
        result["proposals"][0]["rationale"] = "actual changed proposal bytes"
        _rehash(result)

    _mutate_results(env, mutate)
    with pytest.raises(releases.MaintenanceDenied):
        authorizer.authorize(candidate)
    assert _validated_receipt_body.cache_info().misses == 2


def test_live_verification_deduplicates_corpus_not_signatures(tmp_path, monkeypatch):
    authority = qualified_live_authority(tmp_path)
    reader = authority.reader()
    signature = Mock(wraps=releases._verify_signature)
    corpus = Mock(wraps=releases.verify_prerequisite_corpus)
    monkeypatch.setattr(releases, "_verify_signature", signature)
    monkeypatch.setattr(releases, "verify_prerequisite_corpus", corpus)
    reader.read()
    reader.read()
    assert corpus.call_count == 2  # one, not two, per complete live verification
    assert signature.call_count == 2 * (4 + len(releases.LIVE_EVIDENCE_KINDS))
    reference = authority.envelope["payload"]["qualification"]["artifacts"][0]
    path = authority.root / reference["path"]
    stat = path.stat()
    data = path.read_bytes()
    changed = data.replace(b'"origin":"live"', b'"origin":"fake"')
    assert changed != data and len(changed) == len(data)
    path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(releases.MaintenanceDenied, match="live_evidence_digest_mismatch"):
        reader.read()


def test_receipt_index_preserves_valid_numeric_confidence_normalization(
    tmp_path, monkeypatch, authority
):
    env, _, _ = _setup(tmp_path, monkeypatch, authority)
    stored = next(b for b in env.store.list_evidence_batches() if b.get("result"))
    body = copy.deepcopy(stored["result"])
    body.pop("provider_receipt")
    body["proposals"][0]["confidence"] = 1
    members = _validated_receipt_body(
        releases.canonical_json(stored["batch"]), releases.canonical_json(body)
    )
    assert members is not None
    assert _proposal_membership_key(body["proposals"][0]) in members
    body["proposals"][0]["confidence"] = 1.0
    assert _proposal_membership_key(body["proposals"][0]) in members


def test_line_ending_mutation_cannot_reuse_signed_corpus_digest(authority):
    reader = authority.reader()
    reader.read()
    path = authority.root / "phases/07-inventory/07-01-SUMMARY.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(releases.MaintenanceDenied, match="manifest_digest_mismatch"):
        reader.read()


@pytest.mark.parametrize(
    "mutation",
    [
        "corpus", "revoke", "source", "support", "receipt", "proposal",
        "expiry", "evidence-expiry", "signature", "kill", "target",
    ],
)
def test_real_second_sink_write_denied_after_current_bytes_change(
    tmp_path, monkeypatch, authority, mutation
):
    env = dispatched(tmp_path, monkeypatch, authority)
    writes = []
    real = Real(tmp_path, env, authority)
    write = real.delta.write

    def counted(*args, **kwargs):
        result = write(*args, **kwargs)
        writes.append(result)
        return result

    monkeypatch.setattr(real.delta, "write", counted)

    def fault(point):
        if point != "before_table_write:2":
            return
        assert len(writes) == 1  # first real Delta commit, not a mock sink
        if mutation == "corpus":
            _change_same_metadata(authority.root / "phases/07-inventory/07-01-SUMMARY.md")
        elif mutation == "revoke":
            authority.control["revoked_attestations"] = [
                releases.digest(authority.envelope["payload"])
            ]
        elif mutation == "expiry":
            authority.clock[0] += timedelta(days=400)
        elif mutation == "evidence-expiry":
            authority.clock[0] += timedelta(days=2)
        elif mutation == "signature":
            authority.envelope["signature"] = "invalid"
        elif mutation == "kill":
            authority.control["kill"] = True
        elif mutation == "target":
            real.service.onelake.lakehouse_id = "unauthorized-item"
        elif mutation in {"source", "support"}:
            state = env.store._read_state()
            for batch in state["evidence_batches"]:
                for evidence in batch["batch"]["evidence_records"]:
                    if mutation == "support":
                        evidence["supports"] = False
                    else:
                        evidence["source"] = "unauthorized:source"
            env.store._persist_advanced(state, authority.clock[0])
        elif mutation == "receipt":
            _mutate_results(env, lambda r: r["provider_receipt"].update(model="wrong-model"))
        else:
            def mutate(result):
                result["proposals"] = []
                _rehash(result)
            _mutate_results(env, mutate)

    real.materializer._fault = fault
    # The real worker must return a denial/failure without a second sink call.
    result = real.worker.run_once(now=authority.clock[0], limit=1)
    assert result["succeeded"] == 0
    assert len(writes) == 1
    assert active(real.storage) is None


def test_full_manifest_recovery_has_linear_authorization_work(
    tmp_path, monkeypatch, authority
):
    """Run the original troublesome real test, including all 707 products.

    Counts, not CPU timing, enforce the bound. A parent runner supplies the
    separate wall-clock deadline, so a regression cannot hang the test suite.
    """
    verify = Mock(wraps=releases.verify_maintenance_attestation)
    monkeypatch.setattr(releases, "verify_maintenance_attestation", verify)
    guard = CandidateGenerationMaterializer._guard_write
    materialize = CandidateGenerationMaterializer._materialize
    per_sink = []
    completed = []

    def counted_guard(self):
        before = verify.call_count
        guard(self)
        checks = verify.call_count - before
        # Restore: one fresh verification. Admission: at most one runtime
        # guard verification plus one exact-target/model authorization.
        assert 1 <= checks <= 2
        per_sink.append(checks)

    def counted_materialize(self, *args, **kwargs):
        before = len(per_sink)
        receipt = materialize(self, *args, **kwargs)
        assert len(receipt["products"]) == 707  # no dropped empty typed tables
        assert len(per_sink) - before == 708  # tables AND catalog are guarded
        completed.append(receipt["kind"])
        return receipt

    monkeypatch.setattr(CandidateGenerationMaterializer, "_guard_write", counted_guard)
    monkeypatch.setattr(CandidateGenerationMaterializer, "_materialize", counted_materialize)
    recovery_case(tmp_path, monkeypatch, authority)
    assert completed == ["materialization", "materialization", "restoration"]
    assert len(per_sink) == 2124
    assert verify.call_count <= 2 * len(per_sink) + 100
    print(
        f"707 products x3; sink guards={len(per_sink)}; "
        f"fresh release verifications={verify.call_count}; "
        f"max verifications per sink={max(per_sink)}"
    )
