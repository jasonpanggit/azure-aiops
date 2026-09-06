from __future__ import annotations

from datetime import UTC, datetime, timedelta

from onboarding.query_contract import QuerySpec


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
                "defender_assessments",
                "SecurityResources",
                "SecurityResources "
                "| where type =~ 'microsoft.security/assessments' "
                # NOTE: microsoft.security/assessments has no top-level
                # `resourceId` column in Resource Graph -- projecting it makes
                # the whole query fail with Operator_FailedToResolveEntity,
                # which silently starved this dataset. The equivalent value
                # lives at properties.resourceDetails.Id and is extracted by
                # onboarding.defender_normalize._target_resource_id.
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, "
                "location, properties",
                False,
                source_family="defender_recommendation",
                semantic_families=("defender_recommendation", "defender_image"),
            ),
            QuerySpec(
                "defender_subassessments",
                "SecurityResources",
                "SecurityResources "
                "| where type =~ 'microsoft.security/assessments/subassessments' "
                # Same missing-column issue as defender_assessments above.
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, "
                "location, properties",
                False,
                source_family="defender_subassessment",
                semantic_families=("defender_subassessment", "defender_image"),
            ),
            QuerySpec(
                "defender_alerts",
                "SecurityResources",
                "SecurityResources "
                "| where type =~ 'microsoft.security/locations/alerts' "
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, location, properties",
                False,
                source_family="defender_alert",
            ),
            QuerySpec(
                "defender_attack_paths",
                "SecurityResources",
                "SecurityResources "
                "| where type =~ 'microsoft.security/attackpaths' "
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, location, properties",
                False,
                source_family="defender_attack_path",
            ),
            QuerySpec(
                "defender_secure_scores",
                "SecurityResources",
                "SecurityResources "
                "| where type =~ 'microsoft.security/securescores' "
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, location, properties",
                False,
                source_family="defender_posture",
            ),
            QuerySpec(
                "defender_secure_score_controls",
                "SecurityResources",
                "SecurityResources "
                "| where type =~ 'microsoft.security/securescores/securescorecontrols' "
                "| project id, name, type, tenantId, subscriptionId, resourceGroup, location, properties",
                False,
                source_family="defender_posture",
            ),
            QuerySpec(
                "patch_assessments",
                "PatchAssessmentResources",
                "patchassessmentresources "
                "| where type !endswith '/softwarepatches' "
                f"| {projection}",
                False,
                source_family="azure_update_manager_assessment",
            ),
            QuerySpec(
                "patch_assessment_details",
                "PatchAssessmentResources",
                "patchassessmentresources "
                "| where type endswith '/softwarepatches' "
                f"| {projection}",
                False,
                source_family="azure_update_manager_missing",
            ),
            QuerySpec(
                "patch_installations",
                "PatchInstallationResources",
                "patchinstallationresources "
                "| where type endswith '/softwarepatches' "
                f"| {projection}",
                False,
                source_family="azure_update_manager_installation",
            ),
            QuerySpec(
                "advisor_recommendations",
                "AdvisorRecommendations",
                "advisorresources "
                "| where type =~ 'microsoft.advisor/recommendations' "
                f"| {projection}",
                False,
            ),
            *_identity_specs(projection),
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
    "network_private_endpoints": (
        "microsoft.network/privateendpoints",
        "microsoft.network/privateendpoints/privatednszonegroups",
    ),
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


def _identity_specs(projection: str) -> list[QuerySpec]:
    """Role assignments, definitions, and managed identities.

    These come from the ``authorizationresources`` and ``Resources`` tables,
    which the same Reader-scoped service principal can already read -- no
    extra Graph API permission is required, so identity governance works for
    exactly the subscriptions a connection is onboarded for and no others.

    Split per family for the same reason as the network specs: a throttle on
    one table must not blank the whole identity picture. An estate with an
    unreadable role-assignment table is reported as partial, never as an
    estate with no privileged access.
    """
    return [
        QuerySpec(
            "role_assignments",
            "AuthorizationResources",
            "authorizationresources "
            "| where type =~ 'microsoft.authorization/roleassignments' "
            f"| {projection}",
            False,
        ),
        QuerySpec(
            "role_definitions",
            "AuthorizationResources",
            "authorizationresources "
            "| where type =~ 'microsoft.authorization/roledefinitions' "
            f"| {projection}",
            False,
        ),
        QuerySpec(
            "managed_identities",
            "Resources",
            "Resources "
            "| where type =~ 'microsoft.managedidentity/userassignedidentities' "
            f"| {projection}",
            False,
        ),
    ]


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
