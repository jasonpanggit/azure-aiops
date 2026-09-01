from __future__ import annotations

import base64
import json

from fabric.semantic_model_manager import build_semantic_model_definition


def _parts(definition: dict) -> dict[str, dict]:
    return {part["path"]: part for part in definition["parts"]}


def _decode_part(definition: dict, path: str) -> dict:
    payload = _parts(definition)[path]["payload"]
    return json.loads(base64.b64decode(payload).decode("utf-8"))


def test_build_definition_references_only_passed_gold_table_names() -> None:
    tables = ["gold_incident_summary", "gold_patch_risk"]
    definition = build_semantic_model_definition("aiops_gold_semantic_model", tables)
    model = _decode_part(definition, "model.bim")
    actual_table_names = [table["name"] for table in model["model"]["tables"]]

    assert actual_table_names == tables
    assert "gold_invented_table" not in actual_table_names


def test_build_definition_does_not_embed_unified_inventory_identity_fields() -> None:
    definition = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_service_health"],
    )
    model_payload_text = json.dumps(_decode_part(definition, "model.bim"), sort_keys=True)

    assert "resourceId" not in model_payload_text
    assert "subscriptionId" not in model_payload_text
    assert "tenantId" not in model_payload_text


def test_build_definition_emits_required_base64_parts() -> None:
    definition = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_cost_trends"],
    )
    parts = _parts(definition)

    assert set(parts) == {"model.bim", "definition.pbism", ".platform"}
    for part in parts.values():
        assert part["payloadType"] == "InlineBase64"
        decoded = json.loads(base64.b64decode(part["payload"]).decode("utf-8"))
        assert isinstance(decoded, dict)


def test_build_definition_is_deterministic_for_same_table_set() -> None:
    a = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_patch_risk", "gold_incident_summary"],
    )
    b = build_semantic_model_definition(
        "aiops_gold_semantic_model",
        ["gold_incident_summary", "gold_patch_risk"],
    )

    assert a == b
