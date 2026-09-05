"""Wave 0 contracts for semantic old/new Exposure reconciliation."""

from __future__ import annotations

import pytest

from tests.exposure_scenario import load_exposure_scenario


def test_reconciliation_fixture_declares_every_zero_tolerance_difference() -> None:
    scenario = load_exposure_scenario()

    assert set(scenario["reconciliation_contract"]["hard_failure_classes"]) == {
        "scope_widening",
        "source_class_disappearance",
        "false_healthy_empty",
        "false_clear",
        "missing_image_relationship",
        "cursor_duplicate",
        "cursor_omission",
    }


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-18")
def test_shadow_comparison_checks_both_arms_without_assuming_either_is_truth() -> None:
    from operations.exposure_metrics import reconcile_exposure_arms

    assert reconcile_exposure_arms is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-18")
def test_scope_widening_is_a_hard_reconciliation_failure() -> None:
    from operations.exposure_metrics import reconcile_exposure_arms

    assert reconcile_exposure_arms is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-18")
def test_false_clear_or_false_healthy_empty_blocks_cutover() -> None:
    from operations.exposure_metrics import reconcile_exposure_arms

    assert reconcile_exposure_arms is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-18")
def test_source_class_identity_state_order_and_completeness_drift_is_reported() -> None:
    from operations.exposure_metrics import reconcile_exposure_arms

    assert reconcile_exposure_arms is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-18")
def test_expected_time_varying_enrichment_change_is_classified_separately() -> None:
    from operations.exposure_metrics import reconcile_exposure_arms

    assert reconcile_exposure_arms is not None
