from __future__ import annotations

from dataclasses import replace

import pytest

from ontology.ontology_validator import OntologyValidator
from ontology_discovery.publisher import (
    APPROVED_PUBLICATION_CHECKPOINTS,
    OntologyGenerationCandidate,
    OntologyGenerationPublisher,
    PublicationSafetyError,
)
from storage.datasets import DatasetStore, GenerationPointerConditions
from storage.locking import LeaseLostError


def _entity(resource_id: str, entity_type: str) -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "timestamp": "2026-09-07T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": entity_type,
        "name": resource_id,
        "resource_type": "test/resource",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-09-07T00:00:00Z",
        "retired_at": "",
        "ontology_version": "v1",
    }


def _relationship(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "relationship://vm-app",
        "timestamp": "2026-09-07T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "source": "deterministic",
        "scope": "tenant-1/sub-1",
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-09-07T00:00:00Z",
        "retired_at": "",
        "ontology_version": "v1",
        "confidence": 1.0,
    }
    row.update(overrides)
    return row


def _candidate(
    generation_id: str = "generation-1",
    source_generation: str = "source-1",
) -> OntologyGenerationCandidate:
    return OntologyGenerationCandidate(
        generation_id=generation_id,
        source_generation=source_generation,
        entities=(
            _entity("vm-1", "VirtualMachine"),
            _entity("app-1", "Application"),
        ),
        relationships=(_relationship(),),
        proposal_lineage=("proposal-shadow-1",),
        decision_lineage=("decision-shadow-excluded-1",),
        policy_version="ontology-policy/v1",
        schema_version="ontology-generation/v1",
    )


def _publisher(tmp_path):
    store = DatasetStore(tmp_path)
    adapter = store.authoritative_publisher(
        publisher_identity="ontology-publisher",
        approved_publisher_identity="ontology-publisher",
    )
    publisher = OntologyGenerationPublisher(
        adapter,
        validator=OntologyValidator(
            allowed_triples={("VirtualMachine", "member_of", "Application")}
        ),
        approved_publisher_identity="ontology-publisher",
    )
    return store, adapter, publisher


def _publish(
    publisher: OntologyGenerationPublisher,
    candidate: OntologyGenerationCandidate,
    *,
    conditions: GenerationPointerConditions | None = None,
    owner_id: str = "writer-1",
    fence: int = 1,
    compatibility: dict[str, bool] | None = None,
    cancellation_check=lambda: False,
    lease_guard=lambda: None,
):
    return publisher.publish(
        candidate,
        publisher_identity="ontology-publisher",
        checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
        pointer_conditions=conditions or GenerationPointerConditions.initial(),
        owner_id=owner_id,
        fence=fence,
        consumer_compatibility=compatibility
        or {
            "api": True,
            "fabric": True,
            "agent": True,
            "export": True,
            "semantic": True,
        },
        cancellation_check=cancellation_check,
        lease_guard=lease_guard,
    )


def test_stage_is_complete_immutable_and_promoted_only_after_audit(tmp_path):
    _store, adapter, publisher = _publisher(tmp_path)

    result = _publish(publisher, _candidate())
    staged = adapter.read_generation("generation-1")

    assert result.pointer.active_generation == "generation-1"
    assert staged["manifest"]["complete"] is True
    assert staged["manifest"]["generation_id"] == "generation-1"
    assert staged["manifest"]["source_generation"] == "source-1"
    assert staged["manifest"]["owner_id"] == "writer-1"
    assert staged["manifest"]["fence"] == 1
    assert staged["manifest"]["content_hash"]
    assert staged["manifest"]["entity_hash"]
    assert staged["manifest"]["relationship_hash"]
    assert staged["lineage"] == {
        "proposal_ids": ["proposal-shadow-1"],
        "decision_ids": ["decision-shadow-excluded-1"],
    }
    assert staged["validation"]["passed"] is True
    assert staged["compatibility"]["all_consumers_compatible"] is True
    assert staged["audit"]["outcome"] == "promoted"

    with pytest.raises(PublicationSafetyError, match="immutable"):
        _publish(publisher, _candidate())


def test_shadow_model_edge_is_rejected_before_pointer_visibility(tmp_path):
    _store, adapter, publisher = _publisher(tmp_path)
    model_candidate = replace(
        _candidate(),
        relationships=(
            _relationship(
                resource_id="relationship://model",
                source="model",
                model_derived=True,
            ),
        ),
    )

    with pytest.raises(PublicationSafetyError, match="model-derived"):
        _publish(publisher, model_candidate)

    assert adapter.read_pointer().pointer is None
    assert adapter.generation_exists("generation-1") is False


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ({"cancellation_check": lambda: True}, "cancelled"),
        (
            {
                "lease_guard": lambda: (_ for _ in ()).throw(
                    LeaseLostError("lease lost")
                )
            },
            "lease",
        ),
        ({"compatibility": {"api": True}}, "compatibility"),
    ],
)
def test_cancelled_lease_lost_or_incompatible_generation_never_promotes(
    tmp_path,
    mutation,
    error,
):
    _store, adapter, publisher = _publisher(tmp_path)

    with pytest.raises(PublicationSafetyError, match=error):
        _publish(publisher, _candidate(), **mutation)

    assert adapter.read_pointer().pointer is None


def test_invalid_partial_or_unaudited_generation_never_promotes(tmp_path, monkeypatch):
    _store, adapter, publisher = _publisher(tmp_path)
    invalid = replace(
        _candidate(),
        entities=(_entity("vm-1", "VirtualMachine"),),
    )

    with pytest.raises(PublicationSafetyError, match="validation"):
        _publish(publisher, invalid)
    assert adapter.read_pointer().pointer is None

    def fail_audit(*_args, **_kwargs):
        raise OSError("audit unavailable")

    monkeypatch.setattr(adapter, "persist_generation_audit", fail_audit)
    with pytest.raises(PublicationSafetyError, match="audit"):
        _publish(
            publisher,
            _candidate(generation_id="generation-unaudited"),
        )
    assert adapter.read_pointer().pointer is None


def test_stale_writer_loses_and_fenced_rollback_restores_prior_generation(tmp_path):
    _store, adapter, publisher = _publisher(tmp_path)
    first = _publish(publisher, _candidate())
    predecessor = GenerationPointerConditions.from_snapshot(first)
    second = _publish(
        publisher,
        _candidate("generation-2", "source-2"),
        conditions=predecessor,
        owner_id="writer-2",
        fence=2,
    )

    with pytest.raises(PublicationSafetyError, match="stale"):
        _publish(
            publisher,
            _candidate("generation-stale", "source-stale"),
            conditions=predecessor,
            owner_id="writer-1",
            fence=3,
        )

    rolled_back = publisher.rollback(
        target_generation_id="generation-1",
        source_generation="source-1",
        publisher_identity="ontology-publisher",
        checkpoint_ids=APPROVED_PUBLICATION_CHECKPOINTS,
        pointer_conditions=GenerationPointerConditions.from_snapshot(second),
        owner_id="writer-3",
        fence=3,
        cancellation_check=lambda: False,
        lease_guard=lambda: None,
    )

    assert rolled_back.pointer.active_generation == "generation-1"
    assert rolled_back.pointer.prior_generation == "generation-2"
    assert adapter.generation_exists("generation-1")
    assert adapter.generation_exists("generation-2")
