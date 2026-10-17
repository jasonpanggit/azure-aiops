from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError
from test_exposure_history import AUTH, SCOPE, routes

from api.scope import SCOPE_DIMENSIONS
from operations.kb_review import KbReviewRequest, KbReviewStore
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

PATH = "/api/v1/kbs/KB6000001/reviews"


def request(**overrides):
    return KbReviewRequest(**{
        "expected_revision": 0, "generation": "silver-patch:one", "owner": "Operations",
        "window_start": "2026-10-20T01:00:00+00:00", "window_end": "2026-10-20T02:00:00+00:00",
        "dependency_kbs": ["KB6000000"], "disposition": "needs_review", "note": "Confirm prerequisite with owner",
        **overrides,
    })


def source():
    return {"scope": SCOPE, "data": {
        "kb_id": "KB6000001", "generation": "silver-patch:one",
        "snapshot": {"as_of": "2026-10-17T00:00:00Z", "completeness": "partial", "freshness": "stale"},
        "affected_servers": ["must-not-store"], "execution_payload": "must-not-store",
    }}


def test_private_restart_revision_capacity_and_source_allowlist(tmp_path):
    store = KbReviewStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, "KB6000001", request(), source())
    assert "must-not-store" not in json.dumps(first)
    row = first["reviews"][0]
    assert row["source_freshness"] == "stale"
    assert row["recorded_at"] != row["source_observed_at"]
    assert KbReviewStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE, "KB6000001") == first
    assert store.read("other", SCOPE, "KB6000001")["revision"] == 0
    assert store.read("reader", SCOPE, "KB6000002")["revision"] == 0
    for dimension in SCOPE_DIMENSIONS:
        assert store.read("reader", {**SCOPE, dimension: ["other"]}, "KB6000001")["revision"] == 0
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, "KB6000001", request(), source())
    for revision in range(1, 20):
        last = store.append("reader", SCOPE, "KB6000001", request(expected_revision=revision), source())
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, "KB6000001", request(expected_revision=20), source())
    assert last["reviews"][0] == first["reviews"][0]
    assert store.read("reader", SCOPE, "KB6000001") == last


@pytest.mark.parametrize("damage", ["scope", "kb", "generation", "snapshot", "self"])
def test_bad_source_binding_never_writes(tmp_path, damage):
    store, data, payload = KbReviewStore(OneLakeDocumentStore(tmp_path)), source(), request()
    if damage == "scope":
        data["scope"] = {}
    elif damage == "kb":
        data["data"]["kb_id"] = "KB6000002"
    elif damage == "generation":
        data["data"]["generation"] = "other"
    elif damage == "snapshot":
        data["data"]["snapshot"]["freshness"] = False
    else:
        payload = request(dependency_kbs=["KB6000001"])
    with pytest.raises((ValueError, DocumentConflictError)):
        store.append("reader", SCOPE, "KB6000001", payload, data)
    assert store.read("reader", SCOPE, "KB6000001")["revision"] == 0


@pytest.mark.parametrize("extra", [
    {"actor": "other"}, {"source_freshness": "fresh"}, {"owner": " "}, {"note": " "},
    {"expected_revision": True}, {"disposition": "approved"}, {"generation": ""},
    {"window_start": "2026-10-20T01:00:00"}, {"window_end": "2026-10-19T02:00:00Z"},
    {"window_end": "not-a-time"}, {"dependency_kbs": ["KB6000000", "KB6000000"]},
    {"dependency_kbs": ["CVE-2026-2001"]}, {"dependency_kbs": ["https://example.test"]},
])
def test_strict_declarations_do_not_accept_evidence_or_execution(extra):
    with pytest.raises(ValidationError):
        request(**extra)


def test_corruption_and_byte_limit_never_reset_history(tmp_path, monkeypatch):
    from operations import kb_review
    store = KbReviewStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, "KB6000001", request(), source())
    exact = len((json.dumps(first, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(kb_review, "MAX_BYTES", exact)
    assert store.read("reader", SCOPE, "KB6000001") == first
    with pytest.raises(ValueError, match="256 KiB"):
        store.append("reader", SCOPE, "KB6000001", request(expected_revision=1), source())
    assert store.read("reader", SCOPE, "KB6000001") == first
    store.documents.put(store._name("reader", SCOPE, "KB6000001"), {})
    with pytest.raises(ValueError):
        store.read("reader", SCOPE, "KB6000001")


def test_concurrent_cas_preserves_one_record(tmp_path):
    store, barrier = KbReviewStore(OneLakeDocumentStore(tmp_path)), Barrier(2)

    def append():
        barrier.wait()
        try:
            return store.append("reader", SCOPE, "KB6000001", request(), source())["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(lambda _: append(), range(2)))) == ["1", "conflict"]
    assert store.read("reader", SCOPE, "KB6000001")["revision"] == 1


def test_routes_only_acquire_on_explicit_write_and_recover_retained_record(tmp_path, monkeypatch):
    from api.routers import vulnerability
    client, _, _ = routes(tmp_path, monkeypatch)
    calls = []

    def acquire(*args):
        calls.append(args)
        return source()

    monkeypatch.setattr(vulnerability, "kb_detail", acquire)
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 0
    assert not calls
    saved = client.post(PATH, headers=AUTH, json=request().model_dump())
    assert saved.status_code == 201, saved.text
    assert len(calls) == 1
    assert calls[0][2].to_dict() == SCOPE
    assert client.get(PATH, headers=AUTH).json()["data"] == saved.json()["data"]
    assert client.post(PATH, headers=AUTH, json=request().model_dump()).status_code == 409
    assert len(calls) == 1
    assert client.get(PATH).status_code == 401
    assert client.get(PATH + "?subscription=outside", headers=AUTH).status_code == 403
    assert client.post(PATH, headers=AUTH, json=request(expected_revision=1, generation="old").model_dump()).status_code == 409
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 1
    assert client.post(PATH, headers=AUTH, json=request(expected_revision=1, dependency_kbs=["KB6000001"]).model_dump()).status_code == 400
    assert client.get(PATH.replace("KB6000001", "bad"), headers=AUTH).status_code == 400


def test_unavailable_storage_and_corrupt_history_surface_explicit_error(tmp_path, monkeypatch):
    client, context, _ = routes(tmp_path, monkeypatch)
    store = KbReviewStore(context.exposure_history_store.documents)
    store.documents.put(store._name("reader", SCOPE, "KB6000001"), {})
    assert client.get(PATH, headers=AUTH).status_code == 503
    monkeypatch.setattr(context, "exposure_history_store", None)
    assert client.get(PATH, headers=AUTH).status_code == 503
