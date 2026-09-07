"""Small revisioned JSON documents stored in OneLake.

The Fabric lakehouse holds two very different kinds of state:

- Large tabular datasets (inventory, ontology, changes) -- Delta tables under
  ``Tables/``, written by :mod:`storage.delta_writer`.
- Small control-plane documents (the subscription-connection registry, risk
  exceptions, cached CVE enrichment) -- single JSON blobs under ``Files/``.

This module owns the second kind. Previously those documents lived in
PostgreSQL; keeping them in OneLake removes the separate database from the
deployment while preserving the two properties the callers depend on:

- **Optimistic concurrency.** :meth:`OneLakeDocumentStore.write` performs a
  compare-and-swap against a ``revision`` field, so a replica that read a
  stale document cannot silently clobber a concurrent writer. This replaces
  the ``UPDATE ... WHERE revision = %s`` guard the Postgres store used.
- **Local development parity.** A plain filesystem root behaves identically,
  so local runs exercise the same code path as production.

Remote reads/writes talk to OneLake through ``azure-storage-file-datalake``'s
native ADLS Gen2 DFS client rather than through ``adlfs``/``fsspec``. OneLake's
endpoint (``onelake.dfs.fabric.microsoft.com``) only implements the DFS REST
surface; ``adlfs`` falls back to classic Blob Service calls (``list_blobs`` for
``exists()``, staged-block/``upload_blob`` for writes) for several operations,
all of which OneLake rejects with ``IncorrectEndpointError``. The DFS-native
client avoids that fallback entirely.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from storage.fs import ONELAKE_HOST, is_onelake_uri

try:  # pragma: no cover - azure-core is always installed alongside adlfs
    from azure.core import MatchConditions
    from azure.core.exceptions import (
        HttpResponseError,
        ResourceExistsError,
        ResourceModifiedError,
        ResourceNotFoundError,
    )
except ImportError:  # pragma: no cover - local-disk-only environments
    MatchConditions = None  # type: ignore[assignment,misc]
    HttpResponseError = ()  # type: ignore[assignment]
    ResourceExistsError = ()  # type: ignore[assignment]
    ResourceModifiedError = ()  # type: ignore[assignment]
    ResourceNotFoundError = ()  # type: ignore[assignment]


class DocumentConflictError(RuntimeError):
    """Raised when a concurrent writer advanced the revision mid-update."""


@dataclass(frozen=True)
class DocumentSnapshot:
    """One JSON document read together with its storage concurrency token."""

    payload: dict[str, Any]
    etag: str | None

    @property
    def exists(self) -> bool:
        return self.etag is not None


def _document_body(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _local_etag(body: bytes) -> str:
    return f'"sha256:{hashlib.sha256(body).hexdigest()}"'


@contextmanager
def _interprocess_lock(path: Path):
    """Serialize local document updates across processes."""
    lock_path = Path(f"{path}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":  # pragma: no cover - exercised on Windows CI
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class OneLakeDocumentStore:
    """Revisioned JSON documents under a OneLake (or local) root.

    ``root`` is either a local directory or a OneLake URI of the form
    ``abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>/Files/<path>``.
    Documents are addressed by a relative name (``state/connections.json``).
    """

    def __init__(self, root: Path | str) -> None:
        self.root = str(root).rstrip("/")
        self.is_remote = is_onelake_uri(self.root)
        self._lock = threading.Lock()
        self._file_system_client = None
        self._base = self.root if not self.is_remote else None

    def _client(self):
        # Resolved lazily so constructing a store never requires credentials
        # (tests and local runs build one before any Azure identity exists).
        if self._file_system_client is None:
            from azure.identity import DefaultAzureCredential
            from azure.storage.filedatalake import FileSystemClient

            parsed = urlparse(self.root)
            workspace, _, host = parsed.netloc.partition("@")
            if host.lower() != ONELAKE_HOST:
                raise ValueError(
                    f"Only OneLake roots are supported ({ONELAKE_HOST}); got {self.root!r}."
                )
            self._base = parsed.path.strip("/")
            self._file_system_client = FileSystemClient(
                account_url=f"https://{ONELAKE_HOST}",
                file_system_name=workspace,
                credential=DefaultAzureCredential(),
            )
        return self._file_system_client

    def _path(self, name: str) -> str:
        safe = Path(name)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"Document name must be relative and contained: {name}")
        if self.is_remote:
            self._client()
            return f"{self._base}/{safe.as_posix()}"
        return f"{self._base}/{safe.as_posix()}"

    def read(self, name: str) -> dict[str, Any]:
        """Return the document, or ``{}`` when it does not exist yet.

        A missing or malformed document reads as empty rather than raising:
        callers treat "no document" and "unreadable document" identically
        (start from scratch), and a corrupt blob must not take the API down.

        Guarded by the same lock as :meth:`write`: ``upload_data`` on OneLake's
        DFS endpoint is a non-atomic create/append/flush sequence, so an
        unguarded read racing a concurrent write in this process could observe
        a partially-written (empty or truncated) file, fail to parse it, and
        silently return ``{}`` -- making an existing connection look
        "not registered" for the instant the write was in flight. The lock
        only serializes this process's own threads; cross-replica safety
        comes from the conditional ETag write in :meth:`write`.
        """
        with self._lock:
            return self._read_locked(name)

    def read_or_raise(self, name: str) -> dict[str, Any]:
        """Return a document while preserving missing-vs-unreadable semantics."""
        with self._lock:
            return self._read_locked(name, suppress_errors=False)

    def read_snapshot(self, name: str) -> DocumentSnapshot:
        """Read a JSON object and the exact ETag that guarded that read.

        Unlike :meth:`read`, this consequential-write primitive fails closed
        on malformed or unavailable content.  Remote reads pin the download to
        the properties ETag, so callers never pair one payload with another
        version's token.
        """

        with self._lock:
            path = self._path(name)
            if self.is_remote:
                file_client = self._client().get_file_client(path)
                try:
                    properties = file_client.get_file_properties()
                    etag = str(properties.etag)
                    downloaded = file_client.download_file(
                        etag=etag,
                        match_condition=MatchConditions.IfNotModified,
                    )
                    body = downloaded.readall()
                except ResourceNotFoundError:
                    return DocumentSnapshot(payload={}, etag=None)
                except ResourceModifiedError as exc:
                    raise DocumentConflictError(
                        f"Document {name} changed while it was read; reload and retry"
                    ) from exc
            else:
                local_path = Path(path)
                with _interprocess_lock(local_path):
                    try:
                        body = local_path.read_bytes()
                    except FileNotFoundError:
                        return DocumentSnapshot(payload={}, etag=None)
                    etag = _local_etag(body)
            try:
                payload = json.loads(body)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"Document {name} contains invalid JSON") from exc
            if not isinstance(payload, dict):
                raise TypeError(f"Document {name} must contain a JSON object")
            return DocumentSnapshot(payload=payload, etag=etag)

    def create_only(
        self,
        name: str,
        payload: dict[str, Any],
    ) -> DocumentSnapshot:
        """Create an immutable JSON record, failing if it already exists."""

        body = _document_body(payload)
        with self._lock:
            path = self._path(name)
            if self.is_remote:
                file_client = self._client().get_file_client(path)
                try:
                    result = file_client.upload_data(
                        body,
                        overwrite=False,
                        length=len(body),
                    )
                except (ResourceExistsError, ResourceModifiedError) as exc:
                    raise DocumentConflictError(
                        f"Document {name} already exists"
                    ) from exc
                etag = str((result or {}).get("etag") or "")
                if not etag:
                    etag = str(file_client.get_file_properties().etag)
            else:
                local_path = Path(path)
                with _interprocess_lock(local_path):
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        descriptor = os.open(
                            local_path,
                            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                            0o600,
                        )
                    except FileExistsError as exc:
                        raise DocumentConflictError(
                            f"Document {name} already exists"
                        ) from exc
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(body)
                        handle.flush()
                        os.fsync(handle.fileno())
                    etag = _local_etag(body)
        return DocumentSnapshot(payload=dict(payload), etag=etag)

    def replace_if_match(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        expected_etag: str | None,
    ) -> DocumentSnapshot:
        """Replace a document only when storage still has ``expected_etag``."""

        if not expected_etag:
            raise DocumentConflictError(
                f"Document {name} has no predecessor ETag; use create_only"
            )
        body = _document_body(payload)
        with self._lock:
            path = self._path(name)
            if self.is_remote:
                file_client = self._client().get_file_client(path)
                try:
                    result = file_client.upload_data(
                        body,
                        overwrite=True,
                        length=len(body),
                        etag=expected_etag,
                        match_condition=MatchConditions.IfNotModified,
                    )
                except (ResourceNotFoundError, ResourceModifiedError) as exc:
                    raise DocumentConflictError(
                        f"Document {name} ETag changed; reload and retry"
                    ) from exc
                etag = str((result or {}).get("etag") or "")
                if not etag:
                    etag = str(file_client.get_file_properties().etag)
            else:
                local_path = Path(path)
                with _interprocess_lock(local_path):
                    try:
                        current_body = local_path.read_bytes()
                    except FileNotFoundError as exc:
                        raise DocumentConflictError(
                            f"Document {name} ETag changed; reload and retry"
                        ) from exc
                    if _local_etag(current_body) != expected_etag:
                        raise DocumentConflictError(
                            f"Document {name} ETag changed; reload and retry"
                        )
                    temporary_path = ""
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="wb",
                            dir=local_path.parent,
                            prefix=f".{local_path.name}.",
                            suffix=".tmp",
                            delete=False,
                        ) as temporary:
                            temporary.write(body)
                            temporary.flush()
                            os.fsync(temporary.fileno())
                            temporary_path = temporary.name
                        os.chmod(temporary_path, 0o600)
                        os.replace(temporary_path, local_path)
                    finally:
                        if temporary_path:
                            Path(temporary_path).unlink(missing_ok=True)
                    etag = _local_etag(body)
        return DocumentSnapshot(payload=dict(payload), etag=etag)

    def _read_locked(
        self,
        name: str,
        *,
        suppress_errors: bool = True,
    ) -> dict[str, Any]:
        # Validate containment before the fail-open transport boundary. An
        # invalid caller-supplied name is a programming error, not a missing
        # or temporarily unreadable document.
        path = self._path(name)
        try:
            if self.is_remote:
                file_client = self._client().get_file_client(path)
                try:
                    downloaded = file_client.download_file()
                except ResourceNotFoundError:
                    return {}
                payload = json.loads(downloaded.readall())
            else:
                local_path = Path(path)
                if not local_path.exists():
                    return {}
                payload = json.loads(local_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, HttpResponseError):
            if suppress_errors:
                return {}
            raise
        if isinstance(payload, dict):
            return payload
        if suppress_errors:
            return {}
        raise ValueError(f"Document {name} must contain a JSON object")

    def write(self, name: str, payload: dict[str, Any], *, expected_revision: int) -> None:
        """Persist ``payload`` if the stored revision still matches.

        Local updates use an inter-process lock and atomic replacement.
        OneLake updates use the ETag read with the document as an ``If-Match``
        precondition, so two replicas cannot both commit from one revision.
        """
        with self._lock:
            body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            path = self._path(name)
            if self.is_remote:
                file_client = self._client().get_file_client(path)
                data = body.encode("utf-8")
                try:
                    properties = file_client.get_file_properties()
                    etag = str(properties.etag)
                    downloaded = file_client.download_file(
                        etag=etag,
                        match_condition=MatchConditions.IfNotModified,
                    )
                    current_payload = json.loads(downloaded.readall())
                    if not isinstance(current_payload, dict):
                        raise TypeError(
                            f"Document {name} must contain a JSON object"
                        )
                except ResourceNotFoundError:
                    etag = ""
                    current_payload = {}
                except ResourceModifiedError as exc:
                    raise DocumentConflictError(
                        f"Document {name} changed while it was read; reload and retry"
                    ) from exc
                current = int(current_payload.get("revision") or 0)
                if current != expected_revision:
                    raise DocumentConflictError(
                        f"Document {name} changed during update (revision {current}, "
                        f"expected {expected_revision}); reload and retry"
                    )
                try:
                    if etag:
                        file_client.upload_data(
                            data,
                            overwrite=True,
                            length=len(data),
                            etag=etag,
                            match_condition=MatchConditions.IfNotModified,
                        )
                    else:
                        file_client.upload_data(
                            data,
                            overwrite=False,
                            length=len(data),
                        )
                except (ResourceExistsError, ResourceModifiedError) as exc:
                    raise DocumentConflictError(
                        f"Document {name} changed during update; reload and retry"
                    ) from exc
            else:
                local_path = Path(path)
                with _interprocess_lock(local_path):
                    current = int(
                        self._read_locked(
                            name,
                            suppress_errors=False,
                        ).get("revision")
                        or 0
                    )
                    if current != expected_revision:
                        raise DocumentConflictError(
                            f"Document {name} changed during update "
                            f"(revision {current}, expected {expected_revision}); "
                            "reload and retry"
                        )
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary_path = ""
                    try:
                        with tempfile.NamedTemporaryFile(
                            mode="w",
                            encoding="utf-8",
                            dir=local_path.parent,
                            prefix=f".{local_path.name}.",
                            suffix=".tmp",
                            delete=False,
                        ) as temporary:
                            temporary.write(body)
                            temporary.flush()
                            os.fsync(temporary.fileno())
                            temporary_path = temporary.name
                        os.replace(temporary_path, local_path)
                    finally:
                        if temporary_path:
                            Path(temporary_path).unlink(missing_ok=True)

    def put(self, name: str, payload: dict[str, Any]) -> None:
        """Write ``payload`` unconditionally, bumping its revision.

        For last-writer-wins documents (the enrichment cache) where a
        conflict is not worth a retry: losing a concurrent cache write only
        costs one upstream lookup.
        """
        current = int(self.read(name).get("revision") or 0)
        document = dict(payload)
        document["revision"] = current + 1
        try:
            self.write(name, document, expected_revision=current)
        except DocumentConflictError:
            return


__all__ = [
    "DocumentConflictError",
    "DocumentSnapshot",
    "OneLakeDocumentStore",
]
