from __future__ import annotations

from typing import Any

from .fabric_client import FabricClient


class WorkspaceManager:
    def __init__(self, client: FabricClient) -> None:
        self.client = client

    def resolve(
        self,
        *,
        workspace_id: str = "",
        workspace_name: str = "",
    ) -> dict[str, Any]:
        if workspace_id:
            return self.client.request("GET", f"/workspaces/{workspace_id}")
        if not workspace_name:
            raise ValueError("Configure fabric.workspace_id or fabric.workspace_name")
        matches = [
            item
            for item in self.client.iter_items("/workspaces")
            if str(item.get("displayName") or "").casefold() == workspace_name.casefold()
        ]
        if not matches:
            raise LookupError(f"Fabric workspace not found: {workspace_name}")
        if len(matches) > 1:
            raise LookupError(f"Fabric workspace name is ambiguous: {workspace_name}")
        return matches[0]
