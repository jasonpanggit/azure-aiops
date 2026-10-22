from __future__ import annotations

import base64
import json
from unittest.mock import Mock

import pytest
from test_fabric_sync_service import _service

from ontology.definition_compatibility import DefinitionFormatMismatch, decode_parts
from ontology.ontology_publisher import OntologyPublisher

TRIPLE = ("ContainerImageExposure", "exposes", "ContainerRegistry")
TABLE = "ontology_rel_exposes_container_image_exposure_container_registry"


def test_sync_publisher_contract_includes_registry_mapping_without_active_rows(tmp_path):
    service = _service(tmp_path)
    publisher = Mock()
    service.ontology_publisher = publisher
    service._publish_ontology({"ontology_relationships": []})

    publisher.publish.assert_called_once()
    arguments = publisher.publish.call_args.kwargs
    assert arguments["relationships"][TRIPLE] == TABLE
    assert arguments["entity_types"]["ContainerImageExposure"] == (
        "ontology_container_image_exposure_entities"
    )
    assert arguments["entity_types"]["ContainerRegistry"] == (
        "ontology_container_registry_entities"
    )

    generator = OntologyPublisher(
        Mock(), workspace_id="workspace-contract", lakehouse_id="lakehouse-contract",
    )
    definition = generator.build_definition(
        {entity: arguments["entity_types"][entity] for entity in (TRIPLE[0], TRIPLE[2])},
        {TRIPLE: arguments["relationships"][TRIPLE]},
        "Contract only",
    )
    decoded = {
        path: json.loads(part.raw)
        for path, part in decode_parts(definition).items()
        if path != ".platform"
    }
    entities = {
        value["name"]: value
        for path, value in decoded.items()
        if path.startswith("EntityTypes/") and path.endswith("/definition.json")
    }
    relations = [
        value for path, value in decoded.items()
        if path.startswith("RelationshipTypes/") and path.endswith("/definition.json")
        and value["source"]["entityTypeId"] == entities[TRIPLE[0]]["id"]
        and value["target"]["entityTypeId"] == entities[TRIPLE[2]]["id"]
        and value["name"] in {"exposes", "_".join((TRIPLE[1], TRIPLE[0], TRIPLE[2]))}
    ]
    assert len(relations) == 1
    bindings = [
        value for path, value in decoded.items()
        if path.startswith(f"RelationshipTypes/{relations[0]['id']}/Contextualizations/")
    ]
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding["dataBindingTable"] == {
        "workspaceId": "workspace-contract",
        "itemId": "lakehouse-contract",
        "sourceTableName": TABLE,
        "sourceType": "LakehouseTable",
        "sourceSchema": "dbo",
    }
    for key, column, entity in (
        ("sourceKeyRefBindings", "subject_id", TRIPLE[0]),
        ("targetKeyRefBindings", "object_id", TRIPLE[2]),
    ):
        identity = next(
            prop["id"] for prop in entities[entity]["properties"]
            if prop["name"] == "resource_id"
        )
        assert binding[key] == [{
            "sourceColumnName": column, "targetPropertyId": identity,
        }]


def test_registry_binding_contract_does_not_authorize_native_tmdl_replacement():
    manager = Mock()
    manager.resolve.return_value = {"id": "native-contract-target"}
    manager.get_definition.return_value = {"parts": [{
        "path": "Ontology.tmdl",
        "payload": base64.b64encode(b"ontology Native\n").decode(),
        "payloadType": "InlineBase64",
    }]}
    publisher = OntologyPublisher(
        manager, workspace_id="workspace-contract", lakehouse_id="lakehouse-contract",
    )
    with pytest.raises(DefinitionFormatMismatch):
        publisher.publish(
            ontology_id="native-contract-target",
            ontology_name="Native",
            entity_types={
                TRIPLE[0]: "ontology_container_image_exposure_entities",
                TRIPLE[2]: "ontology_container_registry_entities",
            },
            relationships={TRIPLE: TABLE},
            expected_item_id="native-contract-target",
        )
    manager.update_definition.assert_not_called()
    manager.create.assert_not_called()
