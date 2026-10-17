from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from test_exposure_history import AUTH, SCOPE, routes

from api.exposure_query import ExposureQueryPage
from api.scope import SCOPE_DIMENSIONS
from operations.patch_review import CreatePatchReview, PatchReviewStore
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

PATH = "/api/v1/vulnerabilities/exposure/patch-reviews"


def request(**overrides):
    return CreatePatchReview(**{
        "expected_revision": 0, "generation": "gen-one", "page_size": 25, "filters": {"active": True},
        "exposure_ids": ["finding-one"], "owner": "Operations", "note": "Review before planning", **overrides,
    })


def source():
    return {
        "scope": SCOPE, "generation": "gen-one",
        "items": [{"exposure_id": "finding-one", "read_model_generation_id": "gen-one", "target_id": "vm-one",
                   "target_kind": "server", "weakness_id": "KB600001", "severity": "critical", "sla_state": "unknown",
                   "completeness": "partial", "execution_payload": "must-not-store"}],
        "freshness": {"state": "reported", "as_of": "2026-10-17T00:00:00Z"}, "completeness": {"state": "partial"},
    }


def test_private_restart_allowlist_and_revision_capacity(tmp_path):
    store = PatchReviewStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, request(), source())
    assert "execution_payload" not in first["batches"][0]["findings"][0]
    assert PatchReviewStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE) == first
    assert store.read("other", SCOPE)["revision"] == 0
    assert store.read("reader", {"subscription": ["other"]})["revision"] == 0
    for dimension in SCOPE_DIMENSIONS:
        assert store.read("reader", {**SCOPE, dimension: ["different"]})["revision"] == 0
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, request(), source())
    for revision in range(1, 20):
        last = store.append("reader", SCOPE, request(expected_revision=revision), source())
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, request(expected_revision=20), source())
    assert store.read("reader", SCOPE) == last
    assert last["batches"][0] == first["batches"][0]


@pytest.mark.parametrize("damage", ["scope", "generation", "row_generation", "missing_selection", "duplicate_source"])
def test_wrong_source_cannot_create_batch(tmp_path, damage):
    store = PatchReviewStore(OneLakeDocumentStore(tmp_path))
    data = source()
    if damage == "scope":
        data["scope"] = {}
    elif damage == "generation":
        data["generation"] = "other"
    elif damage == "row_generation":
        data["items"][0]["read_model_generation_id"] = "other"
    elif damage == "missing_selection":
        data["items"] = []
    else:
        data["items"] *= 2
    with pytest.raises((ValueError, DocumentConflictError)):
        store.append("reader", SCOPE, request(), data)
    assert store.read("reader", SCOPE)["revision"] == 0


def test_existing_corruption_never_becomes_empty_history(tmp_path):
    store = PatchReviewStore(OneLakeDocumentStore(tmp_path))
    store.documents.put(store._name("reader", SCOPE), {})
    with pytest.raises(ValueError):
        store.read("reader", SCOPE)


def test_sql_public_projection_uses_authorized_page_generation(tmp_path):
    from api.exposure_query import _PAGE_COLUMNS, _public_row
    data = source()
    data["items"] = [_public_row({key: value for key, value in data["items"][0].items() if key in _PAGE_COLUMNS})]
    assert "read_model_generation_id" not in data["items"][0]
    saved = PatchReviewStore(OneLakeDocumentStore(tmp_path)).append("reader", SCOPE, request(), data)
    assert saved["batches"][0]["generation"] == "gen-one"


def test_routes_reacquire_page_only_on_explicit_post_and_recover_without_replay(tmp_path, monkeypatch):
    from api.routers import vulnerability
    client, _, _ = routes(tmp_path, monkeypatch)
    calls = []
    raw = source()
    page = ExposureQueryPage(
        items=tuple(raw["items"]), total_count=100, facets={}, generation="gen-one", applied_scope=SCOPE,
        applied_filters=(), applied_sort={"field": "priority_score", "direction": "desc"}, next_position=None,
        completeness=raw["completeness"], freshness=raw["freshness"],
    )

    def acquire(**kwargs):
        calls.append(kwargs)
        return page

    monkeypatch.setattr(vulnerability, "_query_exposure_page", acquire)
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 0
    assert not calls
    result = client.post(PATH, headers=AUTH, json=request().model_dump())
    assert result.status_code == 201, result.text
    assert len(calls) == 1
    assert calls[0]["active"] is True
    assert calls[0]["generation_id"] == "gen-one"
    assert calls[0]["scope"].to_dict() == SCOPE
    assert client.get(PATH, headers=AUTH).json()["data"] == result.json()["data"]
    assert client.post(PATH, headers=AUTH, json=request().model_dump()).status_code == 409
    assert len(calls) == 1
    assert client.get(PATH).status_code == 401
    assert client.get(PATH + "?subscription=outside", headers=AUTH).status_code == 403
    monkeypatch.setattr(vulnerability, "_query_exposure_page", lambda **kwargs: replace(page, generation="other"))
    assert client.post(PATH, headers=AUTH, json=request(expected_revision=1).model_dump()).status_code == 503
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 1


@pytest.mark.parametrize("extra", [{"actor": "other"}, {"findings": []}, {"expected_revision": True}, {"exposure_ids": ["a", "a"]}, {"note": " "}, {"filters": {"execute": True}}])
def test_invalid_requests_cannot_supply_source_or_execution_fields(tmp_path, monkeypatch, extra):
    client, _, _ = routes(tmp_path, monkeypatch)
    assert client.post(PATH, headers=AUTH, json={**request().model_dump(), **extra}).status_code == 400


def test_image_owner_review_reauthorizes_image_selectors_and_retains_target_kind(tmp_path, monkeypatch):
    from api.routers import vulnerability
    client, _, _ = routes(tmp_path, monkeypatch)
    raw = source()
    raw["items"][0].update(target_kind="container_image", target_id="sha256:" + "a" * 64, weakness_id="CVE-2026-2001")
    calls = []

    def acquire(**kwargs):
        calls.append(kwargs)
        return ExposureQueryPage(
            items=tuple(raw["items"]), total_count=100, facets={}, generation="gen-one", applied_scope=SCOPE,
            applied_filters=(), applied_sort={"field": "priority_score", "direction": "desc"}, next_position=None,
            completeness=raw["completeness"], freshness=raw["freshness"],
        )

    monkeypatch.setattr(vulnerability, "_query_exposure_page", acquire)
    response = client.post(PATH, headers=AUTH, json=request(filters={"target_kind": "container_image", "source_family": "defender_image"}).model_dump())
    assert response.status_code == 201, response.text
    assert calls[0]["target_kind"] == "container_image"
    assert calls[0]["source_family"] == "defender_image"
    assert calls[0]["generation_id"] == "gen-one"
    finding = response.json()["data"]["batches"][0]["findings"][0]
    assert finding["target_kind"] == "container_image"
    assert finding["target_id"] == "sha256:" + "a" * 64
    assert finding["weakness_id"] == "CVE-2026-2001"


def test_failed_persistence_never_reports_success(tmp_path, monkeypatch):
    store = PatchReviewStore(OneLakeDocumentStore(tmp_path))

    def fail(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(store.documents, "create_only", fail)
    with pytest.raises(OSError):
        store.append("reader", SCOPE, request(), source())
    assert store.read("reader", SCOPE)["revision"] == 0


def test_concurrent_captures_preserve_one_revision(tmp_path):
    store = PatchReviewStore(OneLakeDocumentStore(tmp_path))
    barrier = Barrier(2)

    def append():
        barrier.wait()
        try:
            return store.append("reader", SCOPE, request(), source())["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(lambda _: append(), range(2)))) == ["1", "conflict"]
    assert store.read("reader", SCOPE)["revision"] == 1


def test_inclusive_serialized_byte_limit_never_rewrites_old_batches(tmp_path, monkeypatch):
    from operations import patch_review
    store = PatchReviewStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, request(), source())
    exact = len((json.dumps(first, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(patch_review, "MAX_BYTES", exact)
    assert store.read("reader", SCOPE) == first
    with pytest.raises(ValueError, match="256 KiB"):
        store.append("reader", SCOPE, request(expected_revision=1), source())
    assert store.read("reader", SCOPE) == first
