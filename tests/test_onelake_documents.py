"""Unit tests for `storage.onelake_documents.OneLakeDocumentStore`.

The store replaces the PostgreSQL-backed control-plane tables, so the
behaviour that matters is the one the Postgres `UPDATE ... WHERE revision = %s`
guard used to provide: a writer working from a stale read must fail loudly
rather than silently clobber a concurrent update.

These exercise the local-filesystem root, which is the same code path used
against OneLake (the URI only changes which fsspec filesystem is resolved).
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from storage.datasets import DatasetStore, GenerationPointerConditions
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore


def test_read_missing_document_returns_empty(tmp_path):
    store = OneLakeDocumentStore(tmp_path)
    assert store.read("state/absent.json") == {}


def test_write_then_read_roundtrip(tmp_path):
    store = OneLakeDocumentStore(tmp_path)
    store.write("state/registry.json", {"revision": 1, "items": ["a"]}, expected_revision=0)
    assert store.read("state/registry.json") == {"revision": 1, "items": ["a"]}


def test_write_rejects_stale_revision(tmp_path):
    store = OneLakeDocumentStore(tmp_path)
    store.write("state/registry.json", {"revision": 1}, expected_revision=0)

    # A second writer that still believes the document is at revision 0 (it
    # read before the write above landed) must be refused, not applied.
    with pytest.raises(DocumentConflictError):
        store.write("state/registry.json", {"revision": 1, "clobbered": True}, expected_revision=0)

    assert store.read("state/registry.json") == {"revision": 1}


def test_corrupt_document_reads_as_empty(tmp_path):
    """A malformed blob must not take the API down: callers treat it the same
    as a missing document and start from scratch."""
    target = tmp_path / "state" / "registry.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")

    assert OneLakeDocumentStore(tmp_path).read("state/registry.json") == {}


def test_strict_read_surfaces_a_corrupt_document(tmp_path):
    target = tmp_path / "state" / "registry.json"
    target.parent.mkdir(parents=True)
    target.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        OneLakeDocumentStore(tmp_path).read_or_raise("state/registry.json")


def test_put_is_last_writer_wins_and_bumps_revision(tmp_path):
    store = OneLakeDocumentStore(tmp_path)
    store.put("cache/feed.json", {"entries": {"a": 1}})
    store.put("cache/feed.json", {"entries": {"a": 2}})

    document = store.read("cache/feed.json")
    assert document["entries"] == {"a": 2}
    assert document["revision"] == 2


@pytest.mark.parametrize("name", ["/absolute.json", "../escape.json", "state/../../escape.json"])
def test_document_names_cannot_escape_the_root(tmp_path, name):
    with pytest.raises(ValueError):
        OneLakeDocumentStore(tmp_path).read(name)


def test_read_treats_onelake_http_response_error_as_missing(tmp_path):
    """OneLake's DFS-only endpoint rejects classic Blob Service calls with
    HttpResponseError. A read() that hits this on the DFS client must degrade
    to "document not found", not crash the caller."""
    from azure.core.exceptions import HttpResponseError

    store = OneLakeDocumentStore(tmp_path)
    store.is_remote = True

    class _BoomFileClient:
        def download_file(self):
            raise HttpResponseError(message="Operation not supported on the specified endpoint")

    class _BoomFsClient:
        def get_file_client(self, path):
            return _BoomFileClient()

    store._file_system_client = _BoomFsClient()
    store._base = str(tmp_path)
    assert store.read("state/registry.json") == {}


def test_remote_initial_write_uses_native_create_append_flush_not_upload(tmp_path):
    """adlfs routes writes through the classic Blob API (staged-block upload
    or upload_blob), while OneLake rejects ``upload_data(overwrite=False)``
    after its create step. Initial writes must use explicit DFS
    create/append/flush operations with an If-None-Match guard."""
    store = OneLakeDocumentStore(tmp_path)
    store.is_remote = True

    written: dict[str, bytes] = {}
    calls: list[str] = []

    class _FakeFileClient:
        def get_file_properties(self):
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("not found")

        def create_file(self, *, if_none_match):
            assert if_none_match == "*"
            calls.append("create")
            return {"etag": '"created"'}

        def append_data(self, data, *, offset, length):
            assert offset == 0
            assert length == len(data)
            calls.append("append")
            written["state/registry.json"] = data

        def flush_data(self, offset):
            assert offset == len(written["state/registry.json"])
            calls.append("flush")
            return {"etag": '"flushed"'}

        def upload_data(self, *_args, **_kwargs):
            raise AssertionError("initial OneLake write must not use upload_data")

    class _FakeFsClient:
        def get_file_client(self, path):
            return _FakeFileClient()

    store._file_system_client = _FakeFsClient()
    store._base = str(tmp_path)

    store.write("state/registry.json", {"revision": 1, "items": ["a"]}, expected_revision=0)

    [(path, data)] = written.items()
    assert path == "state/registry.json"
    assert json.loads(data.decode("utf-8")) == {"revision": 1, "items": ["a"]}
    assert calls == ["create", "append", "flush"]


def test_remote_conditional_write_rejects_a_replica_that_lost_the_race(
    tmp_path,
):
    """The storage ETag, not a process-local lock, closes the write race."""
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError

    state = {
        "body": json.dumps({"revision": 1, "writer": "original"}).encode(),
        "etag": '"etag-1"',
    }

    class _Download:
        def __init__(self, body):
            self._body = body

        def readall(self):
            return self._body

    class _RacingFileClient:
        def get_file_properties(self):
            return SimpleNamespace(etag=state["etag"])

        def download_file(self, *, etag, match_condition):
            assert etag == state["etag"]
            assert match_condition is MatchConditions.IfNotModified
            return _Download(state["body"])

        def upload_data(
            self,
            data,
            *,
            overwrite,
            length,
            etag,
            match_condition,
        ):
            assert overwrite is True
            assert length == len(data)
            assert match_condition is MatchConditions.IfNotModified
            # A second replica commits after this writer's read but before its
            # conditional upload reaches storage.
            state["body"] = json.dumps(
                {"revision": 2, "writer": "competitor"}
            ).encode()
            state["etag"] = '"etag-2"'
            if etag != state["etag"]:
                raise ResourceModifiedError("condition not met")

    class _FakeFsClient:
        def get_file_client(self, path):
            del path
            return _RacingFileClient()

    stale_replica = OneLakeDocumentStore(tmp_path)
    stale_replica.is_remote = True
    stale_replica._file_system_client = _FakeFsClient()
    stale_replica._base = str(tmp_path)

    with pytest.raises(DocumentConflictError):
        stale_replica.write(
            "state/registry.json",
            {"revision": 2, "writer": "stale"},
            expected_revision=1,
        )

    assert json.loads(state["body"]) == {
        "revision": 2,
        "writer": "competitor",
    }


def test_concurrent_read_does_not_observe_partial_write(tmp_path):
    """Regression test: a read racing a slow, in-flight write must never see
    a partially-written document. Before this fix, ``read()`` held no lock,
    so a reader landing between the local write's ``mkdir``/``write_text``
    calls (or, on OneLake, between the DFS create/append/flush steps) could
    observe a missing/truncated file, fail to parse it, and silently return
    ``{}`` -- indistinguishable from "document never existed". That made an
    existing subscription connection look "not registered" for the instant a
    concurrent sync was persisting ``sync_state``.
    """
    store = OneLakeDocumentStore(tmp_path)
    store.write("state/registry.json", {"revision": 1, "connections": ["demo"]}, expected_revision=0)

    slow_enough = threading.Event()
    release_writer = threading.Event()

    def slow_write(self, name, payload, *, expected_revision):
        # Simulate a slow persist: acquire the lock, signal the reader thread
        # it may now attempt a concurrent read, then hold the lock a bit
        # before actually touching the filesystem.
        with self._lock:
            current = int(self._read_locked(name).get("revision") or 0)
            if current != expected_revision:
                raise DocumentConflictError("stale revision")
            slow_enough.set()
            release_writer.wait(timeout=2)
            body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            path = self._path(name)
            from pathlib import Path

            local_path = Path(path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(body, encoding="utf-8")

    store.write = slow_write.__get__(store, OneLakeDocumentStore)

    results: list[dict] = []

    def reader():
        slow_enough.wait(timeout=2)
        results.append(store.read("state/registry.json"))

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()

    writer_thread = threading.Thread(
        target=lambda: store.write(
            "state/registry.json",
            {"revision": 2, "connections": ["demo", "second"]},
            expected_revision=1,
        )
    )
    writer_thread.start()

    time.sleep(0.05)
    release_writer.set()
    writer_thread.join(timeout=2)
    reader_thread.join(timeout=2)

    assert len(results) == 1
    # The reader must see either the pre-write or post-write document in
    # full -- never an empty/partial one produced by observing the write
    # mid-flight.
    assert results[0] in (
        {"revision": 1, "connections": ["demo"]},
        {"revision": 2, "connections": ["demo", "second"]},
    )


def test_create_only_document_is_immutable_across_store_instances(tmp_path):
    first = OneLakeDocumentStore(tmp_path)
    second = OneLakeDocumentStore(tmp_path)

    created = first.create_only(
        "ontology/generations/generation-1/manifest.json",
        {"generation_id": "generation-1"},
    )

    assert created.payload == {"generation_id": "generation-1"}
    assert created.etag
    with pytest.raises(DocumentConflictError, match="already exists"):
        second.create_only(
            "ontology/generations/generation-1/manifest.json",
            {"generation_id": "replacement"},
        )


def test_independent_clients_cannot_both_replace_one_predecessor_etag(tmp_path):
    creator = OneLakeDocumentStore(tmp_path)
    creator.create_only("ontology/current.json", {"generation": "generation-1"})

    first = OneLakeDocumentStore(tmp_path)
    second = OneLakeDocumentStore(tmp_path)
    first_read = first.read_snapshot("ontology/current.json")
    second_read = second.read_snapshot("ontology/current.json")
    assert first_read.etag == second_read.etag

    first.replace_if_match(
        "ontology/current.json",
        {"generation": "generation-2"},
        expected_etag=first_read.etag,
    )
    with pytest.raises(DocumentConflictError, match="ETag"):
        second.replace_if_match(
            "ontology/current.json",
            {"generation": "stale-generation"},
            expected_etag=second_read.etag,
        )

    assert creator.read("ontology/current.json") == {"generation": "generation-2"}


def test_only_approved_publisher_can_open_authoritative_adapter(tmp_path):
    store = DatasetStore(tmp_path)

    with pytest.raises(PermissionError, match="approved publisher"):
        store.authoritative_publisher(
            publisher_identity="api-runtime",
            approved_publisher_identity="ontology-publisher",
        )

    adapter = store.authoritative_publisher(
        publisher_identity="ontology-publisher",
        approved_publisher_identity="ontology-publisher",
    )
    assert adapter.publisher_identity == "ontology-publisher"


def test_pointer_transition_checks_owner_fence_source_active_and_etag(tmp_path):
    adapter = DatasetStore(tmp_path).authoritative_publisher(
        publisher_identity="ontology-publisher",
        approved_publisher_identity="ontology-publisher",
    )
    initial = adapter.read_pointer()
    assert initial.pointer is None

    promoted = adapter.conditional_promote(
        generation_id="generation-1",
        source_generation="source-1",
        owner_id="writer-1",
        fence=1,
        conditions=GenerationPointerConditions.initial(),
    )
    predecessor = promoted.pointer
    assert predecessor is not None

    conditions = GenerationPointerConditions.from_snapshot(promoted)
    winner = adapter.conditional_promote(
        generation_id="generation-2",
        source_generation="source-2",
        owner_id="writer-2",
        fence=2,
        conditions=conditions,
    )
    assert winner.pointer is not None
    assert winner.pointer.active_generation == "generation-2"
    assert winner.pointer.prior_generation == "generation-1"

    stale_attempts = (
        conditions,
        GenerationPointerConditions(
            etag=winner.etag,
            owner_id="wrong-owner",
            fence=predecessor.fence,
            source_generation=predecessor.source_generation,
            active_generation=predecessor.active_generation,
        ),
        GenerationPointerConditions(
            etag=winner.etag,
            owner_id=winner.pointer.owner_id,
            fence=winner.pointer.fence,
            source_generation="wrong-source",
            active_generation=winner.pointer.active_generation,
        ),
        GenerationPointerConditions(
            etag=winner.etag,
            owner_id=winner.pointer.owner_id,
            fence=winner.pointer.fence,
            source_generation=winner.pointer.source_generation,
            active_generation="wrong-active",
        ),
    )
    for stale in stale_attempts:
        with pytest.raises(DocumentConflictError):
            adapter.conditional_promote(
                generation_id="generation-stale",
                source_generation="source-stale",
                owner_id="writer-stale",
                fence=3,
                conditions=stale,
            )

    assert adapter.read_pointer().pointer == winner.pointer
