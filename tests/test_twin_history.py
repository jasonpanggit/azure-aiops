"""Retained Twin integrity, ownership, scope, atomicity and evidence boundaries."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_api_twin import TOKEN, _auth, _client

from api.auth import StaticTokenAuthenticator
from api.rbac import Grant, Principal
from api.scope import Scope
from semantic.twin_history import (
    MAX_CAPTURE_BYTES,
    MAX_HISTORY_BYTES,
    TwinCapture,
    TwinCaptureRequest,
    TwinHistoryStore,
    _bytes,
    _digest,
    capture_projection,
    compare_captures,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


def _snapshot(scope=None):
    return {
        "scope": scope or {}, "observed_at": "2026-01-01T00:00:00Z",
        "entities": [
            {
                "id": "resource:a", "kind": "resource", "name": "Worker a",
                "state": "current", "confidence": "high",
                "provenance": [{"source": "network.topology", "confidence": "high"}],
                "properties": {"subscription": "sub-a", "owner": "alice", "semantic_attributes": {
                    "supportTeam": "operations", "secret": "unretained-private-marker",
                }, "raw": "unretained-private-marker", "tags": {"private": "unretained-private-marker"}},
            },
            {
                "id": "business_service:payroll", "kind": "business_service", "name": "Payroll",
                "state": "current", "confidence": "high", "provenance": [], "properties": {},
            },
        ],
        "relationships": [{
            "id": "rel:a", "source": "resource:a", "target": "business_service:payroll",
            "type": "supports", "confidence": "high", "provenance": [],
        }],
        "provenance": [{"source": "semantic_graph", "confidence": "unknown"}],
        "warnings": ["Optional source unavailable: Unavailable"],
        "timeline": [{"summary": "unretained-private-marker"}],
    }


def _capture(scope=None):
    return capture_projection(_snapshot(scope), scope or {})


def test_safe_projection_excludes_raw_fields_and_checks_digest():
    capture = _capture()
    serialized = json.dumps(capture.model_dump())
    assert "unretained-private-marker" not in serialized
    assert "semantic_attributes" not in serialized and "timeline" not in serialized
    assert capture.projection.entities[1].attributes == {
        "subscription": "sub-a", "owner": "alice", "support_team": "operations",
    }
    assert capture.snapshot_sha256 == _digest(capture.projection.model_dump())
    modified = capture.model_dump()
    modified["projection"]["entities"][0]["name"] = "Changed"
    with pytest.raises(ValidationError, match="digest"):
        TwinCapture.model_validate(modified)


@pytest.mark.parametrize("invalid", [True, 1.0, "1", 0, 2])
def test_strict_schema_version_is_not_numeric_literal_equality(invalid):
    capture = _capture().model_dump()
    capture["projection"]["schema_version"] = invalid
    capture["snapshot_sha256"] = _digest(capture["projection"])
    with pytest.raises(ValidationError):
        TwinCapture.model_validate(capture)


def test_strict_requests_and_projection_reject_authority_and_raw_properties():
    for payload in [
        {"expected_revision": True}, {"expected_revision": 1.0},
        {"expected_revision": 0, "graph": {}}, {"expected_revision": 0, "authority": "execute"},
    ]:
        with pytest.raises(ValidationError):
            TwinCaptureRequest.model_validate(payload)
    capture = _capture().model_dump()
    capture["projection"]["entities"][0]["attributes"]["authorization"] = "private"
    capture["snapshot_sha256"] = _digest(capture["projection"])
    with pytest.raises(ValidationError):
        TwinCapture.model_validate(capture)


@pytest.mark.parametrize("failure", ["duplicate_entity", "duplicate_link", "dangling_link", "naive_time", "wrong_scope"])
def test_unsafe_compositions_are_rejected_not_partially_saved(failure):
    snapshot = _snapshot()
    if failure == "duplicate_entity":
        snapshot["entities"].append(snapshot["entities"][0])
    elif failure == "duplicate_link":
        snapshot["relationships"].append(snapshot["relationships"][0])
    elif failure == "dangling_link":
        snapshot["relationships"][0]["target"] = "hidden"
    elif failure == "naive_time":
        snapshot["observed_at"] = "2026-01-01"
    else:
        snapshot["scope"] = {"subscription": ["foreign"]}
    with pytest.raises(RuntimeError if failure == "wrong_scope" else ValueError):
        capture_projection(snapshot, {})


def test_restart_identity_revision_duplicate_and_explicit_deletion(tmp_path):
    documents = OneLakeDocumentStore(tmp_path)
    store = TwinHistoryStore(documents)
    scope = {"subscription": ["sub-a"], "region": ["eastus"]}
    capture = _capture(scope)
    assert store.read("owner", scope)["revision"] == 0
    saved = store.update("owner", scope, 0, capture=capture)
    assert TwinHistoryStore(documents).read("owner", scope) == saved
    for actor, other_scope in [("other", scope), ("owner", {}), ("owner", {"subscription": ["sub-a"]})]:
        assert store.read(actor, other_scope)["captures"] == []
    with pytest.raises(DocumentConflictError):
        store.update("owner", scope, 0, capture=_capture(scope))
    with pytest.raises(DocumentConflictError):
        store.update("owner", scope, 1, capture=capture)
    with pytest.raises(KeyError):
        store.update("owner", scope, 1, remove=uuid4().hex)
    assert store.update("owner", scope, 1, remove=capture.snapshot_id)["revision"] == 2
    assert store.read("owner", scope)["captures"] == []


@pytest.mark.parametrize("existing", [False, True])
def test_atomic_create_and_etag_replace_have_one_winner(tmp_path, existing):
    store = TwinHistoryStore(OneLakeDocumentStore(tmp_path))
    if existing:
        store.update("owner", {}, 0, capture=_capture())
    revision = int(existing)
    barrier = Barrier(2)
    original = store.documents.read_snapshot

    def read(name):
        result = original(name)
        barrier.wait(timeout=10)
        return result

    def update(capture):
        try:
            return store.update("owner", {}, revision, capture=capture)["revision"]
        except DocumentConflictError:
            return "conflict"

    with patch.object(store.documents, "read_snapshot", side_effect=read), ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(update, [_capture(), _capture()]))
    assert sorted(map(str, result)) == [str(revision + 1), "conflict"]
    assert len(store.read("owner", {})["captures"]) == revision + 1


def test_count_limit_never_evicts_and_explicit_removal_allows_another_capture(tmp_path):
    store = TwinHistoryStore(OneLakeDocumentStore(tmp_path))
    for revision in range(10):
        store.update("owner", {}, revision, capture=_capture())
    saved = store.read("owner", {})
    with pytest.raises(ValueError, match="full"):
        store.update("owner", {}, 10, capture=_capture())
    assert store.read("owner", {}) == saved
    store.update("owner", {}, 10, remove=saved["captures"][0]["snapshot_id"])
    assert len(store.update("owner", {}, 11, capture=_capture())["captures"]) == 10


@pytest.mark.parametrize("failure", ["schema", "identity", "scope", "digest", "json"])
def test_corrupt_storage_never_becomes_an_empty_history(tmp_path, failure):
    store = TwinHistoryStore(OneLakeDocumentStore(tmp_path))
    saved = store.update("owner", {}, 0, capture=_capture())
    name = store._name("owner", {})
    if failure == "schema":
        saved["schema_version"] = True
    elif failure == "identity":
        saved["actor"] = "foreign"
    elif failure == "scope":
        saved["captures"][0]["projection"]["scope"] = {"region": ["westus"]}
        saved["captures"][0]["snapshot_sha256"] = _digest(saved["captures"][0]["projection"])
    elif failure == "digest":
        saved["captures"][0]["snapshot_sha256"] = "0" * 64
    if failure == "json":
        path = tmp_path / name
        path.write_text("{")
    else:
        current = store.documents.read_snapshot(name)
        store.documents.replace_if_match(name, saved, expected_etag=current.etag)
    with pytest.raises(RuntimeError):
        store.read("owner", {})


def test_unicode_byte_limits_are_measured_without_truncation_or_eviction(tmp_path):
    snapshot = _snapshot()
    template = snapshot["entities"][0]
    template["name"] = "测" * 512
    snapshot["entities"] = [{**template, "id": f"resource:{index}"} for index in range(1000)]
    snapshot["relationships"] = []
    assert _bytes(snapshot) > MAX_CAPTURE_BYTES
    with pytest.raises(ValueError, match="2 MiB"):
        capture_projection(snapshot, {})
    snapshot["entities"] = snapshot["entities"][:500]
    capture = capture_projection(snapshot, {})
    assert _bytes(capture.model_dump()) < MAX_CAPTURE_BYTES
    store = TwinHistoryStore(OneLakeDocumentStore(tmp_path))
    for revision in range(10):
        fresh = capture.model_copy(update={"snapshot_id": uuid4().hex})
        before = store.read("owner", {})
        expected = {**before, "captures": [*before["captures"], fresh.model_dump()]}
        if _bytes(expected) > MAX_HISTORY_BYTES:
            with pytest.raises(ValueError, match="12 MiB"):
                store.update("owner", {}, revision, capture=fresh)
            assert store.read("owner", {}) == before
            break
        store.update("owner", {}, revision, capture=fresh)
    else:
        pytest.fail("Fixture did not reach the real serialized history byte ceiling")


def test_comparison_uses_real_safe_declarations_not_capture_times_or_input_order():
    baseline = _capture()
    snapshot = _snapshot()
    snapshot["observed_at"] = "2026-01-02T00:00:00Z"
    snapshot["entities"].reverse()
    candidate = capture_projection(snapshot, {})
    delta = compare_captures(baseline, candidate)
    assert all(not rows for group in ["entities", "relationships"] for rows in delta[group].values())
    snapshot["entities"][1]["properties"]["owner"] = "bob"
    snapshot["entities"].append({**snapshot["entities"][1], "id": "resource:new"})
    snapshot["relationships"][0]["type"] = "hosts"
    candidate = capture_projection(snapshot, {})
    delta = compare_captures(baseline, candidate)
    assert [row["id"] for row in delta["entities"]["added"]] == ["resource:new"]
    assert delta["entities"]["changed"][0]["fields"] == ["attributes"]
    assert delta["entities"]["changed"][0]["before"]["attributes"]["owner"] == "alice"
    assert delta["entities"]["changed"][0]["after"]["attributes"]["owner"] == "bob"
    assert delta["relationships"]["changed"][0]["fields"] == ["type"]
    with pytest.raises(ValueError):
        compare_captures(baseline, baseline)
    with pytest.raises(ValueError):
        compare_captures(baseline, _capture({"subscription": ["foreign"]}))


def _history_client(tmp_path):
    client = _client(tmp_path)
    context = client.app.state.context
    context.twin_history_store = TwinHistoryStore(OneLakeDocumentStore(tmp_path / "retained"))
    context.authenticator = StaticTokenAuthenticator({
        TOKEN: Principal(subject="admin@example.com", grants=(Grant("admin"),)),
        f"{TOKEN}-reader": Principal(subject="admin@example.com", grants=(Grant("reader"),)),
        f"{TOKEN}-other": Principal(subject="other@example.com", grants=(Grant("reader"),)),
    })
    return client


def test_http_retention_reads_comparison_and_scenario_pair_are_provider_free(tmp_path):
    client = _history_client(tmp_path)
    first = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0})
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 1})
    assert second.status_code == 201, second.text
    captures = second.json()["data"]["captures"]
    context = client.app.state.context
    providers = []
    for name in ["semantic", "network", "vulnerability", "incident", "remediation"]:
        provider = Mock(side_effect=AssertionError("Historical reads must not acquire providers"))
        setattr(context, f"{name}_provider", provider)
        providers.append(provider)
    reader = {"Authorization": f"Bearer {TOKEN}-reader"}
    assert client.get("/api/v1/twin/snapshots", headers=reader).json()["data"]["revision"] == 2
    compared = client.get("/api/v1/twin/snapshots/compare", headers=reader, params={
        "baseline_id": captures[0]["snapshot_id"], "candidate_id": captures[1]["snapshot_id"],
    })
    assert compared.status_code == 200, compared.text
    assert compared.json()["data"]["entities"] == {"added": [], "removed": [], "changed": []}
    scenarios = client.get(f"/api/v1/twin/snapshots/{captures[0]['snapshot_id']}/scenarios", headers=reader, params={
        "left": "patch_deployment", "right": "cve_exploitation", "target": "vm-payroll-1",
    })
    assert scenarios.status_code == 200, scenarios.text
    result = scenarios.json()["data"]
    assert result["left"]["version"] == result["right"]["version"] == result["snapshot_sha256"]
    assert result["left"]["impacted_entities"] == result["right"]["impacted_entities"]
    assert result["left"]["risk_delta"] is result["right"]["risk_delta"] is None
    assert result["authority"] == "none"
    assert "not measured outcomes" in result["interpretation"]
    for provider in providers:
        provider.assert_not_called()


def test_http_history_is_personal_exact_scope_and_mutations_require_admin(tmp_path):
    client = _history_client(tmp_path)
    assert client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0}).status_code == 201
    other = {"Authorization": f"Bearer {TOKEN}-other"}
    reader = {"Authorization": f"Bearer {TOKEN}-reader"}
    assert client.get("/api/v1/twin/snapshots", headers=other).json()["data"]["captures"] == []
    assert client.get("/api/v1/twin/snapshots?region=eastus", headers=_auth()).json()["data"]["captures"] == []
    assert client.post("/api/v1/twin/snapshots", headers=reader, json={"expected_revision": 1}).status_code == 403
    assert client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0}).status_code == 409
    context = client.app.state.context
    context.authenticator = StaticTokenAuthenticator({TOKEN: Principal(
        subject="admin@example.com", grants=(Grant("admin", Scope.from_mapping({"subscription": ["sub-prod"]})),),
    )})
    assert client.get("/api/v1/twin/snapshots", headers=_auth()).json()["data"]["captures"] == []
    result = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0})
    assert result.status_code == 201, result.text
    assert result.json()["scope"] == {"subscription": ["sub-prod"]}
    assert result.json()["data"]["scope"] == {"subscription": ["sub-prod"]}


@pytest.mark.parametrize("params,expected", [
    ({"left": "patch_deployment", "right": "patch_deployment", "target": "vm-payroll-1"}, 400),
    ({"left": "unsupported", "right": "patch_deployment", "target": "vm-payroll-1"}, 400),
    ({"left": "route_change", "right": "patch_deployment", "target": "payroll"}, 404),
])
def test_retained_scenarios_validate_pair_and_exact_seed(tmp_path, params, expected):
    client = _history_client(tmp_path)
    row = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0}).json()["data"]["captures"][0]
    response = client.get(f"/api/v1/twin/snapshots/{row['snapshot_id']}/scenarios", headers=_auth(), params=params)
    assert response.status_code == expected, response.text


def test_runtime_store_uses_the_existing_durable_root(tmp_path, monkeypatch):
    from api.runtime import _twin_history_store

    monkeypatch.setenv("AIOPS_HOME", str(tmp_path))
    store = _twin_history_store()
    store.update("owner", {}, 0, capture=_capture())
    assert _twin_history_store().read("owner", {})["revision"] == 1


def test_http_missing_foreign_deletion_authority_and_raw_graph_rejection(tmp_path):
    client = _history_client(tmp_path)
    first = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0})
    snapshot_id = first.json()["data"]["captures"][0]["snapshot_id"]
    reader = {"Authorization": f"Bearer {TOKEN}-reader"}
    other = {"Authorization": f"Bearer {TOKEN}-other"}
    for headers, query in [(other, {}), (_auth(), {"region": "eastus"})]:
        response = client.get("/api/v1/twin/snapshots/compare", headers=headers, params={
            **query, "baseline_id": snapshot_id, "candidate_id": uuid4().hex,
        })
        assert response.status_code == 404
        response = client.get(f"/api/v1/twin/snapshots/{snapshot_id}/scenarios", headers=headers, params={
            **query, "left": "patch_deployment", "right": "route_change", "target": "vm-payroll-1",
        })
        assert response.status_code == 404
    assert client.post("/api/v1/twin/snapshots/remove", headers=reader, json={
        "expected_revision": 1, "snapshot_id": snapshot_id,
    }).status_code == 403
    assert client.post("/api/v1/twin/snapshots", headers=_auth(), json={
        "expected_revision": 1, "graph": _snapshot(),
    }).status_code == 400
    assert client.post("/api/v1/twin/snapshots/remove", headers=_auth(), json={
        "expected_revision": 0, "snapshot_id": snapshot_id,
    }).status_code == 409
    assert client.post("/api/v1/twin/snapshots/remove", headers=_auth(), json={
        "expected_revision": 1, "snapshot_id": snapshot_id,
    }).status_code == 200
    assert client.get("/api/v1/twin/snapshots", headers=_auth()).json()["data"]["captures"] == []


@pytest.mark.parametrize("failure", ["absent_store", "read", "write", "malformed_source", "invalid_scope", "schema"])
def test_http_storage_and_current_composition_failures_are_unavailable_not_missing_or_empty(tmp_path, failure):
    client = _history_client(tmp_path)
    context = client.app.state.context
    if failure == "absent_store":
        context.twin_history_store = None
        response = client.get("/api/v1/twin/snapshots", headers=_auth())
    elif failure == "read":
        context.twin_history_store.read = Mock(side_effect=OSError("private storage marker"))
        response = client.get("/api/v1/twin/snapshots", headers=_auth())
    elif failure == "write":
        context.twin_history_store.documents.create_only = Mock(side_effect=OSError("private storage marker"))
        response = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0})
    elif failure == "schema":
        documents = context.twin_history_store.documents
        documents.create_only(context.twin_history_store._name("admin@example.com", {}), {"unexpected": "private storage marker"})
        response = client.get("/api/v1/twin/snapshots", headers=_auth())
    else:
        composition = {} if failure == "malformed_source" else _snapshot({"subscription": ["foreign"]})
        with patch("api.routers.twin.OperationalTwinComposer.snapshot", return_value=composition):
            response = client.post("/api/v1/twin/snapshots", headers=_auth(), json={"expected_revision": 0})
    assert response.status_code == 503, response.text
    assert "private storage marker" not in response.text
    assert "captures" not in response.json().get("data", {})


def test_retained_network_attributes_preserve_all_nine_confirmed_scope_dimensions(tmp_path):
    client = _history_client(tmp_path)
    scope = {
        "subscription": ["sub-prod"], "business_service": ["payroll"], "application": ["payroll api"],
        "environment": ["prod"], "owner": ["finance ops"], "subscription_connection": ["conn-prod"],
        "support_team": ["operations"], "region": ["eastus"], "criticality": ["high"],
    }
    resource = {
        "id": "vm-payroll-1", "name": "Payroll", "entity_type": "VirtualMachine",
        "subscription_id": "sub-prod", "business_service": "Payroll", "application": "Payroll API",
        "environment": "prod", "owner": "Finance Ops",
        "details": {"connection_id": "conn-prod", "support_team": "operations", "region": "eastus", "criticality": "high"},
    }
    with patch("test_api_twin._Topology.to_dict", return_value={"resources": [resource], "relationships": []}):
        response = client.post("/api/v1/twin/snapshots", headers=_auth(),
                               params=[(key, values[0]) for key, values in scope.items()],
                               json={"expected_revision": 0})
    assert response.status_code == 201, response.text
    projection = response.json()["data"]["captures"][0]["projection"]
    entity = next(row for row in projection["entities"] if row["id"] == "resource:vm-payroll-1")
    assert {key: entity["attributes"].get(key) for key in scope} == {key: values[0] for key, values in scope.items()}
