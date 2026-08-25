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


def test_remote_write_uses_datalake_upload_data_not_adlfs(tmp_path):
    """adlfs routes writes through the classic Blob API (staged-block upload
    or upload_blob), both of which OneLake rejects. The remote write path
    must instead call the native DFS client's upload_data()."""
    store = OneLakeDocumentStore(tmp_path)
    store.is_remote = True

    written: dict[str, bytes] = {}

    class _FakeFileClient:
        def download_file(self):
            from azure.core.exceptions import ResourceNotFoundError

            raise ResourceNotFoundError("not found")

        def upload_data(self, data, *, overwrite, length):
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
