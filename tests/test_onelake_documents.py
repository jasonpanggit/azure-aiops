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


def test_list_names_pages_documents_under_prefix(tmp_path):
    store = OneLakeDocumentStore(tmp_path)
    for index in range(3):
        store.write(
            f"threads/thread-{index}.json",
            {"revision": 1},
            expected_revision=0,
        )
    store.write("other/ignored.json", {"revision": 1}, expected_revision=0)

    first, continuation = store.list_names("threads", limit=2)
    second, final = store.list_names(
        "threads",
        limit=2,
        continuation=continuation,
    )

    assert first == ["threads/thread-0.json", "threads/thread-1.json"]
    assert second == ["threads/thread-2.json"]
    assert final is None


def test_delete_rejects_stale_revision_and_removes_matching_document(tmp_path):
    store = OneLakeDocumentStore(tmp_path)
    store.write("threads/thread.json", {"revision": 1}, expected_revision=0)

    with pytest.raises(DocumentConflictError):
        store.delete("threads/thread.json", expected_revision=0)

    store.delete("threads/thread.json", expected_revision=1)
    assert store.read("threads/thread.json") == {}


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


def test_remote_write_uses_datalake_upload_data_not_adlfs(tmp_path):
    """adlfs routes writes through the classic Blob API (staged-block upload
    or upload_blob), both of which OneLake rejects. The remote write path
    must instead call the native DFS client's upload_data()."""
    store = OneLakeDocumentStore(tmp_path)
    store.is_remote = True

    written: dict[str, bytes] = {}

    class _FakeFileClient:
        def get_file_properties(self):
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("not found")

        def download_file(self):
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("not found")

        def upload_data(self, data, *, overwrite, length, **conditions):
            assert overwrite is False
            assert conditions == {}
            written["state/registry.json"] = data

    class _FakeFsClient:
        def get_file_client(self, path):
            return _FakeFileClient()

    store._file_system_client = _FakeFsClient()
    store._base = str(tmp_path)

    store.write("state/registry.json", {"revision": 1, "items": ["a"]}, expected_revision=0)

    [(path, data)] = written.items()
    assert path == "state/registry.json"
    assert json.loads(data.decode("utf-8")) == {"revision": 1, "items": ["a"]}


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


def test_remote_list_names_uses_bounded_dfs_paging(tmp_path):
    class _PageIterator:
        continuation_token = "next-page"

        def __init__(self):
            self._served = False

        def __iter__(self):
            return self

        def __next__(self):
            if self._served:
                raise StopIteration
            self._served = True
            return [
                SimpleNamespace(name=f"{tmp_path}/threads/one.json", is_directory=False),
                SimpleNamespace(name=f"{tmp_path}/threads/nested", is_directory=True),
            ]

    class _Paths:
        def by_page(self, *, continuation_token):
            assert continuation_token == "prior-page"
            return _PageIterator()

    class _FakeFsClient:
        def get_paths(self, *, path, recursive, max_results):
            assert path == f"{tmp_path}/threads"
            assert recursive is True
            assert max_results == 2
            return _Paths()

    store = OneLakeDocumentStore(tmp_path)
    store.is_remote = True
    store._file_system_client = _FakeFsClient()
    store._base = str(tmp_path)

    names, continuation = store.list_names(
        "threads",
        limit=2,
        continuation="prior-page",
    )

    assert names == ["threads/one.json"]
    assert continuation == "next-page"


def test_remote_delete_rejects_etag_race(tmp_path):
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError

    class _Download:
        def readall(self):
            return json.dumps({"revision": 1}).encode()

    class _RacingFileClient:
        def get_file_properties(self):
            return SimpleNamespace(etag='"etag-1"')

        def download_file(self, *, etag, match_condition):
            assert etag == '"etag-1"'
            assert match_condition is MatchConditions.IfNotModified
            return _Download()

        def delete_file(self, *, etag, match_condition):
            assert etag == '"etag-1"'
            assert match_condition is MatchConditions.IfNotModified
            raise ResourceModifiedError("condition not met")

    class _FakeFsClient:
        def get_file_client(self, path):
            assert path == f"{tmp_path}/threads/thread.json"
            return _RacingFileClient()

    store = OneLakeDocumentStore(tmp_path)
    store.is_remote = True
    store._file_system_client = _FakeFsClient()
    store._base = str(tmp_path)

    with pytest.raises(DocumentConflictError):
        store.delete("threads/thread.json", expected_revision=1)


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
