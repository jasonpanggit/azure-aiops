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
