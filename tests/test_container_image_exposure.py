from __future__ import annotations

import json
from datetime import UTC, datetime

from onboarding.defender_normalize import (
    is_container_image_assessment,
    normalize_assessment,
    normalize_container_image_exposure,
)
from onboarding.graph_normalize import Normalizer

OBSERVED = "2026-09-02T00:00:00Z"
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
