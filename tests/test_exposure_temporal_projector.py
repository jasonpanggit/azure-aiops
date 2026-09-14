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
    assert "installation_failed" in dict(failed_current.source_states).values()
    assert failed_current.reintroduction_count == 0


def test_failure_only_installation_remains_active() -> None:
    from intelligence.vulnerability.projector import project_current

    current = project_current(
        (
            _observation(
                event="installed",
                event_time="2026-08-02T00:00:00Z",
                operation_succeeded=False,
                provider_status="failed",
                provider_operation_id="failed-install",
            ),
        )
    )

    assert current.state == "missing"
    assert current.active is True
    assert current.active_source_families == ("aum",)
    assert dict(current.source_states) == {"aum": "installation_failed"}


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
    different_generation = _observation(
        payload={"severity": "High", "nested": {"b": 2, "a": 1}},
        source_generation="generation-z",
    )

    assert first.observation_id == reordered.observation_id
    assert first.payload_fingerprint == reordered.payload_fingerprint
    assert first.observation_id != changed.observation_id
    # Retries do not mint a new provider observation identity.
    assert first.observation_id == different_ingestion.observation_id
    assert first.observation_id == different_generation.observation_id
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


def test_persisted_observation_identity_is_revalidated_before_replay() -> None:
    from intelligence.vulnerability.observations import ExposureObservation

    observation = _observation()
    tampered = observation.to_dict()
    tampered["target_id"] = "/subscriptions/sub-a/resourceGroups/rg/providers/x/y"

    with pytest.raises(ValueError, match="current key"):
        ExposureObservation.from_dict(tampered)


def test_unknown_first_detection_produces_indeterminate_sla() -> None:
    from datetime import UTC, datetime

    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    service = VulnerabilityIntelligenceService.from_rows(
        projected_current=[
            {
                "current_key": "exposure-current:v1:unknown-sla",
                "projection_generation_id": "generation-unknown",
                "target_id": "server-a",
                "target_kind": "server",
                "weakness_id": "CVE-2026-0999",
                "weakness_kind": "cve",
                "state": "missing",
                "active": True,
                "active_source_families": ["defender"],
                "first_detected_at": None,
                "first_detection_quality": "unknown",
                "episode_started_at": None,
                "last_observed_at": None,
                "published_at": "2020-01-01T00:00:00Z",
            }
        ],
        projection_generation_id="generation-unknown",
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )

    finding = service.findings[0]
    assert finding.first_detected_at is None
    assert finding.first_observed_at == ""
    assert finding.days_open is None
    assert finding.due_at is None
    assert finding.overdue is None
    assert finding.sla_state == "indeterminate"


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


def _assert_current_equal_ignoring_generation(a, b) -> None:
    import dataclasses

    fields = [
        f.name
        for f in dataclasses.fields(a)
        if f.name not in {"projection_generation_id", "change_version"}
    ]
    for name in fields:
        assert getattr(a, name) == getattr(b, name), name


def test_incremental_matches_full_replay_across_missing_installed_reintroduced() -> None:
    """project_incremental applied batch-by-batch must equal one full replay."""
    from intelligence.vulnerability.projector import (
        project_current,
        project_incremental,
    )

    batch1 = (
        _observation(
            event="missing", event_time="2026-08-01T00:00:00Z", source_sequence=1
        ),
        _observation(
            event="installed",
            event_time="2026-08-02T00:00:00Z",
            source_sequence=2,
            provider_operation_id="install-1",
        ),
    )
    batch2 = (
        _observation(
            event="missing",
            event_time="2026-08-03T00:00:00Z",
            source_sequence=3,
            provider_operation_id="assessment-2",
        ),
    )

    full_replay = project_current(batch1 + batch2, generation_id="gen-full")

    incremental_first = project_current(batch1, generation_id="gen-1")
    incremental_second = project_incremental(
        incremental_first, batch2, generation_id="gen-full"
    )

    _assert_current_equal_ignoring_generation(full_replay, incremental_second)
    assert incremental_second.projection_generation_id == "gen-full"


def test_incremental_no_new_observations_carries_forward_state() -> None:
    from intelligence.vulnerability.projector import (
        project_current,
        project_incremental,
    )

    observations = (
        _observation(event="missing", event_time="2026-08-01T00:00:00Z"),
    )
    previous = project_current(observations, generation_id="gen-1")

    carried = project_incremental(previous, (), generation_id="gen-2")

    _assert_current_equal_ignoring_generation(previous, carried)
    assert carried.projection_generation_id == "gen-2"
    assert carried.change_version != previous.change_version


def test_incremental_multi_cycle_reintroduction_matches_full_replay() -> None:
    """Two reintroduction cycles split across three incremental batches must
    match a single full replay, including reintroduction_count accumulation.
    """
    from intelligence.vulnerability.projector import (
        project_current,
        project_incremental,
    )

    batch1 = (
        _observation(event="missing", event_time="2026-08-01T00:00:00Z", source_sequence=1),
        _observation(
            event="installed",
            event_time="2026-08-02T00:00:00Z",
            source_sequence=2,
            provider_operation_id="install-1",
        ),
    )
    batch2 = (
        _observation(
            event="missing",
            event_time="2026-08-03T00:00:00Z",
            source_sequence=3,
            provider_operation_id="assessment-2",
        ),
        _observation(
            event="installed",
            event_time="2026-08-04T00:00:00Z",
            source_sequence=4,
            provider_operation_id="install-2",
        ),
    )
    batch3 = (
        _observation(
            event="missing",
            event_time="2026-08-05T00:00:00Z",
            source_sequence=5,
            provider_operation_id="assessment-3",
        ),
    )

    full_replay = project_current(
        batch1 + batch2 + batch3, generation_id="gen-full"
    )

    state = project_current(batch1, generation_id="gen-1")
    state = project_incremental(state, batch2, generation_id="gen-2")
    state = project_incremental(state, batch3, generation_id="gen-full")

    _assert_current_equal_ignoring_generation(full_replay, state)
    assert full_replay.reintroduction_count == 2


def test_raw_incremental_can_diverge_from_full_replay_when_history_has_unknown_time() -> None:
    """Documents the known precondition violation of ``project_incremental``.

    Unknown-event-time observations are always replayed last within a full
    replay (``ExposureObservation.ordering_key`` sorts them after every
    known-time observation, regardless of arrival order). Because of that,
    naively folding a later known-time observation on top of state derived
    from an earlier unknown-time observation is NOT guaranteed to match a
    full replay of the same observations -- callers must detect this case
    themselves (see ``materialize_temporal_exposure_tables``) and fall back
    to a full :func:`project_current` replay instead of calling
    :func:`project_incremental` directly. This test pins that divergence so
    a future change to ``ordering_key`` semantics is caught rather than
    silently assumed safe.
    """
    from intelligence.vulnerability.projector import (
        project_current,
        project_incremental,
    )

    batch1 = (
        _observation(event="missing", event_time=None, source_sequence=1),
    )
    batch2 = (
        _observation(
            event="installed",
            event_time="2026-08-05T00:00:00Z",
            source_sequence=2,
            provider_operation_id="install-1",
        ),
    )

    full_replay = project_current(batch1 + batch2, generation_id="gen-full")
    naive_incremental = project_incremental(
        project_current(batch1, generation_id="gen-1"),
        batch2,
        generation_id="gen-full",
    )

    # Full replay always applies the unknown-time "missing" last, so the
    # exposure remains open/missing even though a known-time "installed"
    # observation exists.
    assert full_replay.state == "missing"
    assert full_replay.active is True
    # Naive incremental folding applies batch2 forward and gets a different
    # (incorrect, if used without the pipeline's safety fallback) answer.
    assert naive_incremental.state == "installed"
    assert naive_incremental.active is False


def test_pipeline_falls_back_to_full_replay_for_keys_with_unknown_event_time() -> None:
    """materialize_temporal_exposure_tables must not use the unsafe fast path
    for a key whose history contains any unknown event_time; it must
    reproduce the same result as a full cold-start replay for that key.
    """
    from fabric_pipelines.vulnerability_pipeline import (
        ExposureTemporalProjection,
        materialize_temporal_exposure_tables,
    )
    from intelligence.vulnerability.projector import project_current

    batch1 = _observation(event="missing", event_time=None, source_sequence=1)
    batch2 = _observation(
        event="installed",
        event_time="2026-08-05T00:00:00Z",
        source_sequence=2,
        provider_operation_id="install-1",
    )

    full_replay = project_current((batch1, batch2), generation_id="gen-full")

    first_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(batch1,), current=(), generation_id="gen-1"
        ),
    )
    existing_rows = list(first_run.observation_rows)
    existing_current_rows = list(first_run.current_rows)

    second_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(batch1, batch2), current=(), generation_id="gen-full"
        ),
        existing_rows=existing_rows,
        known_observation_rows=existing_rows,
        existing_current_rows=existing_current_rows,
    )

    assert len(second_run.current_rows) == 1
    row = second_run.current_rows[0]
    assert row["state"] == full_replay.state == "missing"
    assert row["active"] == full_replay.active is True


def test_pipeline_falls_back_to_full_replay_for_late_arriving_known_time_observation() -> None:
    """A new, known-time observation that sorts *before* an already-known
    observation (e.g. a backfilled/corrected earlier event_time) must not
    be blindly folded on top of the prior snapshot; the pipeline must
    detect this and fall back to a full replay of that key so the result
    still matches a true full replay of the combined history.
    """
    from fabric_pipelines.vulnerability_pipeline import (
        ExposureTemporalProjection,
        materialize_temporal_exposure_tables,
    )
    from intelligence.vulnerability.projector import project_current

    # Known first, at a *later* event_time.
    batch1 = _observation(
        event="installed",
        event_time="2026-08-05T00:00:00Z",
        source_sequence=2,
        provider_operation_id="install-1",
    )
    # Backfilled/corrected observation ingested afterwards, but with an
    # *earlier* event_time -- it sorts before batch1 in a true replay.
    batch2 = _observation(
        event="missing",
        event_time="2026-08-01T00:00:00Z",
        source_sequence=1,
        provider_operation_id="assessment-2",
    )

    full_replay = project_current((batch1, batch2), generation_id="gen-full")

    first_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(batch1,), current=(), generation_id="gen-1"
        ),
    )
    existing_rows = list(first_run.observation_rows)
    existing_current_rows = list(first_run.current_rows)

    second_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(batch1, batch2), current=(), generation_id="gen-full"
        ),
        existing_rows=existing_rows,
        known_observation_rows=existing_rows,
        existing_current_rows=existing_current_rows,
    )

    assert len(second_run.current_rows) == 1
    row = second_run.current_rows[0]
    assert row["state"] == full_replay.state
    assert row["active"] == full_replay.active


def test_pipeline_rebuilds_key_missing_from_stale_current_snapshot() -> None:
    """A key with real observation history that is absent from
    ``existing_current_rows`` (stale/partial/missing current snapshot, or a
    recovery scenario) must be rebuilt from its full retained history, not
    silently dropped from ``current_rows`` -- dropping it would let the
    downstream SNAPSHOT_MERGE delete a key that legitimately has history.
    """
    from fabric_pipelines.vulnerability_pipeline import (
        ExposureTemporalProjection,
        materialize_temporal_exposure_tables,
    )
    from intelligence.vulnerability.projector import project_current

    batch1 = _observation(event="installed", event_time="2026-08-01T00:00:00Z")

    full_replay = project_current((batch1,), generation_id="gen-full")

    first_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(batch1,), current=(), generation_id="gen-1"
        ),
    )
    existing_rows = list(first_run.observation_rows)

    # Simulate a stale/partial current snapshot: no rows at all for this
    # key (e.g. the current table was lost, truncated, or not yet backfilled
    # after a recovery), while no new observations arrive this run either.
    second_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(), current=(), generation_id="gen-full"
        ),
        existing_rows=existing_rows,
        known_observation_rows=existing_rows,
        existing_current_rows=[],
    )

    assert len(second_run.current_rows) == 1
    row = second_run.current_rows[0]
    assert row["state"] == full_replay.state == "installed"
    assert row["active"] == full_replay.active is False


def test_pipeline_rebuilds_key_when_present_current_row_predates_known_history() -> None:
    """A key CAN have an entry in ``existing_current_rows`` yet still be
    stale: a prior publication run can append observations to the retained
    (``known``) history and then fail/crash before ever materializing
    ``gold_exposure_current`` for that key. Those observations are already
    ``known`` (persisted) but are NOT reflected in the previous current
    snapshot, and since they will never again appear as "new" this run, a
    naive incremental fold would silently and permanently omit them. The
    pipeline must detect this via the snapshot's own ``observation_count``
    and fall back to a full replay for that key.
    """
    from fabric_pipelines.vulnerability_pipeline import (
        ExposureTemporalProjection,
        materialize_temporal_exposure_tables,
    )
    from intelligence.vulnerability.projector import project_current

    batch1 = _observation(
        event="missing",
        event_time="2026-08-01T00:00:00Z",
        source_sequence=1,
        provider_operation_id="assessment-1",
    )
    batch2 = _observation(
        event="installed",
        event_time="2026-08-05T00:00:00Z",
        source_sequence=2,
        provider_operation_id="install-1",
    )

    # The "true" retained/known history already has BOTH observations
    # persisted (e.g. a prior run appended batch2 to Silver but crashed
    # before writing gold_exposure_current), but the current snapshot we
    # will supply below only reflects batch1 -- it is stale relative to
    # what is already known.
    full_replay = project_current((batch1, batch2), generation_id="gen-full")
    stale_current = project_current((batch1,), generation_id="gen-stale")

    first_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(batch1, batch2), current=(), generation_id="gen-1"
        ),
    )
    existing_rows = list(first_run.observation_rows)

    stale_current_row = {**stale_current.to_dict(), "current_key": stale_current.current_key}

    # This run has zero NEW observations (both are already known/persisted),
    # but the supplied current snapshot is stale relative to that known
    # history -- the pipeline must not simply restamp and carry it forward.
    second_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(), current=(), generation_id="gen-full"
        ),
        existing_rows=existing_rows,
        known_observation_rows=existing_rows,
        existing_current_rows=[stale_current_row],
    )

    assert len(second_run.current_rows) == 1
    row = second_run.current_rows[0]
    assert row["state"] == full_replay.state == "installed"
    assert row["active"] == full_replay.active is False
    assert row["observation_count"] == 2


def test_pipeline_rebuilds_key_when_current_row_has_same_count_but_wrong_observations() -> None:
    """``observation_count`` matching is not sufficient on its own: a stale
    snapshot could coincidentally carry the same count as the true known
    history while actually reflecting a *different* set of observations
    (e.g. cross-generation drift/replacement). The pipeline must also verify
    the snapshot's recorded ``last_observation_id`` against the actual
    most-recent known observation for the key, and fall back to a full
    replay on any mismatch -- even when this run has zero new observations.
    """
    from fabric_pipelines.vulnerability_pipeline import (
        ExposureTemporalProjection,
        materialize_temporal_exposure_tables,
    )
    from intelligence.vulnerability.projector import project_current

    obs_a = _observation(
        event="missing",
        event_time="2026-08-01T00:00:00Z",
        source_sequence=1,
        provider_operation_id="assessment-a",
    )
    obs_b = _observation(
        event="installed",
        event_time="2026-08-05T00:00:00Z",
        source_sequence=2,
        provider_operation_id="install-b",
    )
    # A third observation that is NOT part of the true known/retained
    # history below -- it stands in for a different generation's data that
    # a stale current snapshot happened to be folded from.
    obs_c = _observation(
        event="installed",
        event_time="2026-08-05T00:00:00Z",
        source_sequence=2,
        provider_operation_id="install-c",
    )

    full_replay = project_current((obs_a, obs_b), generation_id="gen-full")
    stale_current = project_current((obs_a, obs_c), generation_id="gen-stale")
    assert stale_current.observation_count == 2

    # Retained/known history for this key is genuinely (A, B) only.
    first_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(obs_a, obs_b), current=(), generation_id="gen-1"
        ),
    )
    existing_rows = list(first_run.observation_rows)

    stale_current_row = {
        **stale_current.to_dict(),
        "current_key": stale_current.current_key,
    }

    second_run = materialize_temporal_exposure_tables(
        ExposureTemporalProjection(
            observations=(), current=(), generation_id="gen-full"
        ),
        existing_rows=existing_rows,
        known_observation_rows=existing_rows,
        existing_current_rows=[stale_current_row],
    )

    assert len(second_run.current_rows) == 1
    row = second_run.current_rows[0]
    assert row["state"] == full_replay.state == "installed"
    assert row["active"] == full_replay.active is False
    assert row["observation_count"] == 2
    assert row["last_observation_id"] == full_replay.last_observation_id
    assert row["last_observation_id"] != stale_current.last_observation_id


def test_project_all_incremental_cold_starts_new_keys_and_folds_existing() -> None:
    from intelligence.vulnerability.observations import ExposureObservation
    from intelligence.vulnerability.projector import (
        project_all,
        project_all_incremental,
    )

    existing_key_batch1 = _observation(
        event="missing", event_time="2026-08-01T00:00:00Z", source_sequence=1
    )
    existing_key_batch2 = _observation(
        event="installed",
        event_time="2026-08-02T00:00:00Z",
        source_sequence=2,
        provider_operation_id="install-1",
    )
    new_key_observation = ExposureObservation.create(
        tenant_id="tenant-a",
        connection_id="connection-a",
        source_family="azure_update_manager_missing",
        target_id=(
            "/subscriptions/sub-a/resourceGroups/rg/providers/"
            "Microsoft.Compute/virtualMachines/vm-a"
        ),
        target_kind="server",
        weakness_id="KB-9999999",
        weakness_kind="kb",
        event="missing",
        provider_operation_id="assessment-other",
        provider_status="succeeded",
        operation_succeeded=True,
        event_time="2026-08-01T00:00:00Z",
        source_sequence=1,
        source_generation="generation-a",
        ingested_at="2026-08-01T00:01:00Z",
        run_at="2026-08-01T00:00:30Z",
        published_at="",
        payload={"severity": "Low"},
        title="Fixture exposure other key",
    )

    previous_current = {
        item.current_key: item
        for item in project_all((existing_key_batch1,), generation_id="gen-0")
    }

    full_replay = project_all(
        (existing_key_batch1, existing_key_batch2, new_key_observation),
        generation_id="gen-full",
    )

    incremental = project_all_incremental(
        (existing_key_batch2, new_key_observation),
        previous_current=previous_current,
        generation_id="gen-full",
    )

    full_by_key = {item.current_key: item for item in full_replay}
    incremental_by_key = {item.current_key: item for item in incremental}
    assert set(full_by_key) == set(incremental_by_key)
    for key, full_current in full_by_key.items():
        _assert_current_equal_ignoring_generation(
            full_current, incremental_by_key[key]
        )


