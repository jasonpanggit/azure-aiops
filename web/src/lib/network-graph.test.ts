import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { RESOURCE_ICONS, SERVICE_ICONS, buildTopologyGraph, serviceIcon, shortName, subscriptionOf } from "@/lib/network-graph";
import type {
  HubClassification,
  NetworkTopology,
  NetworkTopologyResource,
  PeeringLink,
  SharedServiceSummary,
} from "@/lib/types";

function vnet(overrides: Partial<HubClassification> & { vnet_id: string }): HubClassification {
  return {
    name: shortName(overrides.vnet_id),
    role: "spoke",
    score: 0,
    signals: [],
    connection_id: "conn-1",
    subscription_id: "sub-a",
    peer_count: 0,
    ...overrides,
  };
}

function link(overrides: Partial<PeeringLink> & { local_vnet_id: string; remote_vnet_id: string }): PeeringLink {
  return {
    local_connection_id: "conn-1",
    remote_connection_id: "conn-1",
    is_bidirectional: true,
    is_healthy: true,
    is_cross_subscription: false,
    local_state: "Connected",
    remote_state: "Connected",
    allow_forwarded_traffic: false,
    allow_gateway_transit: false,
    use_remote_gateways: false,
    remote_vnet_observed: true,
    ...overrides,
  };
}

function topologyOf(overrides: Partial<NetworkTopology> = {}): NetworkTopology {
  return {
    hubs: [],
    spokes: [],
    isolated: [],
    links: [],
    shared_services: [],
    unresolved_peer_vnet_ids: [],
    connection_ids: [],
    counts: {},
    ...overrides,
  };
}

function resource(
  overrides: Partial<NetworkTopologyResource> & Pick<NetworkTopologyResource, "id" | "entity_type">
): NetworkTopologyResource {
  return {
    name: shortName(overrides.id),
    subscription_id: "sub-a",
    resource_group: "rg-workloads",
    location: "eastus",
    connection_id: "conn-1",
    environment: "prod",
    business_service: "",
    application: "",
    owner: "",
    tags: {},
    details: {},
    ...overrides,
  };
}

const HUB = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/hub";
const SPOKE = "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/spoke";
const GHOST = "/subscriptions/sub-z/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/ghost";
const FABRIC =
  "/subscriptions/sub-a/resourceGroups/rg-workloads/providers/Microsoft.Fabric/capacities/fabric-capacity";
const AI_SERVICES =
  "/subscriptions/sub-a/resourceGroups/rg-workloads/providers/Microsoft.CognitiveServices/accounts/foundry-tools";

describe("buildTopologyGraph", () => {
  it("classifies VNets by role and groups them by subscription", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        hubs: [vnet({ vnet_id: HUB, role: "hub", subscription_id: "sub-a", peer_count: 3 })],
        spokes: [vnet({ vnet_id: SPOKE, subscription_id: "sub-b" })],
      })
    );

    expect(graph.nodes.find((node) => node.id === HUB)?.kind).toBe("hub");
    expect(graph.nodes.find((node) => node.id === SPOKE)?.kind).toBe("spoke");
    expect(graph.groups.map((group) => group.id).sort()).toEqual([
      "subscription:sub-a",
      "subscription:sub-b",
    ]);
  });

  it("draws one edge for a peering observed from both directions", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        hubs: [vnet({ vnet_id: HUB, role: "hub" })],
        spokes: [vnet({ vnet_id: SPOKE })],
        links: [
          link({ local_vnet_id: HUB, remote_vnet_id: SPOKE }),
          link({ local_vnet_id: SPOKE, remote_vnet_id: HUB }),
        ],
      })
    );

    expect(graph.edges).toHaveLength(1);
    expect(graph.edges[0].kind).toBe("healthy");
  });

  it("keeps the unhealthy verdict when one direction is disconnected", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        hubs: [vnet({ vnet_id: HUB, role: "hub" })],
        spokes: [vnet({ vnet_id: SPOKE })],
        links: [
          link({ local_vnet_id: HUB, remote_vnet_id: SPOKE, is_healthy: false, local_state: "Disconnected" }),
          link({ local_vnet_id: SPOKE, remote_vnet_id: HUB }),
        ],
      })
    );

    expect(graph.edges).toHaveLength(1);
    expect(graph.edges[0].kind).toBe("unhealthy");
  });

  it("materialises peers that were never ingested as explicit unresolved nodes", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        hubs: [vnet({ vnet_id: HUB, role: "hub" })],
        links: [link({ local_vnet_id: HUB, remote_vnet_id: GHOST, remote_vnet_observed: false })],
        unresolved_peer_vnet_ids: [GHOST],
      })
    );

    const ghost = graph.nodes.find((node) => node.id === GHOST);
    expect(ghost?.kind).toBe("unresolved");
    expect(ghost?.observed).toBe(false);
    expect(ghost?.subscriptionId).toBe("sub-z");
    expect(graph.edges[0].kind).toBe("unresolved");
  });

  it("links shared services to each observed consumer VNet only", () => {
    const service: SharedServiceSummary = {
      resource_id: "/subscriptions/sub-a/providers/Microsoft.Network/azureFirewalls/fw/sharedservice",
      name: "hub-fw",
      service_kind: "firewall",
      hub_vnet_id: HUB,
      consumer_vnet_ids: [HUB, SPOKE, GHOST],
      connection_id: "conn-1",
      subscription_id: "sub-a",
      environment: "prod",
    };
    const graph = buildTopologyGraph(
      topologyOf({
        hubs: [vnet({ vnet_id: HUB, role: "hub" })],
        spokes: [vnet({ vnet_id: SPOKE })],
        shared_services: [service],
      })
    );

    const serviceEdges = graph.edges.filter((edge) => edge.kind === "service");
    expect(serviceEdges).toHaveLength(2);
    expect(serviceEdges.map((edge) => edge.target).sort()).toEqual([HUB, SPOKE].sort());
    expect(graph.nodes.find((node) => node.id === service.resource_id)?.icon).toBe("/azure-icons/firewall.svg");
  });

  it("labels one-way and cross-subscription peerings", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        hubs: [vnet({ vnet_id: HUB, role: "hub" })],
        spokes: [vnet({ vnet_id: SPOKE, subscription_id: "sub-b" })],
        links: [
          link({
            local_vnet_id: HUB,
            remote_vnet_id: SPOKE,
            is_bidirectional: false,
            is_cross_subscription: true,
            allow_gateway_transit: true,
          }),
        ],
      })
    );

    expect(graph.edges[0].label).toBe("cross-sub · gateway transit · one-way");
  });

  it("prefers resource-level nodes and relationships when present", () => {
    const nsgId = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/app-nsg";
    const ruleId = `${nsgId}/securityRules/allow-sql`;
    const graph = buildTopologyGraph(
      topologyOf({
        resources: [
          {
            id: nsgId,
            name: "app-nsg",
            entity_type: "NetworkSecurityGroup",
            role: "",
            subscription_id: "sub-a",
            resource_group: "rg",
            location: "eastus",
            connection_id: "conn-1",
            environment: "prod",
            business_service: "Payments",
            application: "Checkout",
            owner: "NetOps",
            tags: { owner: "NetOps" },
            details: {
              rules: [{ id: ruleId, name: "allow-sql", priority: 100, access: "Allow", destination_port: "1433" }],
            },
          },
          {
            id: ruleId,
            name: "allow-sql",
            entity_type: "NetworkSecurityRule",
            role: "",
            subscription_id: "sub-a",
            resource_group: "rg",
            location: "eastus",
            connection_id: "conn-1",
            environment: "prod",
            business_service: "Payments",
            application: "Checkout",
            owner: "NetOps",
            tags: {},
            details: { priority: 100, access: "Allow", destination_port: "1433" },
          },
        ],
        relationships: [
          {
            id: `has_rule:${nsgId}::${ruleId}`,
            source: nsgId,
            target: ruleId,
            relationship_type: "has_rule",
            label: "has NSG rule",
            details: { priority: 100, destination_port: "1433" },
          },
        ],
      })
    );

    expect(graph.nodes).toHaveLength(2);
    expect(graph.nodes.find((node) => node.id === nsgId)?.entityType).toBe("NetworkSecurityGroup");
    expect(graph.nodes.find((node) => node.id === nsgId)?.details?.rules).toEqual([
      { id: ruleId, name: "allow-sql", priority: 100, access: "Allow", destination_port: "1433" },
    ]);
    expect(graph.edges).toEqual([
      expect.objectContaining({
        id: `has_rule:${nsgId}::${ruleId}`,
        kind: "relationship",
        relationshipType: "has_rule",
        label: "has NSG rule",
        details: { priority: 100, destination_port: "1433" },
      }),
    ]);
  });

  it("keeps resource relationships when Azure resource ID casing differs", () => {
    const vnetId = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/demo-vnet";
    const subnetId = `${vnetId}/subnets/snet-app`;
    const graph = buildTopologyGraph(
      topologyOf({
        resources: [
          {
            id: vnetId,
            name: "demo-vnet",
            entity_type: "VNet",
            role: "isolated",
            subscription_id: "sub-a",
            resource_group: "rg",
            location: "eastus",
            connection_id: "conn-1",
            environment: "prod",
            business_service: "",
            application: "",
            owner: "",
            tags: {},
            details: {},
          },
          {
            id: subnetId,
            name: "snet-app",
            entity_type: "Subnet",
            role: "",
            subscription_id: "sub-a",
            resource_group: "rg",
            location: "eastus",
            connection_id: "conn-1",
            environment: "prod",
            business_service: "",
            application: "",
            owner: "",
            tags: {},
            details: {},
          },
        ],
        relationships: [
          {
            id: `contains:${vnetId.toLowerCase()}::${subnetId.toLowerCase()}`,
            source: vnetId.toLowerCase(),
            target: subnetId.toLowerCase(),
            relationship_type: "contains",
            label: "contains subnet",
            details: {},
          },
        ],
      })
    );

    expect(graph.edges).toEqual([
      expect.objectContaining({
        source: vnetId,
        target: subnetId,
        relationshipType: "contains",
      }),
    ]);
  });

  it("preserves Fabric and AI Foundry entity types as exactly two graph nodes", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        resources: [
          resource({ id: FABRIC, entity_type: "FabricCapacity" }),
          resource({ id: AI_SERVICES, entity_type: "AIFoundryAccount" }),
        ],
      })
    );

    expect(graph.nodes).toHaveLength(2);
    expect(graph.nodes.map((node) => node.entityType).sort()).toEqual([
      "AIFoundryAccount",
      "FabricCapacity",
    ]);
    expect(graph.nodes.find((node) => node.entityType === "AIFoundryAccount")?.icon).toBe(
      "/azure-icons/ai-services.svg"
    );
    expect(graph.nodes.find((node) => node.entityType === "FabricCapacity")?.icon).toBe("");
  });

  it("uses the existing workload kind for Fabric and AI Foundry nodes", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        resources: [
          resource({ id: FABRIC, entity_type: "FabricCapacity" }),
          resource({ id: AI_SERVICES, entity_type: "AIFoundryAccount" }),
        ],
      })
    );

    expect(graph.nodes.map((node) => node.kind)).toEqual(["workload", "workload"]);
  });

  it("deduplicates dual-projected resources case-insensitively", () => {
    const graph = buildTopologyGraph(
      topologyOf({
        resources: [
          resource({ id: AI_SERVICES, entity_type: "AIFoundryAccount" }),
          resource({ id: AI_SERVICES.toUpperCase(), entity_type: "AIFoundryAccount" }),
        ],
      })
    );

    expect(graph.nodes).toHaveLength(1);
    expect(graph.nodes[0].id.toLowerCase()).toBe(AI_SERVICES.toLowerCase());
  });

  it("recognises a generic private-link resource as an icon-less workload", () => {
    const id = "/subscriptions/sub-a/resourceGroups/rg/providers/Contoso.Widgets/widgets/widget-1";
    const graph = buildTopologyGraph(
      topologyOf({ resources: [resource({ id, entity_type: "PrivateLinkResource" })] })
    );

    expect(graph.nodes[0]).toMatchObject({
      id,
      kind: "workload",
      icon: "",
      entityType: "PrivateLinkResource",
    });
  });

  it("keeps an icon-less Fabric node addressable for finding badges", () => {
    const graph = buildTopologyGraph(
      topologyOf({ resources: [resource({ id: FABRIC, entity_type: "FabricCapacity" })] })
    );
    const findingTarget = graph.nodes.find((node) => node.id.toLowerCase() === FABRIC.toLowerCase());

    expect(findingTarget).toMatchObject({
      id: FABRIC,
      kind: "workload",
      icon: "",
      observed: true,
    });
  });
});

describe("serviceIcon", () => {
  it("maps every known shared service kind to a distinct official icon", () => {
    const kinds = ["firewall", "vpn", "expressroute", "bastion", "dns", "private_dns", "egress"];
    const icons = kinds.map(serviceIcon);
    expect(new Set(icons).size).toBe(kinds.length);
  });

  it("falls back to the VNet glyph for an unknown kind", () => {
    expect(serviceIcon("something-new")).toBe("/azure-icons/virtual-network.svg");
  });
});

describe("subscriptionOf", () => {
  it("extracts the subscription segment and returns empty when absent", () => {
    expect(subscriptionOf(HUB)).toBe("sub-a");
    expect(subscriptionOf("not-an-arm-id")).toBe("");
  });
});

describe("shortName", () => {
  it("never surfaces the synthetic shared-service id suffix as a name", () => {
    expect(shortName("/subscriptions/sub-a/providers/Microsoft.Network/azureFirewalls/hub-fw/sharedservice")).toBe(
      "hub-fw"
    );
  });

  it("returns the final segment of an ordinary resource id", () => {
    expect(shortName(HUB)).toBe("hub");
  });
});

describe("icon assets", () => {
  // A mapped icon that has no file on disk fails silently: the node simply
  // renders blank, which is exactly the bug this guards against.
  const iconDir = resolve(__dirname, "../../public/azure-icons");

  it.each(Object.entries(RESOURCE_ICONS))("has an SVG for the %s entity type", (_entityType, icon) => {
    expect(existsSync(resolve(iconDir, `${icon}.svg`))).toBe(true);
  });

  it.each(Object.entries(SERVICE_ICONS))("has an SVG for the %s service kind", (_kind, icon) => {
    expect(existsSync(resolve(iconDir, `${icon}.svg`))).toBe(true);
  });

  it("draws workloads with their own service glyph", () => {
    for (const entityType of ["VirtualMachine", "CosmosDb"]) {
      expect(RESOURCE_ICONS[entityType]).toBeTruthy();
    }
  });

  it("uses only the available V21 icon and documents Fabric's icon-less fallback", () => {
    const readme = readFileSync(resolve(iconDir, "README.md"), "utf8");

    expect(existsSync(resolve(iconDir, "ai-services.svg"))).toBe(true);
    expect(existsSync(resolve(iconDir, "fabric.svg"))).toBe(false);
    expect(readme).toContain("`ai-services.svg` | Azure AI Services");
    expect(readme).toContain("Microsoft Fabric");
    expect(readme).toContain("intentionally icon-less");
  });
});
