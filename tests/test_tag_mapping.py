from __future__ import annotations

from test_entity_builder import resource

from ontology.entity_builder import EntityBuilder


def test_tag_mapping_is_case_insensitive_and_values_are_not_hardcoded():
    row = resource()
    row["payload_json"] = row["payload_json"].replace("AppName", "appname").replace(
        "Production", "Ephemeral-Blue"
    )

    entities = EntityBuilder().build([row], "run-2")

    assert any(e["entity_type"] == "Application" and e["name"] == "Payments API" for e in entities)
    assert any(e["entity_type"] == "Environment" and e["name"] == "Ephemeral-Blue" for e in entities)


def test_blank_tag_values_do_not_create_semantic_entities():
    row = resource()
    row["payload_json"] = row["payload_json"].replace('"SRE"', '"   "')

    entities = EntityBuilder().build([row], "run-2")

    assert not any(e["entity_type"] == "SupportTeam" for e in entities)
