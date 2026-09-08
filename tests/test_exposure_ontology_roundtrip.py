from __future__ import annotations

import json
from copy import deepcopy

import pytest

from fabric.dataset_mapper import (
    GRANULAR_EXPOSURE_MAX_SOURCE_ROWS,
    GranularExposureOntologyMapper,
    filter_legacy_granular_exposure_graph,
)
from fabric_pipelines.vulnerability_pipeline import (
    CONTAINER_EXPOSURE_CURRENT_TABLE,
    materialize_container_exposure_tables,
)
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
    products = {
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
    products[CONTAINER_EXPOSURE_CURRENT_TABLE] = (
        materialize_container_exposure_tables(
            products,
            projected_at=OBSERVED_AT,
            source_generation=SOURCE_GENERATION,
        )[CONTAINER_EXPOSURE_CURRENT_TABLE]
    )
    return products


def test_granular_mapper_accepts_images_without_vulnerability_observations() -> None:
    products = fabric_products()
    products["silver_container_vulnerability_observations"] = []
    products[CONTAINER_EXPOSURE_CURRENT_TABLE] = []

    entities, relationships = GranularExposureOntologyMapper().build_rows(
        products,
        ontology_generation_id="ontology-generation-7",
        allow_empty=True,
    )

    assert {"LogicalImage", "ImageDigest", "WorkloadDeployment"} <= {
        row["entity_type"] for row in entities
    }
    assert relationships


def test_granular_mapper_projects_canonical_current_exposure_only() -> None:
    mapper = GranularExposureOntologyMapper()
    products = fabric_products()

    entities, _ = mapper.build_rows(
        products,
        ontology_generation_id="ontology-generation-7",
    )
    observations = [
        row
        for row in entities
        if row["entity_type"] == "VulnerabilityObservation"
    ]

    assert len(observations) == 1
    payload = json.loads(observations[0]["payload_json"])
    assert payload["fabric_table"] == CONTAINER_EXPOSURE_CURRENT_TABLE
    assert payload["evidence_refs"] == [OBSERVATION_ID]


def test_canonical_mapper_raises_only_the_source_input_bound() -> None:
    mapper = GranularExposureOntologyMapper()

    assert mapper.entity_builder.max_source_rows == (
        GRANULAR_EXPOSURE_MAX_SOURCE_ROWS
    )
    assert mapper.entity_builder.max_source_rows == 100_000
    assert mapper.entity_builder.max_entities == 100_000
    assert mapper.relationship_builder.max_entities == 100_000
    assert mapper.relationship_builder.max_relationships == 250_000
    assert mapper.synchronizer.max_entities == 100_000
    assert mapper.synchronizer.max_relationships == 250_000


def test_legacy_source_event_nodes_are_removed_before_canonical_sync() -> None:
    legacy_id = "ontology://legacy-source-observation"
    canonical_id = "ontology://canonical-current-exposure"
    entities = [
        {
            "resource_id": legacy_id,
            "entity_type": "VulnerabilityObservation",
            "payload_json": json.dumps(
                {
                    "fabric_table": (
                        "silver_container_vulnerability_observations"
                    )
                }
            ),
        },
        {
            "resource_id": canonical_id,
            "entity_type": "VulnerabilityObservation",
            "payload_json": json.dumps(
                {"fabric_table": CONTAINER_EXPOSURE_CURRENT_TABLE}
            ),
        },
    ]
    relationships = [
        {
            "resource_id": "legacy-edge",
            "subject_id": legacy_id,
            "object_id": "digest",
        },
        {
            "resource_id": "canonical-edge",
            "subject_id": canonical_id,
            "object_id": "digest",
        },
    ]

    retained_entities, retained_relationships = (
        filter_legacy_granular_exposure_graph(
            entities,
            relationships,
        )
    )

    assert [row["resource_id"] for row in retained_entities] == [
        canonical_id
    ]
    assert [row["resource_id"] for row in retained_relationships] == [
        "canonical-edge"
    ]


def test_duplicate_source_observations_share_one_canonical_ontology_exposure() -> None:
    products = fabric_products()
    duplicate = deepcopy(
        products["silver_container_vulnerability_observations"][0]
    )
    duplicate_id = f"{OBSERVATION_ID}-duplicate-source-event"
    duplicate.update(
        {
            "resource_id": duplicate_id,
            "vulnerability_observation_id": duplicate_id,
            "source_event_id": "defender-event-8",
            "assessment_id": "assessment-8",
            "change_version": f"change:{duplicate_id}",
        }
    )
    products["silver_container_vulnerability_observations"].append(duplicate)
    products[CONTAINER_EXPOSURE_CURRENT_TABLE] = (
        materialize_container_exposure_tables(
            products,
            projected_at=OBSERVED_AT,
            source_generation=SOURCE_GENERATION,
        )[CONTAINER_EXPOSURE_CURRENT_TABLE]
    )

    entities, _ = GranularExposureOntologyMapper().build_rows(
        products,
        ontology_generation_id="ontology-generation-8",
    )
    observations = [
        row
        for row in entities
        if row["entity_type"] == "VulnerabilityObservation"
    ]

    assert len(
        products["silver_container_vulnerability_observations"]
    ) == 2
    assert len(products[CONTAINER_EXPOSURE_CURRENT_TABLE]) == 1
    assert len(observations) == 1
    payload = json.loads(observations[0]["payload_json"])
    assert payload["evidence_refs"] == sorted(
        [OBSERVATION_ID, duplicate_id]
    )


def test_canonical_fabric_ontology_round_trip_is_lossless_and_idempotent() -> None:
    products = fabric_products()
    mapper = GranularExposureOntologyMapper()

    graph = mapper.project(products, ontology_generation_id="ontology-generation-3")
    repeated = mapper.project(
        products, ontology_generation_id="ontology-generation-3"
    )
    restored = mapper.to_fabric(graph)

    assert graph == repeated
    assert graph.quality_report["passed"] is True
    canonical_tables = {
        "silver_container_registries",
        "silver_container_logical_images",
        "silver_container_image_digests",
        "silver_workload_deployments",
        "metadata_workload_source_checkpoints",
        CONTAINER_EXPOSURE_CURRENT_TABLE,
    }
    for table in canonical_tables:
        assert restored[table] == products[table]
    assert "silver_container_vulnerability_observations" not in restored

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
            products[CONTAINER_EXPOSURE_CURRENT_TABLE][0][
                "container_exposure_id"
            ],
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


def test_identical_digest_values_remain_distinct_across_subscription_scopes() -> None:
    products = fabric_products()
    second_registry_id = f"{REGISTRY_ID}:subscription-2"
    second_logical_id = f"{LOGICAL_IMAGE_ID}:subscription-2"
    second_digest_id = f"{IMAGE_DIGEST_ID}:subscription-2"
    second_observation_id = f"{OBSERVATION_ID}:subscription-2"

    registry = deepcopy(products["silver_container_registries"][0])
    registry.update(
        {
            "subscription_id": "subscription-2",
            "resource_id": second_registry_id,
            "registry_id": second_registry_id,
            "registry_resource_id": registry["registry_resource_id"].replace(
                "subscription-1",
                "subscription-2",
            ),
        }
    )
    logical = deepcopy(products["silver_container_logical_images"][0])
    logical.update(
        {
            "subscription_id": "subscription-2",
            "resource_id": second_logical_id,
            "logical_image_id": second_logical_id,
            "registry_id": second_registry_id,
            "registry_resource_id": registry["registry_resource_id"],
        }
    )
    digest = deepcopy(products["silver_container_image_digests"][0])
    digest.update(
        {
            "subscription_id": "subscription-2",
            "resource_id": second_digest_id,
            "image_digest_id": second_digest_id,
            "logical_image_ids": [second_logical_id],
            "registry_ids": [second_registry_id],
        }
    )
    observation = deepcopy(
        products["silver_container_vulnerability_observations"][0]
    )
    observation.update(
        {
            "subscription_id": "subscription-2",
            "resource_id": second_observation_id,
            "vulnerability_observation_id": second_observation_id,
            "registry_id": second_registry_id,
            "logical_image_id": second_logical_id,
            "image_digest_id": second_digest_id,
        }
    )
    products["silver_container_registries"].append(registry)
    products["silver_container_logical_images"].append(logical)
    products["silver_container_image_digests"].append(digest)
    products["silver_container_vulnerability_observations"].append(observation)

    graph = GranularExposureOntologyMapper().project(
        products,
        ontology_generation_id="ontology-generation-multi-scope",
    )

    image_digests = [
        row for row in graph.entities if row["entity_type"] == "ImageDigest"
    ]
    assert len(image_digests) == 2
    assert len({row["resource_id"] for row in image_digests}) == 2
