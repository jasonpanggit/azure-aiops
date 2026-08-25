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

import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hermes_arg_connector.fs import ONELAKE_HOST, is_onelake_uri

try:  # pragma: no cover - azure-core is always installed alongside adlfs
    from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
except ImportError:  # pragma: no cover - local-disk-only environments
    HttpResponseError = ()  # type: ignore[assignment]
    ResourceNotFoundError = ()  # type: ignore[assignment]


class DocumentConflictError(RuntimeError):
    """Raised when a concurrent writer advanced the revision mid-update."""


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
        """
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
            return {}
        return payload if isinstance(payload, dict) else {}

    def write(self, name: str, payload: dict[str, Any], *, expected_revision: int) -> None:
        """Persist ``payload`` if the stored revision still matches.

        The check-then-write pair is guarded by a process-local lock so
        concurrent threads in one replica serialize; cross-replica safety
        comes from the revision comparison itself, which turns a lost update
        into a :class:`DocumentConflictError` the caller retries.
        """
        with self._lock:
            current = int(self.read(name).get("revision") or 0)
            if current != expected_revision:
                raise DocumentConflictError(
                    f"Document {name} changed during update (revision {current}, "
                    f"expected {expected_revision}); reload and retry"
                )
            body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
            path = self._path(name)
            if self.is_remote:
                file_client = self._client().get_file_client(path)
                data = body.encode("utf-8")
                # upload_data() creates the file and, with overwrite=True,
                # commits it in a single DFS "create" + "append" + "flush"
                # sequence -- no Blob Service calls involved, so it works
                # against OneLake's DFS-only endpoint.
                file_client.upload_data(data, overwrite=True, length=len(data))
            else:
                local_path = Path(path)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text(body, encoding="utf-8")

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


__all__ = ["DocumentConflictError", "OneLakeDocumentStore"]
