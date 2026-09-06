from __future__ import annotations

import json

import pytest

from fabric.dataset_mapper import GranularExposureOntologyMapper
from ontology.entity_builder import typed_image_semantic_id

DIGEST = f"sha256:{'a' * 64}"
TENANT_ID = "tenant-1"
SUBSCRIPTION_ID = "subscription-1"
SOURCE_GENERATION = "defender-generation-7"
ATTEMPTED_GENERATION = "workload-generation-9"
EFFECTIVE_GENERATION = "workload-generation-8"
OBSERVED_AT = "2026-09-05T10:02:00Z"
DEFENDER_OBSERVED_AT = "2026-09-05T10:00:00Z"
REGISTRY_ID = "registry:v1:acr1"
LOGICAL_IMAGE_ID = "logical-image:v1:acr1.azurecr.io/platform/api"
IMAGE_DIGEST_ID = f"image-digest:v1:{DIGEST}"
OBSERVATION_ID = "vulnerability-observation:v1:defender-event-7:cve-2026-4242"
DEPLOYMENT_ID = f"workload-deployment:v1:{DIGEST}:deployment-7"
CHECKPOINT_ID = "workload-checkpoint:v1:container-images"


def _base(resource_id: str, *, generation: str = SOURCE_GENERATION) -> dict:
    return {
        "tenant_id": TENANT_ID,
        "subscription_id": SUBSCRIPTION_ID,
        "resource_id": resource_id,
        "timestamp": OBSERVED_AT,
        "change_version": f"change:{resource_id}",
        "ingestion_run_id": generation,
    }


def fabric_products(*, completeness: str = "complete") -> dict[str, list[dict]]:
    provenance = json.dumps(
        {
            "connection_id": "connection-1",
            "source_event_id": "defender-event-7",
        },
        sort_keys=True,
    )
    return {
        "silver_container_registries": [
            {
                **_base(REGISTRY_ID),
                "registry_id": REGISTRY_ID,
                "identity_version": "1",
                "contract_version": "1.0.0",
                "registry_resource_id": (
                    "/subscriptions/subscription-1/resourceGroups/rg/providers/"
                    "Microsoft.ContainerRegistry/registries/acr1"
                ).casefold(),
                "registry_host": "acr1.azurecr.io",
                "connection_id": "connection-1",
                "source_system": "defender",
                "source_ids": ["defender-event-7"],
                "observed_at": DEFENDER_OBSERVED_AT,
                "ingested_at": "2026-09-05T10:03:00Z",
                "provenance_json": provenance,
            }
        ],
        "silver_container_logical_images": [
            {
                **_base(LOGICAL_IMAGE_ID),
                "logical_image_id": LOGICAL_IMAGE_ID,
                "identity_version": "1",
                "contract_version": "1.0.0",
                "registry_id": REGISTRY_ID,
                "registry_resource_id": (
                    "/subscriptions/subscription-1/resourceGroups/rg/providers/"
                    "Microsoft.ContainerRegistry/registries/acr1"
                ).casefold(),
                "registry_host": "acr1.azurecr.io",
                "repository": "platform/api",
                "image_tags": ["2026.09", "latest"],
                "connection_id": "connection-1",
                "source_system": "defender",
                "source_ids": ["defender-event-7"],
                "observed_at": DEFENDER_OBSERVED_AT,
                "ingested_at": "2026-09-05T10:03:00Z",
                "provenance_json": provenance,
            }
        ],
        "silver_container_image_digests": [
            {
                **_base(IMAGE_DIGEST_ID),
                "image_digest_id": IMAGE_DIGEST_ID,
                "identity_version": "1",
                "contract_version": "1.0.0",
                "image_digest": DIGEST,
                "logical_image_ids": [LOGICAL_IMAGE_ID],
                "registry_ids": [REGISTRY_ID],
                "image_tags": ["2026.09", "latest"],
                "connection_id": "connection-1",
                "source_system": "defender",
                "source_ids": ["defender-event-7"],
                "observed_at": DEFENDER_OBSERVED_AT,
                "ingested_at": "2026-09-05T10:03:00Z",
                "provenance_json": provenance,
            }
        ],
        "silver_container_vulnerability_observations": [
            {
                **_base(OBSERVATION_ID),
                "vulnerability_observation_id": OBSERVATION_ID,
                "identity_version": "1",
                "contract_version": "1.0.0",
                "registry_id": REGISTRY_ID,
                "logical_image_id": LOGICAL_IMAGE_ID,
                "image_digest_id": IMAGE_DIGEST_ID,
                "image_digest": DIGEST,
                "target_kind": "container_image",
                "cve_id": "CVE-2026-4242",
                "assessment_id": "assessment-7",
                "source_event_id": "defender-event-7",
                "source_family": "defender",
                "status": "Unhealthy",
                "severity": "Critical",
                "software_name": "openssl",
                "package_version": "3.0.0",
                "fixed_version": "3.0.1",
                "provider_event_time": DEFENDER_OBSERVED_AT,
                "provider_event_time_quality": "provider",
                "observed_at": DEFENDER_OBSERVED_AT,
                "ingested_at": "2026-09-05T10:03:00Z",
                "connection_id": "connection-1",
                "source_event_payload_json": json.dumps(
                    {"assessment": "assessment-7"}, sort_keys=True
                ),
                "provenance_json": provenance,
            }
        ],
        "silver_workload_deployments": [
            {
                **_base(DEPLOYMENT_ID, generation=ATTEMPTED_GENERATION),
                "deployment_id": DEPLOYMENT_ID,
                "checkpoint_key": CHECKPOINT_ID,
                "checkpoint_key_version": "1",
                "contract_version": "1.0.0",
                "connection_id": "connection-1",
                "workspace_id": "workspace-1",
                "defender_observation_id": "defender-event-7",
                "image_digest": DIGEST,
                "cluster_id": (
                    "/subscriptions/subscription-1/resourceGroups/rg/providers/"
                    "Microsoft.ContainerService/managedClusters/aks1"
                ).casefold(),
                "namespace": "payments",
                "controller_kind": "Deployment",
                "controller_name": "platform-api",
                "pod_name": "platform-api-7",
                "pod_uid": "pod-uid-7",
                "container_id": "container-7",
                "container_name": "api",
                "observed_at": OBSERVED_AT,
                "defender_observed_at": DEFENDER_OBSERVED_AT,
                "repository": "acr1.azurecr.io/platform/api",
                "tag": "2026.09",
                "attempted_generation": ATTEMPTED_GENERATION,
                "effective_generation": EFFECTIVE_GENERATION,
                "lkg_source_generation": (
                    EFFECTIVE_GENERATION if completeness == "stale" else ""
                ),
                "carried_forward": completeness == "stale",
                "unknown_reason": "",
                "provenance_json": json.dumps(
                    {
                        "defender_observation_id": "defender-event-7",
                        "image_observation_id": "image-observation-7",
                    },
                    sort_keys=True,
                ),
            }
        ],
        "metadata_workload_source_checkpoints": [
            {
                **_base(CHECKPOINT_ID, generation=ATTEMPTED_GENERATION),
                "checkpoint_key": CHECKPOINT_ID,
                "checkpoint_key_version": "1",
                "contract_version": "1.0.0",
                "connection_id": "connection-1",
                "workspace_id": "workspace-1",
                "source_family": "container_image_inventory",
                "source_table": "ContainerImageInventory",
                "query_version": "container-insights-container-image-inventory-v1",
                "status": completeness,
                "attempted_generation": ATTEMPTED_GENERATION,
                "effective_generation": EFFECTIVE_GENERATION,
                "attempted_at": "2026-09-05T10:04:00Z",
                "completed_at": "2026-09-05T10:05:00Z",
                "last_success_at": (
                    "2026-09-05T10:05:00Z" if completeness == "complete" else ""
                ),
                "row_count": 1 if completeness == "complete" else 0,
                "carried_forward": completeness == "stale",
                "lkg_source_generation": (
                    EFFECTIVE_GENERATION if completeness == "stale" else ""
                ),
                "completeness": completeness,
                "safe_error_code": (
                    "" if completeness == "complete" else "provider_timeout"
                ),
                "safe_error_summary": (
                    "" if completeness == "complete" else "Provider timed out."
                ),
                "unknown_reason_counts_json": json.dumps(
                    {} if completeness == "complete" else {"source_unavailable": 1},
                    sort_keys=True,
                ),
            }
        ],
    }


def test_granular_fabric_ontology_fabric_round_trip_is_lossless_and_idempotent() -> None:
    products = fabric_products()
    mapper = GranularExposureOntologyMapper()

    graph = mapper.project(products, ontology_generation_id="ontology-generation-3")
    repeated = mapper.project(
        products, ontology_generation_id="ontology-generation-3"
    )
    restored = mapper.to_fabric(graph)

    assert graph == repeated
    assert graph.quality_report["passed"] is True
    for table in products:
        assert restored[table] == products[table]

    entities = {
        row["entity_type"]: row
        for row in graph.entities
        if row["entity_type"]
        in {
            "LogicalImage",
            "ImageDigest",
            "VulnerabilityObservation",
            "WorkloadDeployment",
        }
    }
    assert set(entities) == {
        "LogicalImage",
        "ImageDigest",
        "VulnerabilityObservation",
        "WorkloadDeployment",
    }
    expected_ids = {
        "LogicalImage": typed_image_semantic_id(
            "LogicalImage", TENANT_ID, SUBSCRIPTION_ID, LOGICAL_IMAGE_ID
        ),
        "ImageDigest": typed_image_semantic_id(
            "ImageDigest", TENANT_ID, SUBSCRIPTION_ID, IMAGE_DIGEST_ID
        ),
        "VulnerabilityObservation": typed_image_semantic_id(
            "VulnerabilityObservation",
            TENANT_ID,
            SUBSCRIPTION_ID,
            OBSERVATION_ID,
        ),
        "WorkloadDeployment": typed_image_semantic_id(
            "WorkloadDeployment", TENANT_ID, SUBSCRIPTION_ID, DEPLOYMENT_ID
        ),
    }
    assert {
        entity_type: row["resource_id"] for entity_type, row in entities.items()
    } == expected_ids
    assert all(
        row["entity_type"] not in {"Resource", "Server", "VirtualMachine", "ArcServer"}
        for row in entities.values()
    )

    triples = {
        (row["subject_type"], row["predicate"], row["object_type"])
        for row in graph.relationships
    }
    assert ("LogicalImage", "hasDigest", "ImageDigest") in triples
    assert ("VulnerabilityObservation", "affects", "ImageDigest") in triples
    assert ("ImageDigest", "deployedAs", "WorkloadDeployment") in triples
    exact_edge = next(
        row
        for row in graph.relationships
        if (
            row["subject_type"],
            row["predicate"],
            row["object_type"],
        )
        == ("ImageDigest", "deployedAs", "WorkloadDeployment")
    )
    edge_evidence = json.loads(exact_edge["payload_json"])
    assert edge_evidence["evidence_identity"] == DEPLOYMENT_ID
    assert edge_evidence["attempted_generation"] == ATTEMPTED_GENERATION
    assert edge_evidence["effective_generation"] == EFFECTIVE_GENERATION
    assert edge_evidence["event_interval"] == {
        "from": DEFENDER_OBSERVED_AT,
        "to": OBSERVED_AT,
    }
    assert edge_evidence["provenance"] == {
        "defender_observation_id": "defender-event-7",
        "image_observation_id": "image-observation-7",
    }
    assert edge_evidence["completeness"] == "complete"


def test_granular_mapping_rejects_missing_or_conflicting_exact_references() -> None:
    mapper = GranularExposureOntologyMapper()
    missing_digest = fabric_products()
    missing_digest["silver_container_image_digests"] = []

    with pytest.raises(ValueError, match="unknown image digest"):
        mapper.project(
            missing_digest,
            ontology_generation_id="ontology-generation-invalid",
        )

    unsafe_target = fabric_products()
    unsafe_target["silver_container_vulnerability_observations"][0][
        "target_kind"
    ] = "server"
    with pytest.raises(ValueError, match="target kind"):
        mapper.project(
            unsafe_target,
            ontology_generation_id="ontology-generation-invalid",
        )


def test_unknown_workload_coverage_creates_no_deployment_edge() -> None:
    products = fabric_products(completeness="unavailable")
    products["silver_workload_deployments"] = []

    graph = GranularExposureOntologyMapper().project(
        products,
        ontology_generation_id="ontology-generation-unknown",
    )

    assert all(
        row["entity_type"] != "WorkloadDeployment" for row in graph.entities
    )
    assert all(row["predicate"] != "deployedAs" for row in graph.relationships)
    digest = next(
        row for row in graph.entities if row["entity_type"] == "ImageDigest"
    )
    coverage = json.loads(digest["payload_json"])["coverage_checkpoints"]
    assert coverage[0]["completeness"] == "unavailable"
    assert json.loads(coverage[0]["unknown_reason_counts_json"]) == {
        "source_unavailable": 1
    }
