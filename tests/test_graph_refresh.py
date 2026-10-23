from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from fabric.graph_refresh import (
    GraphRefreshAmbiguousError,
    GraphRefresher,
    GraphRefreshError,
)
from storage.onelake_documents import DocumentConflictError

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
GRAPH = "e4aa8669-82d3-4ef4-9241-47252fca23fd"
JOB = "7b0f4d58-1111-4222-8333-444455556666"
LOCATION = (
    f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE}/items/{GRAPH}"
    f"/jobs/instances/{JOB}"
)


class Credential:
    def get_token(self, *scopes):
        return SimpleNamespace(token="private-token")


class Store:
    def __init__(self):
        self.doc = {}

    def read(self, name):
        return dict(self.doc)

    def write(self, name, payload, *, expected_revision):
        if int(self.doc.get("revision") or 0) != expected_revision:
            raise DocumentConflictError("conflict")
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


def flow(statuses, post_status=202, retry="1", extra=None):
    calls = []
    queue = list(statuses)

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            assert request.url.path.endswith("/jobs/refreshGraph/instances")
            return httpx.Response(post_status, headers={"Location": LOCATION, "Retry-After": retry})
        return httpx.Response(200, json={"id": JOB, "status": queue.pop(0), **(extra or {})})

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

def test_accepted_job_is_durable_before_poll_failure_and_blocks_replay():
    store = Store()
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": LOCATION, "Retry-After": "1"})
        assert store.doc["phase"] == "requested"
        assert store.doc["jobInstanceId"] == JOB
        assert store.doc["workspaceId"] == WORKSPACE
        assert store.doc["sourceRunId"] == "activation-a"
        raise httpx.ReadTimeout("private-provider-detail")

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert store.doc["phase"] == "requested"
    assert store.doc["jobInstanceId"] == JOB
    assert store.doc["revision"] == 2
    with pytest.raises(GraphRefreshAmbiguousError, match="unresolved_intent"):
        refresher(handler, store).refresh(source_run_id="activation-b")
    assert calls == ["POST", "GET"]


def test_accepted_job_record_cas_conflict_prevents_poll_and_preserves_newer_owner():
    store = Store()
    calls = []

    def handler(request):
        calls.append(request.method)
        store.doc = {"phase": "requested", "owner": "new-owner", "revision": 7}
        return httpx.Response(202, headers={"Location": LOCATION})

    with pytest.raises(GraphRefreshAmbiguousError, match="state_superseded"):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert calls == ["POST"]
    assert store.doc["owner"] == "new-owner"
    assert store.doc["revision"] == 7


def test_lease_loss_after_acceptance_never_polls_or_writes_without_ownership():
    store = Store()
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(202, headers={"Location": LOCATION})

    def guard():
        if calls:
            raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        refresher(handler, store, guard=guard).refresh(source_run_id="activation-a")
    assert calls == ["POST"]
    assert store.doc["revision"] == 1
    assert store.doc["phase"] == "requested"
    assert "jobInstanceId" not in store.doc


def test_accepted_state_cas_write_conflict_never_polls_or_overwrites():
    store = Store()
    calls = []
    original_write = store.write

    def write(name, payload, *, expected_revision):
        if payload.get("jobInstanceId"):
            store.doc = {"phase": "requested", "revision": 8, "owner": "other"}
        original_write(name, payload, expected_revision=expected_revision)

    store.write = write
    handler, calls = flow(["Completed"])
    with pytest.raises(GraphRefreshAmbiguousError, match="state_conflict"):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert calls == ["POST"]
    assert store.doc == {"phase": "requested", "revision": 8, "owner": "other"}


@pytest.mark.parametrize("status", ["Failed", "Cancelled", "Deduped", "Completed"])
def test_terminal_receipt_retains_accepted_job_identity(status):
    store = Store()
    handler, calls = flow([status])
    if status == "Completed":
        refresher(handler, store).refresh(source_run_id="activation-a")
    else:
        with pytest.raises(GraphRefreshError):
            refresher(handler, store).refresh(source_run_id="activation-a")
    assert calls == ["POST", "GET"]
    assert store.doc["jobInstanceId"] == JOB
    assert store.doc["workspaceId"] == WORKSPACE
    assert store.doc["revision"] == 3


def test_failed_job_raises_and_records_failure():
    store = Store()
    handler, _ = flow(["Failed"])
    with pytest.raises(GraphRefreshError):
        refresher(handler, store).refresh(source_run_id="a")
    assert store.doc["phase"] == "failed"


@pytest.mark.parametrize("status", ["Failed", "Cancelled", "Deduped", "Completed", "InProgress"])
@pytest.mark.parametrize("identity", [None, "", "00000000-0000-4000-8000-000000000000", [], {}])
def test_poll_without_verified_job_identity_stays_ambiguous_and_blocks_replay(status, identity):
    store = Store()
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": LOCATION, "Retry-After": "1"})
        assert calls == ["POST", "GET"], "An invalid receipt must stop polling"
        payload = {"status": status}
        if identity is not None:
            payload["id"] = identity
        return httpx.Response(200, json=payload)

    with pytest.raises(GraphRefreshAmbiguousError, match="job_mismatch"):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert store.doc["phase"] == "requested"
    assert store.doc["revision"] == 2
    assert store.doc["jobInstanceId"] == JOB
    with pytest.raises(GraphRefreshAmbiguousError, match="unresolved_intent"):
        refresher(handler, store).refresh(source_run_id="activation-b")
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize("status", [None, [], {}, 1, True, "", "   "])
def test_malformed_poll_status_stays_ambiguous_without_another_poll(status):
    store = Store()
    handler, calls = flow([status])
    with pytest.raises(GraphRefreshAmbiguousError, match="poll_invalid"):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert store.doc["phase"] == "requested"
    assert store.doc["jobInstanceId"] == JOB
    assert store.doc["revision"] == 2
    with pytest.raises(GraphRefreshAmbiguousError, match="unresolved_intent"):
        refresher(handler, store).refresh(source_run_id="activation-b")
    assert calls == ["POST", "GET"]


def test_future_nonterminal_status_remains_bounded_and_can_complete():
    store = Store()
    handler, calls = flow(["FuturePendingState", "Completed"])
    result = refresher(handler, store).refresh(source_run_id="activation-a")
    assert result["status"] == "Completed"
    assert calls == ["POST", "GET", "GET"]


@pytest.mark.parametrize("status", ["Failed", "Cancelled", "Deduped"])
def test_verified_terminal_failure_allows_a_later_distinct_refresh(status):
    store = Store()
    handler, calls = flow([status, "Completed"])
    with pytest.raises(GraphRefreshError, match=f"graph_refresh_{status.lower()}"):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert store.doc["phase"] == "failed"
    assert store.doc["revision"] == 3
    result = refresher(handler, store).refresh(source_run_id="activation-b")
    assert result["phase"] == "completed"
    assert result["sourceRunId"] == "activation-b"
    assert result["revision"] == 6
    assert calls == ["POST", "GET", "POST", "GET"]


@pytest.mark.parametrize("payload", ["null", "[]", '"Completed"', "{}", '{"id":', ""])
def test_malformed_poll_body_retains_accepted_intent(payload):
    store = Store()
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": LOCATION, "Retry-After": "1"})
        assert calls == ["POST", "GET"], "An invalid receipt must stop polling"
        return httpx.Response(200, content=payload)

    with pytest.raises(GraphRefreshAmbiguousError, match="poll_invalid"):
        refresher(handler, store).refresh(source_run_id="activation-a")
    assert store.doc["phase"] == "requested"
    assert store.doc["jobInstanceId"] == JOB
    assert store.doc["revision"] == 2
    with pytest.raises(GraphRefreshAmbiguousError, match="unresolved_intent"):
        refresher(handler, store).refresh(source_run_id="activation-b")
    assert calls == ["POST", "GET"]


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
    assert store.doc["phase"] == "requested"
    assert "jobInstanceId" not in store.doc


def test_invalid_ids_and_timeout():
    with pytest.raises(ValueError):
        GraphRefresher(Credential(), workspace_id="../x", graph_model_id=GRAPH,
                       state_store=Store(), http_client=httpx.Client())
    with pytest.raises(ValueError):
        GraphRefresher(Credential(), workspace_id=WORKSPACE, graph_model_id=GRAPH,
                       state_store=Store(), http_client=httpx.Client(), timeout_seconds=0)


@pytest.mark.parametrize("code", [500, 502, 504, 408, 200])
def test_gateway_or_unexpected_post_status_is_ambiguous(code):
    store = Store()
    handler, calls = flow([], post_status=code)
    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store).refresh(source_run_id="a")
    assert store.doc["phase"] == "requested"
    assert calls == ["POST"]


def test_full_retry_after_honored_and_not_polled_early():
    store, slept = Store(), []
    handler, _ = flow(["Completed"], retry="120")
    GraphRefresher(
        Credential(), workspace_id=WORKSPACE, graph_model_id=GRAPH, state_store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=slept.append,
    ).refresh(source_run_id="a")
    assert slept == [120.0]


def test_retry_after_http_date_honored():
    store, slept = Store(), []
    handler, _ = flow(["Completed"], retry="Wed, 21 Oct 2026 07:30:00 GMT")
    base = 1792567800.0 - 40  # 2026-10-21T07:30:00Z minus 40s
    GraphRefresher(
        Credential(), workspace_id=WORKSPACE, graph_model_id=GRAPH, state_store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=slept.append, wall_clock=lambda: base,
    ).refresh(source_run_id="a")
    assert 39 <= slept[0] <= 41


def test_delay_beyond_deadline_stops_without_polling():
    store, slept = Store(), []
    handler, calls = flow(["Completed"], retry="500")
    with pytest.raises(GraphRefreshAmbiguousError):
        GraphRefresher(
            Credential(), workspace_id=WORKSPACE, graph_model_id=GRAPH, state_store=store,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep=slept.append, timeout_seconds=100, clock=lambda: 0.0,
        ).refresh(source_run_id="a")
    assert slept == [] and calls == ["POST"]
    assert store.doc["phase"] == "requested"
    assert store.doc["jobInstanceId"] == JOB


def test_concurrent_contender_loses_cas_before_post():
    store = Store()
    handler, calls = flow(["Completed"])
    r = refresher(handler, store)
    real_read = store.read

    def racing_read(name):
        doc = real_read(name)
        store.doc = {"phase": "completed", "revision": 1, "owner": "other"}
        return doc

    store.read = racing_read
    with pytest.raises(GraphRefreshAmbiguousError):
        r.refresh(source_run_id="a")
    assert calls == []


def test_terminal_record_never_overwrites_newer_state():
    store = Store()
    handler, _ = flow(["Completed"])

    def handler_swap(request):
        if request.method == "GET":
            store.doc = {"phase": "completed", "revision": 9, "owner": "other"}
        return handler(request)

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler_swap, store).refresh(source_run_id="a")
    assert store.doc["owner"] == "other"


@pytest.mark.parametrize("extra", [{"failureReason": {"message": "x"}}])
def test_completed_with_failure_reason_not_success(extra):
    store = Store()
    handler, _ = flow(["Completed"], extra=extra)
    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store).refresh(source_run_id="a")
    assert store.doc["phase"] == "requested"


def test_job_id_mismatch_and_bad_location_rejected():
    store = Store()

    def wrong_id(request):
        if request.method == "POST":
            return httpx.Response(202, headers={"Location": LOCATION})
        return httpx.Response(200, json={"id": "00000000-0000-4000-8000-000000000000",
                                         "status": "Completed"})

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(wrong_id, store).refresh(source_run_id="a")
    store2 = Store()

    def other_graph(request):
        return httpx.Response(202, headers={"Location": LOCATION.replace(GRAPH, WORKSPACE)})

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(other_graph, store2).refresh(source_run_id="a")


def test_late_completion_after_deadline_not_success():
    store, now = Store(), [0.0]
    inner, _ = flow(["Completed"])

    def handler(request):
        if request.method == "GET":
            now[0] = 1000.0
        return inner(request)

    with pytest.raises(GraphRefreshAmbiguousError):
        refresher(handler, store, timeout_seconds=600, clock=lambda: now[0]).refresh(
            source_run_id="a"
        )
    assert store.doc["phase"] == "requested"


def test_guard_runs_before_post_and_each_record_and_blocks_on_loss():
    store = Store()
    handler, calls = flow(["Completed"])
    seen = []

    def guard():
        seen.append(len(calls))
        if len(calls) == 0 and len(seen) > 1:
            raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        refresher(handler, store, guard=guard).refresh(source_run_id="a")
    assert calls == []

    store2, n = Store(), {"v": 0}
    handler2, calls2 = flow(["Completed"])

    def guard2():
        n["v"] += 1
        if calls2 == ["POST", "GET"]:
            raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        refresher(handler2, store2, guard=guard2).refresh(source_run_id="a")
    assert store2.doc["phase"] == "requested"
