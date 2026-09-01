from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def entity_lineage_summary(entity_id: str, entities: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    if not entity_id:
        return {"status": "not_found", "source_resource_ids": []}
    row = entities.get(entity_id.casefold())
    if not isinstance(row, Mapping):
        return {"status": "not_found", "source_resource_ids": []}
    raw_lineage = row.get("lineage_json")
    parsed = {}
    if isinstance(raw_lineage, str) and raw_lineage:
        try:
            parsed = json.loads(raw_lineage)
        except json.JSONDecodeError:
            parsed = {}
    elif isinstance(raw_lineage, Mapping):
        parsed = dict(raw_lineage)
    sources = parsed.get("source_resource_ids") if isinstance(parsed, Mapping) else None
    if not isinstance(sources, list):
        sources = []
    return {
        "status": "found",
        "source_resource_ids": [str(item) for item in sources if str(item)],
    }


def native_lineage_url(workspace_id: str) -> str:
    value = workspace_id.strip()
    if not value:
        raise ValueError("workspace_id is required")
    return f"https://app.fabric.microsoft.com/groups/{value}/lineage"
