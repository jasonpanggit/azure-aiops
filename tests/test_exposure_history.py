from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_overview_history import AUTH, OTHER, _client

from api.errors import ApiError, ErrorCode
from api.scope import SCOPE_DIMENSIONS, Scope
from operations.exposure_history import ExposureHistoryStore
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

SCOPE = {"subscription": ["sub-a"]}
PATH = "/api/v1/vulnerabilities/exposure/history"


def source(scope=None):
    scope = SCOPE if scope is None else scope
    return {
        "scope": scope,
        "data": {
            "generation": "generation-one", "total_count": 10,
            "facets": {
                "severity": [{"value": "critical", "count": 2}, {"value": "high", "count": 8}],
                "sla_state": [{"value": "indeterminate", "count": 10}],
            },
            "completeness": {"state": "partial", "represented_connections": 1, "expected_connections": 2, "excluded": 3},
            "freshness": {"state": "reported", "as_of": "2026-10-15T00:00:00Z"},
            "contract": {
                "query": {"scope": scope, "generation": "generation-one"}, "counts": {"total": 13},
                "completeness": {"state": "partial", "represented_connections": 1, "expected_connections": 2, "excluded": 3, "total": 13},
                "freshness": {"state": "reported", "as_of": "2026-10-15T00:00:00Z"},
                "safe_error": None,
            },
            "items": [{"private": "never retain me"}],
        },
    }


def test_server_allowlist_survives_restart_and_exact_identity_boundaries(tmp_path):
    store = ExposureHistoryStore(OneLakeDocumentStore(tmp_path))
    result = store.append("reader", SCOPE, 0, source())
    row = result["observations"][0]
    assert row["source_observed_at"] == "2026-10-15T00:00:00Z"
    assert row["captured_at"] != row["source_observed_at"]
    assert row["total_count"] == 10
    assert row["coverage_total_count"] == 13  # Source extent can include excluded findings.
    assert "never retain me" not in json.dumps(result)
    assert ExposureHistoryStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE) == result
    assert store.read("other", SCOPE)["revision"] == 0
    for dimension in SCOPE_DIMENSIONS:
        scope = {**SCOPE, dimension: ["different"]}
        assert store.read("reader", scope)["revision"] == 0


def test_compare_and_swap_preserves_single_concurrent_append(tmp_path):
    store = ExposureHistoryStore(OneLakeDocumentStore(tmp_path))
    barrier = Barrier(2)

    def append():
        barrier.wait()
        try:
            return store.append("reader", SCOPE, 0, source())["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(lambda _: append(), range(2)))) == ["1", "conflict"]
    assert store.read("reader", SCOPE)["revision"] == 1


def test_limit_never_evicts_and_byte_boundary_is_inclusive(tmp_path, monkeypatch):
    from operations import exposure_history

    store = ExposureHistoryStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, 0, source())
    exact = len((json.dumps(first, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(exposure_history, "MAX_BYTES", exact)
    assert store.read("reader", SCOPE) == first
    with pytest.raises(ValueError, match="256 KiB"):
        store.append("reader", SCOPE, 1, source())
    assert store.read("reader", SCOPE) == first
    monkeypatch.setattr(exposure_history, "MAX_BYTES", 256 * 1024)
    for revision in range(1, 30):
        last = store.append("reader", SCOPE, revision, source())
    with pytest.raises(DocumentConflictError, match="no records were evicted"):
        store.append("reader", SCOPE, 30, source())
    assert store.read("reader", SCOPE) == last
    assert last["observations"][0] == first["observations"][0]


@pytest.mark.parametrize("damage", ["scope", "generation", "total", "duplicate", "negative", "overflow", "timestamp", "safe_error", "unavailable", "no_facets"])
def test_invalid_source_never_advances_history(tmp_path, damage):
    store = ExposureHistoryStore(OneLakeDocumentStore(tmp_path))
    payload = source()
    data = payload["data"]
    if damage == "scope":
        payload["scope"] = {}
    elif damage == "generation":
        data["generation"] = "wrong"
    elif damage == "total":
        data["total_count"] = 0
    elif damage == "duplicate":
        data["facets"]["severity"].append({"value": "CRITICAL", "count": 0})
    elif damage == "negative":
        data["facets"]["severity"][0]["count"] = -1
    elif damage == "overflow":
        data["facets"]["severity"] = [{"value": str(i), "count": 0} for i in range(41)]
    elif damage == "timestamp":
        data["contract"]["freshness"]["as_of"] = "2026-10-15"
    elif damage == "safe_error":
        data["contract"]["safe_error"] = {"message": "not usable"}
    elif damage == "unavailable":
        data["completeness"]["state"] = "unavailable"
    else:
        data["facets"] = {}
    with pytest.raises(ValueError):
        store.append("reader", SCOPE, 0, payload)
    assert store.read("reader", SCOPE)["revision"] == 0


@pytest.mark.parametrize("damage", ["empty", "identity", "revision", "duplicate"])
def test_corrupt_existing_document_is_not_empty_history(tmp_path, damage):
    documents = OneLakeDocumentStore(tmp_path)
    store = ExposureHistoryStore(documents)
    data = store.append("reader", SCOPE, 0, source())
    if damage == "empty":
        data = {}
    elif damage == "identity":
        data["actor"] = "other"
    elif damage == "revision":
        data["revision"] = 2
    else:
        data["observations"] *= 2
        data["revision"] = 2
    documents.put(store._name("reader", SCOPE), data)
    with pytest.raises(ValueError):
        store.read("reader", SCOPE)


def routes(tmp_path, monkeypatch):
    client, context, _ = _client(tmp_path, monkeypatch)
    context.exposure_history_store = ExposureHistoryStore(OneLakeDocumentStore(tmp_path / "exposure-history"))
    from api.routers import vulnerability
    calls = []

    def acquire(**kwargs):
        calls.append(kwargs)
        return source(kwargs["scope"].to_dict())

    monkeypatch.setattr(vulnerability, "exposure_facets", acquire)
    return client, context, calls


def test_http_captures_only_after_explicit_action_and_reauthorizes_recovery(tmp_path, monkeypatch):
    client, context, calls = routes(tmp_path, monkeypatch)
    assert client.get(PATH, headers=AUTH).json()["data"]["revision"] == 0
    assert not calls
    result = client.post(PATH, headers=AUTH, json={"expected_revision": 0, "generation": "generation-one"})
    assert result.status_code == 201, result.text
    assert calls[0]["scope"] == Scope.from_mapping(SCOPE)
    assert calls[0]["generation"] == "generation-one"
    assert all(value is None or not hasattr(value, "default") for key, value in calls[0].items() if key not in {"context", "scope", "principal", "facet", "generation"})
    calls.clear()
    assert client.get(PATH, headers=AUTH).json()["data"] == result.json()["data"]
    assert not calls
    assert client.get(PATH, headers={"Authorization": f"Bearer {OTHER}"}).json()["data"]["revision"] == 0
    assert client.get(PATH).status_code == 401
    assert client.get(f"{PATH}?subscription=outside", headers=AUTH).status_code == 403
    assert client.post(PATH, headers=AUTH, json={"expected_revision": 0}).status_code == 409
    assert not calls
    for extra in [{"counts": {}}, {"expected_revision": True}, {"generation": ""}, {"generation": "x/y"}]:
        assert client.post(PATH, headers=AUTH, json={"expected_revision": 1, **extra}).status_code == 400
    context.exposure_history_store = None
    assert client.get(PATH, headers=AUTH).status_code == 503


def test_source_failure_or_generation_mismatch_never_persists(tmp_path, monkeypatch):
    client, context, _ = routes(tmp_path, monkeypatch)
    from api.routers import vulnerability
    assert client.post(PATH, headers=AUTH, json={"expected_revision": 0, "generation": "different"}).status_code == 503

    def unavailable(**kwargs):
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "source unavailable")

    monkeypatch.setattr(vulnerability, "exposure_facets", unavailable)
    assert client.post(PATH, headers=AUTH, json={"expected_revision": 0}).status_code == 503
    assert context.exposure_history_store.read("reader", SCOPE)["revision"] == 0


def test_storage_failure_does_not_publish_capture_success(tmp_path, monkeypatch):
    client, context, _ = routes(tmp_path, monkeypatch)

    def fail(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(context.exposure_history_store.documents, "create_only", fail)
    result = client.post(PATH, headers=AUTH, json={"expected_revision": 0})
    assert result.status_code == 503
    assert context.exposure_history_store.read("reader", SCOPE)["revision"] == 0


def test_capture_accepts_real_contract_projection_with_distinct_coverage_extent(tmp_path, monkeypatch):
    from api.exposure_query import ExposureQueryPage
    from api.routers import vulnerability
    from intelligence.vulnerability.exposure_contracts import ExposureApiPage

    client, _, _ = routes(tmp_path, monkeypatch)
    raw = source()["data"]
    page = ExposureQueryPage(
        items=(), total_count=10, facets=raw["facets"], generation="generation-one",
        applied_scope=SCOPE, applied_filters=(),
        applied_sort={"field": "priority_score", "direction": "desc"}, next_position=None,
        completeness={"state": "partial", "represented_count": 10, "total_count": 13, "excluded_count": 3},
        freshness=raw["freshness"],
    )
    projection = ExposureApiPage(
        total_count=page.total_count, items=page.items, next_cursor=None,
        generation=page.generation, applied_scope=page.applied_scope,
        applied_filters=page.applied_filters, applied_sort=page.applied_sort,
        facets=page.facets, completeness=page.completeness, freshness=page.freshness,
    )
    monkeypatch.setattr(vulnerability, "exposure_facets", lambda **kwargs: vulnerability._exposure_response(page, scope=kwargs["scope"], data=projection.facet_data()))
    result = client.post(PATH, headers=AUTH, json={"expected_revision": 0})
    assert result.status_code == 201, result.text
    row = result.json()["data"]["observations"][0]
    assert row["total_count"] == 10
    assert row["coverage_total_count"] == 13
    assert row["excluded_count"] == 3
