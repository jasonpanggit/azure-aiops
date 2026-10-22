from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from fabric.graph_refresh import (
    GraphRefreshAmbiguousError,
    GraphRefresher,
    GraphRefreshError,
)

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
GRAPH = "e4aa8669-82d3-4ef4-9241-47252fca23fd"
LOCATION = f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE}/items/{GRAPH}/jobs/instances/j1"


class Credential:
    def get_token(self, *scopes):
        return SimpleNamespace(token="private-token")


class Store:
    def __init__(self):
        self.doc = {}

    def read(self, name):
        return dict(self.doc)

    def write(self, name, payload, *, expected_revision):
        assert int(self.doc.get("revision") or 0) == expected_revision
        self.doc = dict(payload)


def refresher(handler, store, **kwargs):
    return GraphRefresher(
        Credential(),
        workspace_id=WORKSPACE,
        graph_model_id=GRAPH,
        state_store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        **kwargs,
    )


def flow(statuses, post_status=202):
    calls = []
    queue = list(statuses)

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert request.url.path.endswith("/jobs/refreshGraph/instances")
            return httpx.Response(post_status, headers={"Location": LOCATION, "Retry-After": "1"})
        return httpx.Response(200, json={"id": "j1", "status": queue.pop(0)})

    return handler, calls


def test_success_polls_until_completed_and_persists_outcome():
    store = Store()
    handler, calls = flow(["InProgress", "Completed"])
    result = refresher(handler, store).refresh(source_run_id="activation-1")
    assert result["status"] == "Completed"
    assert calls == ["POST", "GET", "GET"]
    assert store.doc["phase"] == "completed"
    assert store.doc["sourceRunId"] == "activation-1"
    assert "private-token" not in str(store.doc)


def test_failed_job_raises_and_records_failure():
    store = Store()
    handler, _ = flow(["Failed"])
    with pytest.raises(GraphRefreshError):
        refresher(handler, store).refresh(source_run_id="a")
    assert store.doc["phase"] == "failed"


def test_rejected_post_not_retried():
    store = Store()
    handler, calls = flow([], post_status=429)
    with pytest.raises(GraphRefreshError):
        refresher(handler, store).refresh(source_run_id="a")
    assert calls == ["POST"]
    assert store.doc["phase"] == "rejected"


def test_ambiguous_post_leaves_intent_and_blocks_next_refresh():
    store = Store()

    def broken(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(broken, store).refresh(source_run_id="a")
    assert store.doc["phase"] == "requested"
    handler, calls = flow(["Completed"])
    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store).refresh(source_run_id="b")
    assert calls == []


def test_deadline_is_ambiguous_and_finite():
    store = Store()
    handler, _ = flow(["InProgress"] * 50)
    ticks = iter(range(0, 1000, 400))
    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store, timeout_seconds=600, clock=lambda: next(ticks)).refresh(
            source_run_id="a"
        )
    assert store.doc["phase"] == "requested"


def test_untrusted_location_rejected():
    store = Store()

    def handler(request):
        return httpx.Response(202, headers={"Location": "https://evil.example/x"})

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store).refresh(source_run_id="a")


def test_invalid_ids_and_timeout():
    with pytest.raises(ValueError):
        GraphRefresher(Credential(), workspace_id="../x", graph_model_id=GRAPH,
                       state_store=Store(), http_client=httpx.Client())
    with pytest.raises(ValueError):
        GraphRefresher(Credential(), workspace_id=WORKSPACE, graph_model_id=GRAPH,
                       state_store=Store(), http_client=httpx.Client(), timeout_seconds=0)
