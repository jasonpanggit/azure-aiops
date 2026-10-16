"""Personal query preferences, strict CAS and exact actor/scope isolation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.saved_views import SavedViewStore, ViewUpdate
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

TOKEN = "saved-views-reader-fixture"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SEARCH = {
    "kind": "search", "view_id": "vms", "name": "Production VM discovery",
    "query": "show list of VMs", "entity_type": "VirtualMachine", "source": "ARG",
}
TRIAGE = {
    "kind": "situations", "view_id": "queue", "name": "Old P1 queue", "query": "Payments",
    "priority": "P1", "assigned_owner": "SRE", "lifecycle_state": "open",
    "older_than_hours": 24, "sort": "oldest",
}
SCOPE = {"subscription": ["sub-a", "sub-b"], "support_team": ["sre"]}


def _client(tmp_path, *, scoped=False):
    store = SavedViewStore(OneLakeDocumentStore(tmp_path / "documents"))
    provider = Mock(side_effect=AssertionError("Preferences must not acquire sources"))
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator({
            TOKEN: Principal(subject="reader", grants=(Grant(
                "reader", Scope.from_mapping({"subscription": ["sub-a"]}) if scoped else Scope(),
            ),)),
            TOKEN + "-other": Principal(subject="other", grants=(Grant("reader"),)),
        }),
        authorizer=Authorizer(), telemetry=ApiTelemetry(), saved_view_store=store,
        semantic_provider=provider, situation_provider=provider,
        hybrid_search_provider=provider,
    )
    return TestClient(create_app(context), raise_server_exceptions=False), context, store, provider


def _replace(client, views, revision=0, params=None, headers=None):
    return client.put("/api/v1/saved-views", headers=headers or AUTH, params=params,
                      json={"expected_revision": revision, "views": views})


def test_reader_can_save_replace_delete_and_recover_without_source_acquisition(tmp_path):
    client, _, store, provider = _client(tmp_path)
    initial = client.get("/api/v1/saved-views", headers=AUTH)
    assert initial.status_code == 200
    assert initial.json()["data"]["revision"] == 0
    assert initial.json()["data"]["updated_at"] == ""
    response = _replace(client, [SEARCH, TRIAGE])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["actor"] == "reader" and data["revision"] == 1 and data["updated_at"]
    assert data["views"] == [SEARCH, TRIAGE]
    recovered = SavedViewStore(store.documents).read("reader", {})
    assert recovered == data
    replaced = _replace(client, [{**SEARCH, "query": "production applications"}], 1)
    assert replaced.status_code == 200
    assert replaced.json()["data"]["views"][0]["query"] == "production applications"
    assert _replace(client, [], 2).json()["data"]["revision"] == 3
    assert store.read("reader", {})["views"] == []
    provider.assert_not_called()


def test_actor_and_exact_effective_scope_are_rechecked_on_every_operation(tmp_path):
    client, _, _, _ = _client(tmp_path)
    query = [("subscription", value) for value in SCOPE["subscription"]] + [("support_team", "SRE")]
    response = _replace(client, [SEARCH], params=query)
    assert response.json()["data"]["scope"] == SCOPE
    for headers, params in (
        (AUTH, None), (AUTH, {"subscription": "sub-a", "support_team": "SRE"}),
        (AUTH, {"subscription": "sub-a", "support_team": "Other"}),
        ({"Authorization": f"Bearer {TOKEN}-other"}, query),
    ):
        own = client.get("/api/v1/saved-views", headers=headers, params=params)
        assert own.status_code == 200, own.text
        assert own.json()["data"]["views"] == []
        assert own.json()["data"]["revision"] == 0
    assert client.get("/api/v1/saved-views", headers=AUTH, params=query).json()["data"]["views"] == [SEARCH]


def test_grant_intersects_repeated_query_and_cannot_be_widened(tmp_path):
    client, _, store, _ = _client(tmp_path, scoped=True)
    response = _replace(client, [SEARCH], params=[("subscription", "sub-a"), ("subscription", "sub-b")])
    assert response.status_code == 200
    assert response.json()["scope"] == {"subscription": ["sub-a"]}
    assert store.read("reader", {"subscription": ["sub-a"]})["views"] == [SEARCH]
    assert client.get("/api/v1/saved-views", headers=AUTH, params={"subscription": "sub-b"}).status_code == 403


@pytest.mark.parametrize("method", ["get", "put"])
def test_authentication_is_required(tmp_path, method):
    client, _, _, _ = _client(tmp_path)
    kwargs = {"json": {"expected_revision": 0, "views": []}} if method == "put" else {}
    assert getattr(client, method)("/api/v1/saved-views", **kwargs).status_code == 401


@pytest.mark.parametrize("view", [
    {**SEARCH, "kind": "external"},
    {**SEARCH, "query": " "},
    {**SEARCH, "query": "x" * 513},
    {**SEARCH, "name": " "},
    {**SEARCH, "view_id": "../escape"},
    {**SEARCH, "entity_type": "x" * 129},
    {**SEARCH, "source": "x" * 257},
    {**SEARCH, "href": "https://example.test"},
    {**SEARCH, "scope": {}},
    {**SEARCH, "results": []},
    {**TRIAGE, "priority": "P0"},
    {**TRIAGE, "older_than_hours": 1},
    {**TRIAGE, "older_than_hours": "24"},
    {**TRIAGE, "older_than_hours": 24.0},
    {**TRIAGE, "sort": "risk"},
    {**TRIAGE, "selections": []},
    {**TRIAGE, "execute": True},
])
def test_strict_view_contract_rejects_unsupported_or_authority_fields(tmp_path, view):
    client, _, store, _ = _client(tmp_path)
    response = _replace(client, [view])
    assert response.status_code == 400, response.text
    assert store.read("reader", {})["revision"] == 0


@pytest.mark.parametrize("update", [
    {"expected_revision": True, "views": []},
    {"expected_revision": "0", "views": []},
    {"expected_revision": -1, "views": []},
    {"expected_revision": 9_007_199_254_740_991, "views": []},
    {"expected_revision": 0, "views": [SEARCH, SEARCH]},
    {"expected_revision": 0, "views": [{**SEARCH, "view_id": f"view-{i}"} for i in range(21)]},
    {"expected_revision": 0, "views": [], "actor": "other"},
])
def test_collection_bounds_and_revision_contract(update):
    with pytest.raises(ValidationError):
        ViewUpdate.model_validate(update)


def test_real_oversized_unicode_document_is_rejected_without_writing(tmp_path):
    client, _, store, _ = _client(tmp_path)
    response = _replace(client, [
        {**SEARCH, "view_id": f"view-{i}", "query": "\U0001f680" * 512} for i in range(20)
    ])
    assert response.status_code == 400 and "64 KiB" in response.text
    assert store.read("reader", {})["revision"] == 0


def test_stale_review_cannot_overwrite_saved_collection(tmp_path):
    client, _, store, _ = _client(tmp_path)
    assert _replace(client, [SEARCH]).status_code == 200
    response = _replace(client, [TRIAGE])
    assert response.status_code == 409
    assert store.read("reader", {})["views"] == [SEARCH]


@pytest.mark.parametrize("initial_revision", [0, 1])
def test_concurrent_create_and_replace_are_atomic(tmp_path, monkeypatch, initial_revision):
    store = SavedViewStore(OneLakeDocumentStore(tmp_path))
    if initial_revision:
        store.replace("reader", {}, ViewUpdate(expected_revision=0, views=[]))
    barrier = Barrier(2)
    read = store._read

    def synchronized(*args):
        result = read(*args)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(store, "_read", synchronized)

    def save(view):
        try:
            store.replace("reader", {}, ViewUpdate.model_validate({
                "expected_revision": initial_revision, "views": [view],
            }))
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, [SEARCH, TRIAGE])) == ["conflict", "saved"]
    monkeypatch.setattr(store, "_read", read)
    assert store.read("reader", {})["revision"] == initial_revision + 1


@pytest.mark.parametrize("corruption", ["actor", "scope", "schema", "size", "time"])
def test_corrupt_state_fails_explicitly_instead_of_becoming_empty(tmp_path, corruption):
    client, _, store, _ = _client(tmp_path)
    data = _replace(client, [SEARCH]).json()["data"]
    if corruption == "actor":
        data["actor"] = "other"
    elif corruption == "scope":
        data["scope"] = {"subscription": ["private"]}
    elif corruption == "schema":
        data["unexpected"] = True
    elif corruption == "time":
        data["updated_at"] = "2025-01-01T00:00:00"
    else:
        data["views"][0]["query"] = "x" * 65536
    name = store._name("reader", {})
    snapshot = store.documents.read_snapshot(name)
    store.documents.replace_if_match(name, data, expected_etag=snapshot.etag)
    assert client.get("/api/v1/saved-views", headers=AUTH).status_code == 503
    assert _replace(client, [], 1).status_code == 503


def test_missing_storage_and_failed_write_are_explicit(tmp_path, monkeypatch):
    client, context, store, _ = _client(tmp_path)
    context.saved_view_store = None
    assert client.get("/api/v1/saved-views", headers=AUTH).status_code == 503
    context.saved_view_store = store
    monkeypatch.setattr(store.documents, "create_only", Mock(side_effect=OSError("Storage denied")))
    assert _replace(client, [SEARCH]).status_code == 503
    assert store.read("reader", {})["revision"] == 0


def test_runtime_factory_reuses_existing_document_root(tmp_path, monkeypatch):
    from api import runtime
    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    first = runtime._saved_view_store()
    first.replace("reader", SCOPE, ViewUpdate.model_validate({"expected_revision": 0, "views": [SEARCH]}))
    assert runtime._saved_view_store().read("reader", SCOPE)["views"] == [SEARCH]
