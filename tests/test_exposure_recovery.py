from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_exposure_history import AUTH, OTHER, SCOPE, routes, source
from test_exposure_history import PATH as HISTORY

from api.scope import SCOPE_DIMENSIONS
from operations.exposure_history import ExposureHistoryStore
from operations.exposure_recovery import ExposureRecoveryStore, RecoveryReview
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

PATH = "/api/v1/vulnerabilities/exposure/recovery"


def seed(tmp_path):
    history = ExposureHistoryStore(OneLakeDocumentStore(tmp_path))
    receipt = history.append("reader", SCOPE, 0, source())["observations"][0]
    store = ExposureRecoveryStore(history)
    payload = {"expected_revision": 0, "observation_id": receipt["observation_id"], "reason": "source_evidence", "disposition": "queued", "owner": "Operations", "target_date": "2026-11-01", "note": "Verify excluded evidence"}
    return store, payload


def test_retained_candidates_explicit_review_restart_and_nine_scope_identity_boundaries(tmp_path):
    store, payload = seed(tmp_path)
    initial = store.read("reader", SCOPE)
    assert initial["revision"] == 0
    assert {row["reason"] for row in initial["candidates"]} == {"source_evidence", "connection_coverage", "classification", "sla_unknown"}
    assert all(row["review"] is None for row in initial["candidates"])
    first = store.review("reader", SCOPE, RecoveryReview(**payload))
    assert first["revision"] == 1
    assert first["events"][0]["actor"] == "reader"
    assert "never retain me" not in json.dumps(first)
    restarted = ExposureRecoveryStore(ExposureHistoryStore(OneLakeDocumentStore(tmp_path)))
    assert restarted.read("reader", SCOPE) == first
    for dimension in SCOPE_DIMENSIONS:
        scope = {**SCOPE, dimension: ["different"]}
        assert store.read("reader", scope)["revision"] == 0
        assert store.read("reader", scope)["candidates"] == []
    assert store.read("other", SCOPE)["candidates"] == []
    with pytest.raises(DocumentConflictError):
        store.review("reader", SCOPE, RecoveryReview(**payload))
    closed = store.review("reader", SCOPE, RecoveryReview(**{**payload, "expected_revision": 1, "disposition": "review_closed", "note": "Review complete, source not repaired"}))
    assert closed["events"][0] == first["events"][0]
    assert len(closed["candidates"]) == len(initial["candidates"])
    assert store.history.read("reader", SCOPE)["revision"] == 1


def test_concurrent_event_revision_cannot_lose_a_review(tmp_path):
    store, payload = seed(tmp_path)
    barrier = Barrier(2)

    def append():
        barrier.wait()
        try:
            return store.review("reader", SCOPE, RecoveryReview(**payload))["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(lambda _: append(), range(2)))) == ["1", "conflict"]
    assert store.read("reader", SCOPE)["revision"] == 1


def test_unknown_candidate_and_unqueued_closure_are_rejected(tmp_path):
    store, payload = seed(tmp_path)
    with pytest.raises(LookupError):
        store.review("reader", SCOPE, RecoveryReview(**{**payload, "reason": "freshness"}))
    with pytest.raises(DocumentConflictError, match="first"):
        store.review("reader", SCOPE, RecoveryReview(**{**payload, "disposition": "review_closed"}))
    assert store.read("reader", SCOPE)["revision"] == 0


@pytest.mark.parametrize("damage", ["empty", "actor", "revision", "reference", "timestamp", "transition"])
def test_corrupt_existing_state_never_becomes_empty_queue(tmp_path, damage):
    store, payload = seed(tmp_path)
    data = store.review("reader", SCOPE, RecoveryReview(**payload))
    data.pop("candidates")
    if damage == "empty":
        data = {}
    elif damage == "actor":
        data["actor"] = "other"
    elif damage == "revision":
        data["revision"] = 2
    elif damage == "reference":
        data["events"][0]["observation_id"] = "exo-" + "0" * 32
    elif damage == "timestamp":
        data["events"][0]["recorded_at"] = "2026-10-01"
    else:
        data["events"][0]["disposition"] = "review_closed"
    store.documents.put(store._name("reader", SCOPE), data)
    with pytest.raises(ValueError):
        store.read("reader", SCOPE)


def test_inclusive_byte_and_event_caps_never_evict(tmp_path, monkeypatch):
    from operations import exposure_recovery

    store, payload = seed(tmp_path)
    first = store.review("reader", SCOPE, RecoveryReview(**payload))
    stored = {key: value for key, value in first.items() if key != "candidates"}
    exact = len((json.dumps(stored, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(exposure_recovery, "MAX_BYTES", exact)
    assert store.read("reader", SCOPE) == first
    with pytest.raises(ValueError, match="256 KiB"):
        store.review("reader", SCOPE, RecoveryReview(**{**payload, "expected_revision": 1}))
    assert store.read("reader", SCOPE) == first
    monkeypatch.setattr(exposure_recovery, "MAX_BYTES", 256 * 1024)
    for revision in range(1, 100):
        last = store.review("reader", SCOPE, RecoveryReview(**{**payload, "expected_revision": revision}))
    with pytest.raises(DocumentConflictError, match="no events were evicted"):
        store.review("reader", SCOPE, RecoveryReview(**{**payload, "expected_revision": 100}))
    assert last["events"][0] == first["events"][0]
    assert store.read("reader", SCOPE) == last


def test_http_private_reviews_recovery_validation_and_provider_independence(tmp_path, monkeypatch):
    client, context, calls = routes(tmp_path, monkeypatch)
    assert client.get(PATH, headers=AUTH).json()["data"]["candidates"] == []
    captured = client.post(HISTORY, headers=AUTH, json={"expected_revision": 0}).json()["data"]["observations"][0]
    calls.clear()
    payload = {"expected_revision": 0, "observation_id": captured["observation_id"], "reason": "connection_coverage", "disposition": "queued", "owner": "Operator", "target_date": "", "note": "Review connection gaps"}
    queued = client.post(PATH, headers=AUTH, json=payload)
    assert queued.status_code == 201, queued.text
    assert client.get(PATH, headers=AUTH).json()["data"] == queued.json()["data"]
    assert client.get(PATH, headers={"Authorization": f"Bearer {OTHER}"}).json()["data"]["revision"] == 0
    assert client.get(PATH).status_code == 401
    assert client.get(PATH + "?subscription=outside", headers=AUTH).status_code == 403
    assert client.post(PATH, headers=AUTH, json=payload).status_code == 409
    for extra in [{"note": " "}, {"target_date": "2026-02-30"}, {"actor": "other"}, {"counts": {}}, {"expected_revision": True}, {"disposition": "repaired"}, {"reason": "execute"}]:
        assert client.post(PATH, headers=AUTH, json={**payload, "expected_revision": 1, **extra}).status_code == 400
    assert not calls
    context.exposure_history_store = None
    assert client.get(PATH, headers=AUTH).status_code == 503


def test_failed_persistence_never_returns_review_success(tmp_path, monkeypatch):
    client, context, _ = routes(tmp_path, monkeypatch)
    captured = client.post(HISTORY, headers=AUTH, json={"expected_revision": 0}).json()["data"]["observations"][0]

    def fail(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(context.exposure_history_store.documents, "create_only", fail)
    result = client.post(PATH, headers=AUTH, json={"expected_revision": 0, "observation_id": captured["observation_id"], "reason": "source_evidence", "disposition": "queued", "owner": "", "target_date": "", "note": "Review"})
    assert result.status_code == 503
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 0
