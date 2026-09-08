import type {
  HubClassification,
  NetworkTopology,
  NetworkTopologyRelationship,
  NetworkTopologyResource,
  PeeringLink,
  SharedServiceSummary,
} from "@/lib/types";

/** Node roles rendered on the topology canvas. */
export type TopologyNodeKind = "hub" | "spoke" | "isolated" | "unresolved" | "service" | "resource" | "workload";

/** Peering health as rendered on an edge, distinct from raw boolean flags. */
export type TopologyEdgeKind = "healthy" | "unhealthy" | "unresolved" | "service" | "relationship";

export interface TopologyNodeData {
  id: string;
  label: string;
  kind: TopologyNodeKind;
  /** Compound parent id (a subscription group), omitted for ungrouped nodes. */
  parent?: string;
  icon: string;
  subscriptionId: string;
  peerCount: number;
  score: number;
  signals: string[];
  serviceKind?: string;
  entityType?: string;
  resourceGroup?: string;
  location?: string;
  environment?: string;
  businessService?: string;
  application?: string;
  owner?: string;
  tags?: Record<string, string>;
  details?: Record<string, unknown>;
  connectionId?: string;
  consumerCount?: number;
  /** True when the node was ingested; false for peers in un-onboarded subscriptions. */
  observed: boolean;
  peerResolution?: "not_ingested" | "excluded_by_scope" | "observed" | "unknown";
}

export interface TopologyEdgeData {
  id: string;
  source: string;
  target: string;
  kind: TopologyEdgeKind;
  label: string;
  bidirectional: boolean;
  crossSubscription: boolean;
  allowForwardedTraffic: boolean;
  allowGatewayTransit: boolean;
  useRemoteGateways: boolean;
  localState: string;
  remoteState: string;
  relationshipType?: string;
  details?: Record<string, unknown>;
  peerResolution?: "not_ingested" | "excluded_by_scope" | "observed" | "unknown";
}

export interface TopologyGroupData {
  id: string;
  label: string;
  kind: "subscription";
}

export interface TopologyGraph {
  groups: TopologyGroupData[];
  nodes: TopologyNodeData[];
  edges: TopologyEdgeData[];
  hiddenUnattachedPrivateLinkCount: number;
}

export interface TopologyGraphOptions {
  showUnattachedPrivateLinkCandidates?: boolean;
}

/**
 * Official Azure architecture icons, served unmodified from `public/azure-icons`.
 * Microsoft's icon terms permit use in architecture diagrams such as this canvas,
 * and forbid alteration, so these files must never be recoloured or reshaped.
 */
export const SERVICE_ICONS: Record<string, string> = {
  firewall: "firewall",
  vpn: "vpn-gateway",
  expressroute: "expressroute",
  bastion: "bastion",
  dns: "dns",
  private_dns: "private-dns",
  egress: "nat-gateway",
};

export const RESOURCE_ICONS: Record<string, string> = {
  ApplicationGateway: "application-gateway",
  AzureFirewall: "firewall",
  Bastion: "bastion",
  DnsResolver: "dns",
  ExpressRouteGateway: "expressroute",
  FirewallPolicy: "firewall-policy",
  FirewallRule: "firewall-rule",
  FirewallRuleCollection: "firewall-rule",
  LoadBalancer: "load-balancer",
  NatGateway: "nat-gateway",
  NetworkInterface: "network-interface",
  NetworkSecurityGroup: "network-security-group",
  NetworkSecurityRule: "network-security-group",
  PrivateDnsZone: "private-dns",
  PrivateEndpoint: "private-endpoint",
  Route: "route-table",
  RouteTable: "route-table",
  SharedService: "virtual-network",
  Subnet: "subnet",
  VNet: "virtual-network",
  VNetPeering: "peering",
  VpnGateway: "vpn-gateway",
  // Workloads reached through the network. They are not network resources, but
  // a private endpoint is meaningless without the service on the other side.
  AppService: "app-service",
  AIFoundryAccount: "ai-services",
  ContainerAppEnvironment: "container-app",
  ContainerRegistry: "container-registry",
  CosmosDb: "cosmos-db",
  KeyVault: "key-vault",
  PostgreSqlServer: "postgresql",
  SqlServer: "sql-server",
  StorageAccount: "storage-account",
  VirtualMachine: "virtual-machine",
  VirtualMachineScaleSet: "vm-scale-set",
};

const ICON_BASE = "/azure-icons";

/** Entity types that sit outside the network but are reached through it. */
const WORKLOAD_ENTITY_TYPES = new Set([
  "AppService",
  "AttachedWorkload",
  "ContainerAppEnvironment",
  "ContainerRegistry",
  "CosmosDb",
  "KeyVault",
  "PostgreSqlServer",
  "PrivateLinkResource",
  "SqlServer",
  "StorageAccount",
  "VirtualMachine",
  "VirtualMachineScaleSet",
  "AIFoundryAccount",
  "FabricCapacity",
]);

/** Resolves the icon path for a shared service kind, falling back to a VNet glyph. */
export function serviceIcon(serviceKind: string): string {
  return `${ICON_BASE}/${SERVICE_ICONS[serviceKind] ?? "virtual-network"}.svg`;
}

export const VNET_ICON = `${ICON_BASE}/virtual-network.svg`;

const UNGROUPED = "subscription:unknown";

function groupId(subscriptionId: string): string {
  return subscriptionId ? `subscription:${subscriptionId}` : UNGROUPED;
}

/** Extracts the subscription GUID from an ARM resource id, or "" when absent. */
export function subscriptionOf(resourceId: string): string {
  const match = /\/subscriptions\/([^/]+)/i.exec(resourceId);
  return match ? match[1] : "";
}

/** Last path segment of an ARM id, used as a display name when none is known. */
export function shortName(resourceId: string): string {
  // Shared services carry a synthetic `/sharedservice` suffix from the topology
  // builder; it is an internal id detail and must never surface as a name.
  const trimmed = resourceId.replace(/\/sharedservice$/i, "");
  const segments = trimmed.split("/").filter(Boolean);
  return segments.at(-1) ?? trimmed;
}

function vnetNode(vnet: HubClassification, kind: TopologyNodeKind): TopologyNodeData {
  return {
    id: vnet.vnet_id,
    label: vnet.name || shortName(vnet.vnet_id),
    kind,
    parent: groupId(vnet.subscription_id),
    icon: VNET_ICON,
    subscriptionId: vnet.subscription_id,
    peerCount: vnet.peer_count,
    score: vnet.score,
    signals: vnet.signals ?? [],
    connectionId: vnet.connection_id,
    observed: true,
  };
}

function resourceIcon(resource: NetworkTopologyResource): string {
  const serviceKind = typeof resource.details?.service_kind === "string" ? resource.details.service_kind : "";
  if (resource.entity_type === "SharedService" && serviceKind) return serviceIcon(serviceKind);
  // Workloads reached through the network (a VM behind a NIC, a PaaS service
  // behind a private endpoint) have no network glyph. They are drawn without an
  // icon rather than borrowing an unrelated one that would misrepresent them.
  const icon = RESOURCE_ICONS[resource.entity_type];
  if (!icon) return "";
  return `${ICON_BASE}/${icon}.svg`;
}

function resourceKind(resource: NetworkTopologyResource): TopologyNodeKind {
  if (resource.entity_type === "VNet") {
    if (resource.role === "hub" || resource.role === "spoke" || resource.role === "isolated") return resource.role;
  }
  if (resource.entity_type === "SharedService") return "service";
  if (WORKLOAD_ENTITY_TYPES.has(resource.entity_type)) return "workload";
  return "resource";
}

function resourceNode(resource: NetworkTopologyResource): TopologyNodeData {
  return {
    id: resource.id,
    label: resource.name || shortName(resource.id),
    kind: resourceKind(resource),
    parent: groupId(resource.subscription_id),
    icon: resourceIcon(resource),
    subscriptionId: resource.subscription_id,
    peerCount: Number(resource.details?.peer_count ?? 0),
    score: Number(resource.details?.score ?? 0),
    signals: Array.isArray(resource.details?.signals) ? resource.details.signals.map(String) : [],
    serviceKind: typeof resource.details?.service_kind === "string" ? resource.details.service_kind : undefined,
    entityType: resource.entity_type,
    resourceGroup: resource.resource_group,
    location: resource.location,
    environment: resource.environment,
    businessService: resource.business_service,
    application: resource.application,
    owner: resource.owner,
    tags: resource.tags,
    details: resource.details,
    connectionId: resource.connection_id,
    consumerCount: Array.isArray(resource.details?.consumer_vnet_ids) ? resource.details.consumer_vnet_ids.length : undefined,
    observed: true,
  };
}

function serviceNode(service: SharedServiceSummary): TopologyNodeData {
  return {
    id: service.resource_id,
    label: service.name || shortName(service.resource_id),
    kind: "service",
    parent: groupId(service.subscription_id),
    icon: serviceIcon(service.service_kind),
    subscriptionId: service.subscription_id,
    peerCount: 0,
    score: 0,
    signals: [],
    serviceKind: service.service_kind,
    connectionId: service.connection_id,
    consumerCount: service.consumer_vnet_ids.length,
    observed: true,
  };
}

function unresolvedNode(
  vnetId: string,
  peerResolution: TopologyNodeData["peerResolution"] = "unknown",
): TopologyNodeData {
  const subscriptionId = subscriptionOf(vnetId);
  return {
    id: vnetId,
    label: shortName(vnetId),
    kind: "unresolved",
    parent: subscriptionId ? groupId(subscriptionId) : undefined,
    icon: VNET_ICON,
    subscriptionId,
    peerCount: 0,
    score: 0,
    signals: [],
    observed: false,
    peerResolution,
  };
}

function peerResolutionByFoldedId(
  topology: NetworkTopology,
): Map<string, NonNullable<TopologyNodeData["peerResolution"]>> {
  return new Map(
    (topology.unresolved_peers ?? []).map((peer) => [
      peer.vnet_id.toLowerCase(),
      peer.peer_resolution,
    ]),
  );
}

function edgeKind(link: PeeringLink): TopologyEdgeKind {
  if (!link.remote_vnet_observed) return "unresolved";
  return link.is_healthy ? "healthy" : "unhealthy";
}

function edgeLabel(link: PeeringLink): string {
  const parts: string[] = [];
  if (link.is_cross_subscription) parts.push("cross-sub");
  if (link.allow_gateway_transit) parts.push("gateway transit");
  if (!link.is_bidirectional) parts.push("one-way");
  return parts.join(" · ");
}

function relationshipEdge(relationship: NetworkTopologyRelationship): TopologyEdgeData {
  return {
    id: relationship.id,
    source: relationship.source,
    target: relationship.target,
    kind: "relationship",
    label: relationship.label,
    bidirectional: false,
    crossSubscription: subscriptionOf(relationship.source) !== subscriptionOf(relationship.target),
    allowForwardedTraffic: false,
    allowGatewayTransit: false,
    useRemoteGateways: false,
    localState: "",
    remoteState: "",
    relationshipType: relationship.relationship_type,
    details: relationship.details,
  };
}

function indexNodesByFoldedId(nodes: Map<string, TopologyNodeData>): Map<string, string> {
  const byFoldedId = new Map<string, string>();
  nodes.forEach((_node, id) => byFoldedId.set(id.toLowerCase(), id));
  return byFoldedId;
}

function resolveNodeId(byFoldedId: Map<string, string>, id: string): string | undefined {
  return byFoldedId.get(id.toLowerCase());
}

/**
 * Projects an observed network topology into Cytoscape-ready nodes and edges.
 *
 * Every VNet referenced by a peering is materialised, including peers that were
 * never ingested — those become explicit `unresolved` nodes so the canvas shows a
 * known unknown rather than silently dropping the relationship. Peerings are
 * de-duplicated on the unordered VNet pair so a bidirectional link draws once.
 */
export function buildTopologyGraph(
  topology: NetworkTopology,
  options: TopologyGraphOptions = {},
): TopologyGraph {
  if (topology.resources?.length) {
    return buildResourceTopologyGraph(topology, options);
  }

  const nodes = new Map<string, TopologyNodeData>();
  const resolutions = peerResolutionByFoldedId(topology);

  for (const vnet of topology.hubs) nodes.set(vnet.vnet_id, vnetNode(vnet, "hub"));
  for (const vnet of topology.spokes) nodes.set(vnet.vnet_id, vnetNode(vnet, "spoke"));
  for (const vnet of topology.isolated) nodes.set(vnet.vnet_id, vnetNode(vnet, "isolated"));
  const nodeIds = indexNodesByFoldedId(nodes);
  const unresolvedIds = [
    ...topology.unresolved_peer_vnet_ids,
    ...(topology.unresolved_peers ?? []).map((peer) => peer.vnet_id),
  ];
  for (const id of unresolvedIds) {
    if (resolveNodeId(nodeIds, id)) continue;
    nodes.set(id, unresolvedNode(id, resolutions.get(id.toLowerCase()) ?? "unknown"));
    nodeIds.set(id.toLowerCase(), id);
  }
  for (const service of topology.shared_services) {
    nodes.set(service.resource_id, serviceNode(service));
    nodeIds.set(service.resource_id.toLowerCase(), service.resource_id);
  }

  const edges = new Map<string, TopologyEdgeData>();
  for (const link of topology.links) {
    const localVnetId = resolveNodeId(nodeIds, link.local_vnet_id);
    if (!localVnetId) continue;
    let remoteVnetId = resolveNodeId(nodeIds, link.remote_vnet_id);
    if (!remoteVnetId) {
      remoteVnetId = link.remote_vnet_id;
      nodes.set(
        remoteVnetId,
        unresolvedNode(
          remoteVnetId,
          resolutions.get(remoteVnetId.toLowerCase()) ?? "unknown",
        ),
      );
      nodeIds.set(remoteVnetId.toLowerCase(), remoteVnetId);
    }
    const pair = [localVnetId, remoteVnetId].sort();
    const id = `peering:${pair[0]}::${pair[1]}`;
    const existing = edges.get(id);
    // A pair observed from both directions is one link; keep the worse verdict.
    if (existing && existing.kind !== "healthy") continue;
    edges.set(id, {
      id,
      source: pair[0],
      target: pair[1],
      kind: edgeKind(link),
      label: edgeLabel(link),
      bidirectional: link.is_bidirectional,
      crossSubscription: link.is_cross_subscription,
      allowForwardedTraffic: link.allow_forwarded_traffic,
      allowGatewayTransit: link.allow_gateway_transit,
      useRemoteGateways: link.use_remote_gateways,
      localState: link.local_state,
      remoteState: link.remote_state,
      peerResolution:
        nodes.get(remoteVnetId)?.kind === "unresolved"
          ? nodes.get(remoteVnetId)?.peerResolution
          : undefined,
    });
  }

  for (const service of topology.shared_services) {
    for (const consumerId of service.consumer_vnet_ids) {
      const resolvedConsumerId = resolveNodeId(nodeIds, consumerId);
      if (!resolvedConsumerId) continue;
      const id = `serves:${service.resource_id}::${resolvedConsumerId}`;
      edges.set(id, {
        id,
        source: service.resource_id,
        target: resolvedConsumerId,
        kind: "service",
        label: "",
        bidirectional: false,
        crossSubscription:
          subscriptionOf(resolvedConsumerId) !== service.subscription_id,
        allowForwardedTraffic: false,
        allowGatewayTransit: false,
        useRemoteGateways: false,
        localState: "",
        remoteState: "",
      });
    }
  }

  const groups = new Map<string, TopologyGroupData>();
  for (const node of Array.from(nodes.values())) {
    if (!node.parent || groups.has(node.parent)) continue;
    groups.set(node.parent, {
      id: node.parent,
      label: node.subscriptionId ? `Subscription ${node.subscriptionId.slice(0, 8)}` : "Unknown subscription",
      kind: "subscription",
    });
  }

  return {
    groups: Array.from(groups.values()),
    nodes: Array.from(nodes.values()),
    edges: Array.from(edges.values()),
    hiddenUnattachedPrivateLinkCount: 0,
  };
}

function buildResourceTopologyGraph(
  topology: NetworkTopology,
  options: TopologyGraphOptions,
): TopologyGraph {
  const nodes = new Map<string, TopologyNodeData>();
  const resourceIdsByFoldedId = new Map<string, string>();
  for (const resource of topology.resources ?? []) {
    const foldedId = resource.id.toLowerCase();
    const existingId = resourceIdsByFoldedId.get(foldedId);
    if (existingId) {
      const existing = nodes.get(existingId);
      const existingIsCandidate = existing?.details?.private_link_candidate === true;
      const incomingIsCandidate = resource.details?.private_link_candidate === true;
      if (existingIsCandidate || !incomingIsCandidate) continue;
      nodes.delete(existingId);
    }
    nodes.set(resource.id, resourceNode(resource));
    resourceIdsByFoldedId.set(foldedId, resource.id);
  }

  const edges = new Map<string, TopologyEdgeData>();
  const nodeIds = indexNodesByFoldedId(nodes);
  const resolutions = peerResolutionByFoldedId(topology);
  const unresolvedIds = [
    ...topology.unresolved_peer_vnet_ids,
    ...(topology.unresolved_peers ?? []).map((peer) => peer.vnet_id),
  ];
  for (const id of unresolvedIds) {
    if (resolveNodeId(nodeIds, id)) continue;
    nodes.set(id, unresolvedNode(id, resolutions.get(id.toLowerCase()) ?? "unknown"));
    nodeIds.set(id.toLowerCase(), id);
  }
  for (const relationship of topology.relationships ?? []) {
    const source = resolveNodeId(nodeIds, relationship.source);
    const target = resolveNodeId(nodeIds, relationship.target);
    if (!source || !target) continue;
    edges.set(relationship.id, relationshipEdge({ ...relationship, source, target }));
  }

  for (const link of topology.links) {
    const localVnetId = resolveNodeId(nodeIds, link.local_vnet_id);
    if (!localVnetId) continue;
    let remoteVnetId = resolveNodeId(nodeIds, link.remote_vnet_id);
    if (!remoteVnetId) {
      remoteVnetId = link.remote_vnet_id;
      nodes.set(
        remoteVnetId,
        unresolvedNode(
          remoteVnetId,
          resolutions.get(remoteVnetId.toLowerCase()) ?? "unknown",
        ),
      );
      nodeIds.set(remoteVnetId.toLowerCase(), remoteVnetId);
    }
    const pair = [localVnetId, remoteVnetId].sort();
    const id = `peering:${pair[0]}::${pair[1]}`;
    edges.set(id, {
      id,
      source: pair[0],
      target: pair[1],
      kind: edgeKind(link),
      label: edgeLabel(link) || "peered with",
      bidirectional: link.is_bidirectional,
      crossSubscription: link.is_cross_subscription,
      allowForwardedTraffic: link.allow_forwarded_traffic,
      allowGatewayTransit: link.allow_gateway_transit,
      useRemoteGateways: link.use_remote_gateways,
      localState: link.local_state,
      remoteState: link.remote_state,
      relationshipType: "peered_with",
      details: { ...link },
      peerResolution:
        nodes.get(remoteVnetId)?.kind === "unresolved"
          ? nodes.get(remoteVnetId)?.peerResolution
          : undefined,
    });
  }

  const groups = new Map<string, TopologyGroupData>();
  for (const node of Array.from(nodes.values())) {
    if (!node.parent || groups.has(node.parent)) continue;
    groups.set(node.parent, {
      id: node.parent,
      label: node.subscriptionId ? `Subscription ${node.subscriptionId.slice(0, 8)}` : "Unknown subscription",
      kind: "subscription",
    });
  }

  const graph = {
    groups: Array.from(groups.values()),
    nodes: Array.from(nodes.values()),
    edges: Array.from(edges.values()),
    hiddenUnattachedPrivateLinkCount: 0,
  };
  if (options.showUnattachedPrivateLinkCandidates !== false) return graph;

  const connectedNodeIds = new Set(
    graph.edges.flatMap((edge) => [edge.source, edge.target]),
  );
  const isPrivateLinkCandidate = (node: TopologyNodeData) =>
    node.details?.private_link_candidate === true;
  const hasPrimaryTopology = graph.nodes.some(
    (node) => !isPrivateLinkCandidate(node),
  );
  if (!hasPrimaryTopology) return graph;

  const hiddenIds = new Set(
    graph.nodes
      .filter(
        (node) =>
          isPrivateLinkCandidate(node) && !connectedNodeIds.has(node.id),
      )
      .map((node) => node.id),
  );
  if (hiddenIds.size === 0) return graph;

  const visibleNodes = graph.nodes.filter((node) => !hiddenIds.has(node.id));
  const visibleParentIds = new Set(
    visibleNodes.flatMap((node) => (node.parent ? [node.parent] : [])),
  );
  return {
    groups: graph.groups.filter((group) => visibleParentIds.has(group.id)),
    nodes: visibleNodes,
    edges: graph.edges.filter(
      (edge) => !hiddenIds.has(edge.source) && !hiddenIds.has(edge.target),
    ),
    hiddenUnattachedPrivateLinkCount: hiddenIds.size,
  };
}
