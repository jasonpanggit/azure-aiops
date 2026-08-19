from __future__ import annotations

import json
from pathlib import Path

from azure.core.exceptions import ResourceExistsError

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
