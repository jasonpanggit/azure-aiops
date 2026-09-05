"""Wave 0 contracts for one scoped truth across every Exposure consumer."""

from __future__ import annotations

import pytest

from tests.exposure_scenario import load_exposure_scenario


def test_consumer_fixture_names_one_generation_and_all_required_consumers() -> None:
    scenario = load_exposure_scenario()

    assert scenario["read_model_generation_id"] == "exposure-generation-0001"
    assert scenario["consumer_contract"]["consumers"] == [
        "api",
        "web",
        "copilot",
        "remediation",
    ]
    assert scenario["identity_cases"]["unauthorized"]["target_id"].split("/")[2] in set(
        scenario["scope"]["unauthorized_subscriptions"]
    )


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-14")
def test_api_web_copilot_and_remediation_return_identical_ids_and_generation() -> None:
    from intelligence.vulnerability.exposure_contracts import ExposurePage

    assert ExposurePage is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-14")
def test_every_consumer_excludes_the_unauthorized_subscription_before_counting() -> None:
    from intelligence.vulnerability.read_port import ExposureReadPort

    assert ExposureReadPort is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-14")
def test_consumer_contract_preserves_completeness_freshness_units_and_evidence() -> None:
    from intelligence.vulnerability.exposure_contracts import ExposurePage

    assert ExposurePage is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-14")
def test_container_finding_stops_at_review_handoff_or_no_safe_action() -> None:
    from intelligence.remediation.defender_correlation import (
        DefenderRemediationCorrelator,
    )

    assert DefenderRemediationCorrelator is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-14")
def test_executable_action_registry_remains_the_three_existing_action_ids() -> None:
    from intelligence.remediation.action_catalog import EXECUTABLE_ACTION_IDS

    assert EXECUTABLE_ACTION_IDS == {
        "controlled-patch-recovery",
        "defender-enable-servers-plan-p1",
        "defender-enable-storage-plan-v2",
    }


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-21")
def test_production_factories_carry_the_tracer_without_test_only_consumer_wiring() -> None:
    from api.runtime import build_api_context

    assert build_api_context is not None
