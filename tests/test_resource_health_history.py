from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.routers import resource_health
from api.scope import Scope
from api.telemetry import ApiTelemetry
from intelligence.health.service import ResourceHealthService
from onboarding.service import SubscriptionOnboardingService
from operations import resource_health_history as history
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

RID = "/subscriptions/sub-a/resourceGroups/Rg/providers/Microsoft.Compute/virtualMachines/Vm"
SCOPE = {"subscription": ["sub-a"]}
TOKEN = "health-history-local-reader"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _observation(cpu=12.5, *, cached=False):
    now = datetime.now(UTC).isoformat()
    return history.health_observation(
        {
            "resources": [
                {
                    "resource_id": RID,
                    "observed_at": "2020-01-01T00:00:00Z",
                    "status": "unknown" if cpu is None else "healthy",
                    "error": "",
                    "credential": "never-retained",
                    **{key: None for key in history.RetainedHealthMetrics.model_fields},
                    "cpu_percent": cpu,
                }
            ],
            "observed_at": "2020-01-01T00:00:01Z",
            "cached": cached,
            "cache_ttl_seconds": 120,
            "warnings": ["never-retained"],
            "unavailable_metrics": ["memory_percent"],
        },
        RID,
        now,
        now,
    )


def test_store_is_durable_exact_identity_and_keeps_nulls(tmp_path):
    store = history.ResourceHealthHistoryStore(OneLakeDocumentStore(tmp_path))
    first = store.append("reader", SCOPE, RID, 0, _observation(0))
    state = store.append(
        "reader", SCOPE, RID.swapcase(), 1, _observation(None, cached=True)
    )
    assert state["revision"] == 2
    assert first["observations"][0]["metrics"]["cpu_percent"] == 0
    assert state["observations"][-1]["metrics"]["cpu_percent"] is None
    assert state["observations"][-1]["cached"] is True
    assert len(state["observations"][-1]["metrics"]) == 8
    assert "never-retained" not in json.dumps(state)
    recovered = history.ResourceHealthHistoryStore(OneLakeDocumentStore(tmp_path))
    assert recovered.read("reader", SCOPE, RID) == state
    for actor, scope, resource in [
        ("other", SCOPE, RID),
        ("reader", {}, RID),
        ("reader", SCOPE, RID + "-other"),
    ]:
        assert recovered.read(actor, scope, resource)["revision"] == 0
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, RID, 1, _observation())
    assert recovered.read("reader", SCOPE, RID) == state


def test_retention_has_exact_receipt_extent_and_byte_limit(tmp_path, monkeypatch):
    store = history.ResourceHealthHistoryStore(OneLakeDocumentStore(tmp_path))
    captured = []
    for revision in range(33):
        observation = _observation()
        captured.append(observation.observation_id)
        state = store.append("reader", SCOPE, RID, revision, observation)
    assert state["revision"] == 33
    assert len(state["observations"]) == 30
    assert [row["observation_id"] for row in state["observations"]] == captured[-30:]
    assert store._bytes(state) <= 256 * 1024
    bounded = history.ResourceHealthHistoryStore(
        OneLakeDocumentStore(tmp_path / "bounded")
    )
    initial = bounded.append("reader", SCOPE, RID, 0, _observation())
    with monkeypatch.context() as patch:
        patch.setattr(history, "MAX_HISTORY_BYTES", bounded._bytes(initial))
        with pytest.raises(ValueError, match="256 KiB"):
            bounded.append("reader", SCOPE, RID, 1, _observation())
    assert bounded.read("reader", SCOPE, RID) == initial
    assert store.read("reader", SCOPE, RID) == state


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "95"])
def test_metrics_reject_nonfinite_negative_or_untyped_values(bad):
    with pytest.raises(ValidationError):
        _observation(bad)


@pytest.mark.parametrize(
    "corruption",
    [
        "actor",
        "resource",
        "revision",
        "duplicate",
        "metric",
        "time",
        "version",
        "boolean-version",
        "metric-count",
    ],
)
def test_corrupt_state_is_not_an_empty_history(tmp_path, corruption):
    store = history.ResourceHealthHistoryStore(OneLakeDocumentStore(tmp_path))
    state = store.append("reader", SCOPE, RID, 0, _observation())
    if corruption == "actor":
        state["actor"] = "other"
    elif corruption == "resource":
        state["resource_id"] = RID + "-other"
    elif corruption == "revision":
        state["revision"] = 2
    elif corruption == "duplicate":
        state["observations"] *= 2
        state["revision"] = 2
    elif corruption == "metric":
        state["observations"][0]["metrics"]["cpu_percent"] = True
    elif corruption == "version":
        del state["schema_version"]
    elif corruption == "boolean-version":
        state["schema_version"] = True
    elif corruption == "metric-count":
        state["observations"][0]["warning_count"] = 9_007_199_254_740_992
    else:
        state["observations"][0]["resource_observed_at"] = "2020-01-01"
    (tmp_path / store._name("reader", SCOPE, RID)).write_text(json.dumps(state))
    with pytest.raises(RuntimeError):
        store.read("reader", SCOPE, RID)


def test_concurrent_captures_have_one_cas_winner(tmp_path, monkeypatch):
    documents = OneLakeDocumentStore(tmp_path)
    store = history.ResourceHealthHistoryStore(documents)
    store.append("reader", SCOPE, RID, 0, _observation())
    read = documents.read_snapshot
    barrier = Barrier(2)

    def synchronized_read(name):
        snapshot = read(name)
        barrier.wait(timeout=5)
        return snapshot

    def append():
        try:
            store.append("reader", SCOPE, RID, 1, _observation())
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with monkeypatch.context() as patch:
        patch.setattr(documents, "read_snapshot", synchronized_read)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: append(), range(2)))
    assert sorted(results) == ["conflict", "saved"]
    assert store.read("reader", SCOPE, RID)["revision"] == 2


@pytest.fixture
def api(tmp_path, monkeypatch):
    resource_health._resource_health_detail_cache.clear()
    inventory_calls, metric_calls, provider_calls = [], [], []
    state = {"error": False, "authorized": True, "cpu": 12.5}
    connection = SimpleNamespace(
        connection_id="conn",
        tenant_id="tenant",
        subscription_id="sub-a",
        is_active=True,
        credential=SimpleNamespace(
            credential_id="credential",
            kind="service_principal",
            tenant_id="tenant",
            client_id="client",
            secret_ref="not-a-live-reference",
        ),
    )

    class Inventory:
        def get_resource(self, scope, resource_id):
            inventory_calls.append(resource_id)
            if (
                not state["authorized"]
                or resource_id.casefold() != RID.casefold()
                or not scope.matches(
                    {
                        "subscription": "sub-a",
                        "business_service": "Payments",
                        "owner": "Platform",
                        "region": "eastus",
                    }
                )
            ):
                return None
            return {
                "resource_id": RID,
                "resource_type": "microsoft.compute/virtualmachines",
                "subscription_id": "sub-a",
                "resource_group": "Rg",
                "resource_name": "Vm",
            }

    class Metrics:
        def query_resource_metrics(self, resource_id):
            metric_calls.append(resource_id)
            if state["error"]:
                raise RuntimeError("private-credential-error-never-retain")
            return (
                {}
                if state["cpu"] is None
                else {"Percentage CPU": {"value": state["cpu"]}}
            )

    def provider(subscriptions):
        provider_calls.append(subscriptions)
        return ResourceHealthService(
            connections=lambda: [connection],
            metrics_client_factory=lambda _: Metrics(),
            resource_lister=lambda _: pytest.fail(
                "History must not bulk-list resources"
            ),
        )

    onboarding = SubscriptionOnboardingService(tmp_path / "onboarding")
    monkeypatch.setattr(onboarding.registry, "list", lambda **_: [connection])
    store = history.ResourceHealthHistoryStore(
        OneLakeDocumentStore(tmp_path / "durable")
    )
    principals = {
        token: Principal(
            subject=subject, grants=(Grant("reader", Scope.from_mapping(scope)),)
        )
        for token, subject, scope in [
            (TOKEN, "reader", SCOPE),
            ("other-local-reader", "other", SCOPE),
            ("outside-local-reader", "outside", {"subscription": ["sub-b"]}),
        ]
    }
    context = ApiContext(
        onboarding=onboarding,
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        inventory_read_port_provider=lambda: Inventory(),
        hybrid_resource_health_provider=provider,
        resource_health_history_store=store,
    )
    client = TestClient(create_app(context), raise_server_exceptions=False)
    yield SimpleNamespace(
        client=client,
        context=context,
        state=state,
        store=store,
        inventory_calls=inventory_calls,
        metric_calls=metric_calls,
        provider_calls=provider_calls,
        path="/api/v1/resource-health/resource/history",
        params={"resource_id": RID, "subscription": "sub-a"},
    )
    client.close()
    resource_health._resource_health_detail_cache.clear()


def test_authorized_capture_uses_only_one_resource_and_recovers_without_monitor(api):
    result = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
    )
    assert result.status_code == 201, result.text
    saved = result.json()["data"]
    assert saved["revision"] == 1
    assert api.metric_calls == [RID]
    assert api.provider_calls == [["sub-a"]]
    api.context.hybrid_resource_health_provider = None
    resource_health._resource_health_detail_cache.clear()
    assert (
        api.client.get(api.path, params=api.params, headers=AUTH).json()["data"]
        == saved
    )
    assert api.metric_calls == [RID]
    other = {"Authorization": "Bearer other-local-reader"}
    assert (
        api.client.get(api.path, params=api.params, headers=other).json()["data"][
            "revision"
        ]
        == 0
    )
    assert (
        api.client.post(
            api.path, params=api.params, headers=AUTH, json={"expected_revision": 1}
        ).status_code
        == 503
    )
    assert api.store.read("reader", SCOPE, RID) == saved


def test_scope_and_current_membership_gate_store_and_provider_access(api, monkeypatch):
    def forbidden(*args):
        pytest.fail("Unauthorized history must not access the store")

    monkeypatch.setattr(api.store, "read", forbidden)
    for method in ("get", "post"):
        request = getattr(api.client, method)
        kwargs = {"json": {"expected_revision": 0}} if method == "post" else {}
        assert request(api.path, params=api.params, **kwargs).status_code == 401
        outside = {"Authorization": "Bearer outside-local-reader"}
        assert (
            request(api.path, params=api.params, headers=outside, **kwargs).status_code
            == 403
        )
        assert (
            request(
                api.path,
                params={**api.params, "owner": "outside"},
                headers=AUTH,
                **kwargs,
            ).status_code
            == 404
        )
        api.state["authorized"] = False
        assert (
            request(api.path, params=api.params, headers=AUTH, **kwargs).status_code
            == 404
        )
        api.state["authorized"] = True
    assert api.provider_calls == []
    assert api.metric_calls == []


def test_conflict_and_submitted_metrics_never_acquire_new_source_data(api):
    assert (
        api.client.post(
            api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
        ).status_code
        == 201
    )
    assert (
        api.client.post(
            api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
        ).status_code
        == 409
    )
    assert (
        api.client.post(
            api.path,
            params=api.params,
            headers=AUTH,
            json={"expected_revision": 1, "cpu_percent": 0},
        ).status_code
        == 400
    )
    assert api.metric_calls == [RID]


def test_cached_receipts_are_explicit_and_failed_collections_never_persist(api):
    first = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
    ).json()["data"]
    second = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 1}
    ).json()["data"]
    assert second["observations"][-1]["cached"] is True
    assert (
        second["observations"][-1]["resource_observed_at"]
        == first["observations"][-1]["resource_observed_at"]
    )
    assert api.metric_calls == [RID]
    resource_health._resource_health_detail_cache.clear()
    api.state["error"] = True
    failed = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 2}
    )
    assert failed.status_code == 503, failed.text
    assert "private-credential-error" not in failed.text
    assert api.store.read("reader", SCOPE, RID) == second


def test_runtime_factory_reuses_existing_document_root(tmp_path, monkeypatch):
    from api import runtime

    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    store = runtime._resource_health_history_store()
    state = store.append("reader", SCOPE, RID, 0, _observation())
    assert runtime._resource_health_history_store().read("reader", SCOPE, RID) == state


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "empty",
        "multiple",
        "error",
        "nonfinite",
        "time",
        "warnings",
        "status",
        "missing-metric",
        "missing-cpu",
        "unknown-cpu",
    ],
)
def test_invalid_provider_collections_never_advance_revision(api, monkeypatch, fault):
    source = api.client.get(
        "/api/v1/resource-health/resource", params=api.params, headers=AUTH
    ).json()["data"]
    row = source["resources"][0]
    if fault == "identity":
        row["resource_id"] = RID + "-other"
    elif fault == "empty":
        source["resources"] = []
    elif fault == "multiple":
        source["resources"] *= 2
    elif fault == "error":
        row["error"] = None
    elif fault == "nonfinite":
        row["cpu_percent"] = float("inf")
    elif fault == "time":
        row["observed_at"] = "2020-01-01"
    elif fault == "warnings":
        source["warnings"] = "not a declaration list"
    elif fault == "status":
        row["status"] = "unreported-provider-state"
    elif fault == "missing-cpu":
        row["cpu_percent"] = None
    elif fault == "unknown-cpu":
        row["status"] = "unknown"
    else:
        del row["network_in_bytes"]
    monkeypatch.setattr(
        resource_health,
        "resource_health_resource",
        lambda *args, **kwargs: {"data": source},
    )
    result = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
    )
    assert result.status_code == 503, result.text
    assert api.store.read("reader", SCOPE, RID)["revision"] == 0


def test_membership_revoked_during_collection_prevents_retention(api, monkeypatch):
    acquire = resource_health.resource_health_resource

    def revoked_after_acquisition(*args, **kwargs):
        result = acquire(*args, **kwargs)
        api.state["authorized"] = False
        return result

    monkeypatch.setattr(
        resource_health, "resource_health_resource", revoked_after_acquisition
    )
    result = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
    )
    assert result.status_code == 404, result.text
    assert api.store.read("reader", SCOPE, RID)["revision"] == 0


def test_successful_collection_without_cpu_is_explicitly_unknown_not_healthy(api):
    api.state["cpu"] = None
    result = api.client.post(
        api.path, params=api.params, headers=AUTH, json={"expected_revision": 0}
    )
    assert result.status_code == 201, result.text
    observation = result.json()["data"]["observations"][0]
    assert observation["classification"] == "unknown"
    assert observation["metrics"]["cpu_percent"] is None
    assert all(value is None for value in observation["metrics"].values())
