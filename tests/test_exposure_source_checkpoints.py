"""Wave 0 contracts for source outcomes, checkpoints, and workload evidence."""

from __future__ import annotations

import pytest

from tests.exposure_scenario import (
    fixture_identity,
    load_exposure_scenario,
    scenario_fingerprint,
    stable_identity,
)


def test_authoritative_scenario_validates_and_has_stable_identities() -> None:
    scenario = load_exposure_scenario()

    target = scenario["identity_cases"]["merged"]["target_id"]
    first = stable_identity("exposure", scenario["scope"]["tenant_id"], target, "CVE-2026-1003")
    second = stable_identity("exposure", scenario["scope"]["tenant_id"], target, "CVE-2026-1003")

    assert first == second
    assert first.startswith("exposure:")
    assert fixture_identity(scenario, "aum_only") == "exposure:aum-only:vm-a:cve-2026-1001"
    assert scenario["fixture_fingerprint"] == scenario_fingerprint(scenario)


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-05")
def test_provider_failures_are_control_plane_outcomes_not_domain_rows() -> None:
    from intelligence.vulnerability.acquisition import AcquisitionOutcome

    assert AcquisitionOutcome is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-05")
def test_fully_paged_zero_rows_are_healthy_empty_not_failure() -> None:
    from intelligence.vulnerability.acquisition import AcquisitionOutcome

    assert AcquisitionOutcome is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-05")
def test_live_and_persisted_aum_share_canonical_normalization() -> None:
    from intelligence.vulnerability.normalization import normalize_exposure

    assert normalize_exposure is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-07")
def test_failed_source_retains_only_its_own_last_known_good_partition() -> None:
    from intelligence.vulnerability.acquisition import AcquisitionOutcome

    assert AcquisitionOutcome is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-07")
def test_healthy_empty_replaces_prior_rows_but_failed_empty_does_not() -> None:
    from intelligence.vulnerability.acquisition import AcquisitionOutcome

    assert AcquisitionOutcome is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-07")
def test_failed_source_without_lkg_is_unavailable_and_emits_no_rows() -> None:
    from intelligence.vulnerability.acquisition import AcquisitionOutcome

    assert AcquisitionOutcome is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-07")
def test_one_failed_connection_preserves_healthy_authorized_connections() -> None:
    from semantic.live_provider import ConnectionScopedLiveResourceProvider

    assert ConnectionScopedLiveResourceProvider is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-07")
def test_each_source_family_is_fresh_at_threshold_and_stale_at_plus_one_second() -> None:
    from api.evidence import classify_freshness

    assert classify_freshness is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-06")
def test_workload_impact_requires_exact_container_insights_digest_evidence() -> None:
    from intelligence.vulnerability.workload_inventory import match_workload_digest

    assert match_workload_digest is not None


@pytest.mark.skip(reason="Pending implementation: Plan 03.1-06")
def test_tag_or_repository_match_without_digest_remains_unknown() -> None:
    from intelligence.vulnerability.workload_inventory import match_workload_digest

    assert match_workload_digest is not None
