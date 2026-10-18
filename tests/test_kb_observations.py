from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_exposure_history import AUTH, SCOPE, routes

from api.scope import SCOPE_DIMENSIONS
from operations.kb_observations import CaptureKbObservation, KbObservationStore
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

PATH = "/api/v1/kbs/KB6000001/observations"


def request(**overrides):
    return CaptureKbObservation(**{"expected_revision": 0, "generation": "silver-patch:one", **overrides})


def source():
    return {"scope": SCOPE, "data": {
        "kb_id": "KB6000001", "generation": "silver-patch:one",
        "snapshot": {"as_of": "2026-10-16T00:00:00Z", "completeness": "partial", "freshness": "stale"},
        "installation_status_counts": {"observed_targets": 1000, "missing": 100, "installation_failed": 3, "installed": 800, "other": 97},
        "target_status_observations": [{"target_id": "vm-one", "status": "missing", "observed_at": "2026-10-16T00:00:00Z"}],
        "target_status_observations_truncated": True,
        "enrichment": {"sources": {"msrc:KB6000001": {
            "source": "msrc", "identifier": "KB6000001", "status": "failed", "stale": True,
            "has_last_known_good": True, "source_at": "2026-10-15T00:00:00Z", "payload": {"secret": "never-retain"},
        }}}, "execution": "never-retain",
    }}


def test_private_restart_allowlist_independent_clocks_and_capacity(tmp_path):
    store = KbObservationStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, "KB6000001", request(), source())
    row = first["observations"][0]
    assert "never-retain" not in json.dumps(first)
    assert row["counts"]["observed_targets"] == 1000
    assert len(row["targets"]) == 1 and row["targets_truncated"] is True
    assert row["captured_at"] != row["source_observed_at"] != row["msrc"]["source_at"]
    assert row["msrc"]["status"] == "failed" and row["msrc"]["stale"] is True
    assert KbObservationStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE, "KB6000001") == first
    assert store.read("other", SCOPE, "KB6000001")["revision"] == 0
    assert store.read("reader", SCOPE, "KB6000002")["revision"] == 0
    for dimension in SCOPE_DIMENSIONS:
        assert store.read("reader", {**SCOPE, dimension: ["other"]}, "KB6000001")["revision"] == 0
    for revision in range(1, 20):
        last = store.append("reader", SCOPE, "KB6000001", request(expected_revision=revision), source())
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, "KB6000001", request(expected_revision=20), source())
    assert last["observations"][0] == row
    assert store.read("reader", SCOPE, "KB6000001") == last


@pytest.mark.parametrize("damage", [
    "scope", "kb", "generation", "total", "bool", "negative", "float", "unsafe", "extent", "sample",
    "duplicate", "blank", "too_many", "unavailable", "msrc_identity", "msrc_duplicate",
])
def test_bad_acquisition_never_advances_history(tmp_path, damage):
    store, payload = KbObservationStore(OneLakeDocumentStore(tmp_path)), source()
    data = payload["data"]
    if damage == "scope":
        payload["scope"] = {}
    elif damage == "kb":
        data["kb_id"] = "KB6000002"
    elif damage == "generation":
        data["generation"] = "other"
    elif damage in {"total", "bool", "negative", "float", "unsafe"}:
        data["installation_status_counts"]["missing"] = {"total": 101, "bool": True, "negative": -1, "float": 100.0, "unsafe": 9_007_199_254_740_992}[damage]
    elif damage == "extent":
        data["target_status_observations_truncated"] = False
    elif damage == "sample":
        data["installation_status_counts"].update(missing=0, other=197)
    elif damage == "duplicate":
        data["target_status_observations"] *= 2
    elif damage == "blank":
        data["target_status_observations"][0]["target_id"] = " "
    elif damage == "too_many":
        data["target_status_observations"] = [{"target_id": str(index), "status": "installed", "observed_at": ""} for index in range(101)]
    elif damage == "unavailable":
        data["snapshot"]["completeness"] = "unavailable"
    elif damage == "msrc_identity":
        data["enrichment"]["sources"]["msrc:KB6000001"]["identifier"] = "KB6000002"
    else:
        data["enrichment"]["sources"]["duplicate"] = dict(data["enrichment"]["sources"]["msrc:KB6000001"])
    with pytest.raises((ValueError, DocumentConflictError)):
        store.append("reader", SCOPE, "KB6000001", request(), payload)
    assert store.read("reader", SCOPE, "KB6000001")["revision"] == 0


def test_legacy_unknown_counts_and_unreported_catalog_remain_unknown(tmp_path):
    payload = source()
    for key in ("installation_status_counts", "target_status_observations_truncated", "enrichment"):
        del payload["data"][key]
    store = KbObservationStore(OneLakeDocumentStore(tmp_path))
    row = store.append("reader", SCOPE, "KB6000001", request(), payload)["observations"][0]
    assert row["counts"] is None and row["targets_truncated"] is None and row["msrc"] is None
    assert row["targets"][0]["status"] == "missing"


def test_corrupt_documents_and_byte_limit_fail_instead_of_reset(tmp_path, monkeypatch):
    from operations import kb_observations
    store = KbObservationStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, "KB6000001", request(), source())
    exact = len((json.dumps(first, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(kb_observations, "MAX_BYTES", exact)
    assert store.read("reader", SCOPE, "KB6000001") == first
    with pytest.raises(ValueError, match="512 KiB"):
        store.append("reader", SCOPE, "KB6000001", request(expected_revision=1), source())
    assert store.read("reader", SCOPE, "KB6000001") == first
    store.documents.put(store._name("reader", SCOPE, "KB6000001"), {})
    with pytest.raises(ValueError):
        store.read("reader", SCOPE, "KB6000001")


def test_concurrent_cas_retains_exactly_one_capture(tmp_path):
    store, barrier = KbObservationStore(OneLakeDocumentStore(tmp_path)), Barrier(2)

    def append():
        barrier.wait()
        try:
            return store.append("reader", SCOPE, "KB6000001", request(), source())["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(lambda _: append(), range(2)))) == ["1", "conflict"]


def test_routes_explicit_capture_and_retained_recovery_do_not_refresh_on_get(tmp_path, monkeypatch):
    from api.routers import vulnerability
    client, _, _ = routes(tmp_path, monkeypatch)
    calls = []

    def acquire(*args):
        calls.append(args)
        return source()

    monkeypatch.setattr(vulnerability, "kb_detail", acquire)
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 0
    assert not calls
    first = client.post(PATH, headers=AUTH, json=request().model_dump())
    assert first.status_code == 201, first.text
    assert calls[0][2].to_dict() == SCOPE
    assert client.get(PATH, headers=AUTH).json()["data"] == first.json()["data"]
    assert len(calls) == 1
    assert client.post(PATH, headers=AUTH, json=request().model_dump()).status_code == 409
    assert len(calls) == 1
    assert client.post(PATH, headers=AUTH, json=request(expected_revision=1, generation="old").model_dump()).status_code == 409
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 1
    assert client.get(PATH).status_code == 401
    assert client.get(PATH + "?subscription=outside", headers=AUTH).status_code == 403
    for extra in ({"counts": {}}, {"actor": "other"}, {"captured_at": "now"}, {"expected_revision": True}):
        assert client.post(PATH, headers=AUTH, json={**request().model_dump(), **extra}).status_code == 400
    assert client.get(PATH.replace("KB6000001", "bad"), headers=AUTH).status_code == 400


def test_unavailable_storage_or_corrupt_history_is_explicit(tmp_path, monkeypatch):
    client, context, _ = routes(tmp_path, monkeypatch)
    store = KbObservationStore(context.exposure_history_store.documents)
    store.documents.put(store._name("reader", SCOPE, "KB6000001"), {})
    assert client.get(PATH, headers=AUTH).status_code == 503
    monkeypatch.setattr(context, "exposure_history_store", None)
    assert client.get(PATH, headers=AUTH).status_code == 503
