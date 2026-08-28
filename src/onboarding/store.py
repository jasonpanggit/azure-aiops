"""Storage backends for :class:`~onboarding.registry.ConnectionRegistry`.

The registry itself only knows how to read/write a single JSON payload with
an optimistic-concurrency revision counter. This module supplies two
interchangeable backends for that payload:

- :class:`FileRegistryStore` -- a single JSON file under
  ``$AIOPS_HOME/state/subscription_connections.json``. Used when
  ``AIOPS_HOME`` is a local path (development).
- :class:`OneLakeRegistryStore` -- persists the same JSON payload as a
  document in OneLake, guarded by the same revision counter
  (compare-and-swap). This is the production backend whenever
  ``AIOPS_HOME`` points at OneLake, since it survives container
  restarts/redeploys without requiring a mounted volume or a separate
  database.

Both backends expose the same tiny interface: ``read() -> dict`` and
``write(payload: dict, *, expected_revision: int) -> None``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from storage.datasets import atomic_text
from storage.fs import is_onelake_uri
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

REGISTRY_DOCUMENT = "state/subscription_connections.json"


class RegistryStore(Protocol):
    """Backend contract used by :class:`ConnectionRegistry`."""

    def read(self) -> dict[str, Any]: ...

    def write(self, payload: dict[str, Any], *, expected_revision: int) -> None: ...


class RegistryStoreConflictError(RuntimeError):
    """Raised when a concurrent writer advanced the revision mid-update."""


class FileRegistryStore:
    """JSON-file backed store (default for local development)."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "state" / "subscription_connections.json"

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def write(self, payload: dict[str, Any], *, expected_revision: int) -> None:
        current = int(self.read().get("revision") or 0)
        if current != expected_revision:
            raise RegistryStoreConflictError(
                f"Registry changed during update (revision {current}, expected "
                f"{expected_revision}); reload the connection and retry"
            )
        atomic_text(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


class OneLakeRegistryStore:
    """OneLake-backed store: one JSON document, guarded by a revision field.

    Concurrency safety comes from the document store's compare-and-swap on
    ``revision``, exactly as the previous Postgres backend did with a
    conditional ``UPDATE``.
    """

    def __init__(self, root: str) -> None:
        self.documents = OneLakeDocumentStore(root)

    def read(self) -> dict[str, Any]:
        return self.documents.read(REGISTRY_DOCUMENT)

    def write(self, payload: dict[str, Any], *, expected_revision: int) -> None:
        try:
            self.documents.write(
                REGISTRY_DOCUMENT, payload, expected_revision=expected_revision
            )
        except DocumentConflictError as exc:
            raise RegistryStoreConflictError(str(exc)) from exc


def default_store(root: Path | str) -> RegistryStore:
    """Pick the backend based on the shape of ``root``.

    A OneLake URI selects the OneLake document store; a plain path keeps the
    file-based store, so local development works with zero configuration.
    """
    if is_onelake_uri(root):
        return OneLakeRegistryStore(str(root))
    return FileRegistryStore(str(root))


__all__ = [
    "REGISTRY_DOCUMENT",
    "FileRegistryStore",
    "OneLakeRegistryStore",
    "RegistryStore",
    "RegistryStoreConflictError",
    "default_store",
]
