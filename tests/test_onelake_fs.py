"""OneLake DFS-native filesystem.

The behaviour that matters here is negative: none of these operations may fall
back to a classic Blob Service call, because OneLake answers those with
``IncorrectEndpointError`` and that is exactly what broke dataset publication
during a subscription sync. The fakes below therefore model the DFS surface
only -- ``get_paths``/``get_file_client``/``get_directory_client`` -- and any
attempt to reach for a Blob-flavoured API raises.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from hermes_arg_connector.onelake_fs import OneLakeFileSystem

WORKSPACE = "workspace-id"


class FakePathEntry:
    def __init__(self, name: str, is_directory: bool = False, size: int = 0) -> None:
        self.name = name
        self.is_directory = is_directory
        self.content_length = size
        self.last_modified = datetime(2026, 1, 1, tzinfo=UTC)


class FakeFileClient:
    def __init__(self, store: dict[str, bytes], path: str) -> None:
        self._store = store
        self._path = path

    def exists(self) -> bool:
        return self._path in self._store

    def upload_data(self, content, overwrite: bool = False) -> None:
        if isinstance(content, str):
            content = content.encode("utf-8")
        self._store[self._path] = content

    def download_file(self):
        if self._path not in self._store:
            raise ResourceNotFoundError(self._path)
        payload = self._store[self._path]
        return type("_Download", (), {"readall": lambda _self: payload})()

    def delete_file(self) -> None:
        self._store.pop(self._path, None)

    def rename_file(self, new_name: str) -> None:
        target = new_name.split("/", 1)[1]
        self._store[target] = self._store.pop(self._path, b"")

    # Blob-only surface -- reaching for any of these is the bug under test.
    def stage_block(self, *_args, **_kwargs):
        raise AssertionError("staged-block upload is a Blob-only call")

    def upload_blob(self, *_args, **_kwargs):
        raise AssertionError("upload_blob is a Blob-only call")


class FakeDirectoryClient:
    def __init__(self, directories: set[str], path: str) -> None:
        self._directories = directories
        self._path = path

    def create_directory(self) -> None:
        if self._path in self._directories:
            raise ResourceExistsError(self._path)
        self._directories.add(self._path)

    def delete_directory(self) -> None:
        self._directories.discard(self._path)


class FakeFileSystemClient:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.directories: set[str] = set()

    def get_file_client(self, path: str) -> FakeFileClient:
        return FakeFileClient(self.files, path)

    def get_directory_client(self, path: str) -> FakeDirectoryClient:
        return FakeDirectoryClient(self.directories, path)

    def get_paths(self, path=None, recursive: bool = False):
        prefix = f"{path}/" if path else ""
        known: set[str] = set()
        for name in {*self.directories, *(key.rsplit("/", 1)[0] for key in self.files)}:
            parts = name.split("/")
            for index in range(1, len(parts) + 1):
                known.add("/".join(parts[:index]))
        if path and path not in known:
            raise ResourceNotFoundError(path)
        seen: set[str] = set()
        for name in sorted({*self.files, *self.directories}):
            if not name.startswith(prefix) or name == path:
                continue
            remainder = name[len(prefix) :]
            head = remainder.split("/", 1)[0]
            full = f"{prefix}{head}"
            if full in seen:
                continue
            seen.add(full)
            is_directory = full in self.directories or "/" in remainder
            yield FakePathEntry(
                full, is_directory=is_directory, size=len(self.files.get(full, b""))
            )

    # Blob-only surface.
    def list_blobs(self, *_args, **_kwargs):
        raise AssertionError("list_blobs is a Blob-only call")


@pytest.fixture()
def filesystem(monkeypatch) -> OneLakeFileSystem:
    backend = FakeFileSystemClient()
    monkeypatch.setattr(
        "azure.storage.filedatalake.FileSystemClient",
        lambda **_kwargs: backend,
    )
    instance = OneLakeFileSystem(WORKSPACE, credential=object())
    instance.backend = backend  # type: ignore[attr-defined]
    return instance


def _path(*parts: str) -> str:
    return "/".join([WORKSPACE, *parts])


def test_write_then_read_round_trips_text(filesystem: OneLakeFileSystem) -> None:
    with filesystem.open(_path("lakehouse/Files/a.json"), "wt") as handle:
        handle.write('{"ok": true}')

    with filesystem.open(_path("lakehouse/Files/a.json"), "rt") as handle:
        assert handle.read() == '{"ok": true}'


def test_write_then_read_round_trips_bytes(filesystem: OneLakeFileSystem) -> None:
    with filesystem.open(_path("lakehouse/Files/a.parquet"), "wb") as handle:
        handle.write(b"PAR1")

    with filesystem.open(_path("lakehouse/Files/a.parquet"), "rb") as handle:
        assert handle.read() == b"PAR1"


def test_exists_distinguishes_present_and_missing(filesystem: OneLakeFileSystem) -> None:
    with filesystem.open(_path("lakehouse/Files/a.json"), "wt") as handle:
        handle.write("{}")

    assert filesystem.exists(_path("lakehouse/Files/a.json")) is True
    assert filesystem.exists(_path("lakehouse/Files/missing.json")) is False


def test_reading_a_missing_file_raises_file_not_found(filesystem: OneLakeFileSystem) -> None:
    with pytest.raises(FileNotFoundError):
        filesystem.open(_path("lakehouse/Files/missing.json"), "rt")


def test_makedirs_is_idempotent_when_exist_ok(filesystem: OneLakeFileSystem) -> None:
    filesystem.makedirs(_path("lakehouse/Files/generations"), exist_ok=True)
    filesystem.makedirs(_path("lakehouse/Files/generations"), exist_ok=True)

    assert filesystem.isdir(_path("lakehouse/Files/generations")) is True


def test_makedirs_propagates_conflict_when_not_exist_ok(
    filesystem: OneLakeFileSystem,
) -> None:
    filesystem.makedirs(_path("lakehouse/Files/generations"), exist_ok=True)

    with pytest.raises(ResourceExistsError):
        filesystem.makedirs(_path("lakehouse/Files/generations"), exist_ok=False)


def test_ls_returns_workspace_qualified_paths(filesystem: OneLakeFileSystem) -> None:
    for name in ("one", "two"):
        with filesystem.open(_path(f"lakehouse/Files/gen/{name}.json"), "wt") as handle:
            handle.write("{}")

    listed = filesystem.ls(_path("lakehouse/Files/gen"))

    assert listed == [
        _path("lakehouse/Files/gen/one.json"),
        _path("lakehouse/Files/gen/two.json"),
    ]


def test_ls_of_missing_directory_is_empty(filesystem: OneLakeFileSystem) -> None:
    assert filesystem.ls(_path("lakehouse/Files/nope")) == []


def test_listed_paths_round_trip_back_into_info(filesystem: OneLakeFileSystem) -> None:
    """``_cleanup_generations`` feeds ``ls`` output straight into ``info``."""
    with filesystem.open(_path("lakehouse/Files/gen/one.json"), "wt") as handle:
        handle.write("{}")

    (listed,) = filesystem.ls(_path("lakehouse/Files/gen"))

    assert filesystem.info(listed)["type"] == "file"


def test_info_reports_mtime_for_generation_sorting(filesystem: OneLakeFileSystem) -> None:
    with filesystem.open(_path("lakehouse/Files/gen/one.json"), "wt") as handle:
        handle.write("{}")

    assert filesystem.info(_path("lakehouse/Files/gen/one.json"))["mtime"] > 0


def test_info_raises_for_missing_path(filesystem: OneLakeFileSystem) -> None:
    with pytest.raises(FileNotFoundError):
        filesystem.info(_path("lakehouse/Files/missing.json"))


def test_rm_removes_a_file(filesystem: OneLakeFileSystem) -> None:
    with filesystem.open(_path("lakehouse/Files/a.json"), "wt") as handle:
        handle.write("{}")

    filesystem.rm(_path("lakehouse/Files/a.json"))

    assert filesystem.exists(_path("lakehouse/Files/a.json")) is False


def test_rm_of_missing_path_is_silent(filesystem: OneLakeFileSystem) -> None:
    filesystem.rm(_path("lakehouse/Files/missing.json"))


def test_mv_relocates_content(filesystem: OneLakeFileSystem) -> None:
    with filesystem.open(_path("lakehouse/Files/.tmp"), "wt") as handle:
        handle.write("payload")

    filesystem.mv(_path("lakehouse/Files/.tmp"), _path("lakehouse/Files/state.json"))

    assert filesystem.exists(_path("lakehouse/Files/.tmp")) is False
    with filesystem.open(_path("lakehouse/Files/state.json"), "rt") as handle:
        assert handle.read() == "payload"


def test_resolve_fs_selects_the_dfs_native_backend(monkeypatch) -> None:
    """The regression guard: OneLake roots must not resolve to adlfs."""
    monkeypatch.setattr(
        "azure.storage.filedatalake.FileSystemClient", lambda **_kwargs: FakeFileSystemClient()
    )
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential", lambda *_args, **_kwargs: object()
    )
    from hermes_arg_connector.fs import resolve_fs

    filesystem, root = resolve_fs(
        "abfss://workspace-id@onelake.dfs.fabric.microsoft.com/lakehouse-id/Files/hermes"
    )

    assert isinstance(filesystem, OneLakeFileSystem)
    assert root == "workspace-id/lakehouse-id/Files/hermes"
