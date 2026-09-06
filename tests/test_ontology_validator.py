from __future__ import annotations

import math

from ontology.ontology_validator import OntologyValidator


def _entity(**overrides) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "vm-1",
        "timestamp": "2026-08-17T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "entity_type": "VirtualMachine",
        "name": "vm-1",
        "resource_type": "microsoft.compute/virtualmachines",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-08-17T00:00:00Z",
        "retired_at": "",
        "ontology_version": "v1",
    }
    base.update(overrides)
    return base


def _relationship(**overrides) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": "relationship://rel-1",
        "timestamp": "2026-08-17T00:00:00Z",
        "change_version": "v1",
        "ingestion_run_id": "run-1",
        "subject_id": "vm-1",
        "subject_type": "VirtualMachine",
        "predicate": "member_of",
        "object_id": "app-1",
        "object_type": "Application",
        "source": "test",
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": "2026-08-17T00:00:00Z",
        "retired_at": "",
        "ontology_version": "v1",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


VM = _entity(resource_id="vm-1", entity_type="VirtualMachine", name="vm-1")
APP = _entity(
    resource_id="app-1",
    entity_type="Application",
    name="app-1",
    resource_type="application",
)


def test_entity_missing_required_field_fails_with_correct_category() -> None:
    for field_name in OntologyValidator.ENTITY_REQUIRED:
        entity = {**VM, field_name: ""}

        report = OntologyValidator().validate([entity], [])

        assert report.invalid_entities >= 1, field_name
        assert report.passed is False, field_name
        # No other structural category should be implicated by a bare
        # missing-required-field entity.
        assert report.duplicate_entities == 0, field_name
        assert report.dangling_relationships == 0, field_name
        assert report.self_relationships == 0, field_name
        assert report.invalid_relationships == 0, field_name


def test_dangling_relationship_subject_not_in_known_entities() -> None:
    relationship = _relationship(
        subject_id="does-not-exist",
        object_id="app-1",
    )

    report = OntologyValidator().validate([VM, APP], [relationship])

    assert report.dangling_relationships == 1
    assert report.passed is False


def test_dangling_relationship_object_not_in_known_entities() -> None:
    relationship = _relationship(
        subject_id="vm-1",
        object_id="does-not-exist",
    )

    report = OntologyValidator().validate([VM, APP], [relationship])

    assert report.dangling_relationships == 1
    assert report.passed is False


def test_self_relationship_is_flagged() -> None:
    relationship = _relationship(
        subject_id="vm-1",
        subject_type="VirtualMachine",
        object_id="vm-1",
        object_type="VirtualMachine",
    )

    report = OntologyValidator().validate([VM], [relationship])

    assert report.self_relationships == 1
    assert report.dangling_relationships == 0
    assert report.passed is False


def test_duplicate_relationship_flagged_once_per_extra_occurrence() -> None:
    # Real producers derive a relationship's `resource_id` deterministically
    # from (subject_id, predicate, object_id) -- see
    # relationship_builder.py::_relationship_id -- so "same subject/predicate/
    # object" surfaces here as "same resource_id".
    relationship = _relationship(resource_id="relationship://dup")

    report = OntologyValidator().validate(
        [VM, APP], [relationship, dict(relationship), dict(relationship)]
    )

    assert report.duplicate_relationships == 2
    assert report.passed is False


def test_confidence_outside_valid_range_or_non_finite_fails() -> None:
    for confidence in (True, math.nan, math.inf, -math.inf, -0.1, 1.1, "0.5", None):
        relationship = _relationship(confidence=confidence)

        report = OntologyValidator().validate([VM, APP], [relationship])

        assert report.invalid_relationships >= 1, confidence
        assert report.passed is False, confidence


def test_confidence_within_valid_range_does_not_fail() -> None:
    for confidence in (0.0, 0.5, 1.0):
        relationship = _relationship(confidence=confidence)

        report = OntologyValidator().validate([VM, APP], [relationship])

        assert report.invalid_relationships == 0, confidence


def test_active_relationship_type_mismatch_against_current_entity_fails() -> None:
    # subject_type "Application" disagrees with vm-1's current entity_type
    # ("VirtualMachine") -- for an *active* relationship this is a real
    # data-quality defect.
    relationship = _relationship(
        subject_id="vm-1",
        subject_type="Application",
        object_id="app-1",
        object_type="Application",
        lifecycle_status="active",
        retired_at="",
    )

    report = OntologyValidator().validate([VM, APP], [relationship])

    assert report.invalid_relationships >= 1
    assert report.passed is False


def test_retired_relationship_type_mismatch_against_current_entity_is_allowed() -> None:
    # An exact-vocabulary type disagreement, but on a
    # *retired* relationship -- OntologyValidator deliberately does not
    # enforce type agreement here, since the entity may have been
    # reclassified after the relationship was captured (documented exception
    # in ontology_validator.py).
    relationship = _relationship(
        subject_id="vm-1",
        subject_type="Resource",
        object_id="app-1",
        object_type="Application",
        lifecycle_status="retired",
        retired_at="2026-08-18T00:00:00Z",
    )

    report = OntologyValidator().validate([VM, APP], [relationship])

    assert report.invalid_relationships == 0
    assert report.passed is True


def test_validate_passes_when_all_six_categories_are_zero() -> None:
    relationship = _relationship()

    report = OntologyValidator().validate([VM, APP], [relationship])

    assert report.duplicate_entities == 0
    assert report.duplicate_relationships == 0
    assert report.dangling_relationships == 0
    assert report.self_relationships == 0
    assert report.invalid_entities == 0
    assert report.invalid_relationships == 0
    assert report.passed is True


def test_validate_fails_when_any_single_category_is_nonzero() -> None:
    # Duplicate entities specifically (the one category not covered by a
    # dedicated test above): two entities sharing the same resource_id.
    report = OntologyValidator().validate([VM, dict(VM)], [])

    assert report.duplicate_entities == 1
    assert report.passed is False
