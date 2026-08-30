from fabric.dataset_mapper import InventoryDatasetMapper
from ontology.ontology_validator import OntologyValidator


def test_situations_are_registered_as_ontology_entities_with_typed_links(tmp_path) -> None:
    from datetime import UTC, datetime

    from onboarding.graph_normalize import Normalizer
    from onboarding.ingestion_storage import DatasetStore

    observed = datetime(2026, 8, 25, tzinfo=UTC)
    graph = Normalizer().normalize(
        {
            "resources": [{"id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm", "subscriptionId": "sub-a", "type": "Microsoft.Compute/virtualMachines"}],
            "resource_changes": [{"id": "change", "properties": {"targetResourceId": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm", "changeType": "write", "changeAttributes": {"timestamp": observed.isoformat()}}}],
        },
        observed,
    )
    from situations.materializer import materialize_graph

    generated = materialize_graph(graph, "run", ingested_at=observed.isoformat())
    for name, rows in generated.items():
        setattr(graph, name, rows)
    store = DatasetStore(tmp_path)
    store.publish(graph, {}, {"runId": "run", "startedAt": observed.isoformat()})
    datasets = InventoryDatasetMapper().load(tmp_path / "current", "sync")
    report = OntologyValidator().validate(datasets["ontology_entities"], datasets["ontology_relationships"])
    assert report.passed
    assert any(row["entity_type"] == "Situation" for row in datasets["ontology_entities"])
    assert any(row["subject_type"] == "Situation" for row in datasets["ontology_relationships"])


def test_required_operational_link_families_are_retained_when_unresolved() -> None:
    from datetime import UTC, datetime

    from onboarding.graph_normalize import Normalizer

    resource_id = "/subscriptions/sub-a/resource-groups/rg/providers/microsoft.compute/virtualmachines/vm"
    related = [
        {"entity_type": entity_type, "entity_id": f"{entity_type.lower()}-1"}
        for entity_type in (
            "Incident",
            "Exposure",
            "Compliance",
            "Vulnerability",
            "Change",
            "Service",
            "OperationalTwin",
        )
    ]
    graph = Normalizer().normalize(
        {
            "resources": [{"id": resource_id, "subscriptionId": "sub-a", "type": "Microsoft.Compute/virtualMachines"}],
            "monitor": [
                {
                    "id": "monitor-1",
                    "resource_id": resource_id,
                    "observed_at": "2026-08-25T01:00:00Z",
                    "related_entities": related,
                }
            ],
        },
        datetime(2026, 8, 25, 2, tzinfo=UTC),
        run_id="links-run",
    )

    links = graph.links
    assert {
        link["entity_type"] for link in links
    } >= {"Incident", "Exposure", "Compliance", "Vulnerability", "Change", "Resource", "Service", "OperationalTwin"}
    assert all(link["quality"] == "unresolved" for link in links if link["entity_type"] != "Resource")
    assert any(link["entity_type"] == "Resource" and link["quality"] == "resolved" for link in links)
