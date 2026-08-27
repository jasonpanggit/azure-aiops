"""A minimal DFS-native filesystem for OneLake dataset storage.

OneLake only implements the ADLS Gen2 *DFS* REST surface. ``adlfs``/``fsspec``
silently fall back to classic Blob Service operations for several calls --
``list_blobs`` behind ``exists()``, staged-block ``upload_blob`` behind writes,
``get_blob_properties`` behind ``info()`` -- and OneLake rejects every one of
them with ``IncorrectEndpointError``. That is why dataset publication (the
sync path) failed even though the small-document store, which was already
ported to the DFS-native client, worked.

This class exposes only the handful of operations the dataset/state stores
actually use, implemented directly on ``azure-storage-file-datalake``. It is
deliberately duck-typed rather than an ``fsspec.AbstractFileSystem`` subclass:
the callers only need these methods, and staying off the fsspec base class
keeps the instance cache, protocol stripping, and buffered-file machinery --
each of which has its own Blob-flavoured assumptions -- out of the path.

Paths handed in and out keep the ``<workspace>/<lakehouse>/...`` shape that
:func:`hermes_arg_connector.fs.resolve_fs` returns, so callers that round-trip
a path through :meth:`ls` and back into :meth:`info`/:meth:`rm` keep working.
"""

from __future__ import annotations

import io
from typing import Any

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
)

ONELAKE_HOST = "onelake.dfs.fabric.microsoft.com"


class _UploadBuffer(io.BytesIO):
    """Buffers a write and uploads it to OneLake on close.

    Writes are whole-file uploads rather than staged blocks: the datasets
    written through here are small enough, and staged-block commits are one of
    the Blob-only operations OneLake rejects.
    """

    def __init__(self, file_client: Any) -> None:
        super().__init__()
        self._file_client = file_client
        self._uploaded = False

    def close(self) -> None:
        if not self._uploaded:
            self._uploaded = True
            self._file_client.upload_data(self.getvalue(), overwrite=True)
        super().close()


class OneLakeFileSystem:
    """DFS-native OneLake filesystem covering the dataset-store surface."""

    def __init__(self, workspace: str, credential: Any) -> None:
        from azure.storage.filedatalake import FileSystemClient

        self.workspace = workspace.strip("/")
        self._client = FileSystemClient(
            account_url=f"https://{ONELAKE_HOST}",
            file_system_name=self.workspace,
            credential=credential,
        )

    # -- path helpers ----------------------------------------------------
    def _relative(self, path: str) -> str:
        """Strip the workspace prefix that callers carry on every path."""
        text = str(path).strip("/")
        if text == self.workspace:
            return ""
        return text.removeprefix(f"{self.workspace}/")

    def _absolute(self, relative: str) -> str:
        return f"{self.workspace}/{str(relative).strip('/')}"

    def _stat(self, path: str) -> Any | None:
        """Return the directory listing entry for ``path``, or ``None``.

        Resolved by listing the parent rather than fetching properties
        directly: the listing is the one call that reliably distinguishes a
        directory from a file on OneLake.
        """
        relative = self._relative(path)
        if not relative:
            return None
        parent, _, name = relative.rpartition("/")
        try:
            for entry in self._client.get_paths(path=parent or None, recursive=False):
                if str(entry.name).rstrip("/").rsplit("/", 1)[-1] == name:
                    return entry
        except (ResourceNotFoundError, HttpResponseError):
            # A missing parent is an ordinary "not found" here, and OneLake
            # answers a listing of a path that is itself a file with a 4xx.
            return None
        return None

    # -- filesystem operations -------------------------------------------
    def exists(self, path: str) -> bool:
        relative = self._relative(path)
        if not relative:
            return True
        try:
            if self._client.get_file_client(relative).exists():
                return True
        except (ResourceNotFoundError, HttpResponseError):
            # Fall through to the listing check: a directory answers the
            # file-oriented probe with an error rather than False.
            pass
        return self._stat(path) is not None

    def isdir(self, path: str) -> bool:
        entry = self._stat(path)
        return bool(entry is not None and getattr(entry, "is_directory", False))

    def info(self, path: str) -> dict[str, Any]:
        entry = self._stat(path)
        if entry is None:
            raise FileNotFoundError(path)
        modified = getattr(entry, "last_modified", None)
        return {
            "name": self._absolute(self._relative(path)),
            "type": "directory" if getattr(entry, "is_directory", False) else "file",
            "size": getattr(entry, "content_length", 0) or 0,
            "mtime": modified.timestamp() if hasattr(modified, "timestamp") else 0,
        }

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        relative = self._relative(path)
        if not relative:
            return
        try:
            self._client.get_directory_client(relative).create_directory()
        except ResourceExistsError:
            if not exist_ok:
                raise

    def ls(self, path: str, detail: bool = False) -> list[Any]:
        relative = self._relative(path)
        try:
            entries = list(self._client.get_paths(path=relative or None, recursive=False))
        except ResourceNotFoundError:
            return []
        if not detail:
            return [self._absolute(str(entry.name)) for entry in entries]
        return [
            {
                "name": self._absolute(str(entry.name)),
                "type": "directory" if getattr(entry, "is_directory", False) else "file",
                "size": getattr(entry, "content_length", 0) or 0,
            }
            for entry in entries
        ]

    def open(self, path: str, mode: str = "rb", **_: Any) -> Any:
        relative = self._relative(path)
        file_client = self._client.get_file_client(relative)
        if "w" in mode:
            buffer: Any = _UploadBuffer(file_client)
            return io.TextIOWrapper(buffer, encoding="utf-8") if "b" not in mode else buffer
        try:
            content = file_client.download_file().readall()
        except ResourceNotFoundError as exc:
            raise FileNotFoundError(path) from exc
        if isinstance(content, str):
            content = content.encode("utf-8")
        reader: Any = io.BytesIO(content)
        return io.TextIOWrapper(reader, encoding="utf-8") if "b" not in mode else reader

    def rm(self, path: str, recursive: bool = False) -> None:
        relative = self._relative(path)
        if not relative:
            return
        if self.isdir(path):
            try:
                self._client.get_directory_client(relative).delete_directory()
            except ResourceNotFoundError:
                pass
            return
        try:
            self._client.get_file_client(relative).delete_file()
        except ResourceNotFoundError:
            pass

    def mv(self, source: str, destination: str) -> None:
        relative_source = self._relative(source)
        relative_destination = self._relative(destination)
        self._client.get_file_client(relative_source).rename_file(
            new_name=f"{self.workspace}/{relative_destination}"
        )


__all__ = ["OneLakeFileSystem"]
