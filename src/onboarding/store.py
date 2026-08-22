"""Storage backends for :class:`~onboarding.registry.ConnectionRegistry`.

The registry itself only knows how to read/write a single JSON payload with
an optimistic-concurrency revision counter. This module supplies two
interchangeable backends for that payload:

- :class:`FileRegistryStore` -- the original behaviour, a single JSON file
  under ``$HERMES_HOME/state/subscription_connections.json``. Simple and
  fine for local development, but not safe against ephemeral/container-local
  disks in production.
- :class:`PostgresRegistryStore` -- persists the same JSON payload as a
  single row in a Postgres table, guarded by the same revision counter
  (compare-and-swap via ``UPDATE ... WHERE revision = %s``). This is the
  production backend when ``HERMES_DATABASE_URL`` is configured, since it
  survives container restarts/redeploys without requiring a mounted volume.

Both backends expose the same tiny interface: ``read() -> dict`` and
``write(payload: dict, *, expected_revision: int) -> None``.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Protocol

from hermes_arg_connector.state import _atomic_text

ENV_DATABASE_URL = "HERMES_DATABASE_URL"


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
        _atomic_text(self.path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


class PostgresRegistryStore:
    """Postgres-backed store: one JSONB row, guarded by a revision column.

    Uses a single row (``id = 1``) in ``connection_registry`` as the source of
    truth. Concurrency safety comes from a conditional ``UPDATE ... WHERE
    revision = %s`` (compare-and-swap) instead of file locking.
    """

    _TABLE_DDL = """
        CREATE TABLE IF NOT EXISTS connection_registry (
            id SMALLINT PRIMARY KEY,
            revision INTEGER NOT NULL,
            payload JSONB NOT NULL
        )
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        import psycopg  # imported lazily so file-backed deployments don't need it

        return psycopg.connect(self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._TABLE_DDL)
            conn.commit()

    def read(self) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT revision, payload FROM connection_registry WHERE id = 1")
            row = cur.fetchone()
        if row is None:
            return {}
        revision, payload = row
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = dict(payload or {})
        payload["revision"] = revision
        return payload

    def write(self, payload: dict[str, Any], *, expected_revision: int) -> None:
        body = json.dumps(payload)
        new_revision = int(payload.get("revision") or expected_revision + 1)
        with self._lock, self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT revision FROM connection_registry WHERE id = 1 FOR UPDATE"
            )
            row = cur.fetchone()
            current = int(row[0]) if row else 0
            if current != expected_revision:
                conn.rollback()
                raise RegistryStoreConflictError(
                    f"Registry changed during update (revision {current}, expected "
                    f"{expected_revision}); reload the connection and retry"
                )
            if row is None:
                cur.execute(
                    "INSERT INTO connection_registry (id, revision, payload) "
                    "VALUES (1, %s, %s::jsonb)",
                    (new_revision, body),
                )
            else:
                cur.execute(
                    "UPDATE connection_registry SET revision = %s, payload = %s::jsonb "
                    "WHERE id = 1 AND revision = %s",
                    (new_revision, body, expected_revision),
                )
            conn.commit()


def default_store(root: Path | str) -> RegistryStore:
    """Pick the backend based on ``HERMES_DATABASE_URL``.

    Falls back to the file-based store (rooted at ``root``) when the env var
    is unset, which keeps local development working with zero configuration.
    """
    dsn = os.environ.get(ENV_DATABASE_URL)
    if dsn:
        return PostgresRegistryStore(dsn)
    return FileRegistryStore(root)


__all__ = [
    "ENV_DATABASE_URL",
    "FileRegistryStore",
    "PostgresRegistryStore",
    "RegistryStore",
    "RegistryStoreConflictError",
    "default_store",
]
