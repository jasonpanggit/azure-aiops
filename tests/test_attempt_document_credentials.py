"""Credential/root ownership checks use offline SDK fakes only."""

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)

from ontology_discovery.immutable_attempt_worker import (
    AttemptLifecycleConflict,
    OneLakeAttemptLifecycleJournal,
)
from storage.attempt_documents import bind_remote_attempt_documents
from storage.onelake_documents import OneLakeDocumentStore

WORKSPACE = "11111111-1111-1111-1111-111111111111"
ITEM = "22222222-2222-2222-2222-222222222222"
STAGED = f"abfss://{WORKSPACE}@onelake.dfs.fabric.microsoft.com/{ITEM}/Files/staged"
JOURNAL = STAGED.removesuffix("staged") + "journal"
OWNER = "33333333-3333-3333-3333-333333333333"
JOURNAL_OWNER = "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def sdk(monkeypatch):
    calls = []
    bodies = {}
    etags = {}
    clients = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("implicit credential or DatasetStore filesystem used")

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", forbidden)
    monkeypatch.setattr("storage.fs.resolve_fs", forbidden)

    class Client:
        def __init__(self, *, account_url, file_system_name, credential):
            self.credential = credential
            self.closed = 0
            calls.append(("client", account_url, file_system_name, credential))
            clients.append(self)

        def get_file_client(self, path):
            credential = self.credential

            class File:
                def get_file_properties(self):
                    credential.get_token("offline")
                    calls.append(("read", path, credential))
                    if path not in bodies:
                        raise ResourceNotFoundError("missing")
                    return SimpleNamespace(etag=etags.get(path, "version-one"))

                def download_file(self, **kwargs):
                    if kwargs["etag"] != etags.get(path, "version-one"):
                        raise ResourceModifiedError("stale read")
                    assert kwargs["match_condition"] is not None
                    return SimpleNamespace(readall=lambda: bodies[path])

                def create_file(self, **kwargs):
                    assert credential.allow_write
                    assert kwargs == {"if_none_match": "*"}
                    if path in bodies:
                        raise ResourceExistsError("already created")
                    calls.append(("create", path, credential))
                    return {"etag": "created"}

                def append_data(self, body, **_kwargs):
                    bodies[path] = body

                def flush_data(self, _length):
                    etags[path] = "version-one"
                    return {"etag": "version-one"}

                def upload_data(self, body, **kwargs):
                    assert credential.allow_write
                    if kwargs["etag"] != etags.get(path, "version-one"):
                        raise ResourceModifiedError("stale write")
                    assert kwargs["match_condition"] is not None
                    calls.append(("replace", path, credential))
                    bodies[path] = body
                    etags[path] = "version-two"
                    return {"etag": "version-two"}

            return File()

        def close(self):
            self.closed += 1

    monkeypatch.setattr("azure.storage.filedatalake.FileSystemClient", Client)
    return SimpleNamespace(calls=calls, bodies=bodies, clients=clients)


def credential(*, write=False):
    return SimpleNamespace(get_token=Mock(), close=Mock(), allow_write=write)


def options():
    return {
        "staged_root": STAGED,
        "staged_credential": credential(),
        "staged_owner_object_id": OWNER,
        "journal_root": JOURNAL,
        "journal_credential": credential(write=True),
        "journal_owner_object_id": JOURNAL_OWNER,
    }


@pytest.mark.parametrize("bad", [None, "", "secret", b"secret", object()])
def test_bad_credentials_refused_before_sdk(sdk, bad):
    with pytest.raises(TypeError, match="credential"):
        OneLakeDocumentStore.remote(STAGED, credential=bad)
    assert sdk.calls == []


@pytest.mark.parametrize(
    "root",
    [
        STAGED + "/",
        STAGED + "/../journal",
        STAGED + "?x=1",
        STAGED + "#fragment",
        STAGED.replace("abfss:", "abfs:"),
        STAGED.replace(WORKSPACE, "name"),
        STAGED.replace(ITEM, "name"),
        STAGED.replace("/Files/", "/files/"),
        STAGED.replace("staged", "%73taged"),
        STAGED.replace("staged", "a\\b"),
        STAGED.replace("onelake.dfs", "wrong.dfs"),
    ],
)
def test_bad_roots_refused_before_sdk(sdk, root):
    with pytest.raises(ValueError, match="canonical"):
        OneLakeDocumentStore.remote(root, credential=credential())
    assert sdk.calls == []


@pytest.mark.parametrize(
    "overlap",
    [STAGED, STAGED + "/child", STAGED.upper(), STAGED.replace("staged", "Staged")],
)
def test_overlapping_or_alias_roots_refuse_before_sdk(sdk, overlap):
    values = options()
    values["journal_root"] = overlap
    with pytest.raises(ValueError), bind_remote_attempt_documents(**values):
        pytest.fail("overlap accepted")
    assert sdk.calls == []


def test_same_declared_owner_refused_not_python_object_identity(sdk):
    values = options()
    values["journal_owner_object_id"] = OWNER
    with (
        pytest.raises(ValueError, match="distinct"),
        bind_remote_attempt_documents(**values),
    ):
        pytest.fail("owner alias accepted")
    assert sdk.calls == []


def test_parent_root_overlap_and_missing_credential_refuse_without_clients(sdk):
    values = options()
    values["staged_root"] = STAGED + "/child"
    values["journal_root"] = STAGED
    with pytest.raises(ValueError), bind_remote_attempt_documents(**values):
        pytest.fail("parent overlap accepted")
    values = options()
    values["journal_credential"] = None
    with pytest.raises(TypeError), bind_remote_attempt_documents(**values):
        pytest.fail("missing journal credential accepted")
    assert sdk.calls == []


def test_credential_object_identity_is_not_principal_evidence(sdk):
    values = options()
    values["journal_credential"] = values["staged_credential"]
    with bind_remote_attempt_documents(**values) as binding:
        assert binding.staged_owner_object_id != binding.journal_owner_object_id
    assert sdk.calls == []


def test_journal_target_cas_and_staged_write_denial(sdk):
    values = options()
    with bind_remote_attempt_documents(**values) as binding:
        journal = OneLakeAttemptLifecycleJournal(binding.journal_documents)
        target = {
            "tenant_id": OWNER,
            "subscription_id": OWNER,
            "connection_id": OWNER,
            "workspace_id": WORKSPACE,
            "item_id": ITEM,
            "definition_fingerprint": "v1",
        }
        record = {"target": target, "dispatch_id": "dispatch", "revision": 0}
        created = journal.create_target(record)
        assert journal.read_target(target).record == record
        updated = {**record, "revision": 1, "state": "held"}
        journal.replace_target(updated, expected_revision=created.revision)
        with pytest.raises(AttemptLifecycleConflict, match="revision"):
            journal.replace_target(updated, expected_revision=0)
        staged = OneLakeDocumentStore.remote(
            STAGED, credential=values["staged_credential"]
        )
        try:
            with pytest.raises(AssertionError):
                staged.create_only("not-allowed.json", {})
        finally:
            staged.close()
    with bind_remote_attempt_documents(**values) as restarted:
        journal = OneLakeAttemptLifecycleJournal(restarted.journal_documents)
        assert journal.read_target(target).record == updated
        with pytest.raises(AttemptLifecycleConflict):
            journal.create_target({**record, "dispatch_id": "competitor"})
    assert all(client.closed == 1 for client in sdk.clients)


def test_pinned_roots_lifetime_and_distinct_exact_sdk_routing(sdk):
    values = options()
    prefix = f"{ITEM}/Files/"
    for name, payload in {
        "entities": {"records": []},
        "relationships": {"records": []},
        "manifest": {"generation_id": "g"},
        "lineage": {},
        "validation": {},
        "compatibility": {},
        "stage-authorization-1-" + hashlib.sha256(b"owner").hexdigest()[:16]: {
            "event": "maintenance_stage_authorization"
        },
    }.items():
        sdk.bodies[f"{prefix}staged/generations/g/{name}.json"] = json.dumps(
            payload
        ).encode()
    with bind_remote_attempt_documents(**values) as binding:
        assert sdk.calls == []
        assert not hasattr(binding.staged, "write")
        assert not hasattr(binding.staged, "conditional_promote")
        assert binding.staged.read_generation("g")["manifest"] == {"generation_id": "g"}
        assert (
            binding.staged.read_stage_authorization(
                target_generation_id="g", owner_id="owner", fence=1
            )["event"]
            == "maintenance_stage_authorization"
        )
        store = binding.journal_documents
        with pytest.raises(AttributeError):
            store.root = STAGED
        with pytest.raises(AttributeError):
            store.is_remote = False
        initial = store.create_only("state.json", {"record": 1})
        assert initial.etag == "version-one"
        store.replace_if_match("state.json", {"record": 2}, expected_etag=initial.etag)
        assert store.read_snapshot("state.json").payload == {"record": 2}
    assert all(client.closed == 1 for client in sdk.clients)
    store.close()
    assert all(client.closed == 1 for client in sdk.clients)
    assert not values["staged_credential"].close.called
    assert not values["journal_credential"].close.called
    for kind, path, owner in (call for call in sdk.calls if call[0] != "client"):
        if "/staged/" in path:
            assert kind == "read"
            assert owner is values["staged_credential"]
        else:
            assert "/journal/" in path
            assert owner is values["journal_credential"]
    before = len(sdk.calls)
    with pytest.raises(RuntimeError, match="closed"):
        store.read_snapshot("state.json")
    assert len(sdk.calls) == before


@pytest.mark.parametrize(
    "failure",
    [ClientAuthenticationError("offline denied"), OSError("offline unavailable")],
)
def test_auth_failure_no_fallback_and_context_cleanup(sdk, failure):
    owned = credential()
    owned.get_token.side_effect = failure
    with (
        pytest.raises(type(failure)),
        OneLakeDocumentStore.remote(STAGED, credential=owned) as store,
    ):
        store.read("missing.json")
    assert len(sdk.clients) == 1
    assert sdk.clients[0].closed == 1
    assert not owned.close.called


def test_close_unused_and_failed_client_creation_never_fallback(sdk, monkeypatch):
    store = OneLakeDocumentStore.remote(STAGED, credential=credential())
    store.close()
    assert sdk.clients == []
    with pytest.raises(RuntimeError, match="closed"):
        store.create_only("state.json", {})

    def fail(**_kwargs):
        raise ValueError("SDK construction failed")

    monkeypatch.setattr("azure.storage.filedatalake.FileSystemClient", fail)
    with (
        pytest.raises(ValueError, match="SDK construction"),
        OneLakeDocumentStore.remote(STAGED, credential=credential()) as other,
    ):
        other.read_snapshot("state.json")
    assert sdk.clients == []


def test_directory_creation_serializes_close_and_refuses_after_close(sdk):
    entered, finish, closing, closed = (threading.Event() for _ in range(4))
    store = OneLakeDocumentStore.remote(STAGED, credential=credential(write=True))

    def create_directory(path):
        assert path.endswith("/directory")
        entered.set()
        assert finish.wait(5)
        assert not sdk.clients[0].closed

    store._client().get_directory_client = lambda path: SimpleNamespace(
        create_directory=lambda: create_directory(path)
    )

    def close():
        closing.set()
        store.close()
        closed.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        creating = pool.submit(store.ensure_directory, "directory")
        try:
            assert entered.wait(5)
            stopping = pool.submit(close)
            assert closing.wait(5)
            assert not closed.wait(0.05)
        finally:
            finish.set()
        creating.result(timeout=5)
        stopping.result(timeout=5)
    assert closed.is_set()
    assert sdk.clients[0].closed == 1
    with pytest.raises(RuntimeError, match="closed"):
        store.ensure_directory("other")
