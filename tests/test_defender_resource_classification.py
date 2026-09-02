"""Guards against substring-based misclassification of Defender resources."""

from __future__ import annotations

import pytest

from intelligence.vulnerability.service import _defender_plan, _inventory_kind


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "kind", "plan"),
    [
        # "searchservices" contains the substring "arc" and previously produced
        # "Arc-enabled server" / "Defender for Servers".
        (
            "microsoft.search/searchservices",
            "/subscriptions/s/providers/microsoft.search/searchservices/aiops-dev-search",
            "Azure resource",
            "Defender CSPM",
        ),
        (
            "microsoft.hybridcompute/machines",
            "/subscriptions/s/providers/microsoft.hybridcompute/machines/VM1",
            "Arc-enabled server",
            "Defender for Servers",
        ),
        (
            "microsoft.compute/virtualmachines",
            "/subscriptions/s/providers/microsoft.compute/virtualmachines/vm2",
            "Azure VM",
            "Defender for Servers",
        ),
        (
            "microsoft.containerregistry/registries",
            "/subscriptions/s/providers/microsoft.containerregistry/registries/acr1",
            "Container registry",
            "Defender for Containers",
        ),
        (
            "microsoft.containerservice/managedclusters",
            "/subscriptions/s/providers/microsoft.containerservice/managedclusters/aks1",
            "AKS node",
            "Defender for Containers",
        ),
        (
            "microsoft.storage/storageaccounts",
            "/subscriptions/s/providers/microsoft.storage/storageaccounts/sa",
            "Storage",
            "Defender for Storage",
        ),
    ],
)
def test_classification_uses_resource_type(
    resource_type: str, resource_id: str, kind: str, plan: str
) -> None:
    assert _inventory_kind(resource_type, resource_id) == kind
    assert _defender_plan(resource_type, resource_id) == plan


@pytest.mark.parametrize(
    ("resource_id", "kind"),
    [
        (
            "/subscriptions/s/resourcegroups/g/providers/microsoft.search/searchservices/aiops-dev-search",
            "Azure resource",
        ),
        (
            "/subscriptions/s/providers/microsoft.hybridcompute/machines/VM1",
            "Arc-enabled server",
        ),
    ],
)
def test_classification_falls_back_to_resource_id(resource_id: str, kind: str) -> None:
    """An empty resource type recovers the provider/type from the ARM id."""

    assert _inventory_kind("", resource_id) == kind
