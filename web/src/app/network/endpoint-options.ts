import type {
  NetworkTopology,
  NetworkTopologyResource,
} from "@/lib/types";

/** Sentinel value used by endpoint selectors to reveal free-text entry. */
export const MANUAL_ENDPOINT_VALUE = "__enter_manually__";

/** One canonical endpoint value and its operator-facing disambiguated label. */
export interface NetworkEndpointOption {
  label: string;
  value: string;
}

const DIRECT_ENDPOINT_TYPES = new Set(["NetworkInterface", "Subnet"]);

function resourceTypeLabel(entityType: string): string {
  return entityType
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
}

function endpointResourceIds(topology: NetworkTopology): Set<string> {
  const resourcesById = new Map(
    (topology.resources ?? []).map((resource) => [
      resource.id.toLowerCase(),
      resource,
    ]),
  );
  const endpointIds = new Set(
    Array.from(resourcesById.values())
      .filter((resource) => DIRECT_ENDPOINT_TYPES.has(resource.entity_type))
      .map((resource) => resource.id.toLowerCase()),
  );

  for (const relationship of topology.relationships ?? []) {
    const source = resourcesById.get(relationship.source.toLowerCase());
    if (
      relationship.relationship_type === "attached_to" &&
      source?.entity_type === "NetworkInterface"
    ) {
      endpointIds.add(relationship.target.toLowerCase());
    }
  }

  return endpointIds;
}

function duplicateContext(resource: NetworkTopologyResource): string {
  const segments = resource.id.split("/").filter(Boolean);
  const vnetIndex = segments.findIndex(
    (segment) => segment.toLowerCase() === "virtualnetworks",
  );
  const parentVnet =
    vnetIndex >= 0 && vnetIndex + 1 < segments.length
      ? segments[vnetIndex + 1]
      : "";
  const context = [
    resource.subscription_id,
    resource.resource_group,
    parentVnet,
  ].filter(Boolean);
  return context.length > 0 ? context.join(" / ") : resource.id;
}

/**
 * Builds stable, resolver-safe flow endpoint options from a scoped topology.
 *
 * Subnets and network interfaces resolve directly. Workloads are included only
 * when an observed NIC attachment proves that the flow resolver accepts the
 * workload ARM ID.
 */
export function buildNetworkEndpointOptions(
  topology: NetworkTopology | null,
): NetworkEndpointOption[] {
  if (!topology) return [];

  const endpointIds = endpointResourceIds(topology);
  const resources = (topology.resources ?? []).filter((resource) =>
    endpointIds.has(resource.id.toLowerCase()),
  );
  const baseLabels = new Map<string, number>();

  for (const resource of resources) {
    const baseLabel = `${resource.name} — ${resourceTypeLabel(resource.entity_type)}`;
    const key = baseLabel.toLowerCase();
    baseLabels.set(key, (baseLabels.get(key) ?? 0) + 1);
  }

  const candidateOptions = resources
    .flatMap((resource) => {
      const valueKey = resource.id.toLowerCase();
      if (!resource.id) return [];
      const baseLabel = `${resource.name} — ${resourceTypeLabel(resource.entity_type)}`;
      const label =
        (baseLabels.get(baseLabel.toLowerCase()) ?? 0) > 1
          ? `${baseLabel} · ${duplicateContext(resource)}`
          : baseLabel;
      return [{ label, value: resource.id, valueKey }];
    })
    .filter(
      (option, index, allOptions) =>
        allOptions.findIndex(
          (candidate) => candidate.valueKey === option.valueKey,
        ) === index,
    );
  const candidateLabelCounts = new Map<string, number>();
  for (const option of candidateOptions) {
    const key = option.label.toLowerCase();
    candidateLabelCounts.set(key, (candidateLabelCounts.get(key) ?? 0) + 1);
  }

  return candidateOptions
    .map(({ label, value }) => ({
      label:
        (candidateLabelCounts.get(label.toLowerCase()) ?? 0) > 1
          ? `${label} · ${value}`
          : label,
      value,
    }))
    .sort(
      (left, right) =>
        left.label.localeCompare(right.label) ||
        left.value.localeCompare(right.value),
    );
}
