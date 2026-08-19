from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from .fabric_client import FabricClient


class LakehouseManager:
    def __init__(self, client: FabricClient, workspace_id: str) -> None:
        self.client = client
        self.workspace_id = workspace_id

    @property
    def base_path(self) -> str:
        return f"/workspaces/{self.workspace_id}/lakehouses"

    def resolve(
        self,
        *,
        lakehouse_id: str = "",
        lakehouse_name: str = "",
        create_if_missing: bool = False,
        enable_schemas: bool = False,
    ) -> dict[str, Any]:
        if lakehouse_id:
            return self.client.request("GET", f"{self.base_path}/{lakehouse_id}")
        if not lakehouse_name:
            raise ValueError("Configure fabric.lakehouse_id or fabric.lakehouse_name")
        matches = [
            item
            for item in self.client.iter_items(self.base_path)
            if str(item.get("displayName") or "").casefold() == lakehouse_name.casefold()
        ]
        if len(matches) > 1:
            raise LookupError(f"Fabric lakehouse name is ambiguous: {lakehouse_name}")
        if matches:
            return matches[0]
        if not create_if_missing:
            raise LookupError(f"Fabric lakehouse not found: {lakehouse_name}")
        body: dict[str, Any] = {
            "displayName": lakehouse_name,
            "description": "Hermes Operations Graph inventory lakehouse",
        }
        if enable_schemas:
            body["creationPayload"] = {"enableSchemas": True}
        return self.client.request(
            "POST",
            self.base_path,
            json_body=body,
        )

    def list_tables(self, lakehouse_id: str) -> list[dict[str, Any]]:
        return list(self.client.iter_items(f"{self.base_path}/{lakehouse_id}/tables"))

    def ensure_tables_registered(
        self,
        lakehouse_id: str,
        expected: set[str],
        *,
        attempts: int = 20,
        sleep: Callable[[float], None] = time.sleep,
    ) -> set[str]:
        if not expected:
            return set()
        for attempt in range(attempts):
            present = {
                str(table.get("name") or table.get("displayName") or "")
                for table in self.list_tables(lakehouse_id)
            }
            if expected <= present:
                return expected
            if attempt + 1 < attempts:
                sleep(min(2 ** attempt, 30))
        missing = sorted(expected - present)
        raise TimeoutError("Delta tables were not registered by Fabric: " + ", ".join(missing))

    def create_shortcut(
        self,
        lakehouse_id: str,
        *,
        path: str,
        name: str,
        target: dict[str, Any],
        conflict_policy: str = "CreateOrOverwrite",
    ) -> dict[str, Any]:
        return self.client.request(
            "POST",
            f"/workspaces/{self.workspace_id}/items/{lakehouse_id}/shortcuts",
            params={"shortcutConflictPolicy": conflict_policy},
            json_body={"path": path, "name": name, "target": target},
        )

    def load_table_from_files(
        self,
        lakehouse_id: str,
        table_name: str,
        *,
        relative_path: str,
        mode: str = "Overwrite",
        file_format: str = "Parquet",
    ) -> dict[str, Any]:
        return self.client.request(
            "POST",
            f"{self.base_path}/{lakehouse_id}/tables/{quote(table_name, safe='')}/load",
            json_body={
                "relativePath": relative_path,
                "pathType": "File",
                "mode": mode,
                "recursive": True,
                "formatOptions": {"format": file_format},
            },
        )
