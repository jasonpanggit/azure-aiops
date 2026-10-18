"""Opt-in request admission is durable, authorized, and never redispatched."""
import time
from unittest.mock import Mock

import pytest
from test_api_copilot_history import PARAMS, SCOPE
from test_api_multi_agent import TOKEN, _auth, _client
from test_investigation_thread_store import FakeClock

from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.routers import copilot
from operations import orchestration_service
from operations.investigation_thread_store import InvestigationThreadStore
from storage.onelake_documents import OneLakeDocumentStore

_CANONICAL_ADAPTER = copilot._investigate_via_canonical


def _fixture(tmp_path, monkeypatch):
    client = _client(tmp_path)
    documents = OneLakeDocumentStore(tmp_path / "receipts")
    monkeypatch.setattr(copilot, "investigation_thread_store", lambda: InvestigationThreadStore(documents=documents))
    monkeypatch.setattr(copilot, "canonical_orchestration_enabled", lambda **_: True)
    execute = Mock(return_value={"data": {"thread_id": f"thr-{'b' * 32}", "thread_revision": 2}})
    monkeypatch.setattr(copilot, "_investigate_via_canonical", execute)
    key = f"req-{int(time.time() * 1000)}-{'a' * 32}"
    payload = {"question": "Review current evidence", "session_id": "root", "request_key": key}
    return client, documents, execute, key, payload


def test_admission_completion_and_replay_never_repeat_execution(tmp_path, monkeypatch):
    client, _, execute, key, payload = _fixture(tmp_path, monkeypatch)
    assert client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload).status_code == 200
    for changed in [payload, {**payload, "question": "Different question"}]:
        replay = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=changed)
        assert replay.status_code == 409
    receipt = client.get(f"/api/v1/copilot/requests/{key}", params=PARAMS, headers=_auth())
    assert receipt.status_code == 200
    assert receipt.json()["scope"] == SCOPE.to_dict()
    assert receipt.json()["data"]["status"] == "completed"
    assert receipt.json()["data"]["thread_revision"] == 2
    assert "Review current evidence" not in receipt.text
    execute.assert_called_once()


@pytest.mark.parametrize("unavailable", ["storage", "configuration", "compatibility"])
def test_admission_unavailable_never_dispatches(tmp_path, monkeypatch, unavailable):
    client, documents, execute, _, payload = _fixture(tmp_path, monkeypatch)
    if unavailable == "configuration":
        monkeypatch.setattr(copilot, "investigation_thread_store", lambda: InvestigationThreadStore())
    elif unavailable == "compatibility":
        monkeypatch.setattr(copilot, "canonical_orchestration_enabled", lambda **_: False)
    else:
        monkeypatch.setattr(documents, "create_only", Mock(side_effect=OSError("write failed")))
    response = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload)
    assert response.status_code == 503
    execute.assert_not_called()


def test_completion_write_failure_retains_unknown_outcome_without_reexecution(tmp_path, monkeypatch):
    client, documents, execute, key, payload = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(documents, "write", Mock(side_effect=OSError("completion failed")))
    first = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload)
    assert first.status_code == 503
    assert client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload).status_code == 409
    receipt = client.get(f"/api/v1/copilot/requests/{key}", params=PARAMS, headers=_auth())
    assert receipt.json()["data"]["status"] == "accepted_outcome_unconfirmed"
    execute.assert_called_once()


def test_receipt_authorization_not_found_and_unavailable_are_not_success(tmp_path, monkeypatch):
    client, documents, execute, key, payload = _fixture(tmp_path, monkeypatch)
    path = f"/api/v1/copilot/requests/{key}"
    assert client.get(path, params=PARAMS, headers=_auth()).status_code == 404
    assert client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload).status_code == 200
    assert client.get(path, params=PARAMS).status_code == 401
    assert client.get(path, params={**PARAMS, "owner": "different"}, headers=_auth()).status_code == 404
    client.app.state.context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="foreign", grants=(Grant("admin"),))})
    assert client.get(path, params=PARAMS, headers=_auth()).status_code == 404
    client.app.state.context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="operator@example.com", grants=(Grant("reader", copilot.Scope({"subscription": ["elsewhere"]})),))})
    assert client.get(path, params=PARAMS, headers=_auth()).status_code == 403
    client.app.state.context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))})
    monkeypatch.setattr(documents, "read_or_raise", Mock(side_effect=OSError("unavailable")))
    assert client.get(path, params=PARAMS, headers=_auth()).status_code == 503
    execute.assert_called_once()


def test_keyless_consumers_keep_existing_execution_contract(tmp_path, monkeypatch):
    client, _, execute, _, payload = _fixture(tmp_path, monkeypatch)
    del payload["request_key"]
    assert client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload).status_code == 200
    execute.assert_called_once()


def test_real_canonical_adapter_records_one_retained_turn_and_exact_receipt(tmp_path, monkeypatch):
    client, documents, _, key, payload = _fixture(tmp_path, monkeypatch)
    store = InvestigationThreadStore(documents=documents)
    monkeypatch.setattr(copilot, "investigation_thread_store", lambda: store)
    monkeypatch.setattr(orchestration_service, "investigation_thread_store", lambda: store)
    monkeypatch.setattr(copilot, "_investigate_via_canonical", _CANONICAL_ADAPTER)
    response = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["request_key"] == key
    assert data["thread_revision"] == 1
    assert client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload).status_code == 409
    receipt = client.get(f"/api/v1/copilot/requests/{key}", params=PARAMS, headers=_auth()).json()["data"]
    assert receipt["thread_id"] == data["thread_id"]
    assert receipt["thread_revision"] == 1
    history = client.get(f"/api/v1/copilot/threads/{data['thread_id']}/history", params={**PARAMS, "expected_revision": 1}, headers=_auth())
    assert history.status_code == 200
    assert len(history.json()["data"]["turns"]) == 1
    assert history.json()["data"]["turns"][0]["observation_status"] == "historical"


def _exact_fixture(tmp_path, monkeypatch):
    client, documents, _, key, payload = _fixture(tmp_path, monkeypatch)
    clock = FakeClock(time.time())
    store = InvestigationThreadStore(documents=documents, clock=clock)
    monkeypatch.setattr(copilot, "investigation_thread_store", lambda: store)
    monkeypatch.setattr(orchestration_service, "investigation_thread_store", lambda: store)
    monkeypatch.setattr(copilot, "_investigate_via_canonical", _CANONICAL_ADAPTER)
    legacy = Mock(side_effect=AssertionError("Explicit continuation must not resolve a legacy session"))
    remember = Mock(side_effect=AssertionError("Explicit continuation must not rebind a legacy session"))
    monkeypatch.setattr(orchestration_service, "_legacy_session_thread_for_execution", legacy)
    monkeypatch.setattr(orchestration_service, "_remember_legacy_session_thread", remember)
    thread = store.create("operator@example.com", SCOPE)
    store.append(thread.thread_id, "operator@example.com", SCOPE, {"question": "Original retained question"})
    payload.update(thread_id=thread.thread_id, expected_thread_revision=1)
    return client, documents, store, clock, thread, key, payload, legacy, remember


def test_exact_continuation_appends_only_selected_revision_without_session_rebinding(tmp_path, monkeypatch):
    client, _, store, _, thread, key, payload, legacy, remember = _exact_fixture(tmp_path, monkeypatch)
    response = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["thread_id"] == thread.thread_id
    assert response.json()["data"]["thread_revision"] == 2
    assert response.json()["data"]["request_key"] == key
    retained = store.read_snapshot(thread.thread_id, "operator@example.com", SCOPE, expected_revision=2)
    assert len(retained["turns"]) == 2
    assert retained["turns"][0]["question"] == "Original retained question"
    legacy.assert_not_called()
    remember.assert_not_called()


def test_narrowed_history_read_is_allowed_but_cannot_restore_into_different_scope(tmp_path, monkeypatch):
    client, _, store, _, _, _, payload, legacy, remember = _exact_fixture(tmp_path, monkeypatch)
    thread = store.create("operator@example.com", copilot.Scope({"subscription": ["sub-prod"]}))
    store.append(thread.thread_id, "operator@example.com", copilot.Scope({"subscription": ["sub-prod"]}), {"question": "Broader private question"})
    payload.update(thread_id=thread.thread_id, expected_thread_revision=1)
    history = client.get(f"/api/v1/copilot/threads/{thread.thread_id}/history", params=PARAMS, headers=_auth())
    assert history.status_code == 200
    assert history.json()["data"]["continuation_scope_match"] is False
    assert "Broader private question" not in history.text
    response = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json=payload)
    assert response.status_code == 404
    assert store.read_snapshot(thread.thread_id, "operator@example.com", copilot.Scope({"subscription": ["sub-prod"]}))["thread_revision"] == 1
    legacy.assert_not_called()
    remember.assert_not_called()

@pytest.mark.parametrize("failure,status", [("stale", 409), ("missing", 404), ("foreign", 404), ("scope", 404), ("expired", 404)])
def test_exact_continuation_never_resets_identity_or_substitutes_new_thread(tmp_path, monkeypatch, failure, status):
    client, documents, store, clock, thread, _, payload, legacy, remember = _exact_fixture(tmp_path, monkeypatch)
    params = dict(PARAMS)
    payload["question"] = "show list of VMs"
    tool = Mock(side_effect=AssertionError("Rejected exact continuation cannot execute tools"))
    monkeypatch.setattr(orchestration_service, "call_tool", tool)
    if failure == "stale":
        payload["expected_thread_revision"] = 2
    elif failure == "missing":
        payload["thread_id"] = f"thr-{'f' * 32}"
    elif failure == "foreign":
        client.app.state.context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(subject="foreign", grants=(Grant("admin"),))})
    elif failure == "scope":
        params["owner"] = "different"
    else:
        clock.advance(3601)
    before, _ = documents.list_names("threads/", limit=64)
    response = client.post("/api/v1/copilot/investigate", params=params, headers=_auth(), json=payload)
    assert response.status_code == status, response.text
    after, _ = documents.list_names("threads/", limit=64)
    assert set(after) <= set(before)
    if failure != "expired":
        assert store.read_snapshot(thread.thread_id, "operator@example.com", SCOPE)["thread_revision"] == 1
    legacy.assert_not_called()
    remember.assert_not_called()
    tool.assert_not_called()


@pytest.mark.parametrize("fields", [
    {"thread_id": f"thr-{'b' * 32}"},
    {"expected_thread_revision": 1},
    {"thread_id": "bad", "expected_thread_revision": 1},
    {"thread_id": f"thr-{'b' * 32}", "expected_thread_revision": 0},
    {"thread_id": f"thr-{'b' * 32}", "expected_thread_revision": 1, "request_key": None},
])
def test_incomplete_or_invalid_exact_target_rejected_before_dispatch(tmp_path, monkeypatch, fields):
    client, _, execute, _, payload = _fixture(tmp_path, monkeypatch)
    response = client.post("/api/v1/copilot/investigate", params=PARAMS, headers=_auth(), json={**payload, **fields})
    assert response.status_code in {400, 422}
    execute.assert_not_called()
