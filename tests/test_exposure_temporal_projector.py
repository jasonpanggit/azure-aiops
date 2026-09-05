"""Wave 0 contracts for immutable observations and deterministic replay."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from itertools import permutations

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


def test_successful_later_install_closes_matching_missing_observation() -> None:
    from intelligence.vulnerability.projector import project_current

    observations = (
        _observation(
            event="missing",
            event_time="2026-08-01T00:00:00Z",
            source_sequence=1,
        ),
        _observation(
            event="installed",
            event_time="2026-08-02T00:00:00Z",
            source_sequence=2,
            provider_operation_id="install-1",
        ),
    )

    current = project_current(observations, generation_id="generation-2")

    assert current.state == "installed"
    assert current.active is False
    assert current.active_source_families == ()
    assert current.first_detected_at == "2026-08-01T00:00:00Z"
    assert current.first_detection_quality == "provider"
    assert current.episode_started_at is None
    assert current.projection_generation_id == "generation-2"


def test_later_missing_reopens_exposure_and_increments_reintroduction() -> None:
    from intelligence.vulnerability.projector import project_current

    observations = (
        _observation(event="missing", event_time="2026-08-01T00:00:00Z"),
        _observation(
            event="installed",
            event_time="2026-08-02T00:00:00Z",
            provider_operation_id="install-1",
        ),
        _observation(
            event="missing",
            event_time="2026-08-03T00:00:00Z",
            provider_operation_id="assessment-2",
        ),
    )

    current = project_current(observations, generation_id="generation-3")

    assert current.state == "reintroduced"
    assert current.active is True
    assert current.first_detected_at == "2026-08-01T00:00:00Z"
    assert current.episode_started_at == "2026-08-03T00:00:00Z"
    assert current.reintroduction_count == 1
    assert current.observation_count == 3


def test_stale_or_failed_install_does_not_close_newer_missing_evidence() -> None:
    from intelligence.vulnerability.projector import project_current

    stale = (
        _observation(
            event="installed",
            event_time="2026-08-01T00:00:00Z",
            provider_operation_id="old-install",
        ),
        _observation(
            event="missing",
            event_time="2026-08-02T00:00:00Z",
            provider_operation_id="new-assessment",
        ),
    )
    failed = (
        _observation(event="missing", event_time="2026-08-01T00:00:00Z"),
        _observation(
            event="installed",
            event_time="2026-08-02T00:00:00Z",
            operation_succeeded=False,
            provider_status="failed",
            provider_operation_id="failed-install",
        ),
    )

    assert project_current(stale).state == "missing"
    failed_current = project_current(failed)
    assert failed_current.state == "missing"
    assert failed_current.active is True
    assert failed_current.reintroduction_count == 0


def test_arrival_order_does_not_change_projected_current_state() -> None:
    from intelligence.vulnerability.projector import project_current

    fixture = load_exposure_scenario()["temporal_cases"][0]
    observations = tuple(
        _observation(
            event=item["event"],
            event_time=item["event_time"],
            operation_succeeded=item["operation_succeeded"],
            source_sequence=item["source_sequence"],
            ingested_at=item["ingested_at"],
            provider_operation_id=item["event_id"],
        )
        for item in fixture["observations"]
    )

    projected = {
        project_current(candidate, generation_id="replay-generation").canonical_json()
        for candidate in permutations(observations)
    }

    assert len(projected) == 1
    current = project_current(observations)
    assert current.state == fixture["expected_state"]
    assert current.reintroduction_count == fixture["expected_reintroduction_count"]
    assert current.first_detected_at == fixture["expected_first_detected_at"]


def test_same_time_ties_use_operation_generation_ingestion_and_stable_id_order() -> None:
    from intelligence.vulnerability.projector import project_current

    same_time = "2026-08-05T00:00:00Z"
    observations = (
        _observation(
            event="missing",
            event_time=same_time,
            operation_succeeded=True,
            source_sequence=4,
            source_generation="generation-b",
            ingested_at="2026-08-05T00:04:00Z",
            provider_operation_id="assessment-winning-sequence",
        ),
        _observation(
            event="installed",
            event_time=same_time,
            operation_succeeded=False,
            source_sequence=99,
            source_generation="generation-z",
            ingested_at="2026-08-05T00:09:00Z",
            provider_status="failed",
            provider_operation_id="failed-install",
        ),
        _observation(
            event="resolved",
            event_time=same_time,
            operation_succeeded=True,
            source_sequence=3,
            source_generation="generation-z",
            ingested_at="2026-08-05T00:03:00Z",
            provider_operation_id="resolved-earlier-sequence",
        ),
    )

    current = project_current(observations)

    # Failed operations sort before successful operations at the same provider
    # time, then source sequence/generation and ingestion time decide the winner.
    assert current.state == "missing"
    assert current.last_observation_id == observations[0].observation_id


def test_source_family_evidence_cannot_erase_another_family() -> None:
    from intelligence.vulnerability.projector import project_current

    observations = (
        _observation(
            event="missing",
            event_time="2026-08-01T00:00:00Z",
            source_family="defender_subassessment",
            provider_operation_id="defender-1",
        ),
        _observation(
            event="missing",
            event_time="2026-08-01T01:00:00Z",
            source_family="azure_update_manager_missing",
            provider_operation_id="aum-assess-1",
        ),
        _observation(
            event="installed",
            event_time="2026-08-02T00:00:00Z",
            source_family="azure_update_manager_installation",
            provider_operation_id="aum-install-1",
        ),
    )

    current = project_current(observations)

    assert current.state == "missing"
    assert current.active_source_families == ("defender",)
    assert dict(current.source_states) == {
        "aum": "installed",
        "defender": "missing",
    }


def test_observation_identity_is_immutable_and_payload_sensitive() -> None:
    from intelligence.vulnerability.observations import ExposureObservation

    first = _observation(payload={"severity": "High", "nested": {"b": 2, "a": 1}})
    reordered = _observation(
        payload={"nested": {"a": 1, "b": 2}, "severity": "High"}
    )
    changed = _observation(payload={"severity": "Critical"})
    different_ingestion = _observation(
        payload={"severity": "High", "nested": {"b": 2, "a": 1}},
        ingested_at="2026-08-09T00:00:00Z",
    )

    assert first.observation_id == reordered.observation_id
    assert first.payload_fingerprint == reordered.payload_fingerprint
    assert first.observation_id != changed.observation_id
    # Retries do not mint a new provider observation identity.
    assert first.observation_id == different_ingestion.observation_id
    assert first.current_key == changed.current_key
    assert first.observation_id.startswith("exposure-observation:v1:")
    assert first.current_key.startswith("exposure-current:v1:")
    assert ExposureObservation.from_dict(first.to_dict()) == first
    with pytest.raises(FrozenInstanceError):
        first.status = "resolved"  # type: ignore[misc]


def test_unknown_provider_time_never_uses_ingestion_or_publication_for_detection() -> None:
    from intelligence.vulnerability.projector import project_current

    current = project_current(
        (
            _observation(
                event="missing",
                event_time=None,
                ingested_at="2026-08-06T00:01:00Z",
                published_at="2026-08-06T00:02:00Z",
            ),
        )
    )

    assert current.state == "missing"
    assert current.first_detected_at is None
    assert current.first_detection_quality == "unknown"
    assert current.episode_started_at is None
    assert current.last_observed_at is None


def test_duplicate_observation_identity_rejects_conflicting_content() -> None:
    from intelligence.vulnerability.projector import project_current

    original = _observation()
    conflicting = replace(original, title="mutated existing observation")

    with pytest.raises(ValueError, match="Conflicting immutable observation"):
        project_current((original, conflicting))


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-09")
def test_unknown_first_detection_produces_indeterminate_sla() -> None:
    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    assert VulnerabilityIntelligenceService is not None


def _observation(
    *,
    event: str = "missing",
    event_time: str | None = "2026-08-01T00:00:00Z",
    source_family: str = "azure_update_manager_missing",
    operation_succeeded: bool | None = True,
    provider_status: str = "succeeded",
    source_sequence: int = 1,
    source_generation: str = "generation-a",
    ingested_at: str = "2026-08-01T00:01:00Z",
    published_at: str = "",
    provider_operation_id: str = "assessment-1",
    payload: object | None = None,
):
    from intelligence.vulnerability.observations import ExposureObservation

    return ExposureObservation.create(
        tenant_id="tenant-a",
        connection_id="connection-a",
        source_family=source_family,
        target_id=(
            "/subscriptions/sub-a/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/vm-a"
        ),
        target_kind="server",
        weakness_id="KB-6000001",
        weakness_kind="kb",
        event=event,
        provider_operation_id=provider_operation_id,
        provider_status=provider_status,
        operation_succeeded=operation_succeeded,
        event_time=event_time,
        source_sequence=source_sequence,
        source_generation=source_generation,
        ingested_at=ingested_at,
        run_at="2026-08-01T00:00:30Z",
        published_at=published_at,
        payload=payload or {"severity": "High"},
        title="Fixture exposure",
    )
