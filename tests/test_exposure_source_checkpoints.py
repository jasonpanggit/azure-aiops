"""Wave 0 contracts for source outcomes, checkpoints, and workload evidence."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
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


def test_legacy_inventory_specs_fall_back_to_query_name_for_source_family() -> None:
    from intelligence.inventory.sources.arg import InventoryQuerySpec
    from intelligence.vulnerability.acquisition import (
        AcquisitionFailure,
        ProviderQueryError,
    )
    from onboarding.discovery_source import AzureResourceGraphSource

    source = AzureResourceGraphSource(
        mcp=None,
        arg=_PagedArg(error=ProviderQueryError("provider_timeout")),
        connection_id="connection-inventory",
    )
    spec = InventoryQuerySpec(
        "inventory_resources",
        "Resources",
        "Resources | project id",
    )

    outcome = source.fetch((spec,), ["subscription-inventory"])[spec.name]

    assert isinstance(outcome, AcquisitionFailure)
    assert outcome.source_family == spec.name


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
    assert "monitor" not in by_name
    assert (
        "extend resourceId=tostring(properties.resourceDetails.Id)"
        in by_name["defender"].query
    )
    assert (
        "extend resourceId=tostring(properties.resourceId)"
        in by_name["policy"].query
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


def test_every_query_catalog_family_has_a_governed_freshness_bucket() -> None:
    from fabric.config import freshness_source_family
    from onboarding.query_catalog import QueryCatalog

    for spec in QueryCatalog().build(None):
        family = spec.source_family or spec.name
        assert freshness_source_family(family) in {
            "aum",
            "defender",
            "images",
            "workloads",
            "enrichment",
        }


def test_live_and_persisted_aum_share_canonical_normalization() -> None:
    from intelligence.vulnerability.acquisition import (
        AcquisitionSuccess,
        PagingProof,
    )
    from intelligence.vulnerability.normalization import (
        canonical_exposure_bytes,
        normalize_exposure,
    )

    attempted = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    common = {
        "connection_id": "connection-aum-east",
        "query_name": "patch_assessment_details",
        "source_family": "azure_update_manager_missing",
        "scope": ("00000000-0000-0000-0000-0000000000a1",),
        "attempted_at": attempted,
        "completed_at": attempted + timedelta(seconds=1),
        "watermark": "2026-08-02T00:00:00Z",
        "sequence": "1.0.0:1:1",
    }
    live = AcquisitionSuccess(
        **common,
        paging=PagingProof(1, 1000, 1000, 1, True),
        rows=(ARG_PATCH_ROW,),
    )
    persisted_row = {
        "id": ARG_PATCH_ROW["id"].casefold(),
        "sourceId": ARG_PATCH_ROW["id"],
        "tenantId": ARG_PATCH_ROW["tenantId"],
        "subscriptionId": ARG_PATCH_ROW["subscriptionId"],
        "targetResourceId": ARG_PATCH_ROW["id"].split(
            "/patchAssessmentResults/", 1
        )[0],
        "updateName": ARG_PATCH_ROW["properties"]["patchName"],
        "kbId": ARG_PATCH_ROW["properties"]["kbId"],
        "classifications": ["Critical", "security", "Critical"],
        "sourceClassifications": ARG_PATCH_ROW["properties"]["classifications"],
        "msrcSeverity": ARG_PATCH_ROW["properties"]["msrcSeverity"],
        "publishedDateTime": ARG_PATCH_ROW["properties"]["publishedDateTime"],
        "lastModifiedDateTime": ARG_PATCH_ROW["properties"][
            "lastModifiedDateTime"
        ],
    }
    persisted = AcquisitionSuccess(
        **common,
        paging=PagingProof(1, 1000, 1000, 1, True),
        rows=(persisted_row,),
    )

    live_result = normalize_exposure(live)
    persisted_result = normalize_exposure(persisted)

    assert live_result.quality_failures == ()
    assert persisted_result.quality_failures == ()
    assert canonical_exposure_bytes(live_result) == canonical_exposure_bytes(
        persisted_result
    )
    row = live_result.rows[0]
    assert row.classifications == ("Critical", "Security")
    assert row.source_classifications == ("Security", "Critical")
    assert row.severity == "Critical"
    assert row.source_severity == "Critical"
    assert row.source_family == "azure_update_manager_missing"


def _source_outcome(
    *,
    query_name: str,
    source_family: str,
    connection_id: str = "connection-a",
    scope: tuple[str, ...] = ("sub-a",),
    row_id: str = "",
    failed: bool = False,
    attempted_at: datetime = datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
):
    from intelligence.vulnerability.acquisition import (
        AcquisitionFailure,
        AcquisitionFailureCode,
        AcquisitionSuccess,
        PagingProof,
    )

    common = {
        "connection_id": connection_id,
        "query_name": query_name,
        "source_family": source_family,
        "scope": scope,
        "attempted_at": attempted_at,
        "completed_at": attempted_at + timedelta(seconds=1),
    }
    if failed:
        return AcquisitionFailure(
            **common,
            error_code=AcquisitionFailureCode.PROVIDER_TIMEOUT,
            error_summary="Provider query timed out.",
        )
    rows = ({"id": row_id, "subscriptionId": scope[0]},) if row_id else ()
    return AcquisitionSuccess(
        **common,
        paging=PagingProof(
            pages_fetched=1,
            page_size=1000,
            max_pages=1000,
            row_count=len(rows),
            complete=True,
        ),
        watermark="2026-09-05T00:00:00Z" if rows else None,
        sequence=f"1.0.0:1:{len(rows)}",
        rows=rows,
    )


def _source_projection(
    outcomes: dict[str, Any],
    *,
    generation: str,
    previous=None,
):
    from onboarding.ingestion_service import activate_source_partitions

    return activate_source_partitions(
        outcomes=outcomes,
        attempted_generation=generation,
        completed_at="2026-09-05T00:00:01Z",
        previous_partition_rows=(
            previous.partition_rows if previous is not None else ()
        ),
        previous_statuses=previous.statuses if previous is not None else (),
    )


def test_source_partition_deduplicates_exact_rows_without_collapsing_distinct_findings() -> None:
    outcome = _source_outcome(
        query_name="defender_subassessments",
        source_family="defender_subassessment",
        row_id="shared-id",
    )
    first = {
        "id": "shared-id",
        "subscriptionId": "sub-a",
        "properties": {"severity": "High"},
    }
    distinct = {
        "id": "shared-id",
        "subscriptionId": "sub-a",
        "properties": {"severity": "Medium"},
    }

    projection = _source_projection(
        {
            "defender_subassessments": replace(
                outcome,
                paging=replace(outcome.paging, row_count=3),
                rows=(first, dict(first), distinct),
            )
        },
        generation="generation-1",
    )

    assert projection.rows_by_query["defender_subassessments"] == [
        first,
        distinct,
    ]
    assert len(projection.partition_rows) == 2
    assert projection.statuses[0]["row_count"] == 2


def test_failed_source_retains_only_its_own_last_known_good_partition() -> None:
    first = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
                row_id="aum-old",
            ),
            "defender_subassessments": _source_outcome(
                query_name="defender_subassessments",
                source_family="defender_subassessment",
                row_id="defender-old",
            ),
        },
        generation="generation-1",
    )
    second = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
                failed=True,
            ),
            "defender_subassessments": _source_outcome(
                query_name="defender_subassessments",
                source_family="defender_subassessment",
                row_id="defender-new",
            ),
        },
        generation="generation-2",
        previous=first,
    )

    assert second.rows_by_query["patch_assessment_details"][0]["id"] == "aum-old"
    assert second.rows_by_query["defender_subassessments"][0]["id"] == "defender-new"
    by_family = {row["source_family"]: row for row in second.statuses}
    assert by_family["azure_update_manager_missing"]["completeness"] == "stale"
    assert by_family["azure_update_manager_missing"]["attempted_generation"] == (
        "generation-2"
    )
    assert by_family["azure_update_manager_missing"]["effective_generation"] == (
        "generation-1"
    )
    assert by_family["azure_update_manager_missing"]["last_success_at"] == (
        "2026-09-05T00:00:01Z"
    )
    assert by_family["azure_update_manager_missing"]["safe_error_code"] == (
        "provider_timeout"
    )
    assert by_family["defender_subassessment"]["completeness"] == "complete"
    assert by_family["defender_subassessment"]["effective_generation"] == (
        "generation-2"
    )


@pytest.mark.parametrize(
    "source_family",
    [
        "azure_update_manager_missing",
        "defender_subassessment",
        "defender_image",
        "workloads",
        "enrichment",
    ],
)
def test_every_exposure_family_failure_retains_its_own_lkg(
    source_family: str,
) -> None:
    current = _source_projection(
        {
            "family_query": _source_outcome(
                query_name="family_query",
                source_family=source_family,
                row_id=f"{source_family}-row",
            )
        },
        generation="generation-1",
    )
    failed = _source_projection(
        {
            "family_query": _source_outcome(
                query_name="family_query",
                source_family=source_family,
                failed=True,
            )
        },
        generation="generation-2",
        previous=current,
    )

    assert failed.rows_by_query["family_query"][0]["id"] == (
        f"{source_family}-row"
    )
    assert failed.statuses[0]["source_family"] == source_family
    assert failed.statuses[0]["completeness"] == "stale"
    assert failed.statuses[0]["attempted_generation"] == "generation-2"
    assert failed.statuses[0]["effective_generation"] == "generation-1"


def test_healthy_empty_replaces_prior_rows_but_failed_empty_does_not() -> None:
    populated = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
                row_id="aum-old",
            )
        },
        generation="generation-1",
    )
    healthy_empty = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
            )
        },
        generation="generation-2",
        previous=populated,
    )
    failed = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
                failed=True,
            )
        },
        generation="generation-3",
        previous=populated,
    )

    assert healthy_empty.rows_by_query["patch_assessment_details"] == []
    assert healthy_empty.partition_rows == ()
    assert healthy_empty.statuses[0]["completeness"] == "healthy-empty"
    assert healthy_empty.statuses[0]["effective_generation"] == "generation-2"
    assert failed.rows_by_query["patch_assessment_details"][0]["id"] == "aum-old"
    assert failed.statuses[0]["completeness"] == "stale"
    assert failed.statuses[0]["effective_generation"] == "generation-1"


def test_failed_source_without_lkg_is_unavailable_and_emits_no_rows() -> None:
    projected = _source_projection(
        {
            "defender_subassessments": _source_outcome(
                query_name="defender_subassessments",
                source_family="defender_subassessment",
                failed=True,
            )
        },
        generation="generation-1",
    )

    assert projected.rows_by_query["defender_subassessments"] == []
    assert projected.partition_rows == ()
    assert projected.statuses[0]["status"] == "unavailable"
    assert projected.statuses[0]["availability"] == "unavailable"
    assert projected.statuses[0]["completeness"] == "unavailable"
    assert projected.statuses[0]["effective_generation"] == ""
    assert projected.statuses[0]["represented_count"] == 0
    assert projected.statuses[0]["expected_count"] == 1


@pytest.mark.parametrize(
    "corrupt",
    ["contract", "count", "duplicate", "reference"],
)
def test_invalid_source_partition_stage_never_switches_current_generation(
    tmp_path, corrupt: str
) -> None:
    from storage.datasets import DatasetStore

    projection = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
                row_id="aum-row",
            )
        },
        generation="generation-1",
    )
    store = DatasetStore(tmp_path / corrupt)
    datasets = {
        "exposure/source_partition_rows": [
            dict(row) for row in projection.partition_rows
        ],
        "situations/source_status": [dict(row) for row in projection.statuses],
    }
    store.publish(
        datasets,
        {},
        {"runId": "generation-1", "status": "completed"},
    )
    before = store.current_generation()
    invalid = {name: [dict(row) for row in rows] for name, rows in datasets.items()}
    if corrupt == "contract":
        invalid["situations/source_status"][0].pop("connection_id")
    elif corrupt == "count":
        invalid["situations/source_status"][0]["row_count"] += 1
    elif corrupt == "duplicate":
        invalid["exposure/source_partition_rows"].append(
            dict(invalid["exposure/source_partition_rows"][0])
        )
    else:
        invalid["exposure/source_partition_rows"][0]["partition_key"] = (
            "missing-partition"
        )

    with pytest.raises(ValueError, match="source partition"):
        store.publish(
            invalid,
            {},
            {"runId": "generation-2", "status": "completed"},
        )

    assert store.current_generation() == before
    assert store.read_dataset("exposure/source_partition_rows") == datasets[
        "exposure/source_partition_rows"
    ]


def test_one_failed_connection_preserves_healthy_authorized_connections() -> None:
    from types import SimpleNamespace

    from onboarding.query_contract import QuerySpec
    from semantic.live_provider import ConnectionScopedLiveResourceProvider

    healthy = SimpleNamespace(
        connection_id="connection-a",
        name="Production east",
        subscription_id="sub-a",
        is_active=True,
        credential_reference="secret://must-not-leak",
    )
    failed = SimpleNamespace(
        connection_id="connection-b",
        name="Production west",
        subscription_id="sub-b",
        is_active=True,
        credential_reference="secret://also-must-not-leak",
    )

    class Reader:
        def __init__(self, connection_id: str) -> None:
            self.connection_id = connection_id

        def query(self, spec, scope_ids):
            del spec, scope_ids
            if self.connection_id == "connection-b":
                raise RuntimeError("provider response bearer-secret")
            return [{"id": "healthy-row", "subscriptionId": "sub-a"}]

    provider = ConnectionScopedLiveResourceProvider(
        connections=lambda: [healthy, failed],
        reader_factory=lambda connection: Reader(connection.connection_id),
    )
    observation = provider.query(
        QuerySpec(
            "defender_subassessments",
            "SecurityResources",
            "SecurityResources",
            False,
            source_family="defender_subassessment",
        ),
        subscription_ids=["sub-a", "sub-b"],
    )

    assert observation.rows == (
        {"id": "healthy-row", "subscriptionId": "sub-a"},
    )
    assert observation.completeness == "partial"
    assert observation.represented_count == 1
    assert observation.expected_count == 2
    assert {row.connection_id for row in observation.source_status} == {
        "connection-a",
        "connection-b",
    }
    assert {row.display_name for row in observation.source_status} == {
        "Production east",
        "Production west",
    }
    failed_status = next(
        row
        for row in observation.source_status
        if row.connection_id == "connection-b"
    )
    assert failed_status.completeness == "unavailable"
    assert failed_status.safe_error_code == "provider_unavailable"
    assert "bearer-secret" not in repr(observation)
    assert "secret://" not in repr(observation)


@pytest.mark.parametrize(
    ("source_family", "threshold_seconds"),
    [
        ("aum", 1800),
        ("defender", 21600),
        ("images", 86400),
        ("workloads", 900),
        ("enrichment", 86400),
    ],
)
def test_each_source_family_is_fresh_at_threshold_and_stale_at_plus_one_second(
    source_family: str,
    threshold_seconds: int,
) -> None:
    from api.evidence import qualify_source_freshness

    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    exact = qualify_source_freshness(
        (now - timedelta(seconds=threshold_seconds)).isoformat(),
        source_family=source_family,
        now=now,
    )
    plus_one = qualify_source_freshness(
        (now - timedelta(seconds=threshold_seconds + 1)).isoformat(),
        source_family=source_family,
        now=now,
    )
    future = qualify_source_freshness(
        (now + timedelta(seconds=1)).isoformat(),
        source_family=source_family,
        now=now,
    )
    missing = qualify_source_freshness(
        "",
        source_family=source_family,
        now=now,
    )

    assert exact == {
        "freshness": "fresh",
        "freshness_threshold_seconds": threshold_seconds,
        "freshness_source_family": source_family,
    }
    assert plus_one["freshness"] == "stale"
    assert future["freshness"] == "unknown"
    assert missing["freshness"] == "unknown"
    assert plus_one["freshness_threshold_seconds"] == threshold_seconds
    assert plus_one["freshness_source_family"] == source_family


def test_network_topology_families_map_to_the_images_freshness_bucket() -> None:
    """Regression: network ARG specs left `source_family` unset, so
    ``AzureResourceGraphSource`` fell back to the query name (e.g.
    ``network_firewall_policies``, per ``onboarding.query_catalog
    .NETWORK_RESOURCE_TYPES``). ``_source_partition_status`` then called
    ``freshness_source_family`` on that raw name for every ARG-backed
    connection, and every network family raised ``ValueError`` because none
    of the five governed Exposure buckets recognized a ``network_`` prefix
    -- crashing the whole inventory sync (not just the network partition)
    with "Unknown Exposure freshness source family 'network_firewall_policies'".
    """

    from fabric.config import SourceFreshnessThresholds, freshness_source_family
    from onboarding.query_catalog import NETWORK_RESOURCE_TYPES

    for family_name in NETWORK_RESOURCE_TYPES:
        assert freshness_source_family(family_name) == "images"
        assert SourceFreshnessThresholds().threshold_for(family_name) == 86400


def test_other_hardcoded_source_families_map_to_a_governed_freshness_bucket() -> None:
    """Regression: several call sites set an explicit ``source_family`` that
    was never added to the governed Exposure buckets, so any sync or evidence
    path touching them raised ``ValueError`` in ``freshness_source_family``
    (e.g. the ``ingestion_service`` Log Analytics workspace discovery query,
    which crashed with "Unknown Exposure freshness source family
    'log_analytics_workspace_discovery'" right after the network-family fix
    cleared the first crash). Cover every other hardcoded literal found via
    ``grep -rn 'source_family=' src/`` so a future addition doesn't repeat
    this crash-one-family-at-a-time pattern.
    """

    from fabric.config import SourceFreshnessThresholds, freshness_source_family

    expected = {
        "azure_resource": "images",
        "log_analytics_workspace_discovery": "images",
        "arg_activity_log": "workloads",
    }
    for family_name, bucket in expected.items():
        assert freshness_source_family(family_name) == bucket
        assert SourceFreshnessThresholds().threshold_for(family_name) == (
            SourceFreshnessThresholds().to_dict()[bucket]
        )


def test_fabric_source_freshness_defaults_and_positive_overrides(tmp_path) -> None:
    from fabric.config import FabricRuntimeConfig

    base = {
        "fabric": {
            "workspace_name": "workspace",
            "lakehouse_name": "lakehouse",
            "source_data_root": "./source",
            "exposure": {"enabled": False},
        }
    }
    defaults_path = tmp_path / "defaults.yaml"
    defaults_path.write_text(json.dumps(base))
    defaults = FabricRuntimeConfig.load(defaults_path)
    assert defaults.exposure.freshness_threshold_seconds.to_dict() == {
        "aum": 1800,
        "defender": 21600,
        "images": 86400,
        "workloads": 900,
        "enrichment": 86400,
    }

    base["fabric"]["exposure"]["freshness_threshold_seconds"] = {
        "aum": 181,
        "defender": 182,
        "images": 183,
        "workloads": 184,
        "enrichment": 185,
    }
    override_path = tmp_path / "override.yaml"
    override_path.write_text(json.dumps(base))
    overridden = FabricRuntimeConfig.load(override_path)
    overrides = overridden.exposure.freshness_threshold_seconds
    assert overrides.to_dict() == {
        "aum": 181,
        "defender": 182,
        "images": 183,
        "workloads": 184,
        "enrichment": 185,
    }
    from api.evidence import qualify_source_freshness

    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    for family, threshold in overrides.to_dict().items():
        exact = qualify_source_freshness(
            (now - timedelta(seconds=threshold)).isoformat(),
            source_family=family,
            now=now,
            thresholds=overrides,
        )
        plus_one = qualify_source_freshness(
            (now - timedelta(seconds=threshold + 1)).isoformat(),
            source_family=family,
            now=now,
            thresholds=overrides,
        )
        assert exact["freshness"] == "fresh"
        assert exact["freshness_threshold_seconds"] == threshold
        assert plus_one["freshness"] == "stale"


@pytest.mark.parametrize("invalid", [0, -1, True, "1800"])
def test_fabric_source_freshness_overrides_must_be_positive_integers(
    tmp_path, invalid: Any
) -> None:
    from fabric.config import FabricRuntimeConfig

    path = tmp_path / f"invalid-{type(invalid).__name__}-{invalid}.yaml"
    path.write_text(
        json.dumps(
            {
                "fabric": {
                    "workspace_name": "workspace",
                    "lakehouse_name": "lakehouse",
                    "source_data_root": "./source",
                    "exposure": {
                        "freshness_threshold_seconds": {"aum": invalid}
                    },
                }
            }
        )
    )

    error = TypeError if isinstance(invalid, (bool, str)) else ValueError
    with pytest.raises(error, match="freshness_threshold_seconds.aum"):
        FabricRuntimeConfig.load(path)


def test_source_status_and_evidence_name_the_applied_freshness_policy() -> None:
    from api.evidence import Evidence
    from fabric.schema_registry import schema_for

    projection = _source_projection(
        {
            "patch_assessment_details": _source_outcome(
                query_name="patch_assessment_details",
                source_family="azure_update_manager_missing",
                row_id="aum-row",
            )
        },
        generation="generation-1",
    )
    status = projection.statuses[0]
    assert status["freshness_threshold_seconds"] == 1800
    assert status["freshness_source_family"] == "aum"

    payload = Evidence(
        source_engine="exposure",
        timestamp="2026-09-05T00:00:00Z",
        freshness="fresh",
        freshness_threshold_seconds=1800,
        freshness_source_family="aum",
    ).to_dict()
    assert payload["freshness_threshold_seconds"] == 1800
    assert payload["freshness_source_family"] == "aum"
    assert {
        "freshness_threshold_seconds",
        "freshness_source_family",
    } <= set(schema_for("metadata_source_status").names)
    assert "role_ids_json" in schema_for(
        "silver_remediation_approval_policies"
    ).names


def test_workload_impact_requires_exact_container_insights_digest_evidence() -> None:
    from intelligence.vulnerability.workload_inventory import match_workload_digest

    digest = f"sha256:{'a' * 64}"
    matched = match_workload_digest(
        defender_digest=digest.upper(),
        observed_digest=f"docker-pullable://acr.example/api@{digest}",
        defender_observed_at="2026-09-05T00:00:00Z",
        workload_observed_at="2026-09-05T00:08:00Z",
    )

    assert matched.matched is True
    assert matched.digest == digest
    assert matched.reason == ""


def test_tag_or_repository_match_without_digest_remains_unknown() -> None:
    from intelligence.vulnerability.workload_inventory import match_workload_digest

    result = match_workload_digest(
        defender_digest=f"sha256:{'a' * 64}",
        observed_digest="acr.example/api:v1",
        defender_observed_at="2026-09-05T00:00:00Z",
        workload_observed_at="2026-09-05T00:01:00Z",
    )

    assert result.matched is False
    assert result.reason == "no_exact_digest_observation"


def _workload_outcomes(
    *,
    generation: str,
    fail_family: str = "",
    fail_workspace: str = "",
):
    from intelligence.vulnerability.workload_inventory import (
        WORKLOAD_QUERY_FAMILIES,
        WORKLOAD_QUERY_TABLES,
        WORKLOAD_QUERY_VERSIONS,
        WorkloadFailureCode,
        WorkloadQueryFailure,
        WorkloadQuerySuccess,
    )

    digest = f"sha256:{'a' * 64}"
    rows_by_family = {
        "kube_pod_inventory": (
            {
                "TimeGenerated": "2026-09-05T00:00:00Z",
                "ClusterId": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-a",
                "Namespace": "prod",
                "ControllerKind": "Deployment",
                "ControllerName": "api",
                "Name": "api-pod",
                "PodUid": "pod-a",
                "ContainerID": "containerd://container-a",
                "ContainerName": "api",
            },
        ),
        "container_inventory": (
            {
                "TimeGenerated": "2026-09-05T00:00:00Z",
                "ContainerID": "containerd://container-a",
                "Image": "acr.example/api:v1",
                "ImageID": f"acr.example/api@{digest}",
                "Repository": "acr.example/api",
                "Name": "api",
            },
        ),
        "container_image_inventory": (
            {
                "TimeGenerated": "2026-09-05T00:00:00Z",
                "ImageID": f"acr.example/api@{digest}",
                "Repository": "acr.example/api",
                "Tag": "v1",
            },
        ),
    }
    outcomes = []
    for workspace in ("workspace-a", "workspace-b"):
        for family in WORKLOAD_QUERY_FAMILIES:
            common = {
                "connection_id": "connection-a",
                "workspace_id": workspace,
                "subscription_id": "sub-a",
                "source_family": family,
                "source_table": WORKLOAD_QUERY_TABLES[family],
                "query_version": WORKLOAD_QUERY_VERSIONS[family],
                "attempted_at": "2026-09-05T00:00:00Z",
                "completed_at": "2026-09-05T00:00:01Z",
            }
            if family == fail_family and workspace == fail_workspace:
                outcomes.append(
                    WorkloadQueryFailure(
                        **common,
                        error_code=WorkloadFailureCode.PROVIDER_TIMEOUT,
                        error_summary="Container Insights query timed out.",
                    )
                )
            else:
                outcomes.append(
                    WorkloadQuerySuccess(
                        **common,
                        rows=rows_by_family[family],
                    )
                )
    return tuple(outcomes), generation, digest


def _defender_workload_row(digest: str) -> dict[str, Any]:
    return {
        "id": "defender-image-finding",
        "tenantId": "tenant-a",
        "subscriptionId": "sub-a",
        "properties": {
            "timeGenerated": "2026-09-05T00:00:00Z",
            "additionalData": {"imageDigest": digest},
        },
    }


def test_each_workspace_table_returns_an_isolated_sanitized_outcome() -> None:
    from intelligence.vulnerability.workload_inventory import (
        WorkloadQueryFailure,
        WorkloadQuerySuccess,
        acquire_workload_inventory,
    )

    class Logs:
        def query_kube_pod_inventory(self, workspace_id):
            return [{"Name": workspace_id}]

        def query_container_inventory(self, workspace_id):
            if workspace_id == "workspace-a":
                raise TimeoutError("bearer super-secret timed out")
            return [{"Name": workspace_id}]

        def query_container_image_inventory(self, workspace_id):
            return []

    outcomes = acquire_workload_inventory(
        logs_client=Logs(),
        connection_id="connection-a",
        discovered_workspaces=[
            {"workspaceId": "workspace-a", "subscriptionId": "sub-a"},
            {"workspaceId": "workspace-b", "subscriptionId": "sub-a"},
        ],
        clock=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )

    assert len(outcomes) == 6
    failed = [row for row in outcomes if isinstance(row, WorkloadQueryFailure)]
    succeeded = [row for row in outcomes if isinstance(row, WorkloadQuerySuccess)]
    assert len(failed) == 1
    assert len(succeeded) == 5
    assert failed[0].workspace_id == "workspace-a"
    assert failed[0].source_family == "container_inventory"
    assert failed[0].error_code.value == "provider_timeout"
    assert "super-secret" not in repr(failed[0])
    assert any(
        row.workspace_id == "workspace-b"
        and row.source_family == "container_inventory"
        for row in succeeded
    )


@pytest.mark.parametrize("forbidden", ["query", "kql", "cluster", "scope", "workspace"])
def test_workload_acquisition_rejects_caller_authority_fields(forbidden: str) -> None:
    from intelligence.vulnerability.workload_inventory import acquire_workload_inventory

    with pytest.raises(ValueError, match="server-discovered"):
        acquire_workload_inventory(
            logs_client=object(),
            connection_id="connection-a",
            discovered_workspaces=[
                {
                    "workspaceId": "workspace-a",
                    "subscriptionId": "sub-a",
                    forbidden: "caller-controlled",
                }
            ],
        )


def test_failed_workload_family_retains_stale_lkg_and_original_generation() -> None:
    from intelligence.vulnerability.workload_inventory import (
        activate_workload_partitions,
    )

    first_outcomes, first_generation, digest = _workload_outcomes(
        generation="generation-1"
    )
    first = activate_workload_partitions(
        outcomes=first_outcomes,
        defender_rows=[_defender_workload_row(digest)],
        attempted_generation=first_generation,
        completed_at="2026-09-05T00:00:01Z",
    )
    second_outcomes, second_generation, _ = _workload_outcomes(
        generation="generation-2",
        fail_family="container_image_inventory",
        fail_workspace="workspace-a",
    )

    second = activate_workload_partitions(
        outcomes=second_outcomes,
        defender_rows=[_defender_workload_row(digest)],
        attempted_generation=second_generation,
        completed_at="2026-09-05T00:05:01Z",
        previous_observations=first.observations,
        previous_deployments=first.deployments,
        previous_checkpoints=first.checkpoints,
    )

    failed_checkpoint = next(
        row
        for row in second.checkpoints
        if row["workspace_id"] == "workspace-a"
        and row["source_family"] == "container_image_inventory"
    )
    healthy_checkpoint = next(
        row
        for row in second.checkpoints
        if row["workspace_id"] == "workspace-a"
        and row["source_family"] == "container_inventory"
    )
    retained = next(
        row for row in second.deployments if row["workspace_id"] == "workspace-a"
    )
    advanced = next(
        row for row in second.deployments if row["workspace_id"] == "workspace-b"
    )
    assert failed_checkpoint["status"] == "stale"
    assert failed_checkpoint["attempted_generation"] == "generation-2"
    assert failed_checkpoint["effective_generation"] == "generation-1"
    assert healthy_checkpoint["status"] == "complete"
    assert healthy_checkpoint["effective_generation"] == "generation-2"
    assert retained["carried_forward"] is True
    assert retained["attempted_generation"] == "generation-2"
    assert retained["effective_generation"] == "generation-1"
    assert retained["lkg_source_generation"] == "generation-1"
    assert advanced["effective_generation"] == "generation-2"


def test_failed_family_cannot_create_a_deployment_absent_from_lkg() -> None:
    from intelligence.vulnerability.workload_inventory import (
        activate_workload_partitions,
    )

    first_outcomes, first_generation, digest = _workload_outcomes(
        generation="generation-1"
    )
    first = activate_workload_partitions(
        outcomes=first_outcomes,
        defender_rows=[],
        attempted_generation=first_generation,
        completed_at="2026-09-05T00:00:01Z",
    )
    assert first.deployments == ()
    second_outcomes, second_generation, _ = _workload_outcomes(
        generation="generation-2",
        fail_family="container_image_inventory",
        fail_workspace="workspace-a",
    )

    second = activate_workload_partitions(
        outcomes=second_outcomes,
        defender_rows=[_defender_workload_row(digest)],
        attempted_generation=second_generation,
        completed_at="2026-09-05T00:05:01Z",
        previous_observations=first.observations,
        previous_deployments=first.deployments,
        previous_checkpoints=first.checkpoints,
    )

    assert not any(
        row["workspace_id"] == "workspace-a" for row in second.deployments
    )
    assert "stale_without_deployment_lkg" in second.unknown_reasons
    assert any(
        row["workspace_id"] == "workspace-b" for row in second.deployments
    )


def test_failed_workload_workspace_without_lkg_is_unavailable_and_rowless() -> None:
    from intelligence.vulnerability.workload_inventory import (
        WORKLOAD_QUERY_FAMILIES,
        activate_workload_partitions,
    )

    outcomes, generation, digest = _workload_outcomes(
        generation="generation-1",
        fail_family="container_image_inventory",
        fail_workspace="workspace-a",
    )
    # All three families are unavailable for workspace-a and have no prior LKG.
    failed_a = tuple(
        type(next(row for row in outcomes if row.workspace_id == "workspace-a" and row.source_family == "container_image_inventory"))(
            connection_id="connection-a",
            workspace_id="workspace-a",
            subscription_id="sub-a",
            source_family=family,
            source_table=next(row for row in outcomes if row.source_family == family).source_table,
            query_version=next(row for row in outcomes if row.source_family == family).query_version,
            attempted_at="2026-09-05T00:00:00Z",
            completed_at="2026-09-05T00:00:01Z",
            error_code=next(row for row in outcomes if row.workspace_id == "workspace-a" and row.source_family == "container_image_inventory").error_code,
            error_summary="Container Insights query timed out.",
        )
        for family in WORKLOAD_QUERY_FAMILIES
    )
    healthy_b = tuple(row for row in outcomes if row.workspace_id == "workspace-b")

    projected = activate_workload_partitions(
        outcomes=(*failed_a, *healthy_b),
        defender_rows=[_defender_workload_row(digest)],
        attempted_generation=generation,
        completed_at="2026-09-05T00:00:01Z",
    )

    assert all(
        row["status"] == "unavailable"
        for row in projected.checkpoints
        if row["workspace_id"] == "workspace-a"
    )
    assert not any(
        row["workspace_id"] == "workspace-a" for row in projected.observations
    )
    assert not any(
        row["workspace_id"] == "workspace-a" for row in projected.deployments
    )
    assert any(
        row["workspace_id"] == "workspace-b" for row in projected.deployments
    )


def test_failed_workload_partition_rejects_checkpoint_without_effective_generation() -> None:
    from intelligence.vulnerability.workload_inventory import (
        activate_workload_partitions,
        workload_checkpoint_key,
    )

    outcomes, generation, digest = _workload_outcomes(
        generation="generation-2",
        fail_family="container_image_inventory",
        fail_workspace="workspace-a",
    )
    invalid_checkpoint = {
        "checkpoint_key": workload_checkpoint_key(
            "connection-a",
            "workspace-a",
            "container_image_inventory",
        ),
        "connection_id": "connection-a",
        "workspace_id": "workspace-a",
        "source_family": "container_image_inventory",
        "status": "stale",
        "completeness": "stale",
        "effective_generation": "",
        "last_success_at": "",
    }

    projected = activate_workload_partitions(
        outcomes=outcomes,
        defender_rows=[_defender_workload_row(digest)],
        attempted_generation=generation,
        completed_at="2026-09-05T00:05:01Z",
        previous_checkpoints=[invalid_checkpoint],
    )

    failed = next(
        row
        for row in projected.checkpoints
        if row["workspace_id"] == "workspace-a"
        and row["source_family"] == "container_image_inventory"
    )
    assert failed["status"] == "unavailable"
    assert failed["completeness"] == "unavailable"
    assert failed["effective_generation"] == ""
    assert failed["carried_forward"] is False


def test_fabric_sync_validates_workload_references_before_activation(tmp_path) -> None:
    from deltalake import DeltaTable

    from fabric.data_quality import DataQualityValidator
    from fabric.sync_service import FabricSyncService
    from intelligence.vulnerability.workload_inventory import (
        activate_workload_partitions,
    )
    from storage.datasets import DatasetStore
    from storage.delta_writer import DeltaWriteMode, DeltaWriter
    from storage.onelake_writer import OneLakeWriter

    outcomes, generation, digest = _workload_outcomes(
        generation="generation-1"
    )
    projection = activate_workload_partitions(
        outcomes=outcomes,
        defender_rows=[_defender_workload_row(digest)],
        attempted_generation=generation,
        completed_at="2026-09-05T00:00:01Z",
    )
    source = tmp_path / "source"
    lakehouse = tmp_path / "lakehouse"
    store = DatasetStore(source)
    store.publish(
        {
            "exposure/workload_observations": list(projection.observations),
            "exposure/workload_deployments": list(projection.deployments),
            "exposure/workload_source_checkpoints": list(projection.checkpoints),
        },
        {},
        {
            "runId": generation,
            "startedAt": "2026-09-05T00:00:01Z",
            "status": "completed",
        },
    )
    service = FabricSyncService(
        source_root=source,
        onelake=OneLakeWriter(
            "workspace",
            "lakehouse",
            local_root=lakehouse,
        ),
        delta_writer=DeltaWriter(),
        validator=DataQualityValidator(),
    )

    result = service.sync()

    assert result.status == "completed"
    assert service._write_mode_for_table(
        "silver_workload_observations"
    ) is DeltaWriteMode.APPEND
    assert service._write_mode_for_table(
        "silver_workload_deployments"
    ) is DeltaWriteMode.MERGE
    assert service._write_mode_for_table(
        "metadata_workload_source_checkpoints"
    ) is DeltaWriteMode.MERGE
    deployments_path = lakehouse / "Tables/silver_workload_deployments"
    before = DeltaTable(str(deployments_path)).to_pyarrow_table().to_pylist()
    assert len(before) == 2

    invalid = [dict(row) for row in projection.deployments]
    invalid[0]["checkpoint_key"] = "missing-checkpoint"
    store.publish(
        {
            "exposure/workload_observations": list(projection.observations),
            "exposure/workload_deployments": invalid,
            "exposure/workload_source_checkpoints": list(projection.checkpoints),
        },
        {},
        {
            "runId": "generation-invalid",
            "startedAt": "2026-09-05T00:05:01Z",
            "status": "completed",
        },
    )

    with pytest.raises(ValueError, match="checkpoint"):
        service.sync()

    assert DeltaTable(str(deployments_path)).to_pyarrow_table().to_pylist() == before
