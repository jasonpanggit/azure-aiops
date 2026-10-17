"""Team navigation persistence, current ACL history authorization and atomic revisions."""

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
from api.scope import SCOPE_DIMENSIONS, Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.investigation_workspaces import (
    HypothesisUpdate,
    InvestigationWorkspaceStore,
    WorkspaceAccess,
    WorkspaceCreate,
    WorkspaceUpdate,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

ID = "wrk-" + "a" * 32
BASE = "/api/v1/investigation-workspaces"
VIEW = {"title": "Payments review", "entry_type": "BusinessService", "subject": "Payments", "mode": "executive"}
HYP = "hyp-" + "b" * 32
DRAFT = {
    "explanation": "A routing change may explain the observed failures.",
    "supporting": [{"source": "Incident", "reference": "inc-7", "declared_version": "operator-v1", "note": "Timing overlaps"}],
    "contradicting": [{"source": "Network", "reference": "gap-2", "declared_version": "", "note": "Not all paths affected"}],
    "unknowns": ["Whether the affected route was used"], "disposition": "proposed", "rationale": "",
}


def auth(actor="owner"):
    return {"Authorization": f"Bearer workspace-fixture-{actor}"}


def client_fixture(tmp_path):
    store = InvestigationWorkspaceStore(OneLakeDocumentStore(tmp_path / "documents"))
    provider = Mock(side_effect=AssertionError("Navigation workspaces must not acquire evidence"))
    principals = {
        f"workspace-fixture-{actor}": Principal(subject=actor, grants=(Grant("reader"),))
        for actor in ("owner", "editor", "reader", "foreign")
    }
    principals["workspace-fixture-limited"] = Principal(
        subject="limited", grants=(Grant("reader", Scope.from_mapping({"subscription": ["sub-a"]})),),
    )
    principals["workspace-fixture-nonreader"] = Principal(
        subject="nonreader", grants=(Grant("ontology_maintainer"),),
    )
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(principals),
        authorizer=Authorizer(), telemetry=ApiTelemetry(),
        investigation_workspace_store=store,
        semantic_provider=provider, incident_provider=provider, network_provider=provider,
        vulnerability_provider=provider, remediation_provider=provider,
    )
    return TestClient(create_app(context), raise_server_exceptions=False), context, store, provider


def create(client, *, actor="owner", params=None, view=None):
    return client.post(BASE, headers=auth(actor), params=params, json={"workspace_id": ID, "view": view or VIEW})


def share(client, *, revision=1, readers=None, editors=None, actor="owner", params=None):
    return client.put(f"{BASE}/{ID}/access", headers=auth(actor), params=params, json={
        "expected_revision": revision, "readers": readers or [], "editors": editors or [],
    })


def update(client, *, revision=1, actor="owner", params=None):
    return client.put(f"{BASE}/{ID}", headers=auth(actor), params=params, json={
        "expected_revision": revision, "view": {**VIEW, "title": "Updated title"},
    })


def hypothesis(client, *, revision=1, actor="owner", params=None, draft=None, identity=HYP):
    return client.put(f"{BASE}/{ID}/hypotheses/{identity}", headers=auth(actor), params=params, json={
        "expected_revision": revision, "hypothesis": draft or DRAFT,
    })


def test_private_creation_exact_revision_recovery_and_explicit_current_membership(tmp_path):
    client, _, store, provider = client_fixture(tmp_path)
    first = create(client)
    assert first.status_code == 201, first.text
    assert first.json()["data"]["owner"] == "owner"
    assert first.json()["data"]["latest_revision"] == 1
    assert first.json()["data"]["can_share"] is True
    assert create(client).status_code == 409
    assert create(client, actor="foreign").status_code == 409
    assert client.get(f"{BASE}/{ID}", headers=auth("foreign")).status_code == 404
    assert share(client, readers=["reader"], editors=["editor"]).status_code == 200
    read = client.get(f"{BASE}/{ID}", headers=auth("reader")).json()["data"]
    assert read["can_edit"] is False and read["can_share"] is False
    assert read["current_access"] == {"readers": ["reader"], "editors": ["editor"]}
    assert update(client, actor="editor", revision=2).status_code == 200
    historical = client.get(f"{BASE}/{ID}", headers=auth("reader"), params={"revision": 1})
    assert historical.status_code == 200
    assert historical.json()["data"]["revision"]["view"] == VIEW
    assert historical.json()["data"]["latest_revision"] == 3
    assert historical.json()["data"]["current_access"] == read["current_access"]
    recovered = InvestigationWorkspaceStore(store.documents).read(ID, "owner", {})
    assert [row["change"] for row in recovered["history"]] == ["created", "access_updated", "view_updated"]
    assert recovered["revision"]["actor"] == "editor"
    assert recovered["revision"]["view"]["title"] == "Updated title"
    assert "not retained provider evidence" in first.json()["warnings"][0]
    provider.assert_not_called()


@pytest.mark.parametrize("actor", ["reader", "foreign"])
def test_readers_cannot_write_and_foreign_identities_remain_indistinguishable(tmp_path, actor):
    client, _, _, _ = client_fixture(tmp_path)
    create(client)
    share(client, readers=["reader"])
    expected = 403 if actor == "reader" else 404
    assert update(client, actor=actor, revision=2).status_code == expected
    assert share(client, actor=actor, revision=2, editors=[actor]).status_code == expected


def test_editors_cannot_change_memberships_and_revocation_removes_all_historical_access(tmp_path):
    client, _, _, _ = client_fixture(tmp_path)
    create(client)
    share(client, readers=["reader"], editors=["editor"])
    assert share(client, actor="editor", revision=2, editors=["foreign"]).status_code == 403
    assert share(client, revision=2).status_code == 200
    for actor in ("reader", "editor"):
        for revision in (1, 2, 3):
            assert client.get(f"{BASE}/{ID}", headers=auth(actor), params={"revision": revision}).status_code == 404
        assert update(client, actor=actor, revision=3).status_code == 404


@pytest.mark.parametrize("dimension", SCOPE_DIMENSIONS)
def test_each_effective_scope_dimension_is_exact_for_current_history_and_writes(tmp_path, dimension):
    client, _, _, provider = client_fixture(tmp_path)
    params = {dimension: "value"}
    assert create(client, params=params).status_code == 201
    assert share(client, readers=["reader"], params=params).status_code == 200
    for changed in ({}, {dimension: "other"}):
        assert client.get(f"{BASE}/{ID}", headers=auth("reader"), params={**changed, "revision": 1}).status_code == 404
        assert update(client, revision=2, params=changed).status_code == 404
        assert share(client, revision=2, params=changed).status_code == 404
    assert client.get(f"{BASE}/{ID}", headers=auth("reader"), params=params).status_code == 200
    provider.assert_not_called()


def test_shared_membership_cannot_widen_a_readers_platform_grants(tmp_path):
    client, _, _, _ = client_fixture(tmp_path)
    params = [("subscription", "sub-a"), ("subscription", "sub-b")]
    create(client, params=params)
    share(client, readers=["limited"], params=params)
    assert client.get(f"{BASE}/{ID}", headers=auth("limited"), params=params).status_code == 404
    assert client.get(f"{BASE}/{ID}", headers=auth("limited"), params={"subscription": "sub-b"}).status_code == 403


@pytest.mark.parametrize("method,path,body", [
    ("post", BASE, {"workspace_id": ID, "view": VIEW}),
    ("get", f"{BASE}/{ID}", None),
    ("put", f"{BASE}/{ID}", {"expected_revision": 1, "view": VIEW}),
    ("put", f"{BASE}/{ID}/access", {"expected_revision": 1, "readers": [], "editors": []}),
])
def test_authentication_and_read_role_required(tmp_path, method, path, body):
    client, _, _, _ = client_fixture(tmp_path)
    kwargs = {"json": body} if body else {}
    assert client.request(method, path, **kwargs).status_code == 401
    assert client.request(method, path, headers=auth("nonreader"), **kwargs).status_code == 403


@pytest.mark.parametrize("view", [
    {**VIEW, "entry_type": "Unknown"}, {**VIEW, "mode": "unknown"}, {**VIEW, "title": " "},
    {**VIEW, "title": "x" * 121}, {**VIEW, "subject": "x" * 513},
    {**VIEW, "subject": "bad\nsubject"}, {**VIEW, "evidence": []}, {**VIEW, "scope": {}},
    {**VIEW, "owner": "foreign"}, {**VIEW, "execute": True},
])
def test_strict_navigation_contract_rejects_evidence_and_authority_fields(tmp_path, view):
    client, _, _, _ = client_fixture(tmp_path)
    assert create(client, view=view).status_code == 400
    assert client.get(f"{BASE}/{ID}", headers=auth()).status_code == 404


@pytest.mark.parametrize("body", [
    {"expected_revision": True, "readers": [], "editors": []},
    {"expected_revision": "1", "readers": [], "editors": []},
    {"expected_revision": 0, "readers": [], "editors": []},
    {"expected_revision": 1, "readers": ["reader", "reader"], "editors": []},
    {"expected_revision": 1, "readers": ["reader"], "editors": ["reader"]},
    {"expected_revision": 1, "readers": [""], "editors": []},
    {"expected_revision": 1, "readers": ["x\nx"], "editors": []},
    {"expected_revision": 1, "readers": ["x" * 257], "editors": []},
    {"expected_revision": 1, "readers": [str(index) for index in range(21)], "editors": []},
    {"expected_revision": 1, "readers": [], "editors": [], "owner": "other"},
])
def test_membership_contract_bounds_and_identity_uniqueness(body):
    with pytest.raises(ValidationError):
        WorkspaceAccess.model_validate(body)


def test_owner_is_implicit_and_stale_updates_never_merge_or_replace(tmp_path):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    assert share(client, readers=["owner"]).status_code == 400
    assert share(client, readers=["reader"]).status_code == 200
    assert update(client, revision=1).status_code == 409
    assert share(client, revision=1).status_code == 409
    assert store.read(ID, "owner", {})["latest_revision"] == 2


@pytest.mark.parametrize("revision", [0, -1, 41, 1.5, "invalid"])
def test_historical_revision_validation(tmp_path, revision):
    client, _, _, _ = client_fixture(tmp_path)
    create(client)
    assert client.get(f"{BASE}/{ID}", headers=auth(), params={"revision": revision}).status_code == 400


def test_unwritten_historical_revision_is_unavailable(tmp_path):
    client, _, _, _ = client_fixture(tmp_path)
    create(client)
    assert client.get(f"{BASE}/{ID}", headers=auth(), params={"revision": 2}).status_code == 404


def test_parallel_same_identity_create_has_one_owner_and_one_winner(tmp_path):
    store = InvestigationWorkspaceStore(OneLakeDocumentStore(tmp_path))
    barrier = Barrier(2)

    def attempt(actor):
        barrier.wait(timeout=10)
        try:
            store.create(actor, {}, WorkspaceCreate(workspace_id=ID, view=VIEW))
            return actor
        except DocumentConflictError:
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(attempt, ["owner", "foreign"]))
    winners = [result for result in results if result]
    assert len(winners) == 1
    assert store.read(ID, winners[0], {})["owner"] == winners[0]


def test_cross_instance_revision_writers_have_one_cas_winner(tmp_path, monkeypatch):
    stores = [InvestigationWorkspaceStore(OneLakeDocumentStore(tmp_path)) for _ in range(2)]
    stores[0].create("owner", {}, WorkspaceCreate(workspace_id=ID, view=VIEW))
    barrier = Barrier(2)
    original = InvestigationWorkspaceStore._read

    def synchronized(self, *args):
        result = original(self, *args)
        barrier.wait(timeout=10)
        return result

    def attempt(store):
        try:
            store.replace(ID, "owner", {}, WorkspaceUpdate(expected_revision=1, view=VIEW))
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with monkeypatch.context() as patch:
        patch.setattr(InvestigationWorkspaceStore, "_read", synchronized)
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(attempt, stores)) == ["conflict", "saved"]
    assert stores[0].read(ID, "owner", {})["latest_revision"] == 2


def test_revision_ceiling_never_prunes_history(tmp_path):
    store = InvestigationWorkspaceStore(OneLakeDocumentStore(tmp_path))
    store.create("owner", {}, WorkspaceCreate(workspace_id=ID, view=VIEW))
    for revision in range(1, 40):
        store.replace(ID, "owner", {}, WorkspaceUpdate(expected_revision=revision, view=VIEW))
    with pytest.raises(ValueError, match="40 revisions"):
        store.replace(ID, "owner", {}, WorkspaceUpdate(expected_revision=40, view=VIEW))
    assert len(store.read(ID, "owner", {})["history"]) == 40
    assert store.read(ID, "owner", {}, 1)["revision"]["view"] == VIEW


def test_real_unicode_byte_limit_rejects_append_without_pruning_or_changing_acl(tmp_path):
    store = InvestigationWorkspaceStore(OneLakeDocumentStore(tmp_path))
    store.create("owner", {}, WorkspaceCreate(workspace_id=ID, view=VIEW))
    readers = ["\U0001f680" * 250 + f"r{index}" for index in range(20)]
    editors = ["\U0001f680" * 250 + f"e{index}" for index in range(20)]
    revision = 1
    while True:
        before = store.documents.read_snapshot(store._name(ID))
        try:
            store.share(ID, "owner", {}, WorkspaceAccess(
                expected_revision=revision, readers=readers, editors=editors,
            ))
        except ValueError as exc:
            assert "256 KiB" in str(exc)
            assert store.documents.read_snapshot(store._name(ID)) == before
            break
        revision += 1
        assert revision < 40
    assert store.read(ID, "owner", {})["latest_revision"] == revision


@pytest.mark.parametrize("corruption", ["sequence", "actor", "membership", "timestamp", "id"])
def test_corrupt_history_fails_closed_without_reset(tmp_path, corruption):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    share(client, readers=["reader"])
    name = store._name(ID)
    snapshot = store.documents.read_snapshot(name)
    payload = snapshot.payload
    if corruption == "sequence":
        payload["revisions"][1]["revision"] = 3
    elif corruption == "actor":
        payload["revisions"][1]["actor"] = "foreign"
    elif corruption == "membership":
        payload["revisions"][1]["editors"] = ["owner"]
    elif corruption == "timestamp":
        payload["revisions"][1]["recorded_at"] = "2020-01-01T00:00:00"
    else:
        payload["workspace_id"] = "wrk-" + "b" * 32
    store.documents.replace_if_match(name, payload, expected_etag=snapshot.etag)
    assert client.get(f"{BASE}/{ID}", headers=auth()).status_code == 503
    assert update(client, revision=2).status_code == 503
    assert store.documents.read_snapshot(name).payload == payload


def test_unavailable_storage_and_ambiguous_commit_require_exact_identity_recovery(tmp_path, monkeypatch):
    client, context, store, _ = client_fixture(tmp_path)
    context.investigation_workspace_store = None
    assert create(client).status_code == 503
    context.investigation_workspace_store = store
    original = store.documents.create_only

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("fixture reply lost after commit")

    monkeypatch.setattr(store.documents, "create_only", lost_response)
    assert create(client).status_code == 503
    assert client.get(f"{BASE}/{ID}", headers=auth()).json()["data"]["latest_revision"] == 1
    assert create(client).status_code == 409


@pytest.mark.parametrize("field,value", [
    ("owner", "foreign"), ("actor", "foreign"), ("scope", {}),
    ("readers", ["foreign"]), ("evidence", []),
])
def test_creation_cannot_accept_client_attribution_scope_or_evidence(tmp_path, field, value):
    client, _, _, _ = client_fixture(tmp_path)
    response = client.post(BASE, headers=auth(), json={"workspace_id": ID, "view": VIEW, field: value})
    assert response.status_code == 400
    assert client.get(f"{BASE}/{ID}", headers=auth()).status_code == 404


@pytest.mark.parametrize("payload", [{}, {"broken": True}])
def test_existing_empty_or_corrupt_identity_is_never_overwritten(tmp_path, payload):
    client, _, store, _ = client_fixture(tmp_path)
    store.documents.create_only(store._name(ID), payload)
    assert create(client).status_code == 409
    assert client.get(f"{BASE}/{ID}", headers=auth()).status_code == 503
    assert store.documents.read_snapshot(store._name(ID)).payload == payload


def test_failed_replace_leaves_prior_history_and_acl_unchanged(tmp_path, monkeypatch):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    before = store.documents.read_snapshot(store._name(ID))
    monkeypatch.setattr(store.documents, "replace_if_match", Mock(side_effect=OSError("fixture write unavailable")))
    assert share(client, readers=["reader"]).status_code == 503
    assert store.documents.read_snapshot(store._name(ID)) == before
    assert client.get(f"{BASE}/{ID}", headers=auth("reader")).status_code == 404


def test_hypotheses_are_attributed_operator_annotations_with_immutable_history_and_original_subject(tmp_path):
    client, _, store, provider = client_fixture(tmp_path)
    create(client)
    response = hypothesis(client)
    assert response.status_code == 200, response.text
    row = response.json()["data"]["revision"]
    entry = row["hypotheses"][0]
    assert entry == {
        **DRAFT, "hypothesis_id": HYP, "entry_type": "BusinessService", "subject": "Payments",
        "created_revision": 2, "updated_revision": 2, "actor": "owner", "recorded_at": row["recorded_at"],
    }
    assert row["change"] == "hypothesis_updated"
    assert share(client, revision=2, editors=["editor"], readers=["reader"]).status_code == 200
    changed = client.put(f"{BASE}/{ID}", headers=auth(), json={
        "expected_revision": 3, "view": {**VIEW, "subject": "Different subject"},
    })
    assert changed.status_code == 200
    assert changed.json()["data"]["revision"]["hypotheses"] == [entry]
    dismissed = hypothesis(client, revision=4, actor="editor", draft={
        **DRAFT, "disposition": "dismissed", "rationale": "Operator review did not support the explanation.",
    })
    assert dismissed.status_code == 200, dismissed.text
    current = dismissed.json()["data"]["revision"]["hypotheses"][0]
    assert current["subject"] == "Payments"
    assert current["created_revision"] == 2 and current["updated_revision"] == 5
    assert current["actor"] == "editor"
    retained = store.read(ID, "reader", {}, 2)["revision"]["hypotheses"]
    assert retained == [entry]
    assert store.read(ID, "reader", {}, 1)["revision"]["hypotheses"] == []
    assert store.read(ID, "owner", {})["revision"]["view"]["subject"] == "Different subject"
    provider.assert_not_called()


@pytest.mark.parametrize("actor,status", [("reader", 403), ("foreign", 404), ("nonreader", 403)])
def test_hypothesis_membership_and_read_role_are_required(tmp_path, actor, status):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    share(client, readers=["reader"])
    assert hypothesis(client, revision=2, actor=actor).status_code == status
    assert store.read(ID, "owner", {})["revision"]["hypotheses"] == []
    assert client.put(f"{BASE}/{ID}/hypotheses/{HYP}", json={
        "expected_revision": 2, "hypothesis": DRAFT,
    }).status_code == 401


@pytest.mark.parametrize("dimension", SCOPE_DIMENSIONS)
def test_hypothesis_scope_and_revoked_history_remain_fail_closed(tmp_path, dimension):
    client, _, _, provider = client_fixture(tmp_path)
    params = {dimension: "value"}
    create(client, params=params)
    share(client, editors=["editor"], params=params)
    assert hypothesis(client, revision=2, actor="editor").status_code == 404
    assert hypothesis(client, revision=2, actor="editor", params=params).status_code == 200
    assert share(client, revision=3, params=params).status_code == 200
    assert hypothesis(client, revision=4, actor="editor", params=params).status_code == 404
    assert client.get(f"{BASE}/{ID}", headers=auth("editor"), params={**params, "revision": 3}).status_code == 404
    provider.assert_not_called()


@pytest.mark.parametrize("patch", [
    {"explanation": " "}, {"explanation": "x" * 2001}, {"disposition": "verified"},
    {"disposition": "supported", "rationale": " "}, {"rationale": "x" * 1001},
    {"unknowns": ["x"] * 9}, {"unknowns": ["x" * 513]}, {"unknowns": [" "]},
    {"supporting": [{"source": " ", "reference": "id"}]},
    {"supporting": [{"source": "src", "reference": "x" * 513}]},
    {"supporting": [{"source": "src", "reference": "id", "verified": True}]},
    {"contradicting": [{"source": "src", "reference": "id"}] * 7},
    {"owner": "foreign"}, {"actor": "foreign"}, {"subject": "Other"}, {"created_revision": 1},
    {"retained_evidence": {}}, {"model_reasoning": "hidden"}, {"execute": True},
])
def test_hypothesis_strict_bounds_reject_authority_and_evidence_fields(tmp_path, patch):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    before = store.documents.read_snapshot(store._name(ID))
    assert hypothesis(client, draft={**DRAFT, **patch}).status_code == 400
    assert store.documents.read_snapshot(store._name(ID)) == before


def test_hypothesis_conflicts_noops_bad_ids_and_no_implicit_retry(tmp_path):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    assert hypothesis(client, identity="invalid").status_code == 400
    assert hypothesis(client).status_code == 200
    assert hypothesis(client).status_code == 409
    assert hypothesis(client, revision=2).status_code == 400
    assert hypothesis(client, revision=2, draft={**DRAFT, "explanation": "New interpretation"}).status_code == 200
    assert store.read(ID, "owner", {})["latest_revision"] == 3


def test_existing_v1_navigation_documents_read_as_empty_boards_without_writeback(tmp_path):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    name = store._name(ID)
    snapshot = store.documents.read_snapshot(name)
    del snapshot.payload["revisions"][0]["hypotheses"]
    store.documents.replace_if_match(name, snapshot.payload, expected_etag=snapshot.etag)
    before = store.documents.read_snapshot(name)
    assert store.read(ID, "owner", {})["revision"]["hypotheses"] == []
    assert store.documents.read_snapshot(name) == before
    assert hypothesis(client).status_code == 200
    assert store.read(ID, "owner", {}, 1)["revision"]["hypotheses"] == []


def test_hypothesis_limit_keeps_existing_entries_and_history(tmp_path):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    for index in range(20):
        response = hypothesis(client, revision=index + 1, identity=f"hyp-{index:032x}")
        assert response.status_code == 200, response.text
    before = store.documents.read_snapshot(store._name(ID))
    assert hypothesis(client, revision=21).status_code == 400
    assert store.documents.read_snapshot(store._name(ID)) == before
    assert hypothesis(client, revision=21, identity="hyp-" + "0" * 32, draft={
        **DRAFT, "disposition": "dismissed", "rationale": "No supporting source captured",
    }).status_code == 200
    assert len(store.read(ID, "owner", {})["revision"]["hypotheses"]) == 20


@pytest.mark.parametrize("corruption", ["anchor", "actor", "time", "create", "update", "membership", "remove", "collateral"])
def test_corrupt_hypothesis_history_never_becomes_authoritative(tmp_path, corruption):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    hypothesis(client)
    hypothesis(client, revision=2, identity="hyp-" + "c" * 32)
    name = store._name(ID)
    snapshot = store.documents.read_snapshot(name)
    latest = snapshot.payload["revisions"][-1]
    row = latest["hypotheses"][-1]
    if corruption == "anchor":
        row["subject"] = "Other"
    elif corruption == "actor":
        row["actor"] = "foreign"
    elif corruption == "time":
        row["recorded_at"] = "2026-01-01T00:00:00Z"
    elif corruption == "create":
        row["created_revision"] = 2
    elif corruption == "update":
        row["updated_revision"] = 2
    elif corruption == "membership":
        latest["editors"] = ["foreign"]
    elif corruption == "remove":
        latest["hypotheses"].pop(0)
    else:
        latest["hypotheses"][0]["explanation"] = "Unattributed second change"
    store.documents.replace_if_match(name, snapshot.payload, expected_etag=snapshot.etag)
    assert client.get(f"{BASE}/{ID}", headers=auth()).status_code == 503
    assert hypothesis(client, revision=3).status_code == 503
    assert store.documents.read_snapshot(name).payload == snapshot.payload


def test_hypothesis_lost_reply_requires_explicit_latest_read_and_does_not_duplicate(tmp_path, monkeypatch):
    client, _, store, _ = client_fixture(tmp_path)
    create(client)
    original = store.documents.replace_if_match

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("fixture reply lost after successful annotation write")

    monkeypatch.setattr(store.documents, "replace_if_match", lost_response)
    assert hypothesis(client).status_code == 503
    result = client.get(f"{BASE}/{ID}", headers=auth()).json()["data"]
    assert result["latest_revision"] == 2
    assert result["revision"]["hypotheses"][0]["hypothesis_id"] == HYP
    assert hypothesis(client).status_code == 409
    assert hypothesis(client, revision=2).status_code == 400


def test_hypothesis_and_navigation_compete_for_the_same_cas_revision(tmp_path, monkeypatch):
    stores = [InvestigationWorkspaceStore(OneLakeDocumentStore(tmp_path)) for _ in range(2)]
    stores[0].create("owner", {}, WorkspaceCreate(workspace_id=ID, view=VIEW))
    barrier = Barrier(2)
    original = InvestigationWorkspaceStore._read

    def synchronized(self, *args):
        result = original(self, *args)
        barrier.wait(timeout=10)
        return result

    def attempt(index):
        try:
            if index:
                stores[index].update_hypothesis(ID, HYP, "owner", {}, HypothesisUpdate(expected_revision=1, hypothesis=DRAFT))
            else:
                stores[index].replace(ID, "owner", {}, WorkspaceUpdate(expected_revision=1, view=VIEW))
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with monkeypatch.context() as patch:
        patch.setattr(InvestigationWorkspaceStore, "_read", synchronized)
        with ThreadPoolExecutor(2) as pool:
            assert sorted(pool.map(attempt, [0, 1])) == ["conflict", "saved"]
    result = stores[0].read(ID, "owner", {})
    assert result["latest_revision"] == 2
    assert len(result["revision"]["hypotheses"]) == (1 if result["revision"]["change"] == "hypothesis_updated" else 0)
