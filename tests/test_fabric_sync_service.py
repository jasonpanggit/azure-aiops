from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from test_incremental_sync import _source_snapshot

from fabric.data_quality import DataQualityValidator
from fabric.dataset_mapper import GranularExposureOntologyMapper
from fabric.sync_service import (
    DedicatedOntologyPublisherAdapter,
    FabricSyncService,
    FabricTableWriteProgress,
    _exposure_gold_generation_id,
    _merge_granular_ontology_entities,
    _merge_granular_ontology_relationships,
    _observation_rows_at_or_before,
)
from fabric_pipelines.vulnerability_pipeline import (
    EXPOSURE_GOLD_POINTER_DOCUMENT,
    EXPOSURE_GOLD_TABLES,
)
from ontology.entity_builder import entity_change_version
from ontology.ontology_sync import OntologyGraphResult
from ontology.relationship_builder import relationship_change_version
from ontology_discovery.publisher import OntologyGenerationCandidate
from storage.delta_writer import DeltaWriter
from storage.onelake_documents import OneLakeDocumentStore
from storage.onelake_writer import OneLakeWriter


def _service(tmp_path: Path) -> FabricSyncService:
    source = tmp_path / "source"
    _source_snapshot(source)
    return FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter("workspace", "lakehouse", local_root=tmp_path / "lakehouse"),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )


def test_sync_reports_successful_table_writes_in_completion_order(tmp_path: Path) -> None:
    events: list[FabricTableWriteProgress] = []

    service = _service(tmp_path)
    result = service.sync(progress_callback=events.append)

    assert result.status == "completed"
    assert events
    assert [event.completed_tables for event in events] == list(range(1, len(events) + 1))
    assert all(event.total_tables == len(events) for event in events)
    assert {event.table_name for event in events} == set(result.tables)
    assert all(event.result is not None for event in events)
    assert not (
        tmp_path / "lakehouse" / "Tables" / "bronze_container_image_exposure"
    ).exists()


def test_sync_ignores_progress_callback_errors(tmp_path: Path) -> None:
    calls = 0

    def broken_callback(_event: FabricTableWriteProgress) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("progress sink unavailable")

    result = _service(tmp_path).sync(progress_callback=broken_callback)

    assert result.status == "completed"
    assert calls == len(result.tables)


def test_sync_publishes_repeatable_exposure_generation_and_pointer(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    first = service.sync(exposure_pointer_store=pointer_store)
    first_pointer = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    first_facts = service.delta.read(
        service.onelake.table_uri("gold", "exposure_facts")
    )
    second = service.sync(exposure_pointer_store=pointer_store)

    pointer = pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT)
    second_facts = service.delta.read(
        service.onelake.table_uri("gold", "exposure_facts")
    )
    expected_generation = str(pointer["readable_generation_id"])
    assert first.status == "completed"
    assert second.status == "completed"
    assert expected_generation.startswith("exposure-gold-")
    assert set(EXPOSURE_GOLD_TABLES) <= set(second.tables)
    assert "metadata_exposure_gold_generations" in second.tables
    assert pointer["retained_generations"][expected_generation]
    assert pointer["revision"] > first_pointer["revision"]
    assert pointer["activated_at"] == first_pointer["activated_at"]
    assert pointer["retained_generations"][expected_generation] == (
        first_pointer["retained_generations"][expected_generation]
    )
    assert second_facts == first_facts
    generation_rows = service.delta.read(
        service.onelake.table_uri(
            "metadata",
            "exposure_gold_generations",
        )
    )
    assert {
        row["read_model_generation_id"] for row in generation_rows
    } == {expected_generation}
    assert generation_rows[0]["published_at"] == pointer["activated_at"]
    assert generation_rows[0]["retain_until"] == (
        pointer["retained_generations"][expected_generation]["retain_until"]
    )
    observations = service.delta.read(
        service.onelake.table_uri(
            "silver",
            "exposure_observations",
        )
    )
    assert len(observations) == len(
        {row["observation_id"] for row in observations}
    )
    assert service.delta.read(
        service.onelake.table_uri(
            "gold",
            "container_exposure_coverage",
        )
    )[0]["timestamp"] != "1970-01-01T00:00:00Z"


def test_identical_source_produces_identical_gold_in_clean_lakehouses(
    tmp_path: Path,
) -> None:
    first_service = _service(tmp_path / "first")
    second_service = _service(tmp_path / "second")
    first_pointer = OneLakeDocumentStore(tmp_path / "first-registry")
    second_pointer = OneLakeDocumentStore(tmp_path / "second-registry")

    first_service.sync(exposure_pointer_store=first_pointer)
    second_service.sync(exposure_pointer_store=second_pointer)

    assert first_pointer.read(EXPOSURE_GOLD_POINTER_DOCUMENT)[
        "readable_generation_id"
    ] == second_pointer.read(EXPOSURE_GOLD_POINTER_DOCUMENT)[
        "readable_generation_id"
    ]
    assert first_service.delta.read(
        first_service.onelake.table_uri("gold", "exposure_facts")
    ) == second_service.delta.read(
        second_service.onelake.table_uri("gold", "exposure_facts")
    )


def test_sync_deduplicates_granular_ontology_scope_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_build_rows = GranularExposureOntologyMapper.build_rows

    def build_overlapping_rows(self, datasets, **kwargs):
        entities, relationships = original_build_rows(
            self,
            datasets,
            **kwargs,
        )
        overlapping_entity = dict(datasets["ontology_entities"][0])
        base_payload = json.loads(overlapping_entity["payload_json"])
        overlapping_entity["payload_json"] = json.dumps(
            {
                "fabric_key": "container-registry:v1:overlap",
                "fabric_row": {"registry_id": "registry-overlap"},
                "fabric_table": "silver_container_registries",
                **{
                    key: value
                    for key, value in base_payload.items()
                    if key not in {"fabric_key", "fabric_row", "fabric_table"}
                },
            },
            sort_keys=True,
        )
        return (
            [overlapping_entity, *entities],
            [dict(datasets["ontology_relationships"][0]), *relationships],
        )

    monkeypatch.setattr(
        GranularExposureOntologyMapper,
        "build_rows",
        build_overlapping_rows,
    )
    service = _service(tmp_path)

    result = service.sync(
        exposure_pointer_store=OneLakeDocumentStore(tmp_path / "registry")
    )

    assert result.status == "completed"
    entity_rows = service.delta.read(
        service.onelake.table_uri("ontology", "entities")
    )
    relationship_rows = service.delta.read(
        service.onelake.table_uri("ontology", "relationships")
    )
    assert len(entity_rows) == len(
        {str(row["resource_id"]).strip().casefold() for row in entity_rows}
    )
    assert len(relationship_rows) == len(
        {str(row["resource_id"]).strip().casefold() for row in relationship_rows}
    )
    restored = GranularExposureOntologyMapper().to_fabric(
        OntologyGraphResult(
            entities=entity_rows,
            relationships=relationship_rows,
            views={},
            health={},
            quality_report={},
        )
    )
    assert restored["silver_container_registries"] == [
        {"registry_id": "registry-overlap"}
    ]


def test_granular_entity_merge_is_lossless_and_preserves_primary_casing() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "/Subscriptions/Sub-A/registry",
        "entity_type": "ContainerRegistry",
        "lifecycle_status": "active",
        "payload_json": json.dumps(
            {
                "id": "/Subscriptions/Sub-A/registry",
                "resourceType": "Microsoft.ContainerRegistry/registries",
                "sourceSystem": "AzureResourceGraph",
            }
        ),
        "lineage_json": json.dumps({"source_resource_ids": ["inventory"]}),
        "semantic_metadata_json": json.dumps({"discovery": "inventory"}),
        "change_version": "old",
    }
    granular = {
        **primary,
        "resource_id": "/subscriptions/sub-a/registry",
        "payload_json": json.dumps(
            {
                "id": "/subscriptions/sub-a/registry",
                "resourceType": "microsoft.containerregistry/registries",
                "fabric_table": "silver_container_registries",
                "fabric_row": {"registry_id": "registry-a"},
            }
        ),
        "lineage_json": json.dumps({"source_resource_ids": ["granular"]}),
    }
    rows = [primary]

    _merge_granular_ontology_entities(rows, [granular])

    payload = json.loads(rows[0]["payload_json"])
    assert payload["id"] == "/Subscriptions/Sub-A/registry"
    assert payload["resourceType"] == "Microsoft.ContainerRegistry/registries"
    assert payload["sourceSystem"] == "AzureResourceGraph"
    assert payload["fabric_row"] == {"registry_id": "registry-a"}
    assert json.loads(rows[0]["lineage_json"])["source_resource_ids"] == [
        "granular",
        "inventory",
    ]
    assert rows[0]["semantic_metadata_json"] == primary["semantic_metadata_json"]
    assert rows[0]["change_version"] == entity_change_version(rows[0])


def test_granular_relationship_merge_rejects_conflicting_identity() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "relationship://contains",
        "subject_id": "/subscriptions/sub-a",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": "/subscriptions/sub-a/resourceGroups/one",
        "object_type": "ResourceGroup",
        "source": "inventory",
        "scope": "",
        "lifecycle_status": "active",
        "confidence": 1.0,
        "payload_json": "{}",
        "lineage_json": json.dumps(
            {"source_entity_ids": ["subscription", "group-one"]}
        ),
        "change_version": "",
    }
    primary["change_version"] = relationship_change_version(primary)
    conflict = {
        **primary,
        "object_id": "/subscriptions/sub-a/resourceGroups/two",
    }

    with pytest.raises(
        ValueError,
        match="Conflicting granular ontology relationship .*: object_id",
    ):
        _merge_granular_ontology_relationships([primary], [conflict])


def test_granular_relationship_merge_rejects_conflicting_payload() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "relationship://contains",
        "subject_id": "/subscriptions/sub-a",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": "/subscriptions/sub-a/resourceGroups/one",
        "object_type": "ResourceGroup",
        "source": "inventory",
        "scope": "",
        "lifecycle_status": "active",
        "confidence": 1.0,
        "payload_json": json.dumps({"evidence": "inventory"}),
        "lineage_json": json.dumps(
            {"source_entity_ids": ["subscription", "group-one"]}
        ),
        "change_version": "",
    }
    primary["change_version"] = relationship_change_version(primary)
    conflict = {
        **primary,
        "payload_json": json.dumps({"evidence": "granular"}),
    }

    with pytest.raises(
        ValueError,
        match="Conflicting granular ontology entity payload_json.evidence",
    ):
        _merge_granular_ontology_relationships([primary], [conflict])


def test_granular_relationship_merge_unions_lineage_and_versions_row() -> None:
    primary = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "relationship://contains",
        "subject_id": "/Subscriptions/Sub-A",
        "subject_type": "Subscription",
        "predicate": "contains",
        "object_id": "/Subscriptions/Sub-A/resourceGroups/one",
        "object_type": "ResourceGroup",
        "source": "inventory",
        "scope": "",
        "lifecycle_status": "active",
        "confidence": 1.0,
        "payload_json": "{}",
        "lineage_json": json.dumps(
            {"source_entity_ids": ["subscription"]}
        ),
        "change_version": "old",
    }
    granular = {
        **primary,
        "subject_id": "/subscriptions/sub-a",
        "object_id": "/subscriptions/sub-a/resourcegroups/one",
        "lineage_json": json.dumps({"source_entity_ids": ["group-one"]}),
    }
    rows = [primary]

    _merge_granular_ontology_relationships(rows, [granular])

    assert rows[0]["subject_id"] == "/Subscriptions/Sub-A"
    assert rows[0]["object_id"] == (
        "/Subscriptions/Sub-A/resourceGroups/one"
    )
    assert json.loads(rows[0]["lineage_json"])["source_entity_ids"] == [
        "group-one",
        "subscription",
    ]
    assert rows[0]["change_version"] == relationship_change_version(rows[0])


def test_sync_does_not_activate_gold_pointer_before_finalization(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    pointer_store = OneLakeDocumentStore(tmp_path / "registry")

    def fail_shortcuts() -> None:
        raise RuntimeError("shortcut finalization failed")

    service._create_shortcuts = fail_shortcuts  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="shortcut finalization failed"):
        service.sync(exposure_pointer_store=pointer_store)

    assert pointer_store.read(EXPOSURE_GOLD_POINTER_DOCUMENT) == {}
    assert max(
        service.status(),
        key=lambda row: str(row.get("timestamp") or ""),
    )["status"] == "failed"


def test_replayed_generation_excludes_later_observation_history() -> None:
    rows = [
        {"observation_id": "before", "ingested_at": "2026-09-08T00:00:00Z"},
        {"observation_id": "same", "ingested_at": "2026-09-08T01:00:00Z"},
        {"observation_id": "after", "ingested_at": "2026-09-08T02:00:00Z"},
    ]

    visible = _observation_rows_at_or_before(
        rows,
        projected_at="2026-09-08T01:00:00Z",
    )

    assert [row["observation_id"] for row in visible] == [
        "before",
        "same",
    ]


def test_gold_generation_identity_changes_with_late_observation() -> None:
    datasets = {
        "silver_exposure_observations": [
            {"observation_id": "observation-a"}
        ]
    }
    first = _exposure_gold_generation_id("source-a", datasets)
    datasets["silver_exposure_observations"].append(
        {"observation_id": "observation-late"}
    )

    assert _exposure_gold_generation_id("source-a", datasets) != first


def test_dedicated_publisher_promotes_before_fabric_materialization() -> None:
    calls: list[tuple[str, object]] = []

    class GenerationPublisher:
        def publish(self, candidate, **kwargs):
            calls.append(("generation", kwargs["publisher_identity"]))
            assert kwargs["publisher_identity"] == "ontology-publisher"
            return type(
                "Snapshot",
                (),
                {
                    "pointer": type(
                        "Pointer",
                        (),
                        {"active_generation": candidate.generation_id},
                    )(),
                    "etag": "etag-new",
                },
            )()

    class FabricMaterializer:
        def sync(self, **kwargs):
            calls.append(("fabric", kwargs["replay_source_run_id"]))
            return type(
                "Result",
                (),
                {"run_id": "fabric-run", "status": "completed", "tables": ("ontology_entities",)},
            )()

    candidate = OntologyGenerationCandidate(
        generation_id="ontology-generation-7",
        source_generation="inventory-generation-7",
        entities=(),
        relationships=(),
        proposal_lineage=(),
        decision_lineage=(),
        policy_version="policy-v1",
        schema_version="schema-v1",
    )
    adapter = DedicatedOntologyPublisherAdapter(
        generation_publisher=GenerationPublisher(),
        fabric_sync_service=FabricMaterializer(),
        publisher_identity="ontology-publisher",
        request_factory=lambda run, published: {
            "checkpoint_ids": ("approve-pointer-cutover", "approve-publisher-rbac"),
            "pointer_conditions": object(),
            "owner_id": "publisher-worker",
            "fence": 7,
            "consumer_compatibility": {"api": True},
            "cancellation_check": lambda: False,
            "lease_guard": lambda: None,
        },
        status_reader=lambda run_id: {
            "run_id": run_id,
            "active_generation": "ontology-generation-7",
            "pointer_etag": "etag-new",
        },
    )

    result = asyncio.run(
        adapter.publish(
            run={
                "run_id": "ODR-7",
                # Caller-controlled identity data must be ignored.
                "publisher_identity": "api-identity",
            },
            candidate=candidate,
        )
    )

    assert calls == [
        ("generation", "ontology-publisher"),
        ("fabric", "inventory-generation-7"),
    ]
    assert result == {
        "generation_id": "ontology-generation-7",
        "active_generation": "ontology-generation-7",
        "pointer_etag": "etag-new",
        "fabric_run_id": "fabric-run",
        "fabric_status": "completed",
        "fabric_tables": ["ontology_entities"],
    }


def test_dedicated_publisher_rejects_identity_override_from_request_factory() -> None:
    adapter = DedicatedOntologyPublisherAdapter(
        generation_publisher=object(),
        fabric_sync_service=object(),
        publisher_identity="ontology-publisher",
        request_factory=lambda run, candidate: {
            "publisher_identity": "coordinator-identity"
        },
        status_reader=lambda run_id: {},
    )
    candidate = OntologyGenerationCandidate(
        generation_id="generation-1",
        source_generation="source-1",
        entities=(),
        relationships=(),
        proposal_lineage=(),
        decision_lineage=(),
        policy_version="policy-v1",
        schema_version="schema-v1",
    )

    try:
        asyncio.run(adapter.publish(run={"run_id": "ODR-1"}, candidate=candidate))
    except PermissionError as exc:
        assert "identity" in str(exc).lower()
    else:
        raise AssertionError("coordinator identity substitution must be denied")
