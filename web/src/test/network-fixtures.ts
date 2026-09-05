import { vi } from "vitest";

import type {
  Envelope,
  NetworkGap,
  NetworkSummary,
  NetworkTopology,
  Pagination,
  RuleFinding,
} from "@/lib/types";

export interface CoverageBlock {
  total: number;
  returned: number;
  truncated: boolean;
}

export function buildCoverage(total: number, returned = Math.min(total, 100)): CoverageBlock {
  return {
    total,
    returned,
    truncated: returned < total,
  };
}

export function buildPagination(
  total: number,
  offset = 0,
  limit = 100,
): Pagination {
  const nextOffset = offset + limit;
  return {
    offset,
    limit,
    total,
    next_offset: nextOffset < total ? nextOffset : null,
  };
}

function evidence() {
  return [
    {
      source_engine: "network.NetworkIntelligenceService",
      source_table: "ontology_entities",
      timestamp: "2026-01-01T00:00:00Z",
      subscription_connection: "conn-network-test",
      resource_id: "",
      confidence: "high" as const,
      freshness: "fresh" as const,
    },
  ];
}

function envelope<T>(data: T, pagination?: Pagination): Envelope<T> {
  return {
    data,
    evidence: evidence(),
    scope: { subscription: ["00000000-0000-0000-0000-000000000001"] },
    knowledge_version: "network-fixture-v1",
    warnings: [],
    pagination,
  };
}

export function buildNetworkSummary(
  overrides: Partial<NetworkSummary> = {},
): NetworkSummary {
  return {
    hub_count: 1,
    spoke_count: 1,
    isolated_vnet_count: 0,
    peering_count: 1,
    cross_subscription_peering_count: 0,
    unhealthy_peering_count: 0,
    shared_service_count: 0,
    connection_count: 1,
    gap_count: 0,
    gaps_by_severity: {},
    gaps_by_category: {},
    rule_finding_count: 0,
    rule_findings_by_severity: {},
    rule_findings_by_category: {},
    intended_design_declared: true,
    resource_counts: { vnets: 2 },
    ...overrides,
  };
}

export function buildTopologyEnvelope(
  total = 2,
  returned = Math.min(total, 100),
): Envelope<{
  topology: NetworkTopology;
  summary: NetworkSummary;
  coverage: CoverageBlock;
}> {
  const resources = Array.from({ length: returned }, (_, index) => {
    const id = `/subscriptions/00000000-0000-0000-0000-000000000001/resourcegroups/rg-network/providers/microsoft.network/virtualnetworks/vnet-${index}`;
    return {
      id,
      name: `vnet-${index}`,
      entity_type: "VNet",
      role: index === 0 ? "hub" : "spoke",
      subscription_id: "00000000-0000-0000-0000-000000000001",
      resource_group: "rg-network",
      location: "eastus",
      connection_id: "conn-network-test",
      environment: "test",
      business_service: "Platform",
      application: "",
      owner: "network@example.test",
      tags: {},
      details: {},
    };
  });
  const classifications = resources.map((resource, index) => ({
    vnet_id: resource.id,
    name: resource.name,
    role: (index === 0 ? "hub" : "spoke") as "hub" | "spoke",
    score: index === 0 ? 4 : 0,
    signals: index === 0 ? ["hosts_firewall"] : [],
    connection_id: resource.connection_id,
    subscription_id: resource.subscription_id,
    peer_count: index === 0 ? Math.max(0, returned - 1) : 1,
  }));
  const topology: NetworkTopology = {
    hubs: classifications.slice(0, 1),
    spokes: classifications.slice(1),
    isolated: [],
    links: [],
    shared_services: [],
    resources,
    relationships: [],
    unresolved_peer_vnet_ids: [],
    connection_ids: ["conn-network-test"],
    counts: { vnets: total },
  };
  return envelope({
    topology,
    summary: buildNetworkSummary({
      hub_count: Math.min(returned, 1),
      spoke_count: Math.max(0, total - 1),
      resource_counts: { vnets: total },
    }),
    coverage: buildCoverage(total, returned),
  });
}

export function buildGapsEnvelope(
  total = 0,
  offset = 0,
  limit = 100,
): Envelope<{
  gaps: NetworkGap[];
  intended_design_declared: boolean;
  summary: NetworkSummary;
  coverage: CoverageBlock;
}> {
  const returned = Math.min(limit, Math.max(0, total - offset));
  const gaps = Array.from({ length: returned }, (_, index): NetworkGap => {
    const item = offset + index;
    return {
      gap_id: `gap-${item}`,
      category: "missing_nsg",
      severity: item % 2 === 0 ? "high" : "medium",
      title: `Subnet ${item} has no NSG`,
      detail: "Synthetic network fixture gap",
      resource_id: `/subscriptions/00000000-0000-0000-0000-000000000001/resourcegroups/rg-network/providers/microsoft.network/virtualnetworks/vnet-0/subnets/subnet-${item}`,
      resource_name: `subnet-${item}`,
      resource_type: "Subnet",
      evidence: { fixture: true },
      recommendation: "Associate an approved NSG.",
      basis: "configuration",
      connection_id: "conn-network-test",
      subscription_id: "00000000-0000-0000-0000-000000000001",
      environment: "test",
    };
  });
  return envelope(
    {
      gaps,
      intended_design_declared: true,
      summary: buildNetworkSummary({
        gap_count: total,
        gaps_by_severity: total ? { high: Math.ceil(total / 2), medium: Math.floor(total / 2) } : {},
        gaps_by_category: total ? { missing_nsg: total } : {},
      }),
      coverage: buildCoverage(total, returned),
    },
    buildPagination(total, offset, limit),
  );
}

export function buildRuleFindingsEnvelope(
  total = 0,
  offset = 0,
  limit = 100,
): Envelope<{
  findings: RuleFinding[];
  summary: NetworkSummary;
  coverage: CoverageBlock;
}> {
  const returned = Math.min(limit, Math.max(0, total - offset));
  const findings = Array.from({ length: returned }, (_, index): RuleFinding => {
    const item = offset + index;
    return {
      finding_id: `finding-${item}`,
      category: "broad_source",
      severity: item % 2 === 0 ? "critical" : "high",
      rule_id: `rule-${item}`,
      rule_name: `rule-${item}`,
      control: "NetworkSecurityGroup",
      control_id: `/subscriptions/00000000-0000-0000-0000-000000000001/resourcegroups/rg-network/providers/microsoft.network/networksecuritygroups/nsg-${item}`,
      title: `Broad source on rule ${item}`,
      detail: "Synthetic network fixture finding",
      evidence: { fixture: true },
      recommendation: "Narrow the source range.",
      connection_id: "conn-network-test",
      subscription_id: "00000000-0000-0000-0000-000000000001",
      environment: "test",
    };
  });
  return envelope(
    {
      findings,
      summary: buildNetworkSummary({
        rule_finding_count: total,
        rule_findings_by_severity: total
          ? { critical: Math.ceil(total / 2), high: Math.floor(total / 2) }
          : {},
        rule_findings_by_category: total ? { broad_source: total } : {},
      }),
      coverage: buildCoverage(total, returned),
    },
    buildPagination(total, offset, limit),
  );
}

/** Create the service spies consumed by a test's ``vi.hoisted`` block. */
export function createNetworkServiceMocks() {
  return {
    topology: vi.fn(),
    summary: vi.fn(),
    hubDependents: vi.fn(),
    firewallBypass: vi.fn(),
    trafficFlow: vi.fn(),
    gaps: vi.fn(),
    ruleFindings: vi.fn(),
    policy: vi.fn(),
    updatePolicy: vi.fn(),
    previewPolicy: vi.fn(),
  };
}

export type NetworkServiceMocks = ReturnType<typeof createNetworkServiceMocks>;

/** Return the exact module shape expected by ``vi.mock("@/lib/services")``. */
export function buildNetworkServiceModuleMock(mocks: NetworkServiceMocks) {
  return { networkApi: mocks };
}
