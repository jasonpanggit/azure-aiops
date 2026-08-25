from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class QuerySpec:
    name: str
    table: str
    query: str
    incremental: bool
    scope: str = "subscriptions"
    version: str = "1.0.0"


class QueryCatalog:
    """Versioned ARG queries for the first operational-context slice."""

    def __init__(self, overlap_minutes: int = 10) -> None:
        self.overlap = timedelta(minutes=overlap_minutes)

    def build(
        self, since: datetime | None, *, include_management_groups: bool = False
    ) -> list[QuerySpec]:
        if since is None:
            change_filter = "properties.changeAttributes.timestamp >= ago(7d)"
        else:
            lower_bound = since.astimezone(UTC) - self.overlap
            stamp = lower_bound.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            change_filter = f"properties.changeAttributes.timestamp > datetime({stamp})"

        projection = (
            "project id, name, type, tenantId, subscriptionId, resourceGroup, "
            "location, tags, properties"
        )
        specs = [
            QuerySpec("resources", "Resources", f"Resources | {projection}", False),
            QuerySpec(
                "resource_containers",
                "ResourceContainers",
                "ResourceContainers "
                "| where type in~ ('microsoft.resources/subscriptions', "
                "'microsoft.resources/subscriptions/resourcegroups') "
                f"| {projection}",
                False,
            ),

            QuerySpec(
                "resource_changes",
                "ResourceChanges",
                f"resourcechanges | where {change_filter} | {projection}",
                True,
            ),
            QuerySpec(
                "monitor",
                "InsightsMetrics",
                "InsightsMetrics | project id, name, type, subscriptionId, resourceId, "
                "timestamp, properties",
                False,
            ),
            QuerySpec(
                "service_health",
                "HealthResources",
                "HealthResources | project id, name, type, subscriptionId, properties",
                False,
            ),
            QuerySpec(
                "defender",
                "SecurityResources",
                "SecurityResources | where type startswith 'microsoft.security/' "
                "| project id, name, type, subscriptionId, resourceId, properties",
                False,
            ),
            QuerySpec(
                "policy",
                "PolicyResources",
                "PolicyResources | project id, name, type, subscriptionId, resourceId, properties",
                False,
            ),
            QuerySpec(
                "vulnerability",
                "SecurityResources",
                "SecurityResources | where type contains 'vulnerability' "
                "| project id, name, type, subscriptionId, resourceId, properties",
                False,
            ),
            QuerySpec(
                "patch_assessments",
                "PatchAssessmentResources",
                "patchassessmentresources "
                "| where type !endswith '/softwarepatches' "
                f"| {projection}",
                False,
            ),
            QuerySpec(
                "patch_assessment_details",
                "PatchAssessmentResources",
                "patchassessmentresources "
                "| where type endswith '/softwarepatches' "
                f"| {projection}",
                False,
            ),
            QuerySpec(
                "patch_installations",
                "PatchInstallationResources",
                "patchinstallationresources "
                "| where type endswith '/softwarepatches' "
                f"| {projection}",
                False,
            ),
            QuerySpec(
                "advisor_recommendations",
                "AdvisorRecommendations",
                "advisorresources "
                "| where type =~ 'microsoft.advisor/recommendations' "
                f"| {projection}",
                False,
            ),
            *_inventory_specs(),
            *_network_specs(projection),
        ]
        if include_management_groups:
            specs.insert(
                2,
                QuerySpec(
                    "management_groups",
                    "ResourceContainers",
                    "ResourceContainers "
                    "| where type =~ 'microsoft.management/managementgroups' "
                    f"| {projection}",
                    False,
                    "management_groups",
                ),
            )
        return specs


def _inventory_specs() -> list[QuerySpec]:
        """Independent, fixed ARG queries for the machine OS inventory.

        Native VMs and Arc machines intentionally have separate specs.  Apart from
        making source failures attributable, this prevents the native image SKU
        from being mistaken for an installed OS release on either source.
        """
        return [
            QuerySpec(
                "inventory_native_vm_os",
                "Resources",
                (
                    "Resources "
                    "| where type =~ 'microsoft.compute/virtualmachines' "
                    "| project id, name, type, subscriptionId, resourceGroup, location, tags, "
                    "osType=tostring(properties.storageProfile.osDisk.osType), "
                    "imagePublisher=tostring(properties.storageProfile.imageReference.publisher), "
                    "imageOffer=tostring(properties.storageProfile.imageReference.offer), "
                    "imageSku=tostring(properties.storageProfile.imageReference.sku), "
                    "imageVersion=tostring(properties.storageProfile.imageReference.version) "
                    "| order by id asc"
                ),
                False,
                version="inventory-native-vm-os-v1",
            ),
            QuerySpec(
                "inventory_arc_os",
                "Resources",
                (
                    "Resources "
                    "| where type =~ 'microsoft.hybridcompute/machines' "
                    "| project id, name, type, subscriptionId, resourceGroup, location, tags, "
                    "computerName=tostring(properties.osProfile.computerName), "
                    "osName=tostring(properties.osName), "
                    "osVersion=tostring(properties.osVersion), "
                    "osSku=tostring(properties.osSku), "
                    "status=tostring(properties.status) "
                    "| order by id asc"
                ),
                False,
                version="inventory-arc-os-v1",
            ),
        ]


#: ARM resource types fetched for network topology, grouped by payload key.
#: Each key becomes a ``NormalizedGraph`` entity family in ``normalize.py``.
NETWORK_RESOURCE_TYPES: dict[str, tuple[str, ...]] = {
    "network_vnets": ("microsoft.network/virtualnetworks",),
    "network_security_groups": ("microsoft.network/networksecuritygroups",),
    "network_route_tables": ("microsoft.network/routetables",),
    "network_interfaces": ("microsoft.network/networkinterfaces",),
    "network_firewalls": ("microsoft.network/azurefirewalls",),
    "network_firewall_policies": (
        "microsoft.network/firewallpolicies",
        "microsoft.network/firewallpolicies/rulecollectiongroups",
    ),
    "network_private_endpoints": ("microsoft.network/privateendpoints",),
    "network_private_dns_zones": (
        "microsoft.network/privatednszones",
        "microsoft.network/privatednszones/virtualnetworklinks",
    ),
    "network_gateways": (
        "microsoft.network/virtualnetworkgateways",
        "microsoft.network/expressroutegateways",
        "microsoft.network/expressroutecircuits",
        "microsoft.network/natgateways",
        "microsoft.network/bastionhosts",
        "microsoft.network/dnsresolvers",
        "microsoft.network/vpngateways",
    ),
    "network_load_balancers": (
        "microsoft.network/loadbalancers",
        "microsoft.network/applicationgateways",
    ),
}


def _network_specs(projection: str) -> list[QuerySpec]:
    """One ARG query per network family.

    Split by family rather than issued as a single broad query so that a
    failure or throttle on one resource type does not blank the entire
    topology — a partially observed estate is reported as partial, never as
    an estate with no firewall.
    """
    specs: list[QuerySpec] = []
    for name, resource_types in NETWORK_RESOURCE_TYPES.items():
        types = ", ".join(f"'{value}'" for value in resource_types)
        specs.append(
            QuerySpec(
                name,
                "Resources",
                f"Resources | where type in~ ({types}) | {projection}",
                False,
            )
        )
    return specs
