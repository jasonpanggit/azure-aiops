"""Configuration for API-owned Azure subscription discovery."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from storage.fs import is_onelake_uri


@dataclass(frozen=True)
class ConnectorConfig:
    """Validated configuration shared by discovery and inventory services."""

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
    cost_management_enabled: bool = True
    cost_management_lookback_days: int = 30
    identity_source: str = "arg"
    publish_timeout_seconds: int = 600

    def __post_init__(self) -> None:
        if is_onelake_uri(self.output_dir):
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
        if not 1 <= self.page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")
        if self.cost_management_lookback_days < 1:
            raise ValueError("cost_management_lookback_days must be positive")
        if self.identity_source not in ("arg", "inventory"):
            raise ValueError("identity_source must be 'arg' or 'inventory'")

    @classmethod
    def load(cls, path: str | Path) -> ConnectorConfig:
        config_path = Path(path).expanduser().resolve()
        payload: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
        azure = payload.get("azure") or {}
        cost = azure.get("cost_management") or {}
        storage = payload.get("storage") or {}
        # Falling back to AIOPS_HOME keeps the refresh path's output root
        # identical to the root the API reads the connection registry from.
        # Divergent roots silently split the registry in two: connections get
        # registered under one prefix and looked up under another.
        raw_output_dir = str(
            storage.get("output_dir") or os.environ.get("AIOPS_HOME") or "./data"
        )
        if is_onelake_uri(raw_output_dir):
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
            azure_mcp_command=tuple(
                str(item) for item in (azure.get("mcp_command") or ["azmcp"])
            ),
            page_size=int(azure.get("page_size") or 1000),
            max_pages=int(azure.get("max_pages") or 1000),
            command_timeout_seconds=int(azure.get("command_timeout_seconds") or 60),
            change_overlap_minutes=int(azure.get("change_overlap_minutes") or 10),
            retain_raw_queries=bool(storage.get("retain_raw_queries", False)),
            max_query_workers=int(azure.get("max_query_workers") or 5),
            cost_management_enabled=bool(cost.get("enabled", True)),
            cost_management_lookback_days=int(cost.get("lookback_days") or 30),
            identity_source=str(azure.get("identity_source") or "arg"),
            publish_timeout_seconds=int(azure.get("publish_timeout_seconds") or 600),
        )

    @property
    def cost_management_lookback(self) -> timedelta:
        return timedelta(days=self.cost_management_lookback_days)
