from __future__ import annotations

import pytest

from fabric import data_access_roles


class _FakeClient:
    def __init__(self, *, item_type: str = "Lakehouse", roles: list[dict] | None = None) -> None:
        self.item_type = item_type
        self.roles = roles or []
        self.iter_items_calls = 0
        self.request_calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, **kwargs):
        self.request_calls.append((method, path))
        if method == "GET" and "/items/" in path and "/dataAccessRoles" not in path:
            return {"type": self.item_type}
        raise AssertionError(f"Unexpected request: {method} {path}")

    def iter_items(self, path: str, **kwargs):
        self.iter_items_calls += 1
        yield from self.roles


def test_list_roles_returns_all_pages_via_fabric_iter_items(monkeypatch) -> None:
    fake_client = _FakeClient(
        roles=[
            {"name": "analyst", "eTag": "1"},
            {"name": "operator", "eTag": "2"},
            {"name": "auditor", "eTag": "3"},
        ]
    )
    monkeypatch.setattr(data_access_roles, "_default_fabric_client", lambda: fake_client)

    roles = data_access_roles.list_roles("ws-1", "item-1")

    assert [role["name"] for role in roles] == ["analyst", "operator", "auditor"]
    assert fake_client.iter_items_calls == 1


def test_module_exposes_read_only_surface_only() -> None:
    assert hasattr(data_access_roles, "list_roles")
    assert hasattr(data_access_roles, "get_role")
    assert not hasattr(data_access_roles, "create_role")
    assert not hasattr(data_access_roles, "update_role")
    assert not hasattr(data_access_roles, "delete_role")


def test_non_lakehouse_item_type_raises_clear_error(monkeypatch) -> None:
    fake_client = _FakeClient(item_type="Warehouse")
    monkeypatch.setattr(data_access_roles, "_default_fabric_client", lambda: fake_client)

    with pytest.raises(ValueError, match="Lakehouse"):
        data_access_roles.list_roles("ws-1", "item-1")


def test_default_client_uses_fabric_config_env(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "fabric.yaml"
    config_path.write_text(
        """
fabric:
  auth:
    mode: managed_identity
  workspace_name: workspace
  lakehouse_name: lakehouse
"""
    )
    captured = {}

    def fake_load(path):
        captured["path"] = path
        return type("Config", (), {"auth": object()})()

    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", str(config_path))
    monkeypatch.setattr(data_access_roles.FabricRuntimeConfig, "load", fake_load)
    monkeypatch.setattr(data_access_roles, "build_credential", lambda _auth: object())
    monkeypatch.setattr(data_access_roles, "FabricClient", lambda _credential: object())

    data_access_roles._default_fabric_client()

    assert captured["path"] == str(config_path)
