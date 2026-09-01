from __future__ import annotations

from ontology.confidence import compute_confidence


def test_known_source_returns_documented_base_confidence():
    assert compute_confidence("arg:PatchAssessmentResources") == 0.98
    assert compute_confidence("azure:CostManagement") == 1.0
    assert compute_confidence("resource_tag") == 1.0
    assert compute_confidence("dependency_tag") == 1.0
    assert compute_confidence("subscription_connection") == 1.0
    assert compute_confidence("inventory") == 1.0


def test_unknown_source_defaults_to_one():
    assert compute_confidence("some_never_before_seen_source") == 1.0


def test_prefix_fallback_for_arg_and_azure_sources():
    assert compute_confidence("arg:SomeNewResourceContainers") == 1.0
    assert compute_confidence("azure:SomeNewTelemetry") == 1.0


def test_corroboration_bumps_confidence_but_caps_at_one():
    base = compute_confidence("arg:PatchAssessmentResources")
    corroborated = compute_confidence("arg:PatchAssessmentResources", corroborated=True)
    assert corroborated > base
    assert corroborated <= 1.0

    already_perfect = compute_confidence("azure:CostManagement", corroborated=True)
    assert already_perfect == 1.0


def test_base_override_preserves_call_site_specific_literal():
    assert compute_confidence("arg:Resources", base=0.9) == 0.9
    assert compute_confidence("arg:Resources", base=0.95) == 0.95
    assert compute_confidence("arg:Resources", base=0.99) == 0.99
    corroborated = compute_confidence("arg:Resources", base=0.9, corroborated=True)
    assert corroborated == 0.92
