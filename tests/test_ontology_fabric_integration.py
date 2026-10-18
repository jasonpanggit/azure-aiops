from __future__ import annotations

import json
from copy import deepcopy

import pytest
from test_exposure_ontology_roundtrip import (
    DEPLOYMENT_ID,
    DIGEST,
    EFFECTIVE_GENERATION,
    OBSERVATION_ID,
    fabric_products,
)

from fabric.dataset_mapper import GranularExposureOntologyMapper
from ontology.graph_queries import OntologyQueryService
from ontology.ontology_publisher import OntologyPublisher


def _query(
    *,
    completeness: str = "complete",
    include_deployment: bool = True,
) -> OntologyQueryService:
    products = fabric_products(completeness=completeness)
    if not include_deployment:
        products["silver_workload_deployments"] = []
    graph = GranularExposureOntologyMapper().project(
        products,
        ontology_generation_id="ontology-generation-3",
    )
    return OntologyQueryService(graph.entities, graph.relationships)


def test_cve_impact_returns_only_complete_exact_observed_workloads() -> None:
    result = _query().image_vulnerability_impact("CVE-2026-4242")

    assert result["cve_id"] == "CVE-2026-4242"
    assert result["represented_count"] == 1
    assert result["total_count"] == 1
    assert result["excluded_count"] == 0
    assert result["excluded_reasons"] == {}
    assert result["completeness"] == "complete"
    assert result["items"] == [
        {
            "deployment_id": DEPLOYMENT_ID,
            "image_digest": DIGEST,
            "observation_id": OBSERVATION_ID,
            "effective_generation": EFFECTIVE_GENERATION,
            "event_interval": {
                "from": "2026-09-05T10:00:00Z",
                "to": "2026-09-05T10:02:00Z",
            },
            "provenance": {
                "defender_observation_id": "defender-event-7",
                "image_observation_id": "image-observation-7",
            },
            "path": [
                "VulnerabilityObservation:identifies:CVE",
                "VulnerabilityObservation:affects:ImageDigest",
                "ImageDigest:deployedAs:WorkloadDeployment",
            ],
        }
    ]


@pytest.mark.parametrize("completeness", ["stale", "partial", "unavailable"])
def test_stale_or_incomplete_workload_evidence_is_excluded_with_unknown_metadata(
    completeness: str,
) -> None:
    result = _query(completeness=completeness).image_vulnerability_impact(
        "CVE-2026-4242"
    )

    assert result["represented_count"] == 0
    assert result["total_count"] == 1
    assert result["excluded_count"] == 1
    assert result["items"] == []
    assert result["completeness"] == "unknown"
    assert result["excluded_reasons"] == {"source_unavailable": 1}


def test_missing_workload_evidence_is_unknown_and_never_inferred() -> None:
    result = _query(
        completeness="unavailable",
        include_deployment=False,
    ).image_vulnerability_impact("CVE-2026-4242")

    assert result["represented_count"] == 0
    assert result["total_count"] == 1
    assert result["excluded_count"] == 1
    assert result["items"] == []
    assert result["excluded_reasons"] == {"source_unavailable": 1}


def test_server_vulnerability_traversal_excludes_typed_image_vertices() -> None:
    query = _query()

    assert query.server_vulnerability_impact("CVE-2026-4242") == []


def test_spoofed_evidence_identity_is_excluded_instead_of_traversed() -> None:
    graph = GranularExposureOntologyMapper().project(
        fabric_products(),
        ontology_generation_id="ontology-generation-3",
    )
    affects = next(
        row
        for row in graph.relationships
        if row["subject_type"] == "VulnerabilityObservation"
        and row["predicate"] == "affects"
        and row["object_type"] == "ImageDigest"
    )
    evidence = json.loads(affects["payload_json"])
    evidence["evidence_identity"] = "mutable-tag:latest"
    affects["payload_json"] = json.dumps(evidence, sort_keys=True)

    result = OntologyQueryService(
        graph.entities,
        graph.relationships,
    ).image_vulnerability_impact("CVE-2026-4242")

    assert result["represented_count"] == 0
    assert result["total_count"] == 1
    assert result["items"] == []
    assert result["excluded_reasons"] == {"invalid_exact_evidence": 1}


class _PartiallyFailingManager:
    def __init__(self, active_definition: dict) -> None:
        self.active_definition = deepcopy(active_definition)
        self.update_calls: list[dict] = []

    def resolve(self, **_kwargs: object) -> dict[str, str]:
        return {"id": "ontology-1", "displayName": "Operational Context"}

    def get_definition(self, _ontology_id: str) -> dict:
        return deepcopy(self.active_definition)

    def update_definition(self, _ontology_id: str, definition: dict) -> dict:
        self.update_calls.append(deepcopy(definition))
        if len(self.update_calls) == 1:
            self.active_definition = {
                "parts": deepcopy(definition.get("parts", [])[:1])
            }
            raise RuntimeError("Fabric interrupted after partial replacement")
        self.active_definition = deepcopy(definition)
        return {"id": "ontology-1"}


def test_failed_definition_update_restores_the_previous_active_graph() -> None:
    manager = _PartiallyFailingManager({"parts": []})
    publisher = OntologyPublisher(
        manager,
        workspace_id="workspace-1",
        lakehouse_id="lakehouse-1",
    )
    previous = publisher.build_definition(
        {"LogicalImage": "ontology_previous_logical_image_entities"},
        {},
        "Operational Context",
    )
    manager.active_definition = deepcopy(previous)

    with pytest.raises(
        RuntimeError,
        match="Fabric interrupted after partial replacement",
    ):
        publisher.publish(
            ontology_id="ontology-1",
            ontology_name="Operational Context",
            entity_types={
                "LogicalImage": "ontology_logical_image_entities",
                "ImageDigest": "ontology_image_digest_entities",
            },
            relationships={
                (
                    "LogicalImage",
                    "hasDigest",
                    "ImageDigest",
                ): "ontology_rel_logical_image_has_digest_image_digest",
            },
        )

    assert manager.active_definition == previous
    assert len(manager.update_calls) == 2
    assert manager.update_calls[-1] == previous
