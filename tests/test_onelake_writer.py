from __future__ import annotations

import json
from pathlib import Path

from azure.core.exceptions import HttpResponseError, ResourceExistsError

from storage.onelake_writer import LAKEHOUSE_FOLDERS, OneLakeWriter


def test_local_onelake_writer_creates_standard_structure(tmp_path: Path) -> None:
    writer = OneLakeWriter(
        workspace_id="workspace",
        lakehouse_id="lakehouse",
        local_root=tmp_path,
    )

    writer.ensure_standard_structure()

    for folder in LAKEHOUSE_FOLDERS:
        assert (tmp_path / "Files" / folder).is_dir()


def test_local_onelake_writer_uploads_catalog_metadata(tmp_path: Path) -> None:
    writer = OneLakeWriter("workspace", "lakehouse", local_root=tmp_path)

    writer.write_json("ontology/metadata/catalog.json", {"tables": ["bronze_resources"]})

    payload = json.loads((tmp_path / "Files/ontology/metadata/catalog.json").read_text())
    assert payload["tables"] == ["bronze_resources"]


def test_table_uri_uses_queryable_tables_area(tmp_path: Path) -> None:
    class Credential:
        def get_token(self, *_scopes):
            return type("Token", (), {"token": "token", "expires_on": 4_102_444_800})()

    local = OneLakeWriter("workspace", "lakehouse", local_root=tmp_path)
    cloud = OneLakeWriter(
        "workspace-id",
        "lakehouse-id",
        workspace_name="Operations Workspace",
        lakehouse_name="Inventory",
        table_schema="dbo",
        credential=Credential(),
    )

    assert local.table_uri("bronze", "resources") == str(tmp_path / "Tables/bronze_resources")
    assert cloud.table_uri("silver", "vm_inventory") == (
        "abfss://workspace-id@onelake.dfs.fabric.microsoft.com/"
        "lakehouse-id/Tables/dbo/silver_vm_inventory"
    )


def test_cloud_writer_uses_workspace_filesystem_and_lakehouse_prefix() -> None:
    calls = []

    class Directory:
        def create_directory(self):
            calls.append("created")

    class File:
        def upload_data(self, content, overwrite):
            calls.append((content, overwrite))

    class FileSystem:
        def get_directory_client(self, path):
            calls.append(path)
            return Directory()

        def get_file_client(self, path):
            calls.append(path)
            return File()

    class Service:
        def get_file_system_client(self, name):
            calls.append(name)
            return FileSystem()

    writer = OneLakeWriter("workspace", "lakehouse", service_client=Service())

    writer.ensure_directory("bronze/resources")
    writer.write_json("ontology/metadata/catalog.json", {"ok": True})

    assert "workspace" in calls
    assert "lakehouse/Files/bronze/resources" in calls
    assert "lakehouse/Files/ontology/metadata/catalog.json" in calls


def test_cloud_directory_creation_is_idempotent() -> None:
    class Directory:
        def create_directory(self):
            raise ResourceExistsError("already exists")

    class FileSystem:
        def get_directory_client(self, _path):
            return Directory()

    class Service:
        def get_file_system_client(self, _name):
            return FileSystem()

    OneLakeWriter("workspace", "lakehouse", service_client=Service()).ensure_directory(
        "bronze/resources"
    )


def _lease_error(code: str) -> HttpResponseError:
    error = HttpResponseError(message=code)
    error.error_code = code
    return error


def test_cloud_sync_lock_breaks_stale_lease_when_already_present() -> None:
    events: list[str] = []

    class Directory:
        def create_directory(self):
            events.append("create_directory")

    class File:
        def create_file(self):
            events.append("create_file")

    class FileSystem:
        def get_directory_client(self, _path):
            return Directory()

        def get_file_client(self, _path):
            return File()

    class Service:
        def get_file_system_client(self, _name):
            return FileSystem()

    class Lease:
        def __init__(self, _file_client):
            self._first = True

        def acquire(self, *, lease_duration):
            events.append(f"acquire:{lease_duration}")
            if self._first:
                self._first = False
                raise _lease_error("LeaseAlreadyPresent")

        def break_lease(self, *, lease_break_period):
            events.append(f"break:{lease_break_period}")
            return 0

        def release(self):
            events.append("release")

    import storage.onelake_writer as module

    original = module.DataLakeLeaseClient
    module.DataLakeLeaseClient = Lease
    try:
        with OneLakeWriter("workspace", "lakehouse", service_client=Service()).sync_lock():
            events.append("inside")
    finally:
        module.DataLakeLeaseClient = original

    assert events == [
        "create_directory",
        "create_file",
        "acquire:-1",
        "break:0",
        "acquire:-1",
        "inside",
        "release",
    ]


def test_cloud_sync_lock_tolerates_lease_id_mismatch_on_release() -> None:
    """A concurrent sync may break and re-acquire our lease before we exit.

    ``release()`` then fails with LeaseIdMismatchWithLeaseOperation because
    the lease ID we hold is stale. That must not fail the sync: the publish
    work inside the ``with`` block already completed successfully.
    """

    class Directory:
        def create_directory(self):
            pass

    class File:
        def create_file(self):
            pass

    class FileSystem:
        def get_directory_client(self, _path):
            return Directory()

        def get_file_client(self, _path):
            return File()

    class Service:
        def get_file_system_client(self, _name):
            return FileSystem()

    class Lease:
        def __init__(self, _file_client):
            pass

        def acquire(self, *, lease_duration):
            pass

        def release(self):
            raise _lease_error("LeaseIdMismatchWithLeaseOperation")

    import storage.onelake_writer as module

    original = module.DataLakeLeaseClient
    module.DataLakeLeaseClient = Lease
    completed = False
    try:
        with OneLakeWriter("workspace", "lakehouse", service_client=Service()).sync_lock():
            completed = True
    finally:
        module.DataLakeLeaseClient = original

    assert completed
