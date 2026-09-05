"""Wave 0 contracts for immutable observations and deterministic replay."""

from __future__ import annotations

import pytest

from tests.exposure_scenario import load_exposure_scenario


def test_temporal_fixture_covers_reintroduction_out_of_order_ties_and_unknown_time() -> None:
    scenario = load_exposure_scenario()
    cases = {item["case_id"]: item for item in scenario["temporal_cases"]}

    assert cases["missing-installed-reintroduced"]["expected_state"] == "reintroduced"
    assert cases["missing-installed-reintroduced"]["expected_reintroduction_count"] == 1
    tied = cases["out-of-order-and-same-time-tie"]["observations"]
    assert len({item["event_time"] for item in tied}) < len(tied)
    assert cases["unknown-first-detection"]["expected_first_detected_at"] is None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-08")
def test_successful_later_install_closes_matching_missing_observation() -> None:
    from intelligence.vulnerability.projector import project_current

    assert project_current is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-08")
def test_later_missing_reopens_exposure_and_increments_reintroduction() -> None:
    from intelligence.vulnerability.projector import project_current

    assert project_current is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-08")
def test_stale_or_failed_install_does_not_close_newer_missing_evidence() -> None:
    from intelligence.vulnerability.projector import project_current

    assert project_current is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-08")
def test_arrival_order_does_not_change_projected_current_state() -> None:
    from intelligence.vulnerability.projector import project_current

    assert project_current is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-08")
def test_same_time_ties_use_operation_generation_ingestion_and_stable_id_order() -> None:
    from intelligence.vulnerability.projector import project_current

    assert project_current is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-08")
def test_observation_identity_is_immutable_and_payload_sensitive() -> None:
    from intelligence.vulnerability.observations import ExposureObservation

    assert ExposureObservation is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-09")
def test_unknown_first_detection_produces_indeterminate_sla() -> None:
    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    assert VulnerabilityIntelligenceService is not None
