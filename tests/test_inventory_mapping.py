from __future__ import annotations

from api.scope import Scope
from intelligence.inventory.mapping_repository import (
    MappingRevisionConflict,
    SoftwareMappingRepository,
)
from intelligence.inventory.service import InventoryService


def _payload() -> dict:
    return {
        "observed_at": "2026-08-26T00:00:00Z",
        "software_observations": [
            {
                "software_name": "Widget",
                "software_version": "1.0",
                "raw_software_name": "Widget Suite",
                "raw_software_version": "v1.0",
                "canonical_identity": "Widget|1.0",
                "resource_id": "vm-a",
                "machine_name": "vm-a",
                "source_computer_id": "agent-a",
                "source_type": "azure_vm",
                "join_status": "linked",
                "subscription_id": "sub-a",
                "resource_group": "rg-a",
                "environment": "prod",
                "publisher": "Acme",
                "software_type": "Package",
                "observed_at": "2026-08-26T00:00:00Z",
            }
        ],
        "software_mapping_suggestions": [
            {
                "raw_name": "Widget Suite",
                "raw_version": "v1.0",
                "publisher": "Acme",
                "source_timestamp": "2026-08-26T00:00:00Z",
                "scope_predicate": {"subscription": ["sub-a"]},
                "model_output": {
                    "canonical_name": "Widget",
                    "canonical_version": "1.0",
                    "confidence": 0.91,
                    "provenance": {"model": "approved-normalizer"},
                },
            }
        ],
    }


def test_suggestions_are_server_owned_and_approved_mapping_changes_grouping() -> None:
    repository = SoftwareMappingRepository()
    service = InventoryService(_payload(), mapping_repository=repository)

    pending = service.mapping_collection(Scope.from_mapping({"subscription": ["sub-a"]}))
    assert len(pending["data"]["mappings"]) == 1
    mapping = pending["data"]["mappings"][0]
    assert mapping["status"] == "suggested"
    assert mapping["raw_identity"] == {
        "name": "Widget Suite",
        "version": "v1.0",
        "publisher": "Acme",
    }
    assert service.software_collection(
        Scope.from_mapping({"subscription": ["sub-a"]})
    )["data"]["groups"] == []

    approved = repository.decide(
        mapping["mapping_id"],
        decision="approved",
        expected_revision=mapping["revision"],
        actor="operator@example.com",
        scope_snapshot={"subscription": ["sub-a"]},
        timestamp="2026-08-26T00:01:00Z",
    )
    assert approved.revision == 1
    groups = service.software_collection(
        Scope.from_mapping({"subscription": ["sub-a"]})
    )["data"]["groups"]
    assert groups[0]["key"] == "Widget|1.0"
    assert groups[0]["install_count"] == 1
    assert repository.read().audit_events[-1]["action"] == "software_mapping.approved"
    assert repository.read().audit_events[-1]["actor"] == "operator@example.com"
    assert repository.read().audit_events[-1]["scope_snapshot"] == {
        "subscription": ["sub-a"]
    }
    assert repository.read().audit_events[-1]["mapping_provenance"]["raw_identity"]["publisher"] == "Acme"


def test_rejection_and_stale_revision_do_not_change_counts() -> None:
    repository = SoftwareMappingRepository()
    service = InventoryService(_payload(), mapping_repository=repository)
    mapping = service.mapping_collection(Scope.from_mapping({"subscription": ["sub-a"]}))[
        "data"
    ]["mappings"][0]

    rejected = repository.decide(
        mapping["mapping_id"],
        decision="rejected",
        expected_revision=0,
        actor="operator@example.com",
        scope_snapshot={"subscription": ["sub-a"]},
    )
    assert rejected.status == "rejected"
    assert service.software_collection(
        Scope.from_mapping({"subscription": ["sub-a"]})
    )["data"]["groups"] == []
    try:
        repository.decide(
            mapping["mapping_id"],
            decision="approved",
            expected_revision=0,
            actor="stale@example.com",
            scope_snapshot={"subscription": ["sub-a"]},
        )
    except MappingRevisionConflict as exc:
        assert exc.current == 1
    else:
        raise AssertionError("stale mapping revision was accepted")


def test_malformed_model_output_is_visible_but_non_authoritative() -> None:
    repository = SoftwareMappingRepository()
    item = repository.suggest(
        raw_name="Mystery",
        raw_version="v2",
        publisher="Acme",
        canonical_name="Mystery",
        canonical_version="2",
        provenance={"source": "ai", "validation_error": "canonical_version_missing"},
        source_timestamp="2026-08-26T00:00:00Z",
    )
    assert item.status == "suggested"
    assert item.provenance["validation_error"] == "canonical_version_missing"
    assert repository.read().mappings[0].status == "suggested"
