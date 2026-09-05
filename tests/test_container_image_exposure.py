from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from onboarding.defender_normalize import (
    is_container_image_assessment,
    normalize_assessment,
    normalize_container_image_exposure,
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


def test_workload_schemas_are_additive_and_preserve_approval_role_ids() -> None:
    from fabric.schema_registry import schema_for

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


def test_ingestion_service_persists_the_exact_workload_slice(tmp_path) -> None:
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
                        [_defender_image_row()]
                        if spec.name == "defender_subassessments"
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
