"""Non-blocking writer lock for one connector data root.

Replaces the PostgreSQL advisory lock the connector previously used, keeping
every piece of runtime state in Fabric.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Self
from urllib.parse import urlparse

from storage.fs import is_onelake_uri
from storage.onelake_documents import (
    DocumentConflictError,
    OneLakeDocumentStore,
)

_LOGGER = logging.getLogger(__name__)

# A finite lease that is renewed for as long as the holder lives, rather than
# an infinite one: a replica killed mid-ingestion (OOM, node drain) never runs
# its release, and an infinite lease would then block ingestion permanently
# with no way to recover short of manual intervention.
LEASE_DURATION_SECONDS = 60


class LeaseLostError(RuntimeError):
    """Raised once a finite service lease can no longer be renewed."""


@dataclass(frozen=True)
class FenceToken:
    """Monotonic token proving one writer is newer than its predecessors."""

    scope: str
    owner_id: str
    value: int
    etag: str


class MonotonicFenceAllocator:
    """Allocate per-scope fences through storage-service CAS."""

    def __init__(
        self,
        documents: OneLakeDocumentStore,
        *,
        max_attempts: int = 16,
    ) -> None:
        self._documents = documents
        self._max_attempts = max_attempts

    def allocate(self, *, scope: str, owner_id: str) -> FenceToken:
        normalized_scope = str(scope).strip().casefold()
        normalized_owner = str(owner_id).strip()
        if not normalized_scope or not normalized_owner:
            raise ValueError("fence scope and owner_id are required")
        key = hashlib.sha256(normalized_scope.encode()).hexdigest()
        name = f"state/fences/{key}.json"
        for _attempt in range(self._max_attempts):
            snapshot = self._documents.read_snapshot(name)
            value = int(snapshot.payload.get("fence") or 0) + 1
            payload = {
                "scope": normalized_scope,
                "owner_id": normalized_owner,
                "fence": value,
            }
            try:
                if snapshot.etag is None:
                    written = self._documents.create_only(name, payload)
                else:
                    written = self._documents.replace_if_match(
                        name,
                        payload,
                        expected_etag=snapshot.etag,
                    )
            except DocumentConflictError:
                continue
            if written.etag is None:  # pragma: no cover - storage contract guard
                raise RuntimeError("fence write returned no ETag")
            return FenceToken(
                scope=normalized_scope,
                owner_id=normalized_owner,
                value=value,
                etag=written.etag,
            )
        raise DocumentConflictError(
            f"Could not allocate a fence for {normalized_scope}; retry later"
        )


class RunLock:
    """Cross-replica, non-blocking writer lock for one connector data root.

    Local roots use an OS file lock. OneLake roots take a *lease* on a lock
    file: a lease is granted by the service to exactly one holder, so unlike
    a create-then-read-back check it has no race window, and because it
    expires it self-heals after a replica dies without releasing it.
    """

    LOCK_DOCUMENT = "state/run.lock"

    def __init__(
        self,
        root: Path | str,
        *,
        service_client: object | None = None,
        lock_document: str = LOCK_DOCUMENT,
    ) -> None:
        document = PurePosixPath(lock_document)
        if (
            not lock_document
            or document.is_absolute()
            or ".." in document.parts
            or "." in document.parts
        ):
            raise ValueError("lock document must be a safe contained relative path")
        self.lock_document = document.as_posix()
        root_str = str(root)
        self.is_remote = is_onelake_uri(root_str)
        self._service_client = service_client
        self._lease = None
        self._lease_lost = False
        if self.is_remote:
            self.root = root_str.rstrip("/")
            self.path = f"{self.root}/{self.lock_document}"
        else:
            self.root = Path(root_str)
            self.path = self.root / Path(self.lock_document)
        self._handle = None

    def _busy(self) -> RuntimeError:
        return RuntimeError(f"Azure Resource Graph ingestion is already running for {self.root}")

    def _lock_file_client(self):
        """Resolve the OneLake lock file through the Data Lake SDK.

        fsspec is not used here: leases are a Data Lake protocol feature that
        the fsspec layer does not surface.
        """
        from azure.identity import DefaultAzureCredential
        from azure.storage.filedatalake import DataLakeServiceClient

        parsed = urlparse(self.root)
        workspace = parsed.netloc.split("@")[0]
        # netloc is "<workspace>@onelake.dfs.fabric.microsoft.com"; the path is
        # "/<lakehouse>/Files/<...>", whose first segment names the lakehouse.
        segments = [segment for segment in parsed.path.split("/") if segment]
        if not workspace or not segments:
            raise ValueError(f"Cannot derive a OneLake lock path from {self.root!r}")
        service = self._service_client or DataLakeServiceClient(
            account_url=f"https://{parsed.netloc.split('@')[-1]}",
            credential=DefaultAzureCredential(),
        )
        file_system = service.get_file_system_client(workspace)
        lock_path = PurePosixPath(*segments) / self.lock_document
        return file_system.get_file_client(str(lock_path))

    def _acquire_remote(self) -> None:
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.filedatalake import DataLakeLeaseClient

        file_client = self._lock_file_client()
        try:
            # Creating the file unconditionally would break the lease held by
            # a running peer, so only create it when it is absent.
            if not file_client.exists():
                file_client.create_file()
        except ResourceExistsError:
            pass
        lease = DataLakeLeaseClient(file_client)
        try:
            lease.acquire(lease_duration=LEASE_DURATION_SECONDS)
        except Exception as exc:
            raise self._busy() from exc
        self._lease = lease
        self._lease_lost = False

    def renew(self) -> None:
        """Extend the lease. Long ingestions must call this periodically."""
        if self._lease is not None:
            try:
                self._lease.renew()
            except Exception as exc:
                self._lease_lost = True
                raise LeaseLostError(f"run lock lease lost for {self.root}") from exc

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost

    def assert_held(self) -> None:
        """Fail a consequential write after renewal reports lease loss."""

        if self._lease_lost:
            raise LeaseLostError(f"run lock lease lost for {self.root}")

    def __enter__(self) -> Self:
        if self.is_remote:
            self._acquire_remote()
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
            raise self._busy() from exc
        return self

    def __exit__(self, *_args) -> None:
        if self.is_remote:
            if self._lease is not None:
                if not self._lease_lost:
                    try:
                        self._lease.release()
                    except Exception:
                        # A release failure is not actionable: the lease expires
                        # on its own, so the lock recovers either way.
                        _LOGGER.debug(
                            "run_lock_release_failed root=%s",
                            self.root,
                            exc_info=True,
                        )
                self._lease = None
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
