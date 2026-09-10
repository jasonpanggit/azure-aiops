from __future__ import annotations

import base64
import json

import pytest

from fabric.data_agent_manager import hydrate_data_agent_table_selection
from fabric.gold_grounding_definition import (
    GOLD_GROUNDING_FEW_SHOTS,
    GOLD_GROUNDING_INSTRUCTIONS,
    GOLD_GROUNDING_TABLES,
    build_gold_grounding_definition,
)


def _decoded_parts(definition: dict) -> dict[str, dict]:
    return {
        part["path"]: json.loads(base64.b64decode(part["payload"]))
        for part in definition["parts"]
    }


def test_gold_grounding_definition_matches_runtime_contract() -> None:
    definition = build_gold_grounding_definition(
        lakehouse_id="lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="operational_context_graph_v2",
    )
    parts = _decoded_parts(definition)
    stage = parts["Files/Config/draft/stage_config.json"]
    datasource_path = next(path for path in parts if path.endswith("/datasource.json"))
    fewshots_path = next(path for path in parts if path.endswith("/fewshots.json"))
    datasource = parts[datasource_path]
    fewshots = parts[fewshots_path]

    selected = tuple(
        element["display_name"]
        for element in datasource["elements"]
        if element["is_selected"]
    )
    assert selected == GOLD_GROUNDING_TABLES
    assert "inventory_resource_observations" not in selected
    assert stage["aiInstructions"] == GOLD_GROUNDING_INSTRUCTIONS
    for required_field in (
        "finding_id",
        "resource_ids",
        "citations",
        "scope_ok",
        "degraded",
        "degraded_reason",
        "summary",
    ):
        assert required_field in GOLD_GROUNDING_INSTRUCTIONS
    assert "read-only" in GOLD_GROUNDING_INSTRUCTIONS.casefold()
    assert "inventory" in GOLD_GROUNDING_INSTRUCTIONS.casefold()
    assert "line-delimited json" in GOLD_GROUNDING_INSTRUCTIONS.casefold()
    assert fewshots["fewShots"] == list(GOLD_GROUNDING_FEW_SHOTS)


def test_gold_grounding_few_shots_are_bounded_read_only_queries() -> None:
    assert 3 <= len(GOLD_GROUNDING_FEW_SHOTS) <= 5
    for example in GOLD_GROUNDING_FEW_SHOTS:
        assert example["id"]
        assert example["question"]
        query = example["query"].strip().casefold()
        assert query.startswith("select")
        assert " top (" in query
        assert not any(
            keyword in query
            for keyword in ("insert ", "update ", "delete ", "drop ", "alter ")
        )


def test_hydrated_definition_selects_only_requested_tables() -> None:
    definition = build_gold_grounding_definition(
        lakehouse_id="lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="operational_context_graph_v2",
    )
    live_definition = build_gold_grounding_definition(
        lakehouse_id="lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="operational_context_graph_v2",
    )
    live_parts = _decoded_parts(live_definition)
    datasource_path = next(
        path for path in live_parts if path.endswith("/datasource.json")
    )
    live_parts[datasource_path]["elements"] = [
        {
            "id": "schemas",
            "display_name": "Schemas",
            "type": "schema_grouping",
            "is_selected": False,
            "children": [
                {
                    "id": "dbo",
                    "display_name": "dbo",
                    "type": "lakehouse_tables.schema",
                    "is_selected": False,
                    "children": [
                        {
                            "id": "tables",
                            "display_name": "Tables",
                            "type": "table_grouping",
                            "is_selected": False,
                            "children": [
                                {
                                    "id": f"id-{name}",
                                    "display_name": name,
                                    "type": "lakehouse_tables.table",
                                    "is_selected": False,
                                    "children": [],
                                }
                                for name in (*GOLD_GROUNDING_TABLES, "unrelated_table")
                            ],
                        },
                    ],
                },
            ],
        },
    ]
    live_parts[datasource_path]["metadata"] = {"schemaVersion": "live-v1"}
    live_encoded = {
        "definition": {
            "parts": [
                {
                    "path": path,
                    "payload": base64.b64encode(json.dumps(payload).encode()).decode(),
                    "payloadType": "InlineBase64",
                }
                for path, payload in live_parts.items()
            ]
            + [
                {
                    "path": "Files/Config/publish_info.json",
                    "payload": base64.b64encode(
                        json.dumps(
                            {"description": "current published version"}
                        ).encode()
                    ).decode(),
                    "payloadType": "InlineBase64",
                },
                {
                    "path": "Files/Config/published/stage_config.json",
                    "payload": base64.b64encode(
                        json.dumps(
                            {"aiInstructions": "current published instructions"}
                        ).encode()
                    ).decode(),
                    "payloadType": "InlineBase64",
                },
                {
                    "path": ".platform",
                    "payload": base64.b64encode(
                        json.dumps({"metadata": {"type": "DataAgent"}}).encode()
                    ).decode(),
                    "payloadType": "InlineBase64",
                },
            ],
        },
    }

    hydrated = hydrate_data_agent_table_selection(
        definition,
        live_encoded,
        GOLD_GROUNDING_TABLES,
    )
    hydrated_parts = _decoded_parts(hydrated)
    datasource = hydrated_parts[datasource_path]

    table_nodes = datasource["elements"][0]["children"][0]["children"][0]["children"]
    selected = {node["display_name"] for node in table_nodes if node["is_selected"]}
    assert selected == set(GOLD_GROUNDING_TABLES)
    assert datasource["metadata"] == {"schemaVersion": "live-v1"}
    assert "Files/Config/publish_info.json" in hydrated_parts
    assert "Files/Config/published/stage_config.json" in hydrated_parts
    assert ".platform" in hydrated_parts
    assert (
        next(node for node in table_nodes if node["display_name"] == "unrelated_table")[
            "is_selected"
        ]
        is False
    )


def test_hydration_rejects_a_different_live_datasource_identity() -> None:
    definition = build_gold_grounding_definition(
        lakehouse_id="lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="operational_context_graph_v2",
    )
    live_definition = build_gold_grounding_definition(
        lakehouse_id="different-lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="other_lakehouse",
    )
    live_encoded = {
        "definition": {
            "parts": [
                {
                    "path": part["path"],
                    "payload": part["payload"],
                    "payloadType": "InlineBase64",
                }
                for part in live_definition["parts"]
            ],
        },
    }

    with pytest.raises(ValueError, match="datasource artifactId does not match"):
        hydrate_data_agent_table_selection(
            definition,
            live_encoded,
            GOLD_GROUNDING_TABLES,
        )


def test_hydration_adopts_fabric_canonical_datasource_path() -> None:
    definition = build_gold_grounding_definition(
        lakehouse_id="lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="operational_context_graph_v2",
    )
    live_definition = build_gold_grounding_definition(
        lakehouse_id="lakehouse-id",
        workspace_id="workspace-id",
        lakehouse_display_name="operational_context_graph_v2",
    )
    for part in live_definition["parts"]:
        part["path"] = part["path"].replace(
            "/lakehouse_tables-operational_context_graph_v2/",
            "/lakehouse-tables-operational_context_graph_v2/",
        )
    live_encoded = {"definition": live_definition}

    hydrated = hydrate_data_agent_table_selection(
        definition,
        live_encoded,
        GOLD_GROUNDING_TABLES,
    )
    draft_paths = {
        part["path"]
        for part in hydrated["parts"]
        if "/Files/Config/draft/" in f"/{part['path']}"
    }

    assert (
        "Files/Config/draft/lakehouse-tables-operational_context_graph_v2/"
        "datasource.json"
    ) in draft_paths
    assert (
        "Files/Config/draft/lakehouse-tables-operational_context_graph_v2/fewshots.json"
    ) in draft_paths
