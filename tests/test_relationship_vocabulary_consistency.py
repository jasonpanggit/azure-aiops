"""CI guardrail: keep onboarding's discovery-snapshot vocabulary a subset of Fabric's.

``onboarding.ontology_metadata.RELATIONSHIP_TYPES`` intentionally does not
import ``fabric.dataset_mapper`` (onboarding must not depend on fabric), so
nothing at runtime enforces that its three predicates still exist in the
authoritative ~70-entry Fabric vocabulary. This test imports both modules
(a test-only cross-package import is fine) and asserts the subset invariant
so a future edit to either list that breaks the relationship fails CI instead
of silently drifting.
"""

from __future__ import annotations

from fabric.dataset_mapper import ONTOLOGY_ENTITY_TYPES, ONTOLOGY_RELATIONSHIP_TYPES
from onboarding.ontology_metadata import RELATIONSHIP_TYPES
from ontology.entity_builder import PAAS_ENTITY_TYPES


def test_onboarding_predicates_are_subset_of_fabric_vocabulary() -> None:
    fabric_predicates = {predicate for _subject, predicate, _object in ONTOLOGY_RELATIONSHIP_TYPES}
    onboarding_predicates = set(RELATIONSHIP_TYPES)

    missing = onboarding_predicates - fabric_predicates
    assert not missing, (
        "onboarding.ontology_metadata.RELATIONSHIP_TYPES has predicates not present in "
        f"fabric.dataset_mapper.ONTOLOGY_RELATIONSHIP_TYPES: {sorted(missing)}"
    )


def test_fabric_relationship_endpoint_types_are_registered_entities() -> None:
    entity_types = set(ONTOLOGY_ENTITY_TYPES)
    missing = {
        endpoint_type
        for subject_type, _predicate, object_type in ONTOLOGY_RELATIONSHIP_TYPES
        for endpoint_type in (subject_type, object_type)
        if endpoint_type not in entity_types
    }

    assert not missing, (
        "fabric.dataset_mapper.ONTOLOGY_RELATIONSHIP_TYPES references endpoint "
        f"types not present in ONTOLOGY_ENTITY_TYPES: {sorted(missing)}"
    )


def test_paas_relationship_entity_types_are_registered() -> None:
    missing = set(PAAS_ENTITY_TYPES) - set(ONTOLOGY_ENTITY_TYPES)

    assert not missing, (
        "PaaS entity types produced by RelationshipBuilder must be registered "
        f"before ontology publish: {sorted(missing)}"
    )


def test_modules_remain_independently_importable() -> None:
    # Regression guard: importing onboarding.ontology_metadata alone must not
    # require fabric to be importable (and vice versa is exercised implicitly
    # by every other onboarding test in this suite).
    import importlib

    module = importlib.import_module("onboarding.ontology_metadata")
    assert hasattr(module, "RELATIONSHIP_TYPES")
