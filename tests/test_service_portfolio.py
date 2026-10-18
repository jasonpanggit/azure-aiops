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
from operations.service_portfolio import (
    PortfolioSource,
    ServicePortfolioStore,
    build_portfolio,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

TOKEN = "service-portfolio-reader-token"
OTHER = "service-portfolio-other-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SCOPE = {"subscription": ["sub-a"]}
CONNECTIONS = [
    {
        "business_service": "Payments",
        "subscription_id": "sub-a",
        "owner": "SRE",
        "support_team": "Ops",
        "environment": "prod",
        "credential": {"secret_ref": "must-not-be-retained"},
    },
    {
        "business_service": "Payments",
        "subscription_id": "sub-a",
        "owner": "",
        "support_team": "Ops",
        "environment": "prod",
    },
    {"business_service": "", "subscription_id": "sub-a", "is_active": False},
]
INCIDENTS = [
    {
        "incident": {"severity": "sev1"},
        "blast_radius": {
            "business_services": ["Payments", "Payments", "Unmapped service"]
        },
    },
    {"incident": {"severity": "low"}, "blast_radius": {"business_services": []}},
]


def sources():
    return [
        PortfolioSource(
            id=source_id,
            started_at="2026-10-15T00:00:00Z",
            finished_at="2026-10-15T00:00:01Z",
            observed_at=[],
            source_tables=["fixture"],
            knowledge_version="v1",
            reported_freshness=["unknown"],
            loaded=3 if source_id == "connections" else 2,
            total=3 if source_id == "connections" else 200,
            partial=source_id == "incidents",
            warning_count=0,
        )
        for source_id in ("connections", "incidents")
    ]


def append(store, revision=0, actor="reader", scope=None):
    return store.append(
        actor,
        SCOPE if scope is None else scope,
        revision,
        services=build_portfolio(CONNECTIONS, INCIDENTS),
        sources=sources(),
    )


def test_build_actual_mapping_and_distinct_per_row_associations():
    rows = build_portfolio(CONNECTIONS, INCIDENTS)
    payments = next(row for row in rows if row.name == "Payments")
    assert payments.connection_rows == 2
    assert payments.mapped_rows == 1
    assert payments.missing_owner == 1
    assert payments.subscription_count == 1
    assert payments.incident_associations == payments.critical_associations == 1
    unmapped = next(row for row in rows if row.kind == "unmapped")
    assert (
        unmapped.connection_rows
        == unmapped.missing_support_team
        == unmapped.incident_associations
        == 1
    )
    named = next(row for row in rows if row.name == "Unmapped service")
    assert named.service_key != unmapped.service_key
    assert named.connection_rows == 0


def test_exact_identity_scope_recovery_and_allowlisted_payload(tmp_path):
    store = ServicePortfolioStore(OneLakeDocumentStore(tmp_path))
    assert store.read("reader", SCOPE)["revision"] == 0
    state = append(store)
    assert (
        ServicePortfolioStore(OneLakeDocumentStore(tmp_path)).read("reader", SCOPE)
        == state
    )
    assert store.read("other", SCOPE)["observations"] == []
    assert store.read("reader", {})["observations"] == []
    assert store.read("reader", {"subscription": ["sub-b"]})["observations"] == []
    encoded = json.dumps(state)
    assert "secret_ref" not in encoded and "must-not-be-retained" not in encoded
    assert "SRE" not in encoded and "Ops" not in encoded


def test_latest_twenty_eviction_and_stale_revision(tmp_path):
    store = ServicePortfolioStore(OneLakeDocumentStore(tmp_path))
    first = append(store)["observations"][0]["observation_id"]
    for revision in range(1, 21):
        state = append(store, revision)
    assert len(state["observations"]) == 20
    assert state["revision"] == 21
    assert first not in [row["observation_id"] for row in state["observations"]]
    with pytest.raises(DocumentConflictError):
        append(store, 20)
    assert store.read("reader", SCOPE) == state


def test_concurrent_create_and_append_have_no_lost_updates(tmp_path):
    store = ServicePortfolioStore(OneLakeDocumentStore(tmp_path))
    for revision in (0, 1):
        barrier = Barrier(2)

        def capture(barrier=barrier, revision=revision):
            barrier.wait()
            try:
                return append(store, revision)["revision"]
            except DocumentConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: capture(), range(2)))
        assert results.count("conflict") == results.count(revision + 1) == 1


def test_service_and_complete_serialized_byte_bounds_are_inclusive(
    tmp_path, monkeypatch
):
    from operations import service_portfolio

    rows = [{"business_service": f"Service {i}"} for i in range(250)]
    assert len(build_portfolio(rows, [])) == 250
    with pytest.raises(ValueError, match="250"):
        build_portfolio([*rows, {"business_service": "251st"}], [])
    assert (
        build_portfolio([{"business_service": "Same"}] * 10_000, [])[0].connection_rows
        == 10_000
    )
    with pytest.raises(ValueError, match="bound"):
        build_portfolio([{"business_service": "Same"}] * 10_001, [])
    with pytest.raises(ValueError, match="bound"):
        build_portfolio([], INCIDENTS * 51)
    store = ServicePortfolioStore(OneLakeDocumentStore(tmp_path))
    state = append(store)
    exact = len((json.dumps(state, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(service_portfolio, "MAX_HISTORY_BYTES", exact)
    assert store.read("reader", SCOPE) == state
    with pytest.raises(ValueError, match="document limit"):
        append(store, 1)
    assert store.read("reader", SCOPE) == state
    monkeypatch.setattr(service_portfolio, "MAX_HISTORY_BYTES", exact - 1)
    with pytest.raises(RuntimeError, match="invalid"):
        store.read("reader", SCOPE)


@pytest.mark.parametrize(
    "damage",
    [
        "identity",
        "schema",
        "duplicate",
        "source",
        "timestamp",
        "revision",
        "count",
        "key",
        "extent",
        "source-time",
        "receipt",
    ],
)
def test_corrupt_state_fails_closed(tmp_path, damage):
    store = ServicePortfolioStore(OneLakeDocumentStore(tmp_path))
    payload = append(store)
    observation = payload["observations"][0]
    if damage == "identity":
        payload["actor"] = "other"
    elif damage == "schema":
        observation["services"][0]["connection_rows"] = "2"
    elif damage == "duplicate":
        payload["observations"] *= 2
        payload["revision"] = 2
    elif damage == "source":
        observation["sources"][1] = observation["sources"][0]
    elif damage == "timestamp":
        observation["captured_at"] = "2026-10-16T00:00:00"
    elif damage == "revision":
        payload["revision"] = 19
    elif damage == "count":
        observation["services"][0]["mapped_rows"] = 999
    elif damage == "key":
        observation["services"][0]["service_key"] = "0" * 64
    elif damage == "source-time":
        observation["sources"][0]["finished_at"] = "2026-10-14T00:00:00Z"
    elif damage == "receipt":
        observation["captured_at"] = "2026-10-14T00:00:00Z"
    else:
        observation["sources"][0]["total"] = 999
    (tmp_path / store._name("reader", SCOPE)).write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="Stored service portfolio"):
        store.read("reader", SCOPE)


def client_fixture(tmp_path, monkeypatch):
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
        service_portfolio_store=ServicePortfolioStore(
            OneLakeDocumentStore(tmp_path / "history")
        ),
    )
    from api.routers import service_portfolio

    calls = []

    def connections(context, scope, page, include_disabled):
        calls.append(("connections", scope.to_dict(), page.limit, include_disabled))
        return {"data": CONNECTIONS, "pagination": {"total": len(CONNECTIONS)}}

    def incidents(context, scope, page):
        calls.append(("incidents", scope.to_dict(), page.limit))
        return {"data": {"incidents": INCIDENTS}, "pagination": {"total": 200}}

    monkeypatch.setattr(service_portfolio, "list_connections", connections)
    monkeypatch.setattr(service_portfolio, "list_incidents", incidents)
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        context,
        calls,
    )


def test_routes_server_owned_capture_recovery_auth_scope_and_conflict(
    tmp_path, monkeypatch
):
    client, context, calls = client_fixture(tmp_path, monkeypatch)
    path = "/api/v1/service-portfolio/history"
    response = client.post(path, headers=AUTH, json={"expected_revision": 0})
    assert response.status_code == 201, response.text
    state = response.json()["data"]
    assert state["scope"] == SCOPE and state["revision"] == 1
    assert calls == [("connections", SCOPE, 10_000, True), ("incidents", SCOPE, 100)]
    assert state["observations"][0]["sources"][1]["partial"] is True
    calls.clear()
    assert client.get(path, headers=AUTH).json()["data"] == state
    assert calls == []
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"Authorization": f"Bearer {OTHER}"}).json()["data"][
            "revision"
        ]
        == 0
    )
    assert client.get(path + "?subscription=sub-b", headers=AUTH).status_code == 403
    assert (
        client.post(path, headers=AUTH, json={"expected_revision": 0}).status_code
        == 409
    )
    assert (
        client.post(
            path, headers=AUTH, json={"expected_revision": 1, "services": []}
        ).status_code
        == 400
    )
    assert calls == []
    context.service_portfolio_store = None
    assert client.get(path, headers=AUTH).status_code == 503


def test_acquisition_failure_and_incomplete_registry_leave_history_unchanged(
    tmp_path, monkeypatch
):
    from api.routers import service_portfolio

    client, _, _ = client_fixture(tmp_path, monkeypatch)
    path = "/api/v1/service-portfolio/history"
    state = client.post(path, headers=AUTH, json={"expected_revision": 0}).json()[
        "data"
    ]

    def fail(*args, **kwargs):
        raise ApiError(ErrorCode.PROVIDER_UNAVAILABLE, "Incident source unavailable")

    monkeypatch.setattr(service_portfolio, "list_incidents", fail)
    assert (
        client.post(path, headers=AUTH, json={"expected_revision": 1}).status_code
        == 503
    )
    assert client.get(path, headers=AUTH).json()["data"] == state
    monkeypatch.setattr(
        service_portfolio,
        "list_connections",
        lambda *args, **kwargs: {
            "data": CONNECTIONS,
            "pagination": {"total": 10_001},
        },
    )
    assert (
        client.post(path, headers=AUTH, json={"expected_revision": 1}).status_code
        == 400
    )
    assert client.get(path, headers=AUTH).json()["data"] == state


def test_runtime_root_uses_existing_durable_home(tmp_path, monkeypatch):
    from api.runtime import _service_portfolio_store

    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    state = append(_service_portfolio_store())
    assert _service_portfolio_store().read("reader", SCOPE) == state
