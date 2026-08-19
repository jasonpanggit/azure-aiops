from __future__ import annotations

import base64
import json

from ontology.ontology_manager import OntologyManager
from ontology.ontology_publisher import OntologyPublisher


class Client:
    def __init__(self):
        self.calls = []

    def iter_items(self, path):
        self.calls.append(("iter_items", path, None))
        return iter(())

    def request(self, method, path, json_body=None, params=None):
        self.calls.append((method, path, json_body))
        if method == "POST" and path.endswith("/ontologies"):
            return {"id": "ontology-1", "displayName": json_body["displayName"]}
        return {}


def decode_parts(definition):
    return {
        part["path"]: json.loads(base64.b64decode(part["payload"]))
        for part in definition["parts"]
        if part["path"] != ".platform"
    }


def test_publisher_creates_fabric_native_definition_with_bindings():
    client = Client()
    manager = OntologyManager(client, "workspace-1")
    publisher = OntologyPublisher(
        manager,
        workspace_id="workspace-1",
        lakehouse_id="lakehouse-1",
        source_schema="dbo",
    )

    result = publisher.publish(
        ontology_id="",
        ontology_name="Operational_Context",
        entity_types={
            "Application": "ontology_application_entities",
            "VirtualMachine": "ontology_virtual_machine_entities",
        },
        relationships={
            ("Application", "hosted_on", "VirtualMachine"): (
                "ontology_rel_hosted_on_application_virtual_machine"
            )
        },
    )

    assert result["id"] == "ontology-1"
    create = next(call for call in client.calls if call[0] == "POST")
    parts = decode_parts(create[2]["definition"])
    vm = next(
        value
        for path, value in parts.items()
        if path.startswith("EntityTypes/")
        and path.endswith("/definition.json")
        and value["name"] == "VirtualMachine"
    )
    assert vm["entityIdParts"]
    binding = next(value for path, value in parts.items() if "/DataBindings/" in path and "virtual_machine" in value["dataBindingConfiguration"]["sourceTableProperties"]["sourceTableName"])
    assert binding["dataBindingConfiguration"]["sourceTableProperties"]["itemId"] == "lakehouse-1"
    relationship = next(value for path, value in parts.items() if path.startswith("RelationshipTypes/") and path.endswith("definition.json"))
    assert relationship["name"] == "hosted_on"


def test_manager_updates_existing_ontology_definition():
    client = Client()
    manager = OntologyManager(client, "workspace-1")

    manager.update_definition("ontology-1", {"parts": []})

    assert client.calls[-1][:2] == (
        "POST",
        "/workspaces/workspace-1/ontologies/ontology-1/updateDefinition",
    )


def test_manager_uses_fabric_client_iterator_contract():
    class FabricCompatibleClient:
        def iter_items(self, path):
            assert path == "/workspaces/workspace-1/ontologies"
            yield {"id": "ontology-1", "displayName": "Operational_Context"}

    manager = OntologyManager(FabricCompatibleClient(), "workspace-1")

    assert manager.list()[0]["id"] == "ontology-1"
