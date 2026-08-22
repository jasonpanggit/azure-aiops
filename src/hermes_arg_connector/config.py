from __future__ import annotations

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
        if not 1 <= self.page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")

    @classmethod
    def load(cls, path: str | Path) -> ConnectorConfig:
        config_path = Path(path).expanduser().resolve()
        payload: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
        azure = payload.get("azure") or {}
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
        )
