from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.storage.filedatalake import DataLakeLeaseClient, DataLakeServiceClient

from storage.locking import LEASE_DURATION_SECONDS, LeaseLostError, RunLock

_SYNC_LEASE_RENEW_INTERVAL_SECONDS = LEASE_DURATION_SECONDS / 3


class _RenewableSyncLease:
    """Thread-safe lease-loss signal shared with the sync body."""

    def __init__(self) -> None:
        self._error: BaseException | None = None
        self._lock = threading.Lock()

    def mark_lost(self, error: BaseException) -> None:
        with self._lock:
            self._error = error

    @property
    def lost(self) -> bool:
        with self._lock:
            return self._error is not None

    def assert_held(self) -> None:
        with self._lock:
            error = self._error
        if error is not None:
            raise LeaseLostError(
                "Fabric synchronization lease was lost"
            ) from error


LAKEHOUSE_FOLDERS = (
    "bronze/resources",
    "bronze/subscriptions",
    "bronze/resourcegroups",
    "bronze/advisor",
    "bronze/patchassessment",
    "bronze/resource_changes",
    "silver/vm_inventory",
    "silver/server_inventory",
    "silver/compliance",
    "silver/resource_relationships",
    "ontology/entities",
    "ontology/relationships",
    "ontology/metadata",
    "metadata/ingestion_state",
    "metadata/quality_reports",
)


class OneLakeWriter:
    ENDPOINT = "https://onelake.dfs.fabric.microsoft.com"

    def __init__(
        self,
        workspace_id: str,
        lakehouse_id: str,
        *,
        workspace_name: str = "",
        lakehouse_name: str = "",
        table_schema: str = "",
        credential: object | None = None,
        local_root: Path | None = None,
        storage_options: Mapping[str, str] | None = None,
        service_client: DataLakeServiceClient | None = None,
    ) -> None:
        if not workspace_id or not lakehouse_id:
            raise ValueError("workspace_id and lakehouse_id are required")
        if local_root is None and credential is None and service_client is None:
            raise ValueError("Cloud OneLake access requires a credential")
        self.workspace_id = workspace_id
        self.lakehouse_id = lakehouse_id
        self.workspace_name = workspace_name or workspace_id
        self.lakehouse_name = lakehouse_name or lakehouse_id
        self.table_schema = table_schema
        self.local_root = Path(local_root).resolve() if local_root is not None else None
        self.storage_options = dict(storage_options or {})
        self.service = service_client
        if self.local_root is None and self.service is None:
            self.service = DataLakeServiceClient(self.ENDPOINT, credential=credential)

    def ensure_standard_structure(self) -> None:
        for folder in LAKEHOUSE_FOLDERS:
            self.ensure_directory(folder)
        if self.local_root is not None:
            (self.local_root / "Tables").mkdir(parents=True, exist_ok=True)

    def ensure_directory(self, relative_path: str) -> None:
        safe = _safe_relative(relative_path)
        if self.local_root is not None:
            (self.local_root / "Files" / safe).mkdir(parents=True, exist_ok=True)
            return
        file_system = self.service.get_file_system_client(self.workspace_id)
        directory = file_system.get_directory_client(
            str(PurePosixPath(self.lakehouse_id) / "Files" / safe)
        )
        try:
            directory.create_directory()
        except ResourceExistsError:
            pass

    def write_json(self, relative_path: str, payload: Mapping[str, Any]) -> None:
        self.write_bytes(
            relative_path,
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
        )

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        safe = _safe_relative(relative_path)
        if self.local_root is not None:
            path = self.local_root / "Files" / safe
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return
        file_system = self.service.get_file_system_client(self.workspace_id)
        file_client = file_system.get_file_client(
            str(PurePosixPath(self.lakehouse_id) / "Files" / safe)
        )
        file_client.upload_data(content, overwrite=True)

    def table_uri(self, layer: str, table_name: str) -> str:
        table = _table_name(layer, table_name)
        schema_path = f"/{_table_component(self.table_schema)}" if self.table_schema else ""
        if self.local_root is not None:
            base = self.local_root / "Tables"
            if self.table_schema:
                base /= _table_component(self.table_schema)
            return str(base / table)
        return (
            f"abfss://{self.workspace_id}@onelake.dfs.fabric.microsoft.com/"
            f"{self.lakehouse_id}/Tables{schema_path}/{table}"
        )

    def delete_table(self, layer: str, table_name: str) -> None:
        table = _table_name(layer, table_name)
        if self.local_root is not None:
            path = self.local_root / "Tables"
            if self.table_schema:
                path /= _table_component(self.table_schema)
            shutil.rmtree(path / table, ignore_errors=True)
            return
        file_system = self.service.get_file_system_client(self.workspace_id)
        path = PurePosixPath(self.lakehouse_id) / "Tables"
        if self.table_schema:
            path /= _table_component(self.table_schema)
        file_system.get_directory_client(str(path / table)).delete_directory()

    @contextmanager
    def sync_lock(self):
        if self.local_root is not None:
            with RunLock(self.local_root / ".fabric-sync") as lock:
                yield lock
            return
        file_system = self.service.get_file_system_client(self.workspace_id)
        metadata = file_system.get_directory_client(
            str(PurePosixPath(self.lakehouse_id) / "Files/metadata")
        )
        try:
            metadata.create_directory()
        except ResourceExistsError:
            pass
        lock_path = str(PurePosixPath(self.lakehouse_id) / "Files/metadata/ingestion.lock")
        file_client = file_system.get_file_client(lock_path)
        try:
            file_client.create_file()
        except ResourceExistsError:
            pass
        except HttpResponseError as error:
            # The lock file already exists and is currently leased (e.g. by an
            # orphaned lease from a crashed/interrupted prior run). It's safe
            # to leave the existing file in place; the lease acquire/break
            # logic below handles recovery.
            if getattr(error, "error_code", "") != "LeaseIdMissing":
                raise
        lease = DataLakeLeaseClient(file_client)
        try:
            lease.acquire(lease_duration=LEASE_DURATION_SECONDS)
        except HttpResponseError as error:
            if getattr(error, "error_code", "") in {
                "LeaseIdMissing",
                "LeaseAlreadyPresent",
            }:
                raise RuntimeError(
                    "Fabric synchronization is already running"
                ) from error
            raise
        guard = _RenewableSyncLease()
        stop = threading.Event()

        def renew() -> None:
            while not stop.wait(_SYNC_LEASE_RENEW_INTERVAL_SECONDS):
                try:
                    lease.renew()
                except Exception as error:  # noqa: BLE001 - reported to the owner thread.
                    guard.mark_lost(error)
                    stop.set()
                    return

        worker = threading.Thread(
            target=renew,
            name="fabric-sync-lease-renewal",
            daemon=True,
        )
        worker.start()
        try:
            yield guard
            guard.assert_held()
        finally:
            stop.set()
            worker.join()
            try:
                if not guard.lost:
                    lease.release()
            except HttpResponseError:
                # A finite lease expires without manual recovery if release
                # cannot be observed, so do not mask the publication outcome.
                pass


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"OneLake path must be relative and contained: {value}")
    return path


def _table_name(layer: str, name: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    candidate = f"{layer}_{name}".lower().replace("-", "_")
    if not candidate or any(character not in allowed for character in candidate):
        raise ValueError(f"Invalid Delta table name: {candidate}")
    return candidate


def _table_component(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    if not value or any(character not in allowed for character in value):
        raise ValueError(f"Invalid Lakehouse schema: {value}")
    return value
