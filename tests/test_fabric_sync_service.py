from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from test_incremental_sync import _source_snapshot

from fabric.data_quality import DataQualityValidator
from fabric.sync_service import (
    DedicatedOntologyPublisherAdapter,
    FabricSyncService,
    FabricTableWriteProgress,
    _exposure_gold_generation_id,
    _observation_rows_at_or_before,
)
from fabric_pipelines.vulnerability_pipeline import (
    EXPOSURE_GOLD_POINTER_DOCUMENT,
    EXPOSURE_GOLD_TABLES,
)
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
