from __future__ import annotations

from typing import Any

from fabric.auth import build_credential
from fabric.config import FabricRuntimeConfig
from fabric.fabric_client import FabricClient

SUPPORTED_ITEM_TYPES = {"Lakehouse", "MirroredDatabase"}


def _default_fabric_client() -> FabricClient:
    config = FabricRuntimeConfig.load("fabric.config.yaml")
    return FabricClient(build_credential(config.auth))


def _item_type(client: FabricClient, workspace_id: str, item_id: str) -> str:
    item = client.request("GET", f"/workspaces/{workspace_id}/items/{item_id}")
    return str(item.get("type") or "")


def _assert_supported(item_type: str) -> None:
    if item_type and item_type not in SUPPORTED_ITEM_TYPES:
        supported = ", ".join(sorted(SUPPORTED_ITEM_TYPES))
        raise ValueError(
            f"Data access roles are only supported for {supported}; item type was {item_type!r}"
        )


def list_roles(workspace_id: str, item_id: str, *, client: FabricClient | None = None) -> list[dict[str, Any]]:
    if not workspace_id or not item_id:
        raise ValueError("workspace_id and item_id are required")
    active_client = client or _default_fabric_client()
    _assert_supported(_item_type(active_client, workspace_id, item_id))
    endpoint = f"/workspaces/{workspace_id}/items/{item_id}/dataAccessRoles"
    return list(active_client.iter_items(endpoint))


def get_role(
    workspace_id: str,
    item_id: str,
    role_name: str,
    *,
    client: FabricClient | None = None,
) -> dict[str, Any] | None:
    if not role_name:
        raise ValueError("role_name is required")
    role_name_cf = role_name.casefold()
    for role in list_roles(workspace_id, item_id, client=client):
        if str(role.get("name") or "").casefold() == role_name_cf:
            return role
    return None
