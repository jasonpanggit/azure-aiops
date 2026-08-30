from __future__ import annotations

from typing import Any


class OntologyManager:
    """Thin manager over Microsoft Fabric's public Ontology item APIs."""

    def __init__(self, client, workspace_id: str) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.base_path = f"/workspaces/{workspace_id}/ontologies"

    def list(self) -> list[dict[str, Any]]:
        return list(self.client.iter_items(self.base_path))

    def resolve(self, *, ontology_id: str = "", ontology_name: str = "") -> dict[str, Any] | None:
        if ontology_id:
            return self.client.request("GET", f"{self.base_path}/{ontology_id}")
        matches = [item for item in self.list() if item.get("displayName") == ontology_name]
        if len(matches) > 1:
            raise ValueError(f"Multiple Fabric ontologies named {ontology_name!r}; configure ontology_id")
        return matches[0] if matches else None

    def create(self, display_name: str, definition: dict[str, Any]) -> dict[str, Any]:
        return self.client.request(
            "POST",
            self.base_path,
            json_body={
                "displayName": display_name,
                "description": "Continuously maintained AIOps Operational Context Graph",
                "definition": definition,
            },
        )

    def get_definition(self, ontology_id: str) -> dict[str, Any]:
        response = self.client.request(
            "POST", f"{self.base_path}/{ontology_id}/getDefinition"
        )
        return dict(response.get("definition") or {})

    def update_definition(self, ontology_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        return self.client.request(
            "POST",
            f"{self.base_path}/{ontology_id}/updateDefinition",
            json_body={"definition": definition},
        )
