"""Durable declarations and explicit scoped configuration regression receipts."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from network_scenario import PROD_SUBNET, UAT_SUBNET, network_rows
from pydantic import ValidationError

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network import intents
from network.service import NetworkIntelligenceService
from onboarding.service import SubscriptionOnboardingService
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

TOKEN = "network-intents-reader-fixture"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SCOPE = {"subscription": ["sub-prod"]}
TEST = {
    "test_id": "prod-to-uat",
    "name": "Prod must not reach UAT",
    "source": PROD_SUBNET,
    "destination": UAT_SUBNET,
    "port": 443,
    "protocol": "Tcp",
    "expected_verdict": "denied",
}


def _run(revision: int, tests=None):
    now = datetime.now(UTC).isoformat()
    return intents.IntentRun(
        run_id=str(uuid4()),
        reviewed_revision=revision,
        started_at=now,
        finished_at=now,
        source_observed_at="",
        results=[
            intents.IntentResult(
                test=test,
                verdict="denied",
                unknown_count=0,
                missing_enforcement_count=0,
                outcome="match" if test.expected_verdict == "denied" else "mismatch",
            )
            for test in (tests or [intents.IntentTest.model_validate(TEST)])
        ],
    )


def test_store_survives_restart_and_is_exact_actor_and_scope(tmp_path):
    store = intents.NetworkIntentStore(OneLakeDocumentStore(tmp_path))
    state = store.update(
        "reader", SCOPE, 0, tests=[intents.IntentTest.model_validate(TEST)]
    )
    run = _run(1)
    state = store.update("reader", SCOPE, 1, run=run)
    recovered = intents.NetworkIntentStore(OneLakeDocumentStore(tmp_path))
    assert recovered.read("reader", SCOPE) == state
    for actor, scope in [
        ("different", SCOPE),
        ("reader", {}),
        ("reader", {**SCOPE, "region": ["eastus"]}),
    ]:
        assert recovered.read(actor, scope)["revision"] == 0
    removed = store.update("reader", SCOPE, 2, tests=[])
    assert removed["tests"] == []
    assert removed["runs"][0]["results"][0]["test"] == TEST
    with pytest.raises(DocumentConflictError):
        store.update("reader", SCOPE, 2, tests=[])
    assert store.read("reader", SCOPE) == removed
    assert len(state["runs"][0]["results"][0]) == 5


def test_latest_ten_receipts_are_bounded_and_do_not_rewrite_definitions(tmp_path):
    store = intents.NetworkIntentStore(OneLakeDocumentStore(tmp_path))
    tests = [
        intents.IntentTest.model_validate({**TEST, "test_id": f"test-{index}"})
        for index in range(20)
    ]
    store.update("reader", SCOPE, 0, tests=tests)
    ids = []
    for revision in range(1, 14):
        run = _run(revision, tests)
        ids.append(run.run_id)
        state = store.update("reader", SCOPE, revision, run=run)
    assert state["revision"] == 14
    assert [row["run_id"] for row in state["runs"]] == ids[-10:]
    assert intents.NetworkIntentStore._bytes(state) < intents.MAX_BYTES
    with pytest.raises(ValueError):
        store.update("reader", SCOPE, 14, run=_run(14))
    assert store.read("reader", SCOPE) == state


def test_document_limit_and_corruption_never_become_empty_or_success(
    tmp_path, monkeypatch
):
    documents = OneLakeDocumentStore(tmp_path)
    store = intents.NetworkIntentStore(documents)
    tests = [intents.IntentTest.model_validate(TEST)]
    original = store.update("reader", SCOPE, 0, tests=tests)
    monkeypatch.setattr(intents, "MAX_BYTES", store._bytes(original) + 5)
    with pytest.raises(ValueError, match="512 KiB"):
        store.update("reader", SCOPE, 1, run=_run(1))
    assert store.read("reader", SCOPE) == original
    monkeypatch.setattr(intents, "MAX_BYTES", 1)
    with pytest.raises(RuntimeError, match="document limit"):
        store.read("reader", SCOPE)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.update(actor="other"),
        lambda s: s.update(schema_version=True),
        lambda s: s.pop("schema_version"),
        lambda s: s.update(revision=0),
        lambda s: s.update(tests=[TEST, TEST]),
        lambda s: s["runs"][0]["results"][0].update(outcome="mismatch"),
        lambda s: s["runs"][0].update(started_at="2020-01-01T00:00:00"),
        lambda s: s["runs"][0].update(reviewed_revision=2),
    ],
)
def test_corrupt_stored_state_fails_closed(tmp_path, mutation):
    documents = OneLakeDocumentStore(tmp_path)
    store = intents.NetworkIntentStore(documents)
    store.update("reader", SCOPE, 0, tests=[intents.IntentTest.model_validate(TEST)])
    state = store.update("reader", SCOPE, 1, run=_run(1))
    mutation(state)
    documents.write(store._name("reader", SCOPE), state, expected_revision=2)
    with pytest.raises(RuntimeError):
        store.read("reader", SCOPE)


def test_concurrent_append_is_atomic(tmp_path, monkeypatch):
    store = intents.NetworkIntentStore(OneLakeDocumentStore(tmp_path))
    store.update("reader", SCOPE, 0, tests=[intents.IntentTest.model_validate(TEST)])
    read = store._read
    barrier = Barrier(2)

    def synchronized(*args):
        result = read(*args)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(store, "_read", synchronized)

    def append():
        try:
            store.update("reader", SCOPE, 1, run=_run(1))
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: append(), range(2))) == ["conflict", "saved"]
    monkeypatch.setattr(store, "_read", read)
    assert store.read("reader", SCOPE)["revision"] == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"port": True},
        {"port": 0},
        {"port": 65536},
        {"port": "443"},
        {"source": "  "},
        {"destination": "x" * 513},
        {"name": ""},
        {"protocol": "Any"},
        {"expected_verdict": "indeterminate"},
        {"test_id": "Bad ID"},
        {"results": []},
    ],
)
def test_strict_declared_test_contract(changes):
    with pytest.raises(ValidationError):
        intents.IntentTest.model_validate({**TEST, **changes})


def _client(tmp_path, *, available=True, scoped=False):
    store = intents.NetworkIntentStore(OneLakeDocumentStore(tmp_path / "documents"))
    calls = []
    service = NetworkIntelligenceService.from_rows(network_rows())

    def provider():
        calls.append("network")
        return service if available else None

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {
                TOKEN: Principal(
                    subject="reader",
                    grants=(
                        Grant(
                            "reader", Scope.from_mapping(SCOPE) if scoped else Scope()
                        ),
                    ),
                ),
                TOKEN + "-other": Principal(subject="other", grants=(Grant("reader"),)),
            }
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        network_intent_store=store,
        network_provider=provider,
    )
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        store,
        calls,
        service,
    )


def _save(client, *, revision=0, tests=None, query=None):
    return client.put(
        "/api/v1/network/intents",
        headers=AUTH,
        params=query,
        json={
            "expected_revision": revision,
            "tests": [TEST] if tests is None else tests,
        },
    )


def test_http_reader_can_save_reload_run_and_remove_without_operate_authority(tmp_path):
    client, store, calls, _ = _client(tmp_path)
    response = _save(client)
    assert response.status_code == 200, response.text
    assert calls == []
    assert (
        client.get("/api/v1/network/intents", headers=AUTH).json()["data"]["revision"]
        == 1
    )
    assert calls == []
    response = client.post(
        "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert len(data["runs"][0]["results"]) == 1
    assert data["runs"][0]["results"][0]["test"] == TEST
    assert data["runs"][0]["source_observed_at"] == "2024-06-01T00:00:00Z"
    assert len(calls) == 1
    assert _save(client, revision=2, tests=[]).status_code == 200
    assert store.read("reader", {})["tests"] == []
    assert len(store.read("reader", {})["runs"]) == 1
    assert "not packet probes" in " ".join(response.json()["warnings"])


def test_http_exact_actor_scope_repeated_dimensions_and_no_source_on_read_or_save(
    tmp_path,
):
    client, store, calls, _ = _client(tmp_path)
    query = [
        ("subscription", "sub-prod"),
        ("subscription", "sub-uat"),
        ("business_service", "payments"),
        ("application", "portal"),
        ("environment", "prod"),
        ("subscription_connection", "conn-prod"),
        ("owner", "owner"),
        ("support_team", "platform"),
        ("region", "eastus"),
        ("criticality", "high"),
    ]
    response = _save(client, query=query)
    assert response.status_code == 200, response.text
    scope = response.json()["data"]["scope"]
    assert scope["subscription"] == ["sub-prod", "sub-uat"]
    assert len(scope) == 9
    assert store.read("reader", scope)["revision"] == 1
    assert (
        client.get("/api/v1/network/intents", headers=AUTH).json()["data"]["revision"]
        == 0
    )
    other = client.get(
        "/api/v1/network/intents",
        headers={"Authorization": f"Bearer {TOKEN}-other"},
        params=query,
    )
    assert other.json()["data"]["revision"] == 0
    assert calls == []


def test_empty_or_stale_revision_cannot_acquire_provider(tmp_path):
    client, store, calls, _ = _client(tmp_path)
    assert (
        client.post(
            "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 0}
        ).status_code
        == 400
    )
    assert _save(client).status_code == 200
    assert (
        client.post(
            "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 0}
        ).status_code
        == 409
    )
    assert _save(client).status_code == 409
    assert calls == []
    assert store.read("reader", {})["revision"] == 1


def test_unavailable_provider_does_not_advance_saved_suite(tmp_path):
    client, store, _, _ = _client(tmp_path, available=False)
    assert _save(client).status_code == 200
    response = client.post(
        "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 503, response.text
    assert store.read("reader", {})["revision"] == 1


def test_granted_scope_withholds_foreign_endpoint_in_saved_run(tmp_path):
    client, _, _, _ = _client(tmp_path, scoped=True)
    assert _save(client).status_code == 200
    response = client.post(
        "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 201, response.text
    result = response.json()["data"]["runs"][0]["results"][0]
    assert result["outcome"] == "indeterminate"
    assert result["verdict"] == "indeterminate"
    assert result["unknown_count"] > 0
    assert "rule_id" not in json.dumps(result)


@pytest.mark.parametrize(
    ("verdict", "unknowns", "missing", "outcome"),
    [
        ("denied", (), (), "match"),
        ("allowed", (), (), "mismatch"),
        ("indeterminate", (), (), "indeterminate"),
        ("denied", ("incomplete",), (), "indeterminate"),
        ("denied", (), ("missing-control",), "indeterminate"),
    ],
)
def test_exact_outcomes_do_not_upgrade_unknown_evidence(
    tmp_path,
    monkeypatch,
    verdict,
    unknowns,
    missing,
    outcome,
):
    client, _, _, service = _client(tmp_path)
    original = service.validate_flows

    def validate(self, queries):
        del self
        return tuple(
            replace(
                row,
                verdict=verdict,
                unknowns=unknowns,
                missing_enforcement_points=missing,
            )
            for row in original(queries)
        )

    monkeypatch.setattr(NetworkIntelligenceService, "validate_flows", validate)
    _save(client)
    response = client.post(
        "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 201, response.text
    result = response.json()["data"]["runs"][0]["results"][0]
    assert result["outcome"] == outcome
    assert result["unknown_count"] == len(unknowns)
    assert "incomplete" not in json.dumps(result)
    assert "missing-control" not in json.dumps(result)


@pytest.mark.parametrize(
    "bad", ["cardinality", "query", "verdict", "future-time", "unresolved"]
)
def test_invalid_provider_result_is_not_retained(tmp_path, monkeypatch, bad):
    client, store, _, service = _client(tmp_path)
    original = service.validate_flows

    def validate(self, queries):
        rows = original(queries)
        if bad == "cardinality":
            return ()
        if bad == "query":
            return (replace(rows[0], query=replace(rows[0].query, port=123)),)
        if bad == "verdict":
            return (replace(rows[0], verdict="probably"),)
        if bad == "unresolved":
            return (
                replace(
                    rows[0],
                    verdict="allowed",
                    source_endpoint=replace(rows[0].source_endpoint, resolved=False),
                ),
            )
        self.snapshot = replace(self.snapshot, observed_at="2099-01-01T00:00:00Z")
        return rows

    monkeypatch.setattr(NetworkIntelligenceService, "validate_flows", validate)
    _save(client)
    response = client.post(
        "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 503, response.text
    assert store.read("reader", {})["revision"] == 1


def test_provider_race_cannot_overwrite_concurrent_declarations(tmp_path, monkeypatch):
    client, store, _, service = _client(tmp_path)
    original = service.validate_flows

    def validate(self, queries):
        del self
        store.update("reader", {}, 1, tests=[])
        return original(queries)

    monkeypatch.setattr(NetworkIntelligenceService, "validate_flows", validate)
    _save(client)
    response = client.post(
        "/api/v1/network/intents/run", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 409, response.text
    assert store.read("reader", {})["tests"] == []
    assert store.read("reader", {})["runs"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_revision": True, "tests": []},
        {"expected_revision": 0, "tests": [TEST, TEST]},
        {
            "expected_revision": 0,
            "tests": [{**TEST, "test_id": f"test-{index}"} for index in range(21)],
        },
        {"expected_revision": 0, "tests": [TEST], "verdict": "allowed"},
    ],
)
def test_http_rejects_invalid_declarations(tmp_path, payload):
    client, store, calls, _ = _client(tmp_path)
    response = client.put("/api/v1/network/intents", headers=AUTH, json=payload)
    assert response.status_code == 400, response.text
    assert calls == []
    assert store.read("reader", {})["revision"] == 0


def test_runtime_uses_existing_document_root(tmp_path, monkeypatch):
    from api import runtime

    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    store = runtime._network_intent_store()
    store.update("reader", {}, 0, tests=[intents.IntentTest.model_validate(TEST)])
    assert runtime._network_intent_store().read("reader", {})["revision"] == 1


def test_run_body_cannot_override_saved_declarations_or_supply_results(tmp_path):
    client, store, calls, _ = _client(tmp_path)
    _save(client)
    response = client.post(
        "/api/v1/network/intents/run",
        headers=AUTH,
        json={"expected_revision": 1, "tests": [], "results": [{"outcome": "match"}]},
    )
    assert response.status_code == 400
    assert store.read("reader", {})["revision"] == 1
    assert calls == []


def test_unauthenticated_reads_and_writes_are_rejected(tmp_path):
    client, store, calls, _ = _client(tmp_path)
    assert client.get("/api/v1/network/intents").status_code == 401
    assert (
        client.put(
            "/api/v1/network/intents", json={"expected_revision": 0, "tests": []}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/network/intents/run", json={"expected_revision": 0}
        ).status_code
        == 401
    )
    assert store.read("reader", {})["revision"] == 0
    assert calls == []
