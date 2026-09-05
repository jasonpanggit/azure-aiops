"""Wave 0 contracts for source outcomes, checkpoints, and workload evidence."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
import json
from typing import Any

import pytest

from tests.exposure_scenario import (
    fixture_identity,
    load_exposure_scenario,
    scenario_fingerprint,
    stable_identity,
)


ARG_PATCH_ROW = {
    "id": (
        "/subscriptions/00000000-0000-0000-0000-0000000000a1/"
        "resourceGroups/rg-exposure/providers/Microsoft.Compute/virtualMachines/vm-a/"
        "patchAssessmentResults/latest/softwarePatches/KB6000001"
    ),
    "name": "KB6000001",
    "type": (
        "microsoft.compute/virtualmachines/patchassessmentresults/"
        "softwarepatches"
    ),
    "tenantId": "tenant-exposure-fixture",
    "subscriptionId": "00000000-0000-0000-0000-0000000000a1",
    "resourceGroup": "rg-exposure",
    "properties": {
        "kbId": "6000001",
        "patchName": "Security Update for Azure fixture",
        "classifications": ["Security", "Critical"],
        "msrcSeverity": "Critical",
        "publishedDateTime": "2026-08-01T00:00:00Z",
        "lastModifiedDateTime": "2026-08-02T00:00:00Z",
    },
}


class _PagedArg:
    def __init__(self, result: Any = None, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error

    def query_with_metadata(self, spec: Any, scope_ids: list[str]) -> Any:
        del spec, scope_ids
        if self.error is not None:
            raise self.error
        return self.result


def test_authoritative_scenario_validates_and_has_stable_identities() -> None:
    scenario = load_exposure_scenario()

    target = scenario["identity_cases"]["merged"]["target_id"]
    first = stable_identity("exposure", scenario["scope"]["tenant_id"], target, "CVE-2026-1003")
    second = stable_identity("exposure", scenario["scope"]["tenant_id"], target, "CVE-2026-1003")

    assert first == second
    assert first.startswith("exposure:")
    assert fixture_identity(scenario, "aum_only") == "exposure:aum-only:vm-a:cve-2026-1001"
    assert scenario["fixture_fingerprint"] == scenario_fingerprint(scenario)


def test_provider_failures_are_control_plane_outcomes_not_domain_rows() -> None:
    from intelligence.vulnerability.acquisition import (
        AcquisitionFailure,
        AcquisitionFailureCode,
        ProviderQueryError,
    )
    from onboarding.discovery_source import AzureResourceGraphSource
    from onboarding.query_contract import QuerySpec

    attempted = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    completed = attempted + timedelta(seconds=1)
    times = iter((attempted, completed))
    secret = "Bearer provider-token tenant-should-not-leak"
    source = AzureResourceGraphSource(
        mcp=None,
        arg=_PagedArg(
            error=ProviderQueryError(
                AcquisitionFailureCode.AUTHORIZATION_FAILED,
                protected_detail=secret,
            )
        ),
        connection_id="connection-aum-east",
        clock=lambda: next(times),
    )
    spec = QuerySpec(
        "patch_assessment_details",
        "PatchAssessmentResources",
        "patchassessmentresources | where type endswith '/softwarepatches'",
        False,
        source_family="azure_update_manager_missing",
    )

    outcome = source.fetch((spec,), ["00000000-0000-0000-0000-0000000000a1"])[
        spec.name
    ]

    assert isinstance(outcome, AcquisitionFailure)
    assert outcome.error_code is AcquisitionFailureCode.AUTHORIZATION_FAILED
    assert outcome.error_summary == "Provider authorization failed."
    assert outcome.connection_id == "connection-aum-east"
    assert outcome.source_family == "azure_update_manager_missing"
    assert outcome.scope == ("00000000-0000-0000-0000-0000000000a1",)
    assert outcome.attempted_at == attempted
    assert outcome.completed_at == completed
    assert not hasattr(outcome, "rows")
    assert secret not in repr(outcome)
    with pytest.raises(FrozenInstanceError):
        outcome.error_summary = secret  # type: ignore[misc]


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_summary"),
    [
        (
            TimeoutError("command az graph query --token super-secret timed out"),
            "provider_timeout",
            "Provider query timed out.",
        ),
        (
            TypeError("response body included tenant-should-not-leak"),
            "malformed_response",
            "Provider returned an invalid response.",
        ),
        (
            RuntimeError("ARG query exceeded max_pages=1; skip-token=secret"),
            "paging_incomplete",
            "Provider paging did not complete.",
        ),
        (
            RuntimeError("opaque provider crash containing bearer-token"),
            "provider_unavailable",
            "Provider query failed.",
        ),
    ],
)
def test_acquisition_failures_have_stable_sanitized_codes(
    error: BaseException,
    expected_code: str,
    expected_summary: str,
) -> None:
    from intelligence.vulnerability.acquisition import AcquisitionFailure
    from onboarding.discovery_source import AzureResourceGraphSource
    from onboarding.query_contract import QuerySpec

    source = AzureResourceGraphSource(
        mcp=None,
        arg=_PagedArg(error=error),
        connection_id="connection-aum-east",
    )
    spec = QuerySpec(
        "patch_assessment_details",
        "PatchAssessmentResources",
        "patchassessmentresources",
        False,
        source_family="azure_update_manager_missing",
    )

    outcome = source.fetch((spec,), ["sub-a"])[spec.name]

    assert isinstance(outcome, AcquisitionFailure)
    assert outcome.error_code.value == expected_code
    assert outcome.error_summary == expected_summary
    assert not hasattr(outcome, "rows")
    serialized = repr(outcome).casefold()
    assert "super-secret" not in serialized
    assert "tenant-should-not-leak" not in serialized
    assert "skip-token=secret" not in serialized
    assert "bearer-token" not in serialized


def test_fully_paged_zero_rows_are_healthy_empty_not_failure() -> None:
    from intelligence.vulnerability.acquisition import AcquisitionSuccess
    from onboarding.azure_clients import PagedArgQueryResult
    from onboarding.discovery_source import AzureResourceGraphSource
    from onboarding.query_contract import QuerySpec

    now = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    source = AzureResourceGraphSource(
        mcp=None,
        arg=_PagedArg(
            PagedArgQueryResult(
                rows=(),
                pages_fetched=1,
                page_size=1000,
                max_pages=1000,
                complete=True,
            )
        ),
        connection_id="connection-aum-east",
        clock=lambda: now,
    )
    spec = QuerySpec(
        "patch_installations",
        "PatchInstallationResources",
        "patchinstallationresources",
        False,
        source_family="azure_update_manager_installation",
    )

    outcome = source.fetch((spec,), ["sub-a"])[spec.name]

    assert isinstance(outcome, AcquisitionSuccess)
    assert outcome.rows == ()
    assert outcome.healthy_empty is True
    assert outcome.paging.complete is True
    assert outcome.paging.pages_fetched == 1
    assert outcome.paging.row_count == 0
    assert outcome.completed_at == now


def test_arg_client_exposes_complete_multi_page_proof() -> None:
    from onboarding.azure_clients import AzureCliArgClient, CommandResult
    from onboarding.query_contract import QuerySpec

    class Runner:
        def __init__(self) -> None:
            self.responses = [
                CommandResult(
                    0,
                    json.dumps({"data": [ARG_PATCH_ROW], "skip_token": "next-page"}),
                    "",
                ),
                CommandResult(
                    0,
                    json.dumps(
                        {
                            "data": [
                                {
                                    **ARG_PATCH_ROW,
                                    "id": ARG_PATCH_ROW["id"].replace(
                                        "KB6000001", "KB6000002"
                                    ),
                                    "name": "KB6000002",
                                }
                            ]
                        }
                    ),
                    "",
                ),
            ]

        def run(self, command: list[str], timeout: int) -> CommandResult:
            del command, timeout
            return self.responses.pop(0)

    result = AzureCliArgClient(
        runner=Runner(),
        page_size=1,
        max_pages=2,
    ).query_with_metadata(
        QuerySpec(
            "patch_assessment_details",
            "PatchAssessmentResources",
            "patchassessmentresources",
            False,
            source_family="azure_update_manager_missing",
        ),
        ["sub-a"],
    )

    assert result.complete is True
    assert result.pages_fetched == 2
    assert result.page_size == 1
    assert result.max_pages == 2
    assert len(result.rows) == 2


def test_query_catalog_declares_semantic_families_independently_of_tables() -> None:
    from onboarding.query_catalog import QueryCatalog

    by_name = {spec.name: spec for spec in QueryCatalog().build(None)}

    assert by_name["patch_assessment_details"].source_family == (
        "azure_update_manager_missing"
    )
    assert by_name["patch_installations"].source_family == (
        "azure_update_manager_installation"
    )
    assert by_name["defender_assessments"].source_family == (
        "defender_recommendation"
    )
    assert by_name["defender_subassessments"].source_family == (
        "defender_subassessment"
    )
    assert by_name["defender_secure_scores"].source_family == "defender_posture"
    assert "defender_image" in by_name["defender_subassessments"].semantic_families
    assert (
        by_name["patch_assessment_details"].source_family
        != by_name["patch_assessment_details"].table.casefold()
    )


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
