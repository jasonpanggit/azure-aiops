from __future__ import annotations

import asyncio
from pathlib import Path

from test_incremental_sync import _source_snapshot

from fabric.data_quality import DataQualityValidator
from fabric.sync_service import (
    DedicatedOntologyPublisherAdapter,
    FabricSyncService,
    FabricTableWriteProgress,
)
from ontology_discovery.publisher import OntologyGenerationCandidate
from storage.delta_writer import DeltaWriter
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
