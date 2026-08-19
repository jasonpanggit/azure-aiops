from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ConnectorConfig:
    output_dir: Path
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser().resolve())
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
        output_dir = Path(storage.get("output_dir") or "./data").expanduser()
        if not output_dir.is_absolute():
            output_dir = config_path.parent / output_dir
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
