"""Durable annotations require exact-scope authorization and optimistic concurrency."""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from situations.notes import NoteAppend, SituationNotesStore
from situations.store import SituationReadProvider
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

SCOPE = {"subscription": ["sub-a"]}
SUB_A = Scope.from_mapping(SCOPE)
SUB_B = Scope.from_mapping({"subscription": ["sub-b"]})
TOKENS = {
    "reader-token-0123456789": Principal(subject="reader", grants=(Grant("reader", SUB_A),)),
    "operator-token-0123456789": Principal(subject="operator", grants=(Grant("operator", SUB_A),)),
    "mixed-token-0123456789": Principal(subject="mixed", grants=(Grant("reader"), Grant("operator", SUB_A))),
    "outsider-token-0123456789": Principal(subject="outsider", grants=(Grant("operator", SUB_B),)),
}
NOTES = "/api/v1/situations/situation-a/notes"
CHANGE = {"expected_revision": 0, "evidence_run_id": "run-1", "text": "Confirm current ownership before handover."}


def headers(role="operator"):
    return {"Authorization": f"Bearer {role}-token-0123456789"}


@pytest.fixture
def notes_api(tmp_path):
    store = SituationNotesStore(OneLakeDocumentStore(tmp_path))
    rows = [{"situation_id": "situation-a", "scope": SCOPE, "run_id": "run-1"}]
    provider = SituationReadProvider(None, situations=rows)
    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "registry"),
        authenticator=StaticTokenAuthenticator(TOKENS), authorizer=Authorizer(), telemetry=ApiTelemetry(),
        situation_provider=lambda: provider, situation_notes_store=store,
    )
    return TestClient(create_app(context), raise_server_exceptions=False), store, rows


def test_notes_are_durable_append_only_server_attributed_annotations(notes_api):
    client, store, _ = notes_api
    initial = client.get(NOTES, headers=headers()).json()["data"]
    assert initial["revision"] == 0
    assert initial["notes"] == []
    assert initial["can_append"] is True
    response = client.post(NOTES, json=CHANGE, headers=headers())
    assert response.status_code == 200, response.text
    note = response.json()["data"]["notes"][0]
    assert note["actor"] == "operator"
    assert note["evidence_run_id"] == "run-1"
    assert note["revision"] == 1
    assert note["created_at"].endswith("+00:00")
    restarted = SituationNotesStore(store.documents)
    assert restarted.read("situation-a", SCOPE)["notes"] == [note]
    assert client.get(NOTES, headers=headers("reader")).json()["data"]["notes"] == [note]
    assert client.get(NOTES, headers=headers("reader")).json()["data"]["can_append"] is False


def test_readers_cannot_append_and_outside_scope_is_not_found(notes_api):
    client, _, _ = notes_api
    assert client.post(NOTES, json=CHANGE, headers=headers("reader")).status_code == 403
    assert client.get(NOTES, headers=headers("outsider")).status_code == 404
    assert client.post(NOTES, json=CHANGE, headers=headers("outsider")).status_code == 404
    assert client.get(NOTES).status_code == 401
    assert client.post(NOTES, json=CHANGE).status_code == 401


def test_broad_reader_cannot_widen_narrow_operator_write_scope(notes_api):
    client, _, _ = notes_api
    assert client.get(NOTES, headers=headers("mixed")).json()["data"]["can_append"] is False
    assert client.post(NOTES, json=CHANGE, headers=headers("mixed")).status_code == 403
    result = client.post(NOTES + "?subscription=sub-a", json=CHANGE, headers=headers("mixed"))
    assert result.status_code == 200, result.text


def test_stale_note_revision_and_changed_source_run_fail_without_overwrite(notes_api):
    client, _, rows = notes_api
    assert client.post(NOTES, json=CHANGE, headers=headers()).status_code == 200
    assert client.post(NOTES, json=CHANGE, headers=headers()).status_code == 409
    rows[0]["run_id"] = "run-2"
    stale = {**CHANGE, "expected_revision": 1}
    assert client.post(NOTES, json=stale, headers=headers()).status_code == 409
    assert client.get(NOTES, headers=headers()).json()["data"]["revision"] == 1


def test_encoded_durable_situation_ids_resolve_to_notes_not_detail(notes_api):
    client, _, rows = notes_api
    rows[0]["situation_id"] = "situation://with/slash"
    url = f"/api/v1/situations/{quote(rows[0]['situation_id'], safe='')}/notes"
    result = client.post(url, json=CHANGE, headers=headers())
    assert result.status_code == 200, result.text
    assert client.get(url, headers=headers()).json()["data"]["situation_id"] == "situation://with/slash"


def test_runtime_notes_store_uses_existing_durable_root(tmp_path, monkeypatch):
    from api import runtime

    monkeypatch.setattr(runtime, "aiops_home", lambda: tmp_path)
    store = runtime._situation_notes_store()
    store.append("situation-a", SCOPE, NoteAppend(**CHANGE), "operator")
    assert runtime._situation_notes_store().read("situation-a", SCOPE)["revision"] == 1


@pytest.mark.parametrize("patch", [
    {"text": " "}, {"text": "x" * 2001}, {"expected_revision": -1},
    {"expected_revision": True}, {"actor": "forged-admin"}, {"execute": True}, {"evidence_run_id": ""},
])
def test_invalid_notes_and_forged_actor_are_rejected(notes_api, patch):
    client, _, _ = notes_api
    assert client.post(NOTES, json={**CHANGE, **patch}, headers=headers()).status_code == 400


def test_different_exact_scopes_and_situation_identities_do_not_inherit_notes(notes_api):
    _, store, _ = notes_api
    store.append("situation-a", SCOPE, NoteAppend(**CHANGE), "operator")
    assert store.read("situation-a", {})["notes"] == []
    assert store.read("situation-b", SCOPE)["notes"] == []
    assert store.read("situation-a", {"subscription": ["sub-b"]})["notes"] == []


def test_concurrent_appends_never_lose_a_writer(notes_api):
    _, store, _ = notes_api
    def append(actor):
        try:
            store.append("situation-a", SCOPE, NoteAppend(**CHANGE), actor)
        except DocumentConflictError:
            return "conflict"
        return "written"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, ["operator-a", "operator-b"])) == ["conflict", "written"]
    state = store.read("situation-a", SCOPE)
    assert state["revision"] == 1
    assert len(state["notes"]) == 1


def test_storage_cas_conflict_surfaces_as_409_without_claiming_saved(notes_api, monkeypatch):
    client, store, _ = notes_api
    assert client.post(NOTES, json=CHANGE, headers=headers()).status_code == 200
    def conflict(*args, **kwargs):
        raise DocumentConflictError("ETag changed")
    monkeypatch.setattr(store.documents, "replace_if_match", conflict)
    result = client.post(NOTES, json={**CHANGE, "expected_revision": 1}, headers=headers())
    assert result.status_code == 409
    assert store.read("situation-a", SCOPE)["revision"] == 1


def test_corrupt_state_is_not_reset_or_replaced(notes_api):
    client, store, _ = notes_api
    store.documents.create_only(store._name("situation-a", SCOPE), {"revision": 99})
    assert client.get(NOTES, headers=headers()).status_code == 500
    assert client.post(NOTES, json=CHANGE, headers=headers()).status_code == 500
    assert store.documents.read_snapshot(store._name("situation-a", SCOPE)).payload == {"revision": 99}


def test_full_history_requires_explicit_archival_instead_of_silent_truncation(notes_api):
    _, store, _ = notes_api
    template = {
        "note_id": "note", "evidence_run_id": "run-1", "actor": "operator",
        "created_at": "2026-10-16T00:00:00+00:00", "text": "Reviewed",
    }
    state = {"schema_version": 1, "situation_id": "situation-a", "scope": SCOPE,
             "revision": 200, "notes": [{**template, "revision": i} for i in range(1, 201)]}
    store.documents.create_only(store._name("situation-a", SCOPE), state)
    with pytest.raises(ValueError, match="archival"):
        store.append("situation-a", SCOPE, NoteAppend(**{**CHANGE, "expected_revision": 200}), "operator")
    assert store.read("situation-a", SCOPE) == state
