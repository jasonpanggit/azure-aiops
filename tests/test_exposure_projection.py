from __future__ import annotations

import json

import pytest

from fabric.dataset_mapper import exposure_gold_products_from_datasets
from fabric.schema_registry import schema_for
from intelligence.vulnerability.connector import enrichment_provenance_hash
from intelligence.vulnerability.exposure_projection import (
    EXPOSURE_GOLD_TABLES,
    project_exposure_gold,
)


GENERATION = "gold-generation-12"
PROJECTED_AT = "2026-09-06T08:00:00Z"
SERVER_ID = (
    "/subscriptions/sub-a/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm-a"
)


def _durable_enrichment(
    source: str,
    identifier: str,
    payload: dict,
    *,
    status: str = "succeeded",
    stale: bool = False,
) -> dict:
    source_at = "2026-09-05T00:00:00Z"
    return {
        "tenant_id": "system",
        "subscription_id": "not-applicable",
        "resource_id": f"{source}|{identifier}",
        "timestamp": "2026-09-05T01:00:00Z",
        "change_version": f"{source}|{identifier}|v1",
        "ingestion_run_id": "enrichment-generation-23",
        "enrichment_key": f"{source}|{identifier}",
        "source": source,
        "identifier": identifier,
        "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "payload_version": "1.0.0",
        "provenance_hash": enrichment_provenance_hash(
            source,
            identifier,
            payload,
            source_at=source_at,
            payload_version="1.0.0",
        ),
        "request_hash": "a" * 64,
        "attempted_at": "2026-09-05T01:00:00Z",
        "succeeded_at": "2026-09-05T01:00:00Z",
        "source_at": source_at,
        "enriched_at": "2026-09-05T01:00:00Z",
        "refresh_after": "2026-09-06T01:00:00Z",
        "stale_after": "2026-09-07T01:00:00Z",
        "status": status,
        "stale": stale,
        "safe_error_code": "",
    }


def _datasets() -> dict[str, list[dict]]:
    server_current = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-a",
        "resource_id": "current-server",
        "timestamp": "2026-09-05T00:00:00Z",
        "change_version": "server-v1",
        "ingestion_run_id": "temporal-generation-9",
        "current_key": "server-current-key",
        "contract_version": "1.0.0",
        "projection_generation_id": "temporal-generation-9",
        "target_id": SERVER_ID,
        "target_kind": "server",
        "weakness_id": "CVE-2026-1001",
        "weakness_kind": "cve",
        "state": "missing",
        "active": True,
        "active_source_families": [
            "azure_update_manager_missing",
            "defender_subassessment",
        ],
        "source_states_json": json.dumps(
            {
                "azure_update_manager_missing": "missing",
                "defender_subassessment": "unhealthy",
            },
            sort_keys=True,
        ),
        "first_detected_at": "2026-09-01T08:00:00Z",
        "first_detection_quality": "provider",
        "episode_started_at": "2026-09-01T08:00:00Z",
        "last_observed_at": "2026-09-05T00:00:00Z",
        "reintroduction_count": 0,
        "observation_count": 2,
        "last_observation_id": "observation-defender",
        "sla_target_seconds": 604800,
    }
    observations = [
        {
            "tenant_id": "tenant-a",
            "subscription_id": "sub-a",
            "resource_id": "observation-aum",
            "observation_id": "observation-aum",
            "current_key": "server-current-key",
            "connection_id": "connection-a",
            "source_family": "azure_update_manager_missing",
            "source_generation": "temporal-generation-9",
            "event_time": "2026-09-01T08:00:00Z",
            "payload_json": json.dumps(
                {
                    "severity": "Critical",
                    "recommendation": "Install KB600001",
                    "evidence_url": "/evidence/aum/observation-aum",
                }
            ),
        },
        {
            "tenant_id": "tenant-a",
            "subscription_id": "sub-a",
            "resource_id": "observation-defender",
            "observation_id": "observation-defender",
            "current_key": "server-current-key",
            "connection_id": "connection-a",
            "source_family": "defender_subassessment",
            "source_generation": "temporal-generation-9",
            "event_time": "2026-09-05T00:00:00Z",
            "payload_json": json.dumps(
                {
                    "severity": "High",
                    "recommendation": "Upgrade the vulnerable package",
                    "evidence_url": "/evidence/defender/observation-defender",
                }
            ),
        },
    ]
    container_current = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-b",
        "resource_id": "container-current",
        "timestamp": "2026-09-05T02:00:00Z",
        "change_version": "container-v1",
        "ingestion_run_id": "container-generation-11",
        "container_exposure_id": "container-exposure-1",
        "contract_version": "1.0.0",
        "target_kind": "container_image",
        "registry_id": "registry-1",
        "logical_image_id": "logical-image-1",
        "image_digest_id": "digest-id-1",
        "image_digest": f"sha256:{'a' * 64}",
        "cve_id": "CVE-2026-2001",
        "vulnerability_observation_ids": ["container-observation-1"],
        "severity": "Medium",
        "risk_score": 50.0,
        "impact_score": 30.0,
        "priority_score": 80.0,
        "deployment_state": "observed_exact_digest",
        "workload_ids": ["deployment-1", "deployment-2"],
        "workload_checkpoint_generations": ["workload-generation-6"],
        "represented_workload_count": 2,
        "total_workload_count": 5,
        "unknown_workload_count": 3,
        "unknown_reason_counts_json": json.dumps(
            {"no_exact_digest_observation": 3}
        ),
        "business_service_ids": ["business-service:checkout"],
        "server_patch_eligible": False,
        "source_generations": ["container-generation-11"],
        "observed_at": "2026-09-05T02:00:00Z",
    }
    container_observation = {
        "tenant_id": "tenant-a",
        "subscription_id": "sub-b",
        "resource_id": "container-observation-1",
        "vulnerability_observation_id": "container-observation-1",
        "connection_id": "connection-b",
        "source_family": "defender_image",
        "source_event_payload_json": json.dumps(
            {"evidence_url": "/evidence/container/container-observation-1"}
        ),
    }
    return {
        "gold_exposure_current": [server_current],
        "silver_exposure_observations": observations,
        "gold_container_exposure_current": [container_current],
        "silver_container_vulnerability_observations": [
            container_observation
        ],
        "silver_exposure_enrichment": [
            _durable_enrichment(
                "nvd",
                "CVE-2026-1001",
                {
                    "id": "CVE-2026-1001",
                    "description": "Safe durable NVD detail",
                    "cvss_score": 9.8,
                },
            ),
            _durable_enrichment(
                "epss",
                "CVE-2026-1001",
                {"cve": "CVE-2026-1001", "epss_score": 0.91},
            ),
        ],
        "metadata_source_status": [
            {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-a",
                "connection_id": "connection-a",
                "source_family": "azure_update_manager_missing",
                "state": "complete",
                "completeness": "complete",
                "last_attempt_at": "2026-09-05T00:00:00Z",
                "last_success_at": "2026-09-05T00:00:00Z",
            },
            {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-a",
                "connection_id": "connection-a",
                "source_family": "defender_subassessment",
                "state": "failed-with-lkg",
                "completeness": "partial",
                "last_attempt_at": "2026-09-05T00:00:00Z",
                "last_success_at": "2026-09-04T00:00:00Z",
            },
            {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-b",
                "connection_id": "connection-b",
                "source_family": "defender_image",
                "state": "complete",
                "completeness": "complete",
                "last_attempt_at": "2026-09-05T02:00:00Z",
                "last_success_at": "2026-09-05T02:00:00Z",
            },
        ],
        "silver_defender_secure_scores": [
            {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-a",
                "timestamp": "2026-09-05T00:00:00Z",
                "currentScore": 20.0,
                "maxScore": 100.0,
            },
            {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-b",
                "timestamp": "2026-09-05T00:00:00Z",
                "currentScore": 30.0,
                "maxScore": 50.0,
            },
            {
                "tenant_id": "tenant-a",
                "subscription_id": "sub-out-of-scope",
                "timestamp": "2026-09-05T00:00:00Z",
                "currentScore": 100.0,
                "maxScore": 100.0,
            },
        ],
    }


def test_gold_contracts_are_registered_additively_and_keep_role_identity() -> None:
    assert EXPOSURE_GOLD_TABLES == (
        "gold_exposure_facts",
        "gold_exposure_dimensions",
        "gold_exposure_facets",
        "gold_exposure_summaries",
        "gold_exposure_evidence",
    )
    assert {
        "fact_id",
        "scope_key",
        "read_model_generation_id",
        "connection_id",
        "target_kind",
        "weakness_id",
        "source_family",
        "source_state",
        "current_state",
        "sla_age_seconds",
        "sla_target_seconds",
        "recommendation",
        "deployment_state",
        "represented_workload_count",
        "total_workload_count",
        "unknown_workload_count",
        "source_status",
        "completeness",
        "evidence_refs_json",
        "detail_path",
        "ordering_priority_score",
    } <= set(schema_for("gold_exposure_facts").names)
    assert {
        "facet_key",
        "dimension_name",
        "dimension_value",
        "raw_order_text",
        "raw_order_numeric",
        "exposure_count",
        "fact_count",
    } <= set(schema_for("gold_exposure_facets").names)
    assert {
        "summary_key",
        "exposure_count",
        "secure_score_current",
        "secure_score_max",
        "secure_score_percentage",
        "count_unit",
        "duration_unit",
        "percentage_unit",
    } <= set(schema_for("gold_exposure_summaries").names)

    approval = schema_for("silver_remediation_approval_policies")
    assert approval.field("role_ids_json").nullable is True


def test_projection_builds_generation_pinned_scoped_facts_facets_and_summaries() -> None:
    datasets = _datasets()
    projection = project_exposure_gold(
        datasets,
        generation_id=GENERATION,
        projected_at=PROJECTED_AT,
    )
    repeated = project_exposure_gold(
        datasets,
        generation_id=GENERATION,
        projected_at=PROJECTED_AT,
    )

    assert projection == repeated
    assert len(projection.facts) == 3
    assert {
        row["target_kind"] for row in projection.facts
    } == {"server", "container_image"}
    assert {
        row["source_family"] for row in projection.facts
    } == {
        "azure_update_manager_missing",
        "defender_subassessment",
        "defender_image",
    }
    assert all(
        row["read_model_generation_id"] == GENERATION
        for table in projection.as_tables().values()
        for row in table
    )

    server_facts = [
        row for row in projection.facts if row["target_kind"] == "server"
    ]
    assert len({row["scope_key"] for row in server_facts}) == 1
    assert len({row["fact_id"] for row in server_facts}) == 2
    assert {
        row["source_state"] for row in server_facts
    } == {"missing", "unhealthy"}
    assert {row["source_status"] for row in server_facts} == {
        "complete",
        "failed-with-lkg",
    }
    assert {row["completeness"] for row in server_facts} == {
        "complete",
        "partial",
    }
    assert all(row["sla_age_seconds"] == 432000 for row in server_facts)
    assert all(row["sla_target_seconds"] == 604800 for row in server_facts)
    assert {
        row["recommendation"] for row in server_facts
    } == {"Install KB600001", "Upgrade the vulnerable package"}
    assert all(
        row["detail_path"] == "/exposure/cves/CVE-2026-1001"
        for row in server_facts
    )
    assert all(row["evidence_count"] == 2 for row in server_facts)

    image = next(
        row for row in projection.facts if row["target_kind"] == "container_image"
    )
    assert image["deployment_state"] == "observed_exact_digest"
    assert image["represented_workload_count"] == 2
    assert image["total_workload_count"] == 5
    assert image["unknown_workload_count"] == 3
    assert image["recommendation"] == ""
    assert image["sla_age_seconds"] is None

    target_kind_facets = {
        row["dimension_value"]: row
        for row in projection.facets
        if row["scope_kind"] == "tenant"
        and row["dimension_name"] == "target_kind"
    }
    assert target_kind_facets["server"]["exposure_count"] == 1
    assert target_kind_facets["server"]["fact_count"] == 2
    assert target_kind_facets["container_image"][
        "represented_workload_count"
    ] == 2
    assert target_kind_facets["container_image"]["total_workload_count"] == 5
    assert target_kind_facets["container_image"]["unknown_workload_count"] == 3

    tenant_summary = next(
        row for row in projection.summaries
        if row["scope_kind"] == "tenant"
    )
    assert tenant_summary["exposure_count"] == 2
    assert tenant_summary["fact_count"] == 3
    assert tenant_summary["secure_score_current"] == 50.0
    assert tenant_summary["secure_score_max"] == 150.0
    assert tenant_summary["secure_score_percentage"] == pytest.approx(
        33.333333333333336
    )
    assert tenant_summary["count_unit"] == "count"
    assert tenant_summary["duration_unit"] == "seconds"
    assert tenant_summary["percentage_unit"] == "percent"
    assert tenant_summary["unknown_workload_count"] == 3


def test_generation_changes_fact_keys_but_not_scope_keys_and_mapper_matches() -> None:
    datasets = _datasets()
    first = project_exposure_gold(
        datasets,
        generation_id=GENERATION,
        projected_at=PROJECTED_AT,
    )
    second = project_exposure_gold(
        datasets,
        generation_id="gold-generation-13",
        projected_at=PROJECTED_AT,
    )

    assert {row["scope_key"] for row in first.facts} == {
        row["scope_key"] for row in second.facts
    }
    assert {row["fact_id"] for row in first.facts}.isdisjoint(
        {row["fact_id"] for row in second.facts}
    )
    assert exposure_gold_products_from_datasets(
        datasets,
        generation_id=GENERATION,
        projected_at=PROJECTED_AT,
    ) == first.as_tables()


def test_untrusted_enrichment_is_isolated_and_never_flows_to_gold_payloads() -> None:
    datasets = _datasets()
    datasets["silver_exposure_enrichment"].append(
        {
            **_durable_enrichment(
                "kev",
                "CVE-2026-1001",
                {"cve": "CVE-2026-1001"},
            ),
            "payload_json": json.dumps(
                {"description": "<script>provider control</script>"}
            ),
        }
    )

    projection = project_exposure_gold(
        datasets,
        generation_id=GENERATION,
        projected_at=PROJECTED_AT,
    )

    assert {row["source"] for row in projection.evidence} == {"nvd", "epss"}
    assert projection.reconciliation["invalid_enrichment_count"] == 1
    assert "<script>" not in json.dumps(projection.as_tables())
