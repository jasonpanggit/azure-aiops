"""Opt-in request admission is durable, authorized, and never redispatched."""
import time
from unittest.mock import Mock

import pytest
from test_api_copilot_history import PARAMS, SCOPE
from test_api_multi_agent import TOKEN, _auth, _client

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
