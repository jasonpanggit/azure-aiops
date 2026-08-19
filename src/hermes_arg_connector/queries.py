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
                "patch_assessments",
                "PatchAssessmentResources",
                "patchassessmentresources "
                "| where type !endswith '/softwarepatches' "
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
