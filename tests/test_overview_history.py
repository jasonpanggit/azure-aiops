from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.errors import ApiError, ErrorCode
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.overview_history import OverviewHistoryStore, OverviewSource
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

SCOPE = {"subscription": ["sub-a"]}
TOKEN = "overview-reader-test-token"
OTHER = "overview-other-reader-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _sources():
    return [
        OverviewSource(
            id=source_id,
            started_at="2026-10-16T06:00:00+00:00",
            finished_at="2026-10-16T06:00:01+00:00",
            observed_at=["2026-10-15T00:00:00Z"],
            source_tables=[f"test-{source_id}"],
            knowledge_version="v1",
            loaded=100 if source_id == "situations" else None,
            total=350 if source_id == "situations" else None,
            partial=source_id == "situations",
            warning_count=1,
        )
        for source_id in ("situations", "network", "exposure")
    ]


def _append(store, revision=0, actor="reader", scope=None):
    return store.append(
        actor,
        SCOPE if scope is None else scope,
        revision,
        critical_situations=2,
        exposed_findings=3,
        network_gaps=4,
        sources=_sources(),
    )


def test_explicit_captures_survive_reload_and_are_exact_owner_scope(tmp_path):
    store = OverviewHistoryStore(OneLakeDocumentStore(tmp_path))
    assert store.read("reader", SCOPE)["revision"] == 0
    first = _append(store)
    assert first["revision"] == 1
    assert len(first["observations"]) == 1
    assert first["observations"][0]["sources"][0]["partial"] is True
    assert (
        OverviewHistoryStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE)
        == first
    )
    assert store.read("other", SCOPE)["observations"] == []
    assert store.read("reader", {})["observations"] == []
    assert store.read("reader", {"subscription": ["sub-b"]})["observations"] == []


def test_retains_only_latest_30_explicit_receipts_and_conflicts_do_not_mutate(tmp_path):
    store = OverviewHistoryStore(OneLakeDocumentStore(tmp_path))
    first = _append(store)["observations"][0]["observation_id"]
    for revision in range(1, 31):
        last = _append(store, revision)
    assert last["revision"] == 31
    assert len(last["observations"]) == 30
    assert first not in [row["observation_id"] for row in last["observations"]]
    with pytest.raises(DocumentConflictError):
        _append(store, 30)
    assert store.read("reader", SCOPE) == last


def test_simultaneous_capture_never_loses_an_observation(tmp_path):
    store = OverviewHistoryStore(OneLakeDocumentStore(tmp_path))
    barrier = Barrier(2)

    def append():
        barrier.wait()
        try:
            return _append(store)["revision"]
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: append(), range(2)))
    assert results.count(1) == results.count("conflict") == 1
    assert store.read("reader", SCOPE)["revision"] == 1


def test_complete_serialized_document_byte_limit_is_inclusive(tmp_path, monkeypatch):
    from operations import overview_history

    store = OverviewHistoryStore(OneLakeDocumentStore(tmp_path))
    first = _append(store)
    exact = len((json.dumps(first, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(overview_history, "MAX_HISTORY_BYTES", exact)
    assert store.read("reader", SCOPE) == first
    with pytest.raises(ValueError, match="document limit"):
        _append(store, 1)
    assert store.read("reader", SCOPE) == first
    monkeypatch.setattr(overview_history, "MAX_HISTORY_BYTES", exact - 1)
    with pytest.raises(RuntimeError, match="document limit"):
        store.read("reader", SCOPE)


@pytest.mark.parametrize(
    "damage", ["identity", "schema", "duplicate", "source", "timestamp", "revision"]
)
def test_corrupt_history_fails_explicitly(tmp_path, damage):
    store = OverviewHistoryStore(OneLakeDocumentStore(tmp_path))
    payload = _append(store)
    if damage == "identity":
        payload["actor"] = "other"
    elif damage == "schema":
        payload["observations"][0]["exposed_findings"] = "3"
    elif damage == "duplicate":
        payload["observations"] *= 2
        payload["revision"] = 2
    elif damage == "source":
        payload["observations"][0]["sources"][1] = payload["observations"][0][
            "sources"
        ][0]
    elif damage == "timestamp":
        payload["observations"][0]["captured_at"] = "2026-10-16T00:00:00"
    else:
        payload["revision"] = 29
    path = tmp_path / store._name("reader", SCOPE)
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="Stored Overview"):
        store.read("reader", SCOPE)


def _client(tmp_path, monkeypatch):
    context = ApiContext(
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(
                    subject="reader",
                    grants=(Grant("reader", Scope.from_mapping(SCOPE)),),
                ),
                OTHER: Principal(
                    subject="other",
                    grants=(Grant("reader", Scope.from_mapping(SCOPE)),),
                ),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        onboarding=SubscriptionOnboardingService(tmp_path / "onboarding"),
        overview_history_store=OverviewHistoryStore(
            OneLakeDocumentStore(tmp_path / "history")
        ),
    )
    calls = []
    from api.routers import overview

    def situations(context, scope, page, **filters):
        calls.append(("situations", scope.to_dict(), page.limit, filters))
        return {
            "data": [{"priority": "P1"}, {"priority": "P3"}],
            "evidence": [
                {"timestamp": "2026-10-15T00:00:00Z", "source_table": "situations"}
            ],
            "pagination": {"total": 350, "next_offset": 100},
            "warnings": ["Partial"],
        }

    def network(context, scope):
        calls.append(("network", scope.to_dict()))
        return {"data": {"gap_count": 4}, "evidence": []}

    def exposure(context, scope):
        calls.append(("exposure", scope.to_dict()))
        return {"data": {"internet_exposed_count": 3}, "evidence": []}

    monkeypatch.setattr(overview, "list_situations", situations)
    monkeypatch.setattr(overview, "network_summary", network)
    monkeypatch.setattr(overview, "vulnerability_summary", exposure)
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        context,
        calls,
    )


def test_routes_capture_server_counts_and_reauthorize_each_read(tmp_path, monkeypatch):
    client, context, calls = _client(tmp_path, monkeypatch)
    result = client.post(
        "/api/v1/overview/history", headers=AUTH, json={"expected_revision": 0}
    )
    assert result.status_code == 201, result.text
    state = result.json()["data"]
    assert state["scope"] == SCOPE
    observation = state["observations"][0]
    assert observation["critical_situations"] == 1
    assert observation["exposed_findings"] == 3
    assert observation["network_gaps"] == 4
    assert observation["sources"][0]["loaded"] == 2
    assert observation["sources"][0]["total"] == 350
    assert observation["sources"][0]["observed_at"] == ["2026-10-15T00:00:00Z"]
    assert all(call[1] == SCOPE for call in calls)
    assert calls[0][2] == 100
    assert all(not hasattr(value, "default") for value in calls[0][3].values())
    calls.clear()
    assert client.get("/api/v1/overview/history", headers=AUTH).json()["data"] == state
    assert calls == []  # Retained recovery does not acquire live providers.
    assert (
        client.get(
            "/api/v1/overview/history", headers={"Authorization": f"Bearer {OTHER}"}
        ).json()["data"]["revision"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/overview/history?subscription=sub-b", headers=AUTH
        ).status_code
        == 403
    )
    assert client.get("/api/v1/overview/history").status_code == 401
    assert (
        client.post(
            "/api/v1/overview/history", headers=AUTH, json={"expected_revision": 0}
        ).status_code
        == 409
    )
    assert calls == []
    context.overview_history_store = None
    assert client.get("/api/v1/overview/history", headers=AUTH).status_code == 503


def test_failed_acquisition_and_submitted_counts_cannot_create_history(
    tmp_path, monkeypatch
):
    client, context, _ = _client(tmp_path, monkeypatch)
    from api.routers import overview

    def fail(*_):
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Source unavailable")

    monkeypatch.setattr(overview, "network_summary", fail)
    assert (
        client.post(
            "/api/v1/overview/history", headers=AUTH, json={"expected_revision": 0}
        ).status_code
        == 503
    )
    assert context.overview_history_store.read("reader", SCOPE)["revision"] == 0
    assert (
        client.post(
            "/api/v1/overview/history",
            headers=AUTH,
            json={"expected_revision": 0, "critical_situations": 0},
        ).status_code
        == 400
    )


def test_runtime_composes_history_on_the_existing_root(tmp_path, monkeypatch):
    from api import runtime

    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    store = runtime._overview_history_store()
    _append(store)
    assert list((tmp_path / "state" / "overview-history").glob("*.json"))
