from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import httpx

from .fabric_client import FabricClient

if TYPE_CHECKING:
    from ontology_discovery.generation_resolver import (
        CompatibilityAlias,
        GenerationSelection,
    )

ITEM_TYPE = "SemanticModel"
_BLOCKED_CODES: frozenset[str] = frozenset(
    {
        "InvalidItemType",
        "ItemDisplayNameAlreadyInUse",
        "CorruptedPayload",
        "WorkspaceItemsLimitExceeded",
    }
)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _b64(payload: object) -> str:
    return base64.b64encode(_canonical_json(payload).encode("utf-8")).decode("ascii")


def _normalize_gold_tables(gold_tables: list[str]) -> list[str]:
    if not isinstance(gold_tables, list) or not gold_tables:
        raise ValueError("gold_tables must be a non-empty list[str]")
    cleaned = sorted(
        {
            value.strip()
            for value in gold_tables
            if isinstance(value, str) and value.strip()
        },
        key=str.casefold,
    )
    if not cleaned or len(cleaned) != len(
        [value for value in gold_tables if isinstance(value, str) and value.strip()]
    ):
        raise ValueError("gold_tables contains invalid or duplicate table names")
    return cleaned


def _validate_name(name: str, field: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return name.strip()


def build_semantic_model_definition(
    display_name: str,
    gold_tables: list[str],
    *,
    generation: GenerationSelection | None = None,
    table_aliases: Mapping[str, CompatibilityAlias] | None = None,
    semantic_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    semantic_model_name = _validate_name(display_name, "display_name")
    tables = _normalize_gold_tables(gold_tables)
    if table_aliases is not None:
        if generation is None:
            raise ValueError("generation is required with ontology table aliases")
        tables = [
            _bound_alias_name(table, generation, table_aliases)
            for table in tables
        ]

    metadata = _normalize_semantic_metadata(semantic_metadata or {}, tables)
    annotations = []
    if generation is not None:
        annotations.append(
            {
                "name": "aiops.ontologyGeneration",
                "value": (
                    f"{generation.compatibility_alias_version}:"
                    f"{generation.generation_id}"
                ),
            }
        )
    if metadata["proposal_ids"]:
        annotations.append(
            {
                "name": "aiops.semanticProposalIds",
                "value": ",".join(metadata["proposal_ids"]),
            }
        )
    model_bim = {
        "name": semantic_model_name,
        "compatibilityLevel": 1605,
        "model": {
            "name": semantic_model_name,
            "culture": "en-US",
            "tables": [
                {
                    "name": table_name,
                    "partitions": [
                        {
                            "name": table_name,
                            "mode": "directLake",
                            "source": {
                                "type": "entity",
                                "entityName": table_name,
                            },
                        }
                    ],
                    **metadata["tables"].get(table_name, {}),
                }
                for table_name in tables
            ],
            **({"relationships": metadata["relationships"]} if metadata["relationships"] else {}),
            **({"roles": metadata["roles"]} if metadata["roles"] else {}),
            **({"measures": metadata["measures"]} if metadata["measures"] else {}),
            **({"annotations": annotations} if annotations else {}),
        },
    }
    definition_pbism = {
        "version": "1.0",
        "semanticModel": {"name": semantic_model_name, "storageMode": "DirectLake"},
        "tables": [
            {"name": table_name, **metadata["tables"].get(table_name, {})}
            for table_name in tables
        ],
    }
    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/platformProperties/1.0.0/schema.json",
        "metadata": {"itemType": ITEM_TYPE, "configVersion": "1.0.0"},
    }
    return {
        "parts": [
            {"path": "model.bim", "payload": _b64(model_bim), "payloadType": "InlineBase64"},
            {
                "path": "definition.pbism",
                "payload": _b64(definition_pbism),
                "payloadType": "InlineBase64",
            },
            {"path": ".platform", "payload": _b64(platform), "payloadType": "InlineBase64"},
        ]
    }


def _normalize_semantic_metadata(
    metadata: Mapping[str, Any], tables: list[str]
) -> dict[str, Any]:
    """Validate and deterministically normalize reviewed additive metadata."""
    allowed = {"descriptions", "synonyms", "classifications", "columns",
               "relationships", "hierarchies", "measures", "proposal_ids"}
    unknown = set(metadata) - allowed
    if unknown:
        raise ValueError(f"semantic_metadata contains unsupported fields: {sorted(unknown)}")
    table_set = set(tables)
    result: dict[str, Any] = {
        "tables": {},
        "relationships": [],
        "roles": [],
        "measures": [],
        "proposal_ids": [],
    }
    for name in ("descriptions", "synonyms", "classifications", "columns"):
        values = metadata.get(name, {})
        if values is None:
            continue
        if not isinstance(values, Mapping):
            raise TypeError(f"semantic_metadata.{name} must be a mapping")
        for table, value in sorted(values.items(), key=lambda item: str(item[0]).casefold()):
            table_name = str(table)
            if table_name not in table_set:
                raise ValueError(f"semantic metadata references unknown table {table_name!r}")
            result["tables"].setdefault(table_name, {})
            key = {"descriptions": "description", "synonyms": "synonyms",
                   "classifications": "classifications", "columns": "columns"}[name]
            result["tables"][table_name][key] = value
    for name, target in (("relationships", "relationships"), ("hierarchies", "roles"), ("measures", "measures")):
        values = metadata.get(name, ())
        if values is None:
            continue
        if not isinstance(values, (list, tuple)):
            raise TypeError(f"semantic_metadata.{name} must be a sequence")
        normalized = []
        for value in values:
            if not isinstance(value, Mapping):
                raise TypeError(f"semantic_metadata.{name} entries must be mappings")
            item = dict(value)
            refs = [item.get(key) for key in ("from", "to", "table", "source", "target")]
            for ref in refs:
                if ref is not None and str(ref) not in table_set:
                    raise ValueError(f"semantic metadata references unknown table {ref!r}")
            normalized.append(item)
        result[target] = sorted(
            normalized,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    proposal_ids = metadata.get("proposal_ids", ())
    if proposal_ids is not None:
        if not isinstance(proposal_ids, (list, tuple)):
            raise TypeError("semantic_metadata.proposal_ids must be a sequence")
        result["proposal_ids"] = sorted({str(value) for value in proposal_ids})
    return result


def _bound_alias_name(
    name: str,
    generation: GenerationSelection,
    table_aliases: Mapping[str, CompatibilityAlias],
) -> str:
    alias = table_aliases.get(name)
    if alias is None:
        return name
    if alias.logical_name != name or alias.generation_id != generation.generation_id:
        raise ValueError(f"Compatibility alias for {name!r} is not bound to the selection")
    return alias.logical_name


def _normalize_definition(definition: dict[str, Any]) -> dict[str, Any]:
    parts = definition.get("parts")
    if not isinstance(parts, list):
        return {"parts": []}
    normalized = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        path = str(part.get("path") or "")
        if not path:
            continue
        normalized.append(
            {
                "path": path,
                "payload": str(part.get("payload") or ""),
                "payloadType": str(part.get("payloadType") or ""),
            }
        )
    return {"parts": sorted(normalized, key=lambda row: row["path"])}


def _definitions_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return _canonical_json(_normalize_definition(left)) == _canonical_json(
        _normalize_definition(right)
    )


def _resolve_by_name(
    client: FabricClient, workspace_id: str, display_name: str
) -> dict[str, Any] | None:
    matches = [
        item
        for item in client.iter_items(
            f"/workspaces/{workspace_id}/items",
            params={"type": ITEM_TYPE},
        )
        if str(item.get("displayName") or "") == display_name
    ]
    if len(matches) > 1:
        raise ValueError(f"Multiple Fabric semantic models named {display_name!r}; configure item_id")
    return matches[0] if matches else None


def _get_definition(client: FabricClient, workspace_id: str, item_id: str) -> dict[str, Any]:
    payload = client.request("POST", f"/workspaces/{workspace_id}/items/{item_id}/getDefinition")
    return dict(payload.get("definition") or {})


def _extract_error_code(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("errorCode", "code", "error_code"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("error")
    if isinstance(nested, dict):
        for key in ("errorCode", "code", "error_code"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    details = payload.get("details")
    if isinstance(details, list):
        for entry in details:
            code = _extract_error_code(entry)
            if code:
                return code
    return None


def _blocked_result(reason: str, *, item_id: str = "") -> dict[str, str]:
    result: dict[str, str] = {
        "status": "deployment-blocked",
        "reason": reason,
        "manifest_disposition": "dormant",
    }
    if item_id:
        result["item_id"] = item_id
    return result


def _map_http_error(error: httpx.HTTPStatusError) -> str:
    try:
        payload = error.response.json()
    except ValueError:
        payload = {}
    code = _extract_error_code(payload)
    if code:
        return code
    return f"HTTP_{error.response.status_code}"


def _map_runtime_error(error: RuntimeError | TimeoutError) -> str:
    if isinstance(error, TimeoutError):
        return "OperationTimeout"
    message = str(error)
    for code in sorted(_BLOCKED_CODES):
        if code in message:
            return code
    return "FabricOperationFailed"


def _deploy_create(
    client: FabricClient,
    workspace_id: str,
    display_name: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/semanticModels",
        json_body={
            "displayName": display_name,
            "description": "Direct Lake semantic model over curated Gold tables.",
            "definition": definition,
        },
        wait_for_completion=True,
    )


def _deploy_update(
    client: FabricClient,
    workspace_id: str,
    item_id: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    return client.request(
        "POST",
        f"/workspaces/{workspace_id}/items/{item_id}/updateDefinition",
        json_body={"definition": definition},
        wait_for_completion=True,
    )


def deploy_semantic_model(
    manager: FabricClient,
    workspace_id: str,
    display_name: str,
    gold_tables: list[str],
) -> dict[str, Any]:
    workspace = _validate_name(workspace_id, "workspace_id")
    semantic_name = _validate_name(display_name, "display_name")
    definition = build_semantic_model_definition(semantic_name, gold_tables)

    existing = _resolve_by_name(manager, workspace, semantic_name)
    if existing:
        item_id = str(existing.get("id") or "")
        current = _get_definition(manager, workspace, item_id)
        if _definitions_equal(current, definition):
            return {"status": "unchanged", "item_id": item_id}
        try:
            _deploy_update(manager, workspace, item_id, definition)
            return {"status": "updated", "item_id": item_id}
        except httpx.HTTPStatusError as error:
            reason = _map_http_error(error)
            return _blocked_result(reason, item_id=item_id)
        except (RuntimeError, TimeoutError) as error:
            return _blocked_result(_map_runtime_error(error), item_id=item_id)

    try:
        created = _deploy_create(manager, workspace, semantic_name, definition)
        item_id = str(created.get("id") or created.get("itemId") or "")
        return {"status": "created", "item_id": item_id}
    except httpx.HTTPStatusError as error:
        reason = _map_http_error(error)
        return _blocked_result(reason)
    except (RuntimeError, TimeoutError) as error:
        return _blocked_result(_map_runtime_error(error))


__all__ = ["ITEM_TYPE", "build_semantic_model_definition", "deploy_semantic_model"]
