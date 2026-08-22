from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Self
from urllib.parse import urlparse


def _is_remote_root(root: str) -> bool:
    return urlparse(root).scheme in ("abfss", "abfs", "az")


class RunLock:
    """Cross-replica, non-blocking writer lock for one connector data root.

    Production deployments use a PostgreSQL advisory lock when
    ``HERMES_DATABASE_URL`` is configured. Local deployments retain the
    filesystem lock.
    """

    def __init__(self, root: Path | str) -> None:
        root_str = str(root)
        if _is_remote_root(root_str):
            import hashlib
            import tempfile

            digest = hashlib.sha256(root_str.encode()).hexdigest()[:16]
            self.root = Path(tempfile.gettempdir()) / "hermes-locks" / digest
        else:
            self.root = Path(root_str)
        self.path = self.root / "state" / "run.lock"
        self._handle = None
        self._database = None
        self._lock_key = root_str

    def __enter__(self) -> Self:
        dsn = os.environ.get("HERMES_DATABASE_URL", "").strip()
        if dsn and _is_remote_root(self._lock_key):
            import psycopg

            self._database = psycopg.connect(dsn)
            with self._database.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_lock(hashtext(%s))",
                    (self._lock_key,),
                )
                acquired = bool(cursor.fetchone()[0])
            if not acquired:
                self._database.close()
                self._database = None
                raise RuntimeError(
                    f"Azure Resource Graph ingestion is already running for {self.root}"
                )
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if sys.platform != "win32":
            self.path.parent.chmod(0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        self._handle = os.fdopen(descriptor, "r+")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError(f"Azure Resource Graph ingestion is already running for {self.root}") from exc
        return self

    def __exit__(self, *_args) -> None:
        if self._database is not None:
            with self._database.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    (self._lock_key,),
                )
            self._database.close()
            self._database = None
            return
        if self._handle is None:
            return
        if sys.platform == "win32":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
