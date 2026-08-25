from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class ConnectorConfig:
    output_dir: Path | str
    subscriptions: tuple[str, ...] = field(default_factory=tuple)
    management_groups: tuple[str, ...] = field(default_factory=tuple)
    tenant_id: str = ""
    azure_mcp_command: tuple[str, ...] = ("azmcp",)
    page_size: int = 1000
    max_pages: int = 1000
    command_timeout_seconds: int = 60
    change_overlap_minutes: int = 10
    retain_raw_queries: bool = False
    max_query_workers: int = 5
    connection_context: Mapping[str, str] = field(default_factory=dict)
    logs_workspaces: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Keep URI-shaped roots (e.g. abfss://...) untouched; only resolve
        # plain filesystem paths, since Path() would mangle a URI's "//".
        if urlparse(str(self.output_dir)).scheme in ("abfss", "abfs", "az"):
            object.__setattr__(self, "output_dir", str(self.output_dir).rstrip("/"))
        else:
            object.__setattr__(
                self, "output_dir", Path(self.output_dir).expanduser().resolve()
            )
        object.__setattr__(
            self,
            "connection_context",
            MappingProxyType(
                {
                    str(key): str(value)
                    for key, value in dict(self.connection_context or {}).items()
                    if str(value or "").strip()
                }
            ),
        )
        workspaces: dict[str, tuple[str, ...]] = {}
        for connection_id, values in dict(self.logs_workspaces or {}).items():
            key = str(connection_id).strip()
            if not key:
                raise ValueError("Logs workspace mappings require a connection ID")
            if isinstance(values, str):
                raw_values = (values,)
            elif isinstance(values, (list, tuple)):
                raw_values = tuple(values)
            else:
                raise TypeError(
                    f"Logs workspace mapping for {key!r} must contain workspace IDs"
                )
            normalized = tuple(_validated_workspace_id(value) for value in raw_values)
            if not normalized:
                raise ValueError(f"Logs workspace mapping for {key!r} cannot be empty")
            workspaces[key] = normalized
        object.__setattr__(self, "logs_workspaces", MappingProxyType(workspaces))
        if not 1 <= self.page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")

    @classmethod
    def load(cls, path: str | Path) -> ConnectorConfig:
        config_path = Path(path).expanduser().resolve()
        payload: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
        azure = payload.get("azure") or {}
        raw_workspaces = azure.get("logs_workspaces") or azure.get(
            "log_analytics_workspaces"
        ) or (payload.get("logs") or {}).get("workspaces") or {}
        if not isinstance(raw_workspaces, dict):
            raise TypeError(
                "azure.logs_workspaces must be a mapping of connection IDs to workspace IDs"
            )
        storage = payload.get("storage") or {}
        raw_output_dir = str(storage.get("output_dir") or "./data")
        if urlparse(raw_output_dir).scheme in ("abfss", "abfs", "az"):
            output_dir: Path | str = raw_output_dir
        else:
            output_path = Path(raw_output_dir).expanduser()
            output_dir = (
                output_path
                if output_path.is_absolute()
                else config_path.parent / output_path
            )
        return cls(
            output_dir=output_dir,
            subscriptions=tuple(str(x) for x in (azure.get("subscriptions") or [])),
            management_groups=tuple(
                str(x) for x in (azure.get("management_groups") or [])
            ),
            tenant_id=str(azure.get("tenant_id") or ""),
            azure_mcp_command=tuple(str(item) for item in (azure.get("mcp_command") or ["azmcp"])),
            page_size=int(azure.get("page_size") or 1000),
            max_pages=int(azure.get("max_pages") or 1000),
            command_timeout_seconds=int(azure.get("command_timeout_seconds") or 60),
            change_overlap_minutes=int(azure.get("change_overlap_minutes") or 10),
            retain_raw_queries=bool(storage.get("retain_raw_queries", False)),
            max_query_workers=int(azure.get("max_query_workers") or 5),
            logs_workspaces={
                str(connection_id): (
                    tuple(str(item) for item in workspace_ids)
                    if isinstance(workspace_ids, (list, tuple))
                    else str(workspace_ids)
                )
                for connection_id, workspace_ids in raw_workspaces.items()
            },
        )

    def workspaces_for_connection(self, connection_id: str) -> tuple[str, ...]:
        """Return only the server-configured workspaces for one connection."""
        key = str(connection_id or "").strip()
        if key in self.logs_workspaces:
            return self.logs_workspaces[key]
        folded = key.casefold()
        return next(
            (
                values
                for configured_id, values in self.logs_workspaces.items()
                if configured_id.casefold() == folded
            ),
            (),
        )


_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validated_workspace_id(value: Any) -> str:
    workspace = str(value or "").strip()
    if not _WORKSPACE_ID.fullmatch(workspace):
        raise ValueError("Logs workspace ID is invalid")
    return workspace
