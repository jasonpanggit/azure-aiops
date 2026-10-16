"""Exact owned historical reads never execute or silently replace a thread."""
from unittest.mock import Mock

import pytest
from test_api_multi_agent import TOKEN, _auth, _client
from test_investigation_thread_store import FakeClock, FakeDocuments

from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.routers import copilot
from api.scope import Scope
from operations.investigation_thread_store import (
    IDLE_TTL_SECONDS,
    InvestigationThreadStore,
)

PARAMS = {
    "subscription": "sub-prod", "subscription_connection": "conn-a",
    "business_service": "Payroll", "application": "API", "environment": "prod",
    "owner": "Finance", "support_team": "Ops", "region": "eastus", "criticality": "high",
}
SCOPE = Scope.from_mapping(PARAMS)


def _fixture(tmp_path, monkeypatch):
    client, documents, clock = _client(tmp_path), FakeDocuments(), FakeClock()
    store = InvestigationThreadStore(documents=documents, clock=clock)
    thread = store.create("operator@example.com", SCOPE)
    store.append(thread.thread_id, "operator@example.com", SCOPE, {
        "question": "retained question", "status": "ok",
        "tool_results": [], "citations": [],
    })
    monkeypatch.setattr(copilot, "investigation_thread_store", lambda: store)
    executor = Mock(side_effect=AssertionError("History cannot execute tools"))
    monkeypatch.setattr(copilot, "execute_from_question", executor)
    return client, documents, clock, thread, executor


def test_exact_history_preserves_scope_identity_and_durable_observations(tmp_path, monkeypatch):
    client, documents, _, thread, executor = _fixture(tmp_path, monkeypatch)
    before = documents.read(next(iter(documents.documents)))
    documents.fail_writes = True
    response = client.get(f"/api/v1/copilot/threads/{thread.thread_id}/history", params=PARAMS, headers=_auth())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == SCOPE.to_dict()
    assert body["data"]["thread_id"] == thread.thread_id
    assert body["data"]["thread_revision"] == 1
    assert body["data"]["durability"] == "durable"
    assert body["data"]["observation_status"] == "historical"
    assert body["data"]["turns"][0]["question"] == "retained question"
    assert body["data"]["turns"][0]["observation_status"] == "historical"
    assert documents.read(next(iter(documents.documents))) == before
    assert not documents.deleted
    executor.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "foreign", "wider", "expired", "invalid"])
def test_hidden_thread_identity_errors_are_consistent_not_found(tmp_path, monkeypatch, failure):
    client, documents, clock, thread, executor = _fixture(tmp_path, monkeypatch)
    params, identifier = dict(PARAMS), thread.thread_id
    if failure == "foreign":
        client.app.state.context.authenticator = StaticTokenAuthenticator({
            TOKEN: Principal(subject="foreign", grants=(Grant("admin"),)),
        })
    elif failure == "wider":
        params["subscription"] = "sub-foreign"
    elif failure == "expired":
        clock.advance(IDLE_TTL_SECONDS + 1)
    elif failure == "invalid":
        identifier = "malformed"
    else:
        identifier = "thr-" + "f" * 32
    response = client.get(f"/api/v1/copilot/threads/{identifier}/history", params=params, headers=_auth())
    assert response.status_code == 404, response.text
    assert response.json()["error"]["message"] == "Investigation thread not found"
    assert "retained question" not in response.text
    assert not documents.deleted
    executor.assert_not_called()


def test_history_requires_auth_and_current_read_grant(tmp_path, monkeypatch):
    client, _, _, thread, executor = _fixture(tmp_path, monkeypatch)
    path = f"/api/v1/copilot/threads/{thread.thread_id}/history"
    assert client.get(path, params=PARAMS).status_code == 401
    client.app.state.context.authenticator = StaticTokenAuthenticator({
        TOKEN: Principal(subject="operator@example.com", grants=(Grant("reader", Scope({"subscription": ["elsewhere"]})),)),
    })
    assert client.get(path, params=PARAMS, headers=_auth()).status_code == 403
    executor.assert_not_called()


def test_history_storage_failure_is_explicit_503(tmp_path, monkeypatch):
    client, documents, _, thread, executor = _fixture(tmp_path, monkeypatch)
    documents.fail_reads = True
    response = client.get(f"/api/v1/copilot/threads/{thread.thread_id}/history", params=PARAMS, headers=_auth())
    assert response.status_code == 503, response.text
    assert "data" not in response.json()
    executor.assert_not_called()
