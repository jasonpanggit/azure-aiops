"""Tests for the advisory relationship-suggestion scaffold: the staging
table contract, the Data Agent definition builder, and the response
parser. These prove the pure-Python parts of the "relationship suggestion"
layer are correct in isolation; they do NOT exercise a live Fabric Data
Agent invocation (see docs/fabric-data-agent-relationship-suggestions.md
for why that step is not automatable from this repo today)."""

from __future__ import annotations

from fabric.data_agent_manager import (
    RELATIONSHIP_SUGGESTION_INSTRUCTIONS,
    build_data_agent_definition,
)
from fabric_pipelines.relationship_suggestion_parser import (
    parse_suggestions,
    suggestions_to_rows,
)
from fabric_pipelines.relationship_suggestions_contract import (
    DEFAULT_SUGGESTION_STATUS,
    RELATIONSHIP_SUGGESTIONS_CONTRACT,
    RelationshipSuggestion,
    to_suggestion_row,
)


def test_relationship_suggestions_contract_is_separate_from_relationships_contract():
    from fabric_pipelines.ontology_fabric_contracts import (
        ONTOLOGY_RELATIONSHIPS_CONTRACT,
    )

    assert RELATIONSHIP_SUGGESTIONS_CONTRACT.table_name == "relationship_suggestions"
    assert RELATIONSHIP_SUGGESTIONS_CONTRACT.table_name != ONTOLOGY_RELATIONSHIPS_CONTRACT.table_name
    # Distinct pyarrow schema objects -- the suggestions schema carries
    # confidence/rationale/suggested_by/status columns the authoritative
    # relationships schema does not.
    suggestion_fields = set(RELATIONSHIP_SUGGESTIONS_CONTRACT.schema.names)
    assert {"suggestion_id", "rationale", "suggested_by", "status"} <= suggestion_fields


def test_to_suggestion_row_shapes_expected_delta_row():
    suggestion = RelationshipSuggestion(
        subject_id="/subscriptions/sub/resourceGroups/rg/vm-a",
        subject_type="VirtualMachine",
        predicate="possiblyRelatedTo",
        object_id="/subscriptions/sub/resourceGroups/rg/vm-b",
        object_type="VirtualMachine",
        confidence=0.62,
        rationale="Both resources share tag costCenter=finance and were deployed the same day.",
    )
    row = to_suggestion_row(
        suggestion,
        tenant_id="tenant-1",
        subscription_id="sub-1",
        run_id="run-1",
        timestamp="2026-01-01T00:00:00Z",
        change_version="2026-01-01T00:00:00Z",
        suggestion_id="suggestion-1",
    )
    assert row["subject_id"] == suggestion.subject_id
    assert row["object_id"] == suggestion.object_id
    assert row["predicate"] == "possiblyRelatedTo"
    assert row["confidence"] == 0.62
    assert row["status"] == DEFAULT_SUGGESTION_STATUS
    assert row["suggested_by"] == "fabric_data_agent"
    # required_fields from the contract must all be present on the row.
    for field in RELATIONSHIP_SUGGESTIONS_CONTRACT.required_fields:
        assert field in row


def test_build_data_agent_definition_stages_lakehouse_datasource_and_instructions():
    import base64
    import json

    definition = build_data_agent_definition(
        lakehouse_id="lakehouse-id-123",
        lakehouse_workspace_id="workspace-id-456",
        lakehouse_display_name="operational_context_graph",
        ai_instructions=RELATIONSHIP_SUGGESTION_INSTRUCTIONS,
    )
    parts_by_path = {part["path"]: part for part in definition["parts"]}
    assert "Files/Config/data_agent.json" in parts_by_path
    assert "Files/Config/draft/stage_config.json" in parts_by_path

    datasource_paths = [
        path for path in parts_by_path if path.endswith("/datasource.json")
    ]
    assert len(datasource_paths) == 1
    datasource_payload = json.loads(
        base64.b64decode(parts_by_path[datasource_paths[0]]["payload"])
    )
    assert datasource_payload["artifactId"] == "lakehouse-id-123"
    assert datasource_payload["workspaceId"] == "workspace-id-456"
    assert datasource_payload["type"] == "lakehouse_tables"

    stage_config_payload = json.loads(
        base64.b64decode(parts_by_path["Files/Config/draft/stage_config.json"]["payload"])
    )
    assert stage_config_payload["aiInstructions"] == RELATIONSHIP_SUGGESTION_INSTRUCTIONS
    assert "advisory" in RELATIONSHIP_SUGGESTION_INSTRUCTIONS.lower() or "suggest" in RELATIONSHIP_SUGGESTION_INSTRUCTIONS.lower()

    # Discovered live during this session: a datasource with no selected
    # table elements leaves the agent with nothing to query. Every
    # datasource this builder produces must select at least one table.
    assert datasource_payload["elements"], "datasource must select queryable tables"
    selected_names = {
        element["display_name"]
        for element in datasource_payload["elements"]
        if element["is_selected"]
    }
    assert {"ontology_entities", "ontology_relationships"} <= selected_names


def test_parse_suggestions_extracts_json_lines_and_ignores_prose():
    response_text = "\n".join(
        [
            "Here are some candidate relationships I noticed:",
            "```",
            (
                '{"subject_id": "vm-a", "subject_type": "VirtualMachine", '
                '"predicate": "possiblyRelatedTo", "object_id": "vm-b", '
                '"object_type": "VirtualMachine", "confidence": 0.7, '
                '"rationale": "shared tag costCenter=finance"}'
            ),
            (
                '{"subject_id": "app-a", "subject_type": "Application", '
                '"predicate": "possiblyDependsOn", "object_id": "svc-b", '
                '"object_type": "Service", "confidence": 0.4, '
                '"rationale": "naming similarity: app-a-svc vs svc-b"}'
            ),
            "```",
            "That's what I found based on the data.",
            "not json at all",
            '{"missing_keys": true}',
        ]
    )
    suggestions = parse_suggestions(response_text)
    assert len(suggestions) == 2
    assert suggestions[0].subject_id == "vm-a"
    assert suggestions[0].predicate == "possiblyRelatedTo"
    assert suggestions[0].confidence == 0.7
    assert suggestions[1].object_id == "svc-b"


def test_parse_suggestions_returns_empty_list_for_pure_prose():
    assert parse_suggestions("I don't see any additional relationships worth suggesting.") == []


def test_suggestions_to_rows_produces_valid_delta_rows():
    suggestions = parse_suggestions(
        '{"subject_id": "vm-a", "subject_type": "VirtualMachine", '
        '"predicate": "possiblyRelatedTo", "object_id": "vm-b", '
        '"object_type": "VirtualMachine", "confidence": 0.55, '
        '"rationale": "co-tagged"}'
    )
    rows = suggestions_to_rows(
        suggestions,
        tenant_id="tenant-1",
        subscription_id="sub-1",
        run_id="run-1",
    )
    assert len(rows) == 1
    row = rows[0]
    for field in RELATIONSHIP_SUGGESTIONS_CONTRACT.required_fields:
        assert field in row
    assert row["confidence"] == 0.55
