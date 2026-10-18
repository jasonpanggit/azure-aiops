"""Retained topology projections: bounded, scoped, explicit, and not lifecycle proof."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from network_scenario import network_rows
from pydantic import ValidationError

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from network import history
from network.service import NetworkIntelligenceService, NetworkScope
from onboarding.service import SubscriptionOnboardingService
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

TOKEN = "network-history-reader-fixture"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SCOPE = {"subscription": ["sub-prod"]}


def _capture(service=None):
    service = service or NetworkIntelligenceService.from_rows(network_rows())
    now = datetime.now(UTC).isoformat()
    return history.topology_capture(
        service.analyze().topology.to_dict(detail="summary"),
        service.snapshot.observed_at,
        now,
        now,
    )


def _client(tmp_path, *, scoped=False):
    calls = []
    service = NetworkIntelligenceService.from_rows(network_rows())
    store = history.NetworkHistoryStore(OneLakeDocumentStore(tmp_path / "documents"))

    def provider():
        calls.append("network")
        return service

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
        network_history_store=store,
        network_provider=provider,
    )
    return (
        TestClient(create_app(context), raise_server_exceptions=False),
        context,
        store,
        calls,
        service,
    )


def test_projection_is_safe_fixed_connected_and_sorted():
    capture = _capture()
    assert capture.nodes and capture.edges
    assert capture.source_observed_at == "2024-06-01T00:00:00Z"
    assert [node.id for node in capture.nodes] == sorted(
        node.id for node in capture.nodes
    )
    assert [edge.id for edge in capture.edges] == sorted(
        edge.id for edge in capture.edges
    )
    assert set(capture.nodes[0].model_dump()) == set(history.TopologyNode.model_fields)
    assert {"details", "tags", "properties", "rules"}.isdisjoint(
        capture.nodes[0].model_dump()
    )
    assert any(edge.peering for edge in capture.edges)
    ids = {node.id for node in capture.nodes}
    assert all(edge.source in ids and edge.target in ids for edge in capture.edges)


def test_boundary_peering_retains_count_not_foreign_identity():
    service = NetworkIntelligenceService.from_rows(network_rows()).scoped(
        NetworkScope(subscription_ids=("sub-prod",))
    )
    topology = service.analyze().topology.to_dict(detail="summary")
    assert topology["links"]
    foreign = "/subscriptions/not-observed/resourcegroups/foreign/providers/microsoft.network/virtualnetworks/foreign"
    topology["links"][0]["remote_vnet_id"] = foreign
    now = datetime.now(UTC).isoformat()
    capture = history.topology_capture(topology, "", now, now)
    assert capture.omitted_boundary_peering_count > 0
    assert foreign not in capture.model_dump_json()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda t: t["coverage"].update(truncated=True),
        lambda t: t["coverage"]["nodes"].update(truncated=True),
        lambda t: t["coverage"]["nodes"].update(returned=0),
        lambda t: t["coverage"]["relationships"].update(truncated=True),
        lambda t: t["resources"].append(t["resources"][0]),
        lambda t: t["relationships"][0].update(target="missing"),
        lambda t: t["resources"][0].update(name=12),
        lambda t: t["counts"].update(dropped_relationships={"unknown": True}),
    ],
)
def test_provider_drift_and_truncation_fail_instead_of_saving_partial_projection(
    mutation,
):
    topology = (
        NetworkIntelligenceService.from_rows(network_rows())
        .analyze()
        .topology.to_dict(detail="summary")
    )
    mutation(topology)
    now = datetime.now(UTC).isoformat()
    with pytest.raises(ValueError):
        history.topology_capture(topology, "", now, now)


def test_store_survives_restart_isolation_and_exact_five_retention(tmp_path):
    store = history.NetworkHistoryStore(OneLakeDocumentStore(tmp_path))
    ids = []
    for revision in range(7):
        capture = _capture()
        ids.append(capture.capture_id)
        state = store.append("reader", SCOPE, revision, capture)
    recovered = history.NetworkHistoryStore(OneLakeDocumentStore(tmp_path))
    assert recovered.read("reader", SCOPE) == state
    assert [row["capture_id"] for row in state["captures"]] == ids[-5:]
    for actor, scope in [
        ("other", SCOPE),
        ("reader", {}),
        ("reader", {**SCOPE, "region": ["eastus"]}),
    ]:
        assert recovered.read(actor, scope)["captures"] == []
    with pytest.raises(DocumentConflictError):
        store.append("reader", SCOPE, 6, _capture())
    assert store.read("reader", SCOPE) == state


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.update(schema_version=True),
        lambda s: s.pop("schema_version"),
        lambda s: s.update(actor="other"),
        lambda s: s.update(scope={}),
        lambda s: s.update(revision=0),
        lambda s: s["captures"].append(s["captures"][0]),
        lambda s: s["captures"][0].update(started_at="2020-01-01T00:00:00"),
        lambda s: s["captures"][0].update(source_observed_at="9999-01-01T00:00:00Z"),
    ],
)
def test_corruption_does_not_become_empty_history(tmp_path, mutation):
    documents = OneLakeDocumentStore(tmp_path)
    store = history.NetworkHistoryStore(documents)
    state = store.append("reader", SCOPE, 0, _capture())
    mutation(state)
    documents.write(store._name("reader", SCOPE), state, expected_revision=1)
    with pytest.raises(RuntimeError):
        store.read("reader", SCOPE)


def test_serialized_byte_bound_is_enforced_without_write(tmp_path, monkeypatch):
    store = history.NetworkHistoryStore(OneLakeDocumentStore(tmp_path))
    state = store.append("reader", {}, 0, _capture())
    monkeypatch.setattr(history, "MAX_BYTES", store._bytes(state) + 5)
    with pytest.raises(ValueError, match="2 MiB"):
        store.append("reader", {}, 1, _capture())
    assert store.read("reader", {}) == state
    monkeypatch.setattr(history, "MAX_BYTES", 1)
    with pytest.raises(RuntimeError, match="document limit"):
        store.read("reader", {})


def test_real_serialized_bound_handles_large_valid_unicode_without_partial_history(
    tmp_path,
):
    store = history.NetworkHistoryStore(OneLakeDocumentStore(tmp_path))
    data = _capture().model_dump()
    template = data["nodes"][0]
    data["nodes"] = [
        {
            **template,
            "id": f"resource-{i}",
            "name": "\u2603" * 512,
            "owner": "\u2603" * 512,
            "application": "\u2603" * 512,
            "business_service": "\u2603" * 512,
        }
        for i in range(100)
    ]
    data["edges"] = []
    first = history.TopologyCapture.model_validate(data)
    state = store.append("reader", {}, 0, first)
    assert store._bytes(state) <= 2 * 1024 * 1024
    data["capture_id"] = str(uuid4())
    with pytest.raises(ValueError, match="2 MiB"):
        store.append("reader", {}, 1, history.TopologyCapture.model_validate(data))
    assert store.read("reader", {}) == state


def test_capture_count_and_field_bounds_are_real():
    data = _capture().model_dump()
    data["nodes"] = [{**data["nodes"][0], "id": f"node-{i}"} for i in range(1501)]
    with pytest.raises(ValidationError):
        history.TopologyCapture.model_validate(data)
    data = _capture().model_dump()
    data["edges"] *= (6001 // len(data["edges"])) + 1
    with pytest.raises(ValidationError):
        history.TopologyCapture.model_validate(data)
    data = _capture().model_dump()
    data["nodes"][0]["id"] = "x" * 2049
    with pytest.raises(ValidationError):
        history.TopologyCapture.model_validate(data)


def test_concurrent_create_is_atomic(tmp_path, monkeypatch):
    store = history.NetworkHistoryStore(OneLakeDocumentStore(tmp_path))
    barrier = Barrier(2)
    read = store._read
    captures = [_capture(), _capture()]

    def synchronized(*args):
        result = read(*args)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(store, "_read", synchronized)

    def append(capture):
        try:
            store.append("reader", {}, 0, capture)
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, captures)) == ["conflict", "saved"]
    monkeypatch.setattr(store, "_read", read)
    assert store.read("reader", {})["revision"] == 1


def test_comparison_reports_exact_safe_fields_additions_and_absence():
    before = _capture()
    node = before.nodes[0]
    changed = node.model_copy(update={"name": "Updated name"})
    fresh = node.model_copy(update={"id": "new-id", "name": "New projected node"})
    after = before.model_copy(
        update={
            "capture_id": str(uuid4()),
            "nodes": [changed, fresh],
            "edges": [],
        }
    )
    rows = history.compare_captures(before, after)
    assert next(row for row in rows if row["id"] == node.id)["changed_fields"] == [
        "name"
    ]
    assert next(row for row in rows if row["id"] == "new-id")["change"] == "added"
    assert sum(row["change"] == "no_longer_observed" for row in rows) == len(
        before.nodes
    ) - 1 + len(before.edges)
    assert history.compare_captures(before, before) == []


def test_peering_flag_change_is_observable_without_raw_configuration():
    before = _capture()
    edge = next(edge for edge in before.edges if edge.peering)
    changed = edge.model_copy(
        update={
            "peering": edge.peering.model_copy(
                update={"allow_gateway_transit": not edge.peering.allow_gateway_transit}
            )
        }
    )
    after = before.model_copy(
        update={
            "edges": [changed if row.id == edge.id else row for row in before.edges]
        }
    )
    assert history.compare_captures(before, after) == [
        {
            "kind": "edge",
            "id": edge.id,
            "change": "changed",
            "changed_fields": ["peering"],
            "before": edge.model_dump(),
            "after": changed.model_dump(),
        }
    ]


def test_http_read_compare_are_provider_free_and_capture_is_explicit(tmp_path):
    client, _, _, calls, _ = _client(tmp_path)
    assert (
        client.get("/api/v1/network/topology/history", headers=AUTH).json()["data"][
            "revision"
        ]
        == 0
    )
    assert calls == []
    first = client.post(
        "/api/v1/network/topology/history", headers=AUTH, json={"expected_revision": 0}
    )
    assert first.status_code == 201, first.text
    second = client.post(
        "/api/v1/network/topology/history", headers=AUTH, json={"expected_revision": 1}
    )
    assert second.status_code == 201, second.text
    captures = second.json()["data"]["captures"]
    assert calls == ["network", "network"]
    result = client.get(
        "/api/v1/network/topology/history/compare",
        headers=AUTH,
        params={
            "baseline_id": captures[0]["capture_id"],
            "target_id": captures[1]["capture_id"],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["data"]["changes"] == []
    assert result.json()["data"]["counts"] == {
        "added": 0,
        "no_longer_observed": 0,
        "changed": 0,
    }
    assert calls == ["network", "network"]
    assert (
        client.get(
            "/api/v1/network/topology/history",
            headers={"Authorization": f"Bearer {TOKEN}-other"},
        ).json()["data"]["revision"]
        == 0
    )


def test_http_comparison_is_paginated_validated_and_personal(tmp_path):
    client, _, store, calls, _ = _client(tmp_path)
    first = _capture()
    data = first.model_dump()
    data.update(capture_id=str(uuid4()), edges=[])
    data["nodes"][0]["name"] = "Changed"
    second = history.TopologyCapture.model_validate(data)
    store.append("reader", {}, 0, first)
    store.append("reader", {}, 1, second)
    query = {
        "baseline_id": first.capture_id,
        "target_id": second.capture_id,
        "limit": 1,
    }
    result = client.get(
        "/api/v1/network/topology/history/compare", headers=AUTH, params=query
    )
    assert result.status_code == 200
    assert len(result.json()["data"]["changes"]) == 1
    assert result.json()["data"]["total"] == len(first.edges) + 1
    assert result.json()["pagination"]["total"] == len(first.edges) + 1
    later = client.get(
        "/api/v1/network/topology/history/compare",
        headers=AUTH,
        params={**query, "offset": 1},
    )
    assert later.json()["data"]["changes"] != result.json()["data"]["changes"]
    for baseline, target, status in [
        (first.capture_id, first.capture_id, 400),
        (second.capture_id, first.capture_id, 400),
        (str(uuid4()), second.capture_id, 404),
    ]:
        response = client.get(
            "/api/v1/network/topology/history/compare",
            headers=AUTH,
            params={"baseline_id": baseline, "target_id": target},
        )
        assert response.status_code == status
    assert (
        client.get(
            "/api/v1/network/topology/history/compare",
            headers=AUTH,
            params=query | {"region": "westus"},
        ).status_code
        == 404
    )
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"expected_revision": 0, "nodes": []},
        {"expected_revision": 0, "capture_id": str(uuid4())},
    ],
)
def test_http_capture_accepts_only_reviewed_revision(tmp_path, body):
    client, _, store, calls, _ = _client(tmp_path)
    assert (
        client.post(
            "/api/v1/network/topology/history", headers=AUTH, json=body
        ).status_code
        == 400
    )
    assert store.read("reader", {})["revision"] == 0 and calls == []


def test_stale_revision_does_not_acquire_provider(tmp_path):
    client, _, _, calls, _ = _client(tmp_path)
    response = client.post(
        "/api/v1/network/topology/history", headers=AUTH, json={"expected_revision": 1}
    )
    assert response.status_code == 409
    assert calls == []


def test_provider_unavailable_and_storage_failure_are_explicit(tmp_path, monkeypatch):
    client, context, store, _, _ = _client(tmp_path)
    context.network_provider = lambda: None
    assert (
        client.post(
            "/api/v1/network/topology/history",
            headers=AUTH,
            json={"expected_revision": 0},
        ).status_code
        == 503
    )
    assert store.read("reader", {})["revision"] == 0
    monkeypatch.setattr(
        store.documents,
        "read_snapshot",
        lambda _: (_ for _ in ()).throw(OSError("storage unavailable")),
    )
    assert (
        client.get("/api/v1/network/topology/history", headers=AUTH).status_code >= 500
    )


def test_capture_race_returns_conflict_and_does_not_overwrite(tmp_path):
    client, context, store, calls, service = _client(tmp_path)

    def racing_provider():
        store.append("reader", {}, 0, _capture())
        calls.append("network")
        return service

    context.network_provider = racing_provider
    result = client.post(
        "/api/v1/network/topology/history", headers=AUTH, json={"expected_revision": 0}
    )
    assert result.status_code == 409, result.text
    assert store.read("reader", {})["revision"] == 1


def test_http_invalid_truncated_projection_never_advances_revision(
    tmp_path, monkeypatch
):
    client, _, store, _, _ = _client(tmp_path)
    from api.routers import network

    project = network.topology_capture

    def truncated(topology, *args):
        topology["coverage"]["truncated"] = True
        return project(topology, *args)

    monkeypatch.setattr(network, "topology_capture", truncated)
    response = client.post(
        "/api/v1/network/topology/history", headers=AUTH, json={"expected_revision": 0}
    )
    assert response.status_code == 503, response.text
    assert "No capture was saved" in response.text
    assert store.read("reader", {})["revision"] == 0


def test_http_current_grants_and_nine_dimensions_filter_before_capture(tmp_path):
    client, _, store, _, service = _client(tmp_path, scoped=True)
    enriched = replace(
        service.snapshot,
        vnets=tuple(
            replace(
                row,
                support_team="sre",
                region="eastus",
                criticality="high",
                environment="prod",
                business_service="payments",
                application="portal",
                owner="platform",
            )
            for row in service.snapshot.vnets
        ),
    )
    service.snapshot = enriched
    query = [
        ("subscription", "sub-prod"),
        ("subscription", "sub-uat"),
        ("business_service", "payments"),
        ("application", "portal"),
        ("environment", "prod"),
        ("owner", "platform"),
        ("support_team", "sre"),
        ("region", "eastus"),
        ("criticality", "high"),
        ("subscription_connection", "conn-prod"),
    ]
    response = client.post(
        "/api/v1/network/topology/history",
        headers=AUTH,
        params=query,
        json={"expected_revision": 0},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["scope"]["subscription"] == ["sub-prod"]
    nodes = payload["data"]["captures"][0]["nodes"]
    assert nodes, "Require positive evidence before asserting exclusion"
    assert all(node["subscription_id"] == "sub-prod" for node in nodes)
    assert "sub-uat" not in str(nodes)
    assert store.read("reader", {})["revision"] == 0
    narrower = client.get(
        "/api/v1/network/topology/history",
        headers=AUTH,
        params=[(key, "westus" if key == "region" else value) for key, value in query],
    )
    assert narrower.status_code == 200, narrower.text
    assert narrower.json()["data"]["revision"] == 0


def test_authentication_and_runtime_store(tmp_path, monkeypatch):
    client, _, _, _, _ = _client(tmp_path)
    assert client.get("/api/v1/network/topology/history").status_code == 401
    assert (
        client.post(
            "/api/v1/network/topology/history", json={"expected_revision": 0}
        ).status_code
        == 401
    )
    from api import runtime

    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    store = runtime._network_history_store()
    store.append("reader", {}, 0, _capture())
    assert runtime._network_history_store().read("reader", {})["revision"] == 1
