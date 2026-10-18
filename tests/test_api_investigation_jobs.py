"""Async admission, stop, recovery and confirmed-ledger HTTP contracts."""
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_api_multi_agent import TOKEN, _auth, _client

import api.routers.multi_agent as routes
import operations.autonomous_investigation as investigation
from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.scope import SCOPE_DIMENSIONS, Scope
from operations.investigation_jobs import InvestigationJobStore
from operations.tools import ToolResult
from storage.onelake_documents import OneLakeDocumentStore

JOB = f"job-{'a' * 32}"
ROOT = "/api/v1/agents/investigation-jobs"
SCOPE = Scope.from_mapping({"subscription": ["sub-prod"]})
PAYLOAD = {"job_id": JOB, "objective": "Review network", "timeout_seconds": 30.0}


@pytest.fixture
def client(tmp_path, monkeypatch):
    value = _client(tmp_path)
    documents = OneLakeDocumentStore(tmp_path / "state")
    value.app.state.context.investigation_job_store = InvestigationJobStore(documents)
    monkeypatch.setattr(investigation, "_LEDGER_STORE", investigation.InvestigationLedgerStore(documents=documents))
    monkeypatch.setattr(routes, "canonical_orchestration_enabled", lambda **_: False)
    monkeypatch.setattr(routes, "_JOB_SLOTS", threading.BoundedSemaphore(2))
    return value


def test_admission_response_precedes_worker_and_completion_has_retained_ledger(client, monkeypatch):
    sent = []
    original_worker = routes._run_job

    def worker(*args):
        assert any(message["type"] == "http.response.body" for message in sent)
        original_worker(*args)

    monkeypatch.setattr(routes, "_run_job", worker)

    async def app(scope, receive, send):
        async def record(message):
            sent.append(message)
            await send(message)
        await client.app(scope, receive, record)

    response = TestClient(app).post(f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD)
    assert response.status_code == 202
    assert response.json()["data"]["status"] == "accepted_outcome_unconfirmed"
    assert response.json()["evidence"][0]["freshness"] == "unknown"
    job = client.get(f"{ROOT}/{JOB}?subscription=sub-prod", headers=_auth()).json()["data"]
    assert job["status"] == "completed", job
    retained = client.get(f"/api/v1/agents/investigations/{job['ledger_id']}?subscription=sub-prod", headers=_auth())
    assert retained.status_code == 200 and retained.json()["data"]["ledger_id"] == job["ledger_id"]
    investigation.ledger_store().ledgers.clear()
    assert client.get(f"/api/v1/agents/investigations/{job['ledger_id']}?subscription=sub-prod", headers=_auth()).status_code == 200
    retry = client.post(f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD)
    assert retry.status_code == 200 and retry.json()["data"] == job


def test_stop_waits_for_actual_provider_return_and_prevents_next_call_or_synthesis(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def tool(*args, **kwargs):
        calls.append(args[0])
        entered.set()
        assert release.wait(5)
        return ToolResult(status="ok", data={"fixture": "returned"})

    def no_synthesis(*args, **kwargs):
        pytest.fail("Stopped job must not synthesize")

    monkeypatch.setattr(investigation, "call_tool", tool)
    monkeypatch.setattr(investigation, "_synthesis", no_synthesis)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD)
        try:
            assert entered.wait(5)
            running = client.get(f"{ROOT}/{JOB}?subscription=sub-prod", headers=_auth()).json()["data"]
            assert running["status"] == "running" and len(calls) == 1
            stopped = client.post(f"{ROOT}/{JOB}/stop?subscription=sub-prod", headers=_auth()).json()["data"]
            assert stopped["stop_requested"] and stopped["status"] == "running"
            assert not future.done()  # No claim that the in-flight call was killed.
        finally:
            release.set()
        assert future.result(timeout=5).status_code == 202
    final = client.get(f"{ROOT}/{JOB}?subscription=sub-prod", headers=_auth()).json()["data"]
    assert final["status"] == "stopped" and not final["ledger_id"]
    assert len(calls) == 1 and not investigation.ledger_store().ledgers
    assert client.post(f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD).status_code == 200
    assert len(calls) == 1


def test_read_and_duplicate_admission_never_recover_by_replaying_an_abandoned_marker(client, monkeypatch):
    store = client.app.state.context.investigation_job_store
    store.accept("operator@example.com", JOB, SCOPE, objective=PAYLOAD["objective"], timeout_seconds=30.0)
    monkeypatch.setattr(routes, "_run_job", lambda *args: pytest.fail("No automatic dispatch"))
    before = store.read("operator@example.com", JOB, SCOPE)
    assert client.get(f"{ROOT}/{JOB}?subscription=sub-prod", headers=_auth()).json()["data"] == before
    retry = client.post(f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD)
    assert retry.status_code == 200 and retry.json()["data"] == before
    store.claim("operator@example.com", JOB, SCOPE, "c" * 32)
    assert client.post(f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD).json()["data"]["status"] == "running"


@pytest.mark.parametrize("dimension", SCOPE_DIMENSIONS)
def test_http_status_and_stop_cannot_cross_any_scope_dimension(client, dimension):
    exact = Scope.from_mapping({key: [f"{key}-a"] for key in SCOPE_DIMENSIONS})
    client.app.state.context.investigation_job_store.accept(
        "operator@example.com", JOB, exact, objective=PAYLOAD["objective"], timeout_seconds=30.0,
    )
    query = [(key, value) for key, values in exact.with_dimension(dimension, ["other"]).to_dict().items() for value in values]
    assert client.get(f"{ROOT}/{JOB}", params=query, headers=_auth()).status_code == 404
    assert client.post(f"{ROOT}/{JOB}/stop", params=query, headers=_auth()).status_code == 404


def test_foreign_principal_and_unauthenticated_requests_never_see_job(client):
    client.app.state.context.investigation_job_store.accept(
        "operator@example.com", JOB, SCOPE, objective=PAYLOAD["objective"], timeout_seconds=30.0,
    )
    client.app.state.context.authenticator = StaticTokenAuthenticator({
        TOKEN: Principal(subject="foreign", grants=(Grant("admin"),)),
    })
    assert client.get(f"{ROOT}/{JOB}?subscription=sub-prod", headers=_auth()).status_code == 404
    assert client.post(f"{ROOT}/{JOB}/stop?subscription=sub-prod", headers=_auth()).status_code == 404
    assert client.get(f"{ROOT}/{JOB}?subscription=sub-prod").status_code == 401
    assert client.post(ROOT, json=PAYLOAD).status_code == 401


@pytest.mark.parametrize("change", [
    {"job_id": "../escape"}, {"job_id": "job-short"}, {"objective": ""},
    {"timeout_seconds": 31.0}, {"timeout_seconds": "8"}, {"worker_id": "caller"},
    {"principal_subject": "other"}, {"scope": {"subscription": ["outside"]}},
])
def test_admission_rejects_invalid_or_caller_authority_fields(client, change):
    assert client.post(ROOT, headers=_auth(), json={**PAYLOAD, **change}).status_code == 400
    assert not list(Path(client.app.state.context.investigation_job_store.documents.root).glob("investigation-jobs/*.json"))


def test_capacity_and_missing_storage_never_admit_silent_fallback(client, monkeypatch):
    semaphore = threading.BoundedSemaphore(1)
    semaphore.acquire()
    monkeypatch.setattr(routes, "_JOB_SLOTS", semaphore)
    response = client.post(ROOT, headers=_auth(), json=PAYLOAD)
    assert response.status_code == 503
    assert not list(Path(investigation.ledger_store().documents.root).glob("investigation-jobs/*.json"))
    semaphore.release()
    client.app.state.context.investigation_job_store = None
    assert client.post(ROOT, headers=_auth(), json=PAYLOAD).status_code == 503


def test_ledger_write_failure_never_publishes_completed_or_caches_success(client, monkeypatch):
    documents = investigation.ledger_store().documents
    def fail(*args, **kwargs):
        raise OSError("Synthetic storage failure")
    monkeypatch.setattr(documents, "put", fail)
    assert client.post(f"{ROOT}?subscription=sub-prod", headers=_auth(), json=PAYLOAD).status_code == 202
    result = client.get(f"{ROOT}/{JOB}?subscription=sub-prod", headers=_auth()).json()["data"]
    assert result["status"] == "failed" and not result["ledger_id"]
    assert not investigation.ledger_store().ledgers


def test_unconfigured_durable_ledger_prevents_dispatch(client):
    investigation.ledger_store().documents = None
    assert client.post(ROOT, headers=_auth(), json=PAYLOAD).status_code == 503
