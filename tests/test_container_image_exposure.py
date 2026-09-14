from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from onboarding.defender_normalize import (
    is_container_image_assessment,
    normalize_assessment,
    normalize_container_image_exposure,
    normalize_container_image_products,
)
from onboarding.graph_normalize import Normalizer

OBSERVED = "2026-09-02T00:00:00Z"
DIGEST_A = f"sha256:{'a' * 64}"
DIGEST_B = f"sha256:{'b' * 64}"
REGISTRY = (
    "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.ContainerRegistry"
    "/registries/acr1"
)
IMAGE = f"{REGISTRY}/securityentitydata/repositories-api-images-sha256:abc123"


def _image_row(package: str, severities: list[str], cves: list[str]) -> dict:
    return {
        "id": f"{IMAGE}/providers/Microsoft.Security/assessments/{package}",
        "name": package,
        "subscriptionId": "sub1",
        "properties": {
            "displayName": f"Update {package}",
            "resourceAdditionalData": json.dumps(
                {
                    "RepositoryDetails": {
                        "RepositoryName": "api",
                        "RegistryHost": "acr1.azurecr.io",
                    },
                    "ImageUri": "acr1.azurecr.io/api@sha256:abc123",
                    "Digest": "sha256:abc123",
                    "Tags": ["v1"],
                    "LastPushedToRegistryUTC": "09/01/2026 16:19:54",
                }
            ),
            "resourceDetails": {
                "ResourceProvider": "acr",
                "ResourceType": ".containerimage",
                "Id": IMAGE,
            },
            "status": {"code": "Unhealthy"},
            "additionalData": {
                "SoftwareName": package,
                "CvesDetails": json.dumps(
                    [
                        {"CveId": cve, "Severity": sev}
                        for cve, sev in zip(cves, severities, strict=True)
                    ]
                ),
            },
        },
    }


def _granular_image_row(
    package: str,
    severities: list[str],
    cves: list[str],
    *,
    digest: str = DIGEST_A,
    tags: list[str] | None = None,
) -> dict:
    row = _image_row(package, severities, cves)
    details = json.loads(row["properties"]["resourceAdditionalData"])
    details.update(
        {
            "Digest": digest,
            "ImageUri": f"acr1.azurecr.io/api@{digest}",
            "Tags": list(tags or ["v1"]),
        }
    )
    row["properties"]["resourceAdditionalData"] = json.dumps(details)
    row["properties"]["timeGenerated"] = OBSERVED
    return row


def _vm_row() -> dict:
    return {
        "id": "/subscriptions/sub1/.../providers/Microsoft.Security/assessments/vm-a",
        "name": "vm-a",
        "subscriptionId": "sub1",
        "properties": {
            "displayName": "Machines should have vulnerability findings resolved",
            "resourceDetails": {
                "ResourceProvider": "Azure",
                "ResourceType": "virtualMachine",
                "Id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            },
            "status": {"code": "Unhealthy", "severity": "High"},
        },
    }


def test_container_image_assessments_are_classified() -> None:
    assert is_container_image_assessment(_image_row("openssl", ["High"], ["CVE-2026-1001"]))
    assert not is_container_image_assessment(_vm_row())


def test_rollup_collapses_packages_into_one_entity_per_image() -> None:
    rows = [
        _image_row("openssl", ["Critical", "Low"], ["CVE-2026-1001", "CVE-2026-1002"]),
        _image_row("pip", ["Medium"], ["CVE-2026-1003"]),
        _image_row("tar", ["High"], ["CVE-2026-1001"]),
    ]

    entities = normalize_container_image_exposure(rows, OBSERVED)

    assert len(entities) == 1
    entity = entities[0]
    assert entity["entityType"] == "ContainerImageExposure"
    assert entity["id"] == IMAGE.casefold()
    assert entity["vulnerablePackageCount"] == 3
    # CVE-2026-1001 appears in two packages but is only counted once.
    assert entity["cveCount"] == 3
    assert entity["severity"] == "Critical"
    assert entity["criticalCount"] == 1
    assert entity["highCount"] == 1
    assert entity["repository"] == "api"
    assert entity["registryHost"] == "acr1.azurecr.io"
    assert entity["imageDigest"] == "sha256:abc123"
    assert entity["imageTags"] == ["v1"]
    assert entity["registryResourceId"] == REGISTRY.casefold()


def test_granular_container_products_preserve_tag_aliases_and_per_cve_evidence() -> None:
    rows = [
        _granular_image_row(
            "openssl",
            ["Critical", "Low"],
            ["CVE-2026-1001", "CVE-2026-1002"],
            tags=["latest", "v1"],
        ),
        _granular_image_row(
            "pip",
            ["Medium"],
            ["CVE-2026-1003"],
            tags=["v1"],
        ),
    ]

    products = normalize_container_image_products(rows, OBSERVED)

    assert len(products.registries) == 1
    assert len(products.logical_images) == 1
    assert len(products.digests) == 1
    assert len(products.vulnerability_observations) == 3
    registry = products.registries[0]
    logical_image = products.logical_images[0]
    digest = products.digests[0]
    assert registry["registryResourceId"] == REGISTRY.casefold()
    assert logical_image["logicalImageId"].startswith("logical-image:v1:")
    assert logical_image["imageTags"] == ["latest", "v1"]
    assert digest["imageDigestId"].startswith("image-digest:v1:")
    assert digest["imageDigest"] == DIGEST_A
    assert digest["logicalImageIds"] == [logical_image["logicalImageId"]]
    assert {
        observation["cveId"]
        for observation in products.vulnerability_observations
    } == {"CVE-2026-1001", "CVE-2026-1002", "CVE-2026-1003"}
    assert all(
        observation["targetKind"] == "container_image"
        and observation["imageDigestId"] == digest["imageDigestId"]
        and observation["providerEventTime"] == OBSERVED
        and observation["sourceEventId"]
        and observation["provenance"]
        for observation in products.vulnerability_observations
    )

    moved = normalize_container_image_products(
        [
            _granular_image_row(
                "openssl",
                ["Critical"],
                ["CVE-2026-1001"],
                tags=["v2"],
            )
        ],
        OBSERVED,
    )
    assert moved.logical_images[0]["logicalImageId"] == logical_image["logicalImageId"]
    assert moved.digests[0]["imageDigestId"] == digest["imageDigestId"]
    matching = next(
        row
        for row in products.vulnerability_observations
        if row["cveId"] == "CVE-2026-1001"
    )
    assert (
        moved.vulnerability_observations[0]["vulnerabilityObservationId"]
        == matching["vulnerabilityObservationId"]
    )
    assert moved.logical_images[0]["imageTags"] == ["v2"]


def test_granular_container_products_reject_conflicting_source_digest_evidence() -> None:
    first = _granular_image_row(
        "openssl",
        ["Critical"],
        ["CVE-2026-1001"],
        digest=DIGEST_A,
    )
    conflicting = _granular_image_row(
        "openssl",
        ["Critical"],
        ["CVE-2026-1001"],
        digest=DIGEST_B,
    )

    with pytest.raises(ValueError, match="conflicting digest"):
        normalize_container_image_products([first, conflicting], OBSERVED)


def test_changed_vulnerability_detail_creates_new_immutable_observation() -> None:
    unknown = _granular_image_row(
        "openssl",
        ["Unknown"],
        ["CVE-2026-1001"],
    )
    enriched = _granular_image_row(
        "openssl",
        ["Medium"],
        ["CVE-2026-1001"],
    )

    products = normalize_container_image_products(
        [unknown, enriched],
        OBSERVED,
    )

    assert len(products.vulnerability_observations) == 2
    assert {
        row["identityVersion"]
        for row in products.vulnerability_observations
    } == {"2"}
    assert len(
        {
            row["vulnerabilityObservationId"]
            for row in products.vulnerability_observations
        }
    ) == 2
    assert {
        row["severity"]
        for row in products.vulnerability_observations
    } == {"Unknown", "Medium"}


def test_healthy_images_are_dropped() -> None:
    row = _image_row("openssl", ["High"], ["CVE-2026-1001"])
    row["properties"]["status"] = {"code": "Healthy"}

    assert normalize_container_image_exposure([row], OBSERVED) == []


def test_malformed_additional_data_does_not_raise() -> None:
    row = _image_row("openssl", ["High"], ["CVE-2026-1001"])
    row["properties"]["resourceAdditionalData"] = "not-json"
    row["properties"]["additionalData"]["CvesDetails"] = "{broken"

    entities = normalize_container_image_exposure([row], OBSERVED)

    assert len(entities) == 1
    assert entities[0]["cveCount"] == 0
    assert entities[0]["repository"] == ""


def test_normalizer_routes_image_rows_away_from_defender_assessments() -> None:
    payload = {
        # Dangling edges are pruned, so the registry must exist as a resource
        # for the exposure -> registry edge to survive.
        "resources": [
            {
                "id": REGISTRY,
                "name": "acr1",
                "type": "Microsoft.ContainerRegistry/registries",
                "location": "australiaeast",
                "subscriptionId": "sub1",
                "resourceGroup": "rg1",
                "tenantId": "tenant1",
            }
        ],
        "defender_assessments": [
            _image_row("openssl", ["Critical"], ["CVE-2026-1001"]),
            _image_row("pip", ["Low"], ["CVE-2026-1002"]),
            _vm_row(),
        ],
    }

    graph = Normalizer().normalize(payload, datetime(2026, 9, 2, tzinfo=UTC))

    # Only the VM finding survives as a per-row assessment.
    assert len(graph.entities["DefenderAssessment"]) == 1
    assert len(graph.entities["ContainerImageExposure"]) == 1

    exposure = graph.entities["ContainerImageExposure"][0]
    edges = [
        edge
        for edge in graph.relationships
        if edge["subjectId"] == exposure["id"] and edge["predicate"] == "impacts"
    ]
    assert len(edges) == 1
    assert edges[0]["objectId"] == REGISTRY.casefold()


def test_normalizer_and_mapper_dual_write_granular_container_products(
    tmp_path: Path,
) -> None:
    from fabric.dataset_mapper import InventoryDatasetMapper
    from fabric.schema_registry import schema_for
    from onboarding.ingestion_storage import DatasetStore

    payload = {
        "resources": [
            {
                "id": REGISTRY,
                "name": "acr1",
                "type": "Microsoft.ContainerRegistry/registries",
                "location": "australiaeast",
                "subscriptionId": "sub1",
                "resourceGroup": "rg1",
                "tenantId": "tenant1",
            }
        ],
        "defender_assessments": [
            _granular_image_row(
                "openssl",
                ["Critical", "Low"],
                ["CVE-2026-1001", "CVE-2026-1002"],
            ),
        ],
    }
    graph = Normalizer(
        {"connection_id": "connection-1"}
    ).normalize(
        payload,
        datetime(2026, 9, 2, tzinfo=UTC),
        run_id="generation-1",
    )

    assert len(graph.entities["ContainerImageExposure"]) == 1
    assert len(graph.entities["LogicalImage"]) == 1
    assert len(graph.entities["ImageDigest"]) == 1
    assert len(graph.entities["VulnerabilityObservation"]) == 2

    store = DatasetStore(tmp_path)
    store.publish(
        graph,
        payload,
        {
            "runId": "generation-1",
            "startedAt": OBSERVED,
            "status": "completed",
        },
    )
    snapshot = store.current_generation()
    assert snapshot is not None
    datasets = InventoryDatasetMapper().load(snapshot, "fabric-run-1")

    registry = datasets["silver_container_registries"][0]
    logical_image = datasets["silver_container_logical_images"][0]
    digest = datasets["silver_container_image_digests"][0]
    observations = datasets["silver_container_vulnerability_observations"]
    assert registry["registry_id"] == logical_image["registry_id"]
    assert logical_image["logical_image_id"] in digest["logical_image_ids"]
    assert {row["cve_id"] for row in observations} == {
        "CVE-2026-1001",
        "CVE-2026-1002",
    }
    assert all(
        row["target_kind"] == "container_image"
        and row["image_digest_id"] == digest["image_digest_id"]
        and row["connection_id"] == "connection-1"
        and json.loads(row["provenance_json"])["source_event_id"]
        for row in observations
    )
    assert datasets["silver_container_image_exposure"], (
        "aggregate dual-write must remain available for rollback"
    )

    expected_fields = {
        "silver_container_registries": {"registry_id", "registry_resource_id"},
        "silver_container_logical_images": {
            "logical_image_id",
            "registry_id",
            "image_tags",
        },
        "silver_container_image_digests": {
            "image_digest_id",
            "image_digest",
            "logical_image_ids",
        },
        "silver_container_vulnerability_observations": {
            "vulnerability_observation_id",
            "image_digest_id",
            "target_kind",
            "cve_id",
            "source_event_id",
            "provider_event_time",
            "provenance_json",
        },
    }
    for table_name, fields in expected_fields.items():
        assert fields <= set(schema_for(table_name).names)

    remapped = InventoryDatasetMapper().load(snapshot, "fabric-run-2")
    assert (
        remapped["silver_container_vulnerability_observations"]
        == observations
    ), "immutable provider observations must not change across Fabric retries"

    approval = schema_for("silver_remediation_approval_policies")
    assert approval.field("role_ids_json").nullable is True


def test_vm_assessment_still_normalizes() -> None:
    entity = normalize_assessment(_vm_row(), OBSERVED)

    assert entity is not None
    assert entity["entityType"] == "DefenderAssessment"
    assert entity["severity"] == "High"


def test_assessment_severity_reads_metadata() -> None:
    """Defender publishes assessment severity under properties.metadata.severity."""

    row = {
        "id": "/subscriptions/s/providers/microsoft.security/assessments/a1",
        "name": "a1",
        "properties": {
            "displayName": "Machines should have vulnerabilities resolved",
            "metadata": {"severity": "Medium"},
            "status": {"code": "Unhealthy"},
            "resourceDetails": {
                "ResourceProvider": "hybridcompute",
                "ResourceType": "machines",
                "Id": "/subscriptions/s/providers/microsoft.hybridcompute/machines/VM1",
            },
        },
    }

    entity = normalize_assessment(row, "2026-09-01T00:00:00Z")

    assert entity is not None
    assert entity["severity"] == "Medium"


def test_assessment_severity_defaults_to_unknown_without_source() -> None:
    row = {
        "id": "/subscriptions/s/providers/microsoft.security/assessments/a2",
        "name": "a2",
        "properties": {
            "status": {"code": "Unhealthy"},
            "resourceDetails": {
                "ResourceProvider": "hybridcompute",
                "ResourceType": "machines",
                "Id": "/subscriptions/s/providers/microsoft.hybridcompute/machines/VM1",
            },
        },
    }

    entity = normalize_assessment(row, "2026-09-01T00:00:00Z")

    assert entity is not None
    assert entity["severity"] == "Unknown"


def test_mapper_flattens_container_image_exposure_entity() -> None:
    from fabric.dataset_mapper import _container_image_exposure_row

    entity = {
        "id": IMAGE,
        "name": "repo/img@sha256:abcdef",
        "entityType": "ContainerImageExposure",
        "targetResourceId": REGISTRY,
        "registryResourceId": REGISTRY,
        "registryHost": "acr1.azurecr.io",
        "repository": "repo/img",
        "imageDigest": "sha256:abc123",
        "imageTags": ["latest"],
        "imageUri": "acr1.azurecr.io/repo/img:latest",
        "lastPushedAt": "2026-08-01T00:00:00Z",
        "status": "Unhealthy",
        "severity": "Critical",
        "criticalCount": 3,
        "highCount": 2,
        "vulnerablePackageCount": 5,
        "cveCount": 8,
        "cveIds": ["CVE-2024-0001"],
        "vulnerablePackages": ["openssl"],
        "recommendation": "Rebuild image",
        "lastAssessedAt": OBSERVED,
        "resourceType": "Microsoft.ContainerRegistry/registries/images",
    }

    row = _container_image_exposure_row(entity, "run-1")

    assert row["entity_type"] == "ContainerImageExposure"
    assert row["target_resource_id"] == REGISTRY.casefold()
    assert row["registry_resource_id"] == REGISTRY.casefold()
    assert row["registry_host"] == "acr1.azurecr.io"
    assert row["repository"] == "repo/img"
    assert row["critical_count"] == 3
    assert row["cve_count"] == 8
    assert row["cve_ids"] == ["CVE-2024-0001"]
    assert row["vulnerable_packages"] == ["openssl"]


def test_service_surfaces_container_image_exposures_and_overview_counts() -> None:
    from api.scope import Scope
    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    rows = [
        {
            "id": "img1",
            "server_id": REGISTRY,
            "target_resource_id": REGISTRY,
            "registry_resource_id": REGISTRY,
            "registry_host": "acr1.azurecr.io",
            "repository": "repo/img",
            "image_digest": "sha256:abc123",
            "image_tags": ["latest"],
            "image_uri": "acr1.azurecr.io/repo/img:latest",
            "last_pushed_at": "2026-08-01T00:00:00Z",
            "status": "Unhealthy",
            "severity": "Critical",
            "critical_count": 3,
            "high_count": 2,
            "vulnerable_package_count": 5,
            "cve_count": 8,
            "cve_ids": ["CVE-2024-0001"],
            "vulnerable_packages": ["openssl"],
            "recommendation": "Rebuild image",
            "last_assessed_at": OBSERVED,
            "subscription_id": "sub1",
        }
    ]

    service = VulnerabilityIntelligenceService.from_rows(container_image_exposures=rows)
    scope = Scope()

    exposures = service.container_image_exposures(scope)
    assert len(exposures) == 1
    assert exposures[0]["repository"] == "repo/img"

    overview = service.defender_overview(scope)
    assert overview["vulnerable_container_image_count"] == 1
    assert overview["container_image_cve_count"] == 8


def _defender_image_row(
    *,
    digest: str = DIGEST_A,
    observed_at: str = OBSERVED,
) -> dict[str, Any]:
    return {
        "id": "defender-subassessment-1",
        "tenantId": "tenant1",
        "subscriptionId": "sub1",
        "properties": {
            "timeGenerated": observed_at,
            "additionalData": {
                "imageDigest": digest,
                "repository": "acr1.azurecr.io/api",
                "tag": "v1",
            },
        },
    }


def _defender_assessment_image_row(
    *,
    digest: str = DIGEST_A,
    provider_event_time: str | None = OBSERVED,
) -> dict[str, Any]:
    status: dict[str, Any] = {"code": "Unhealthy"}
    if provider_event_time is not None:
        status["statusChangeDate"] = provider_event_time
    return {
        "id": "defender-assessment-1",
        "tenantId": "tenant1",
        "subscriptionId": "sub1",
        "properties": {
            "status": status,
            "resourceDetails": {
                "ResourceProvider": "acr",
                "ResourceType": ".containerimage",
                "Id": IMAGE,
            },
            "resourceAdditionalData": {
                "Digest": digest,
                "RepositoryDetails": {
                    "RepositoryName": "api",
                    "RegistryHost": "acr1.azurecr.io",
                },
                "Tags": ["v1"],
            },
        },
    }


def _workload_rows(
    *,
    digest: str = DIGEST_A,
    observed_at: str = OBSERVED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pods = [
        {
            "TimeGenerated": observed_at,
            "ClusterId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks1",
            "Namespace": "payments",
            "ControllerKind": "Deployment",
            "ControllerName": "api",
            "Name": "api-7d9f",
            "PodUid": "pod-1",
            "ContainerID": "containerd://container-1",
            "ContainerName": "api",
        }
    ]
    containers = [
        {
            "TimeGenerated": observed_at,
            "ContainerID": "containerd://container-1",
            "Image": "acr1.azurecr.io/api:v1",
            "ImageID": f"docker-pullable://acr1.azurecr.io/api@{digest}",
            "Repository": "acr1.azurecr.io/api",
            "Name": "api",
        }
    ]
    images = [
        {
            "TimeGenerated": observed_at,
            "ImageID": f"acr1.azurecr.io/api@{digest}",
            "Repository": "acr1.azurecr.io/api",
            "Tag": "v1",
        }
    ]
    return pods, containers, images


def test_container_insights_queries_are_fixed_minimal_and_bounded() -> None:
    from onboarding.monitor_logs import CONTAINER_INSIGHTS_QUERIES

    assert set(CONTAINER_INSIGHTS_QUERIES) == {
        "kube_pod_inventory",
        "container_inventory",
        "container_image_inventory",
    }
    expected_tables = {
        "kube_pod_inventory": "KubePodInventory",
        "container_inventory": "ContainerInventory",
        "container_image_inventory": "ContainerImageInventory",
    }
    for family, query in CONTAINER_INSIGHTS_QUERIES.items():
        assert query.splitlines()[0] == expected_tables[family]
        assert "| where TimeGenerated > ago(15m)" in query
        assert "| project " in query
        assert "| take 25000" in query
        assert "*" not in query

    image_query = CONTAINER_INSIGHTS_QUERIES["container_image_inventory"]
    assert "Tag=ImageTag" in image_query
    assert "Repository, Tag, _SubscriptionId" not in image_query


def test_exact_digest_and_observation_time_produce_one_deployment() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_image_row()],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert len(result.deployments) == 1
    deployment = result.deployments[0]
    assert deployment["image_digest"] == DIGEST_A
    assert deployment["cluster_id"].endswith("/managedClusters/aks1")
    assert deployment["namespace"] == "payments"
    assert deployment["controller_kind"] == "Deployment"
    assert deployment["controller_name"] == "api"
    assert deployment["effective_generation"] == "generation-2"
    assert deployment["repository"] == "acr1.azurecr.io/api"
    assert deployment["tag"] == "v1"
    assert DIGEST_A in deployment["deployment_id"]
    moved_tag_images = [{**images[0], "Tag": "v2"}]
    moved_tag = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_image_row()],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=moved_tag_images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )
    assert moved_tag.deployments[0]["deployment_id"] == deployment["deployment_id"]
    assert moved_tag.deployments[0]["tag"] == "v2"


@pytest.mark.parametrize(
    ("offset_seconds", "expected_match", "expected_reason"),
    [
        (899, True, ""),
        (900, True, ""),
        (901, False, "stale_digest_observation"),
    ],
)
def test_exact_digest_join_fails_closed_at_fifteen_minute_boundary(
    offset_seconds: int,
    expected_match: bool,
    expected_reason: str,
) -> None:
    from intelligence.vulnerability.workload_inventory import (
        match_workload_digest,
    )

    defender_time = datetime.fromisoformat(OBSERVED)
    workload_time = defender_time + timedelta(seconds=offset_seconds)
    result = match_workload_digest(
        defender_digest=DIGEST_A,
        observed_digest=DIGEST_A,
        defender_observed_at=defender_time.isoformat(),
        workload_observed_at=workload_time.isoformat(),
    )

    assert result.matched is expected_match
    assert result.reason == expected_reason


def test_assessment_nested_digest_and_provider_event_time_produce_deployment() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_assessment_image_row()],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert len(result.deployments) == 1
    assert result.deployments[0]["image_digest"] == DIGEST_A
    assert result.deployments[0]["defender_observed_at"] == OBSERVED
    assert result.unknown_reasons == ()


def test_missing_defender_provider_event_time_never_uses_completed_at() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[
            _defender_assessment_image_row(provider_event_time=None)
        ],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert result.deployments == ()
    assert result.unknown_reasons == (
        "missing_defender_provider_event_time",
    )


def test_malformed_defender_provider_event_time_remains_unknown() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[
            _defender_assessment_image_row(provider_event_time="not-a-time")
        ],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert result.deployments == ()
    assert result.unknown_reasons == (
        "malformed_defender_provider_event_time",
    )


def test_missing_workload_provider_event_time_never_uses_completed_at() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    for row in (*pods, *containers, *images):
        row.pop("TimeGenerated")
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_assessment_image_row()],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert result.deployments == ()
    assert result.unknown_reasons == (
        "missing_workload_provider_event_time",
    )


def test_duplicate_defender_rows_produce_one_deployment_identity() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[
            _defender_assessment_image_row(),
            {**_defender_assessment_image_row(), "id": "defender-assessment-2"},
        ],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert len(result.deployments) == 1


def test_unproved_workload_links_remain_typed_unknown() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    cases = [
        (
            _defender_image_row(digest="sha256:not-a-digest"),
            _workload_rows(),
            "malformed_defender_digest",
        ),
        (
            _defender_image_row(),
            _workload_rows(digest=DIGEST_B),
            "no_exact_digest_observation",
        ),
        (
            _defender_image_row(),
            _workload_rows(observed_at="2026-09-02T01:00:00Z"),
            "stale_digest_observation",
        ),
    ]

    for defender, (pods, containers, images), reason in cases:
        result = normalize_workload_evidence(
            connection_id="connection-1",
            workspace_id="workspace-1",
            defender_rows=[defender],
            kube_pod_rows=pods,
            container_rows=containers,
            image_rows=images,
            attempted_generation="generation-2",
            completed_at=OBSERVED,
        )
        assert result.deployments == ()
        assert result.unknown_reasons == (reason,)


def test_fresh_exact_image_wins_over_stale_duplicate_observation() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    stale = {**images[0], "TimeGenerated": "2026-09-01T00:00:00Z"}
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_image_row()],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=[stale, images[0]],
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert len(result.deployments) == 1
    assert result.unknown_reasons == ()


def test_conflicting_runtime_controller_evidence_remains_unknown() -> None:
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )

    pods, containers, images = _workload_rows()
    conflicting = {
        **pods[0],
        "ControllerName": "different-controller",
        "PodUid": "pod-conflict",
    }
    result = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_image_row()],
        kube_pod_rows=[pods[0], conflicting],
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )

    assert result.deployments == ()
    assert result.unknown_reasons == ("conflicting_runtime_evidence",)


def test_workload_schemas_are_additive_and_preserve_approval_role_ids() -> None:
    from fabric.schema_registry import schema_for
    from fabric.sync_service import FabricSyncService

    assert {
        "observation_id",
        "checkpoint_key",
        "checkpoint_key_version",
        "attempted_generation",
        "effective_generation",
    } <= set(schema_for("silver_workload_observations").names)
    assert {
        "deployment_id",
        "image_digest",
        "unknown_reason",
        "lkg_source_generation",
    } <= set(schema_for("silver_workload_deployments").names)
    assert {
        "checkpoint_key",
        "connection_id",
        "workspace_id",
        "source_family",
        "attempted_generation",
        "effective_generation",
        "unknown_reason_counts_json",
    } <= set(schema_for("metadata_workload_source_checkpoints").names)
    approval_field = schema_for("silver_remediation_approval_policies").field(
        "role_ids_json"
    )
    assert approval_field.nullable is True
    assert "silver_container_vulnerability_observations" in (
        FabricSyncService._WORKLOAD_APPEND_WRITE_TABLES
    )
    assert {
        "silver_container_registries",
        "silver_container_logical_images",
        "silver_container_image_digests",
    } <= FabricSyncService._WORKLOAD_MERGE_WRITE_TABLES


@pytest.mark.parametrize(
    ("defender_query_name", "defender_row"),
    [
        ("defender_assessments", _defender_assessment_image_row()),
        ("defender_subassessments", _defender_image_row()),
    ],
)
def test_ingestion_service_persists_the_exact_workload_slice(
    tmp_path: Path,
    defender_query_name: str,
    defender_row: dict[str, Any],
) -> None:
    from onboarding.config import ConnectorConfig
    from onboarding.ingestion_service import IngestionService

    pods, containers, images = _workload_rows()

    class Source:
        def fetch(self, specs, subscription_ids):
            assert subscription_ids == ["sub1"]
            return {
                spec.name: (
                    [
                        {
                            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/law1",
                            "name": "law1",
                            "subscriptionId": "sub1",
                            "resourceGroup": "rg1",
                            "workspaceId": "workspace-1",
                        }
                    ]
                    if spec.name == "inventory_log_analytics_workspaces"
                    else (
                        [defender_row]
                        if spec.name == defender_query_name
                        else []
                    )
                )
                for spec in specs
            }

    class Logs:
        def query_kube_pod_inventory(self, workspace_id):
            assert workspace_id == "workspace-1"
            return pods

        def query_container_inventory(self, workspace_id):
            assert workspace_id == "workspace-1"
            return containers

        def query_container_image_inventory(self, workspace_id):
            assert workspace_id == "workspace-1"
            return images

    service = IngestionService(
        ConnectorConfig(
            output_dir=tmp_path,
            subscriptions=("sub1",),
            tenant_id="tenant1",
            connection_context={"connection_id": "connection-1"},
            cost_management_enabled=False,
        ),
        source=Source(),
        logs_client=Logs(),
        clock=lambda: datetime(2026, 9, 2, tzinfo=UTC),
    )

    manifest = service.run()

    assert manifest["datasets"]["exposure/workload_deployments"]["rowCount"] == 1
    deployments = service.store.read_dataset("exposure/workload_deployments")
    checkpoints = service.store.read_dataset("exposure/workload_source_checkpoints")
    assert deployments[0]["image_digest"] == DIGEST_A
    assert {row["source_family"] for row in checkpoints} == {
        "kube_pod_inventory",
        "container_inventory",
        "container_image_inventory",
    }


def test_granular_container_pipeline_round_trips_and_projects_exact_impact(
    tmp_path: Path,
) -> None:
    from fabric.dataset_mapper import InventoryDatasetMapper
    from fabric_pipelines.vulnerability_pipeline import (
        ContainerExposureFabricWriter,
        project_container_exposure,
    )
    from intelligence.vulnerability.workload_inventory import (
        normalize_workload_evidence,
    )
    from onboarding.ingestion_storage import DatasetStore
    from storage.delta_writer import DeltaWriter

    payload = {
        "resources": [
            {
                "id": REGISTRY,
                "name": "acr1",
                "type": "Microsoft.ContainerRegistry/registries",
                "location": "australiaeast",
                "subscriptionId": "sub1",
                "resourceGroup": "rg1",
                "tenantId": "tenant1",
            }
        ],
        "defender_assessments": [
            _granular_image_row(
                "openssl",
                ["Critical"],
                ["CVE-2026-1001"],
            )
        ],
    }
    graph = Normalizer(
        {"connection_id": "connection-1"}
    ).normalize(
        payload,
        datetime(2026, 9, 2, tzinfo=UTC),
        run_id="generation-2",
    )
    source = tmp_path / "source"
    store = DatasetStore(source)
    store.publish(
        graph,
        payload,
        {
            "runId": "generation-2",
            "startedAt": OBSERVED,
            "status": "completed",
        },
    )
    snapshot = store.current_generation()
    assert snapshot is not None
    datasets = InventoryDatasetMapper().load(snapshot, "fabric-run-2")

    pods, containers, images = _workload_rows()
    workload = normalize_workload_evidence(
        connection_id="connection-1",
        workspace_id="workspace-1",
        defender_rows=[_defender_image_row()],
        kube_pod_rows=pods,
        container_rows=containers,
        image_rows=images,
        attempted_generation="generation-2",
        completed_at=OBSERVED,
    )
    datasets.update(
        {
            "silver_workload_deployments": list(workload.deployments),
            "metadata_workload_source_checkpoints": list(
                workload.checkpoints
            ),
        }
    )
    projection = project_container_exposure(datasets)
    assert len(projection.findings) == 1
    finding = projection.findings[0]
    assert finding["target_kind"] == "container_image"
    assert finding["image_digest"] == DIGEST_A
    assert finding["cve_id"] == "CVE-2026-1001"
    assert finding["deployment_state"] == "observed_exact_digest"
    assert finding["represented_workload_count"] == 1
    assert finding["total_workload_count"] == 1
    assert finding["unknown_workload_count"] == 0
    assert finding["workload_checkpoint_generations"] == ["generation-2"]
    assert finding["server_patch_eligible"] is False
    assert finding["impact_score"] > 0
    assert projection.coverage["represented_workload_count"] == 1
    assert projection.coverage["total_workload_count"] == 1

    writer = ContainerExposureFabricWriter(
        table_root=tmp_path / "Tables",
        delta_writer=DeltaWriter(),
    )
    writer.publish(datasets)
    reread = writer.read_products()
    repeated = writer.publish(reread)
    projected_again = project_container_exposure(reread)
    assert projected_again == projection
    assert all(
        result.rows_added == 0
        and result.rows_changed == 0
        and result.rows_removed == 0
        for result in repeated.values()
    ), {table: result for table, result in repeated.items()}


def test_container_projection_preserves_unknown_coverage_without_inference(
    tmp_path: Path,
) -> None:
    from fabric.dataset_mapper import InventoryDatasetMapper
    from fabric_pipelines.vulnerability_pipeline import (
        project_container_exposure,
    )
    from intelligence.vulnerability.workload_inventory import (
        WorkloadFailureCode,
        WorkloadQueryFailure,
        activate_workload_partitions,
    )
    from onboarding.ingestion_storage import DatasetStore

    payload = {
        "resources": [
            {
                "id": REGISTRY,
                "name": "acr1",
                "type": "Microsoft.ContainerRegistry/registries",
                "subscriptionId": "sub1",
                "resourceGroup": "rg1",
                "tenantId": "tenant1",
            }
        ],
        "defender_assessments": [
            _granular_image_row(
                "openssl",
                ["Critical"],
                ["CVE-2026-1001"],
            )
        ],
    }
    graph = Normalizer(
        {"connection_id": "connection-1"}
    ).normalize(
        payload,
        datetime(2026, 9, 2, tzinfo=UTC),
        run_id="generation-unknown",
    )
    store = DatasetStore(tmp_path / "source")
    store.publish(
        graph,
        payload,
        {
            "runId": "generation-unknown",
            "startedAt": OBSERVED,
            "status": "completed",
        },
    )
    snapshot = store.current_generation()
    assert snapshot is not None
    datasets = InventoryDatasetMapper().load(snapshot, "fabric-unknown")
    outcomes = [
        WorkloadQueryFailure(
            connection_id="connection-1",
            workspace_id="workspace-1",
            subscription_id="sub1",
            source_family=family,
            source_table={
                "kube_pod_inventory": "KubePodInventory",
                "container_inventory": "ContainerInventory",
                "container_image_inventory": "ContainerImageInventory",
            }[family],
            query_version=f"container-insights-{family}-v1",
            attempted_at=OBSERVED,
            completed_at=OBSERVED,
            error_code=WorkloadFailureCode.PROVIDER_TIMEOUT,
            error_summary="Container Insights query timed out.",
        )
        for family in (
            "kube_pod_inventory",
            "container_inventory",
            "container_image_inventory",
        )
    ]
    unknown = activate_workload_partitions(
        outcomes=outcomes,
        defender_rows=[_defender_image_row()],
        attempted_generation="generation-unknown",
        completed_at=OBSERVED,
    )
    datasets.update(
        {
            "silver_workload_deployments": list(unknown.deployments),
            "metadata_workload_source_checkpoints": list(
                unknown.checkpoints
            ),
        }
    )

    projection = project_container_exposure(datasets)

    assert projection.findings[0]["deployment_state"] == "unknown"
    assert projection.findings[0]["represented_workload_count"] == 0
    assert projection.findings[0]["total_workload_count"] == 1
    assert projection.findings[0]["unknown_workload_count"] == 1
    assert projection.findings[0]["unknown_reason_counts"] == {
        "source_unavailable": 1
    }
    assert projection.findings[0]["workload_ids"] == []
    assert projection.findings[0]["business_service_ids"] == []
    assert projection.findings[0]["server_patch_eligible"] is False
    assert projection.coverage == {
        "represented_workload_count": 0,
        "total_workload_count": 1,
        "unknown_workload_count": 1,
        "unknown_reason_counts": {"source_unavailable": 1},
    }
