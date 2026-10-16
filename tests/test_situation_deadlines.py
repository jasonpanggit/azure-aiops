"""Declared timing is exact-scope/run-bound, never an inferred SLA outcome."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from pydantic import ValidationError
from test_situation_triage import HEADERS, triage_client

from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.scope import Scope
from situations.deadlines import (
    DeadlineChange,
    DeadlineState,
    SituationDeadlineStore,
    project_deadline,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

SCOPE = {"subscription": ["sub-a"]}
NOW = datetime(2026, 10, 17, tzinfo=UTC)


def change(revision=0, **updates):
    return DeadlineChange(**{
        "expected_revision": revision, "evidence_run_id": "run-1", "due_at": "2026-10-16T00:00:00Z",
        "reason": "Explicit response-review commitment", **updates,
    })


def test_explicit_shared_scope_declarations_recover_remove_and_never_inherit(tmp_path):
    store = SituationDeadlineStore(OneLakeDocumentStore(tmp_path))
    assert store.read(SCOPE).declarations == []
    state = store.change(SCOPE, "case", "admin-a", change())
    assert SituationDeadlineStore(store.documents).read(SCOPE) == state
    assert store.read({}).declarations == []
    assert store.read({"subscription": ["sub-a"], "region": ["eastus"]}).declarations == []
    assert state.declarations[0].actor == "admin-a"
    with pytest.raises(DocumentConflictError):
        store.change(SCOPE, "case", "admin-b", change())
    assert store.change(SCOPE, "case", "admin-b", change(1, due_at=None)).declarations == []
    with pytest.raises(KeyError):
        store.change(SCOPE, "case", "admin-b", change(2, due_at=None))


@pytest.mark.parametrize("updates", [
    {"expected_revision": True}, {"due_at": "2026-10-17"}, {"due_at": ""},
    {"reason": ""}, {"evidence_run_id": ""}, {"due_at": 123}, {"sla_met": True},
    {"due_at": "0001-01-01T00:00:00+01:00"}, {"due_at": "2026-02-30T00:00:00Z"},
])
def test_no_default_naive_time_or_fabricated_attainment(updates):
    with pytest.raises(ValidationError):
        change(**updates)


@pytest.mark.parametrize("lifecycle,run,status", [
    ("open", "run-1", "overdue"), ("investigating", "run-1", "overdue"),
    ("closed", "run-1", "closed"), ("resolved", "run-1", "closed"),
    ("open", "run-2", "unknown"), ("provider-custom", "run-1", "unknown"),
])
def test_only_known_lifecycle_and_exact_run_support_due_state(tmp_path, lifecycle, run, status):
    store = SituationDeadlineStore(OneLakeDocumentStore(tmp_path))
    state = store.change(SCOPE, "case", "admin", change())
    result = project_deadline({"situation_id": "case", "run_id": run, "lifecycle_state": lifecycle}, state, NOW)
    assert result["state"] == status
    assert result["authority"] == "none"
    assert "contractual SLA" in result["interpretation"]
    assert result["declaration"]["evidence_run_id"] == "run-1"
    assert project_deadline({"situation_id": "absent"}, state, NOW)["state"] == "unknown"
    assert project_deadline({"situation_id": "case"}, None, NOW)["state"] == "unknown"
    if lifecycle == "open" and run == "run-1":
        state = store.change(SCOPE, "case", "admin", change(1, due_at="2026-10-18T00:00:00Z"))
        assert project_deadline({"situation_id": "case", "run_id": run, "lifecycle_state": lifecycle}, state, NOW)["state"] == "due"


@pytest.mark.parametrize("existing", [False, True])
def test_atomic_single_winner_on_create_and_replace(tmp_path, existing):
    store = SituationDeadlineStore(OneLakeDocumentStore(tmp_path))
    if existing:
        store.change(SCOPE, "case", "admin", change())
    barrier, read = Barrier(2), store._read

    def simultaneous(scope):
        result = read(scope); barrier.wait(); return result

    store._read = simultaneous

    def write(actor):
        try:
            store.change(SCOPE, "case", actor, change(int(existing)))
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["admin-a", "admin-b"])) == ["conflict", "saved"]


@pytest.mark.parametrize("failure", ["scope", "schema", "duplicate", "time", "revision"])
def test_corrupt_declarations_never_become_empty_defaults(tmp_path, failure):
    store = SituationDeadlineStore(OneLakeDocumentStore(tmp_path))
    payload = store.change(SCOPE, "case", "admin", change()).model_dump()
    if failure == "scope": payload["scope"] = {}
    elif failure == "schema": payload["schema_version"] = True
    elif failure == "duplicate": payload["declarations"] *= 2
    elif failure == "time": payload["declarations"][0]["due_at"] = "2026-01-01"
    else: payload["declarations"][0]["revision"] = 2
    name = store._name(SCOPE)
    store.documents.replace_if_match(name, payload, expected_etag=store.documents.read_snapshot(name).etag)
    with pytest.raises(RuntimeError):
        store.read(SCOPE)


def test_exact_byte_limit_not_estimated_row_size(monkeypatch):
    from situations import deadlines

    payload = {"schema_version": 1, "scope": {"region": ["\u4e2d"]}, "revision": 0, "updated_at": "", "updated_by": "", "declarations": []}
    size = len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(deadlines, "MAX_BYTES", size)
    DeadlineState.model_validate(payload)
    monkeypatch.setattr(deadlines, "MAX_BYTES", size - 1)
    with pytest.raises(ValidationError, match="512 KiB"):
        DeadlineState.model_validate(payload)


def http(tmp_path):
    client, rows = triage_client(tmp_path)
    from test_situation_triage import TOKEN

    context = client.app.state.context
    context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="admin", grants=(Grant("admin", Scope.from_mapping(SCOPE)),))})
    context.situation_deadline_store = SituationDeadlineStore(OneLakeDocumentStore(tmp_path / "deadlines"))
    return client, rows


def put(client, identity="situation-0", **updates):
    return client.put(f"/api/v1/situations/{identity}/response-deadline", headers=HEADERS, json=change(**updates).model_dump())


def test_api_rechecks_scope_run_and_revision_before_mutation_and_filters_before_paging(tmp_path):
    client, rows = http(tmp_path)
    for index in range(3):
        response = put(client, f"situation-{index}", revision=index)
        assert response.status_code == 200, response.text
        assert response.json()["data"]["state"] == "overdue"
    queue = client.get("/api/v1/situations?response_deadline=overdue&offset=1&limit=1", headers=HEADERS).json()
    assert queue["pagination"]["total"] == 3
    assert len(queue["data"]) == 1
    assert queue["data"][0]["response_deadline"]["policy_revision"] == 3
    assert put(client, revision=0).status_code == 409
    assert put(client, revision=3, evidence_run_id="stale").status_code == 409
    assert put(client, identity="private-situation", revision=3).status_code == 404
    assert client.get("/api/v1/situations/private-situation/response-deadline", headers=HEADERS).status_code == 404
    rows[0]["run_id"] = "run-2"
    assert client.get("/api/v1/situations/situation-0", headers=HEADERS).json()["data"]["response_deadline"]["state"] == "unknown"
    artifact = client.post("/api/v1/situations/handoff", headers=HEADERS, json={
        "selections": [{"situation_id": "situation-0", "run_id": "run-2"}],
    }).json()["data"]["artifact"]
    assert artifact["situations"][0]["response_deadline"]["state"] == "unknown"
    assert client.get("/api/v1/situations?response_deadline=invalid", headers=HEADERS).status_code == 400


def test_reader_and_partial_admin_cannot_write_whole_read_scope(tmp_path):
    from test_situation_triage import TOKEN

    client, _ = http(tmp_path)
    context = client.app.state.context
    for grants in (
        (Grant("reader", Scope.from_mapping(SCOPE)),),
        (Grant("reader"), Grant("admin", Scope.from_mapping({"subscription": ["sub-b"]}))),
    ):
        context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="reader", grants=grants)})
        assert client.get("/api/v1/situations/situation-0/response-deadline", headers=HEADERS).json()["data"]["can_write"] is False
        assert put(client).status_code == 403
    assert context.situation_deadline_store.read(SCOPE).revision == 0


def test_capacity_never_evicts_and_explicit_removal_frees_space(tmp_path):
    store = SituationDeadlineStore(OneLakeDocumentStore(tmp_path))
    state = store.change(SCOPE, "case", "admin", change())
    payload = state.model_dump()
    payload["declarations"] = [{**payload["declarations"][0], "situation_id": f"case-{index}"} for index in range(200)]
    name = store._name(SCOPE)
    store.documents.replace_if_match(name, payload, expected_etag=store.documents.read_snapshot(name).etag)
    with pytest.raises(ValueError, match="200"):
        store.change(SCOPE, "new", "admin", change(1))
    assert len(store.read(SCOPE).declarations) == 200
    assert store.read(SCOPE).revision == 1
    store.change(SCOPE, "case-0", "admin", change(1, due_at=None))
    assert len(store.change(SCOPE, "new", "admin", change(2)).declarations) == 200


def test_equivalent_timezones_and_equality_are_overdue(tmp_path):
    state = SituationDeadlineStore(OneLakeDocumentStore(tmp_path)).change(
        SCOPE, "case", "admin", change(due_at="2026-10-17T02:00:00+02:00"),
    )
    assert project_deadline({"situation_id": "case", "run_id": "run-1", "lifecycle_state": "open"}, state, NOW)["state"] == "overdue"


def test_unavailable_storage_never_claims_empty_or_committed_write(tmp_path, monkeypatch):
    client, _ = http(tmp_path)
    store = client.app.state.context.situation_deadline_store

    def unavailable(*args, **kwargs):
        raise OSError("private storage detail")

    monkeypatch.setattr(store.documents, "create_only", unavailable)
    response = put(client)
    assert response.status_code == 503
    assert "private storage detail" not in response.text
    assert store.read(SCOPE).revision == 0
    monkeypatch.setattr(store, "read", unavailable)
    for url in ("/situations", "/situations/situation-0", "/situations/situation-0/response-deadline"):
        response = client.get(f"/api/v1{url}", headers=HEADERS)
        assert response.status_code == 503
        assert "private storage detail" not in response.text


def test_handoff_projects_one_revision_and_time_for_every_case(tmp_path, monkeypatch):
    client, _ = http(tmp_path)
    store = client.app.state.context.situation_deadline_store
    put(client)
    put(client, identity="situation-1", revision=1)
    read, calls = store.read, []

    def capture(scope):
        calls.append(scope)
        return read(scope)

    monkeypatch.setattr(store, "read", capture)
    result = client.post("/api/v1/situations/handoff", headers=HEADERS, json={
        "selections": [{"situation_id": f"situation-{i}", "run_id": "run-1"} for i in range(2)],
    })
    assert result.status_code == 200
    observations = [row["response_deadline"] for row in result.json()["data"]["artifact"]["situations"]]
    assert calls == [SCOPE]
    assert {item["policy_revision"] for item in observations} == {2}
    assert len({item["evaluated_at"] for item in observations}) == 1


def test_path_identity_and_unconfigured_timing_are_explicit(tmp_path, monkeypatch):
    from urllib.parse import quote

    from api import runtime

    client, rows = http(tmp_path)
    rows[0]["situation_id"] = "situation://case/a"
    path = f"/api/v1/situations/{quote(rows[0]['situation_id'], safe='')}/response-deadline"
    assert client.put(path, headers=HEADERS, json=change().model_dump()).status_code == 200
    assert client.get(path, headers=HEADERS).json()["data"]["declaration"]["situation_id"] == rows[0]["situation_id"]
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "runtime"))
    assert runtime._situation_deadline_store().read(SCOPE).revision == 0
    client.app.state.context.situation_deadline_store = None
    data = client.get(path, headers=HEADERS).json()["data"]
    assert data["state"] == "unknown" and data["policy_revision"] is None and data["can_write"] is False
