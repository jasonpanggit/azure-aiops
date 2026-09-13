import { readdirSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { CopilotPageKind, CopilotPageKindV2, CopilotPageSnapshot } from "@/lib/types";
import {
  buildChangesCopilotContext,
  buildComplianceCopilotContext,
  buildConnectionsCopilotContext,
  buildCveDetailCopilotContext,
  buildDefenderPostureCopilotContext,
  buildExposureCopilotContext,
  buildFabricMedallionCopilotContext,
  buildFinOpsCopilotContext,
  buildGovernanceCopilotContext,
  buildIdentityCopilotContext,
  buildInventoryCopilotContext,
  buildKbDetailCopilotContext,
  buildNetworkCopilotContext,
  buildOverviewCopilotContext,
  buildPatchPrioritiesCopilotContext,
  buildPredeployCopilotContext,
  buildRemediationCopilotContext,
  buildResourceHealthCopilotContext,
  buildServiceDetailCopilotContext,
  buildServicesCopilotContext,
  buildSituationDetailCopilotContext,
  buildSituationsCopilotContext,
  buildTwinCopilotContext,
  canonicalEvidenceStableId,
  CORE_COPILOT_PAGE_ADAPTERS,
  COPILOT_ROUTE_DISPOSITIONS,
  COPILOT_SNAPSHOT_LIMITS,
  copilotPageDisposition,
  normalizeCopilotSnapshotV2,
  serializeCopilotSnapshot,
  type InventoryCopilotRecord,
} from "./page-adapters";

const records: InventoryCopilotRecord[] = [
  {
    identity: "Windows Server|2019",
    kind: "os_group",
    source: "inventory/os_observations",
    observedAt: "2026-08-25T10:00:00Z",
    data: {
      os_name: "Windows Server",
      os_version: "2019",
      machine_count: 2,
    },
  },
  {
    identity: "vm-1",
    kind: "azure_group",
    source: "inventory/resource_observations",
    observedAt: "2026-08-25T10:00:00Z",
    resourceId:
      "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.App/containerApps/App-1",
    data: {
      resource_type: "microsoft.app/containerapps",
      resource_count: 1,
    },
  },
];

const baseInput = {
  scope: { subscription: ["sub-a"] },
  tab: "os" as const,
  filters: { search: "windows", lifecycle: "supported" },
  sort: { os_name: "asc" as const },
  records,
  selectedIdentity: "Windows Server|2019",
  totalCount: 4,
  offset: 0,
  limit: 50,
  sourceStatuses: [
    {
      source: "azure_vm",
      observedAt: "2026-08-25T10:00:00Z",
      status: "fresh",
    },
    {
      source: "arc",
      observedAt: "2026-08-25T09:00:00Z",
      status: "partial",
    },
  ],
};

describe("inventory Copilot page adapter", () => {
  it("has an explicit integrated route disposition", () => {
    expect(copilotPageDisposition("/inventory")).toBe("integrated");
  });

  const corePageInput = {
    scope: { subscription: ["sub-a"] },
    filters: { search: ["critical"] },
    sort: { priority: "asc" as const },
    records: [
      {
        identity: "situation-1",
        namespace: "operations",
        kind: "situation",
        source: "situations/visible",
        observedAt: "2026-09-07T10:00:00Z",
        selected: true,
        data: { title: "Critical service interruption", priority: "P1" },
      },
      {
        identity:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Network/virtualNetworks/Hub-1",
        namespace: "network",
        kind: "virtual_network",
        source: "network/topology",
        resourceId:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Network/virtualNetworks/Hub-1",
        resourceType: "Microsoft.Network/virtualNetworks",
        name: "Hub-1",
        observedAt: "2026-09-07T09:00:00Z",
        selected: true,
        data: { role: "hub" },
      },
    ],
    evidence: [
      {
        source_engine: "ARG",
        source_table: "resources",
        timestamp: "2026-09-07T10:00:00Z",
        resource_id:
          "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/hub-1",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
    coverage: [
      {
        key: "situations",
        visibleCount: 2,
        totalCount: 5,
        truncated: true,
      },
    ],
    sourceStatuses: [
      {
        source: "situations",
        observedAt: "2026-09-07T10:00:00Z",
        status: "fresh" as const,
      },
      {
        source: "network",
        observedAt: "2026-09-07T09:00:00Z",
        status: "partial" as const,
      },
    ],
  };

  describe("core Copilot page adapters", () => {
    it("registers Overview, Network, Compliance, Exposure, Situations, and Remediation as integrated routes", () => {
      expect(Object.keys(CORE_COPILOT_PAGE_ADAPTERS)).toEqual([
        "/",
        "/compliance",
        "/exposure",
        "/network",
        "/remediation",
        "/situations",
      ]);
      expect(copilotPageDisposition("/")).toBe("integrated");
      expect(copilotPageDisposition("/network")).toBe("integrated");
      expect(copilotPageDisposition("/compliance")).toBe("integrated");
      expect(copilotPageDisposition("/exposure")).toBe("integrated");
      expect(copilotPageDisposition("/situations")).toBe("integrated");
      expect(copilotPageDisposition("/remediation")).toBe("integrated");
    });

    it("builds bounded Overview evidence with stable domain identities and conditional executive intent", () => {
      const context = buildOverviewCopilotContext(corePageInput);
      const reordered = buildOverviewCopilotContext({
        ...corePageInput,
        records: [...corePageInput.records].reverse().map((record) => ({
          ...record,
          observedAt: "2026-09-08T10:00:00Z",
        })),
      });

      expect(context.snapshot).toMatchObject({
        version: "1",
        page_kind: "resource",
        page_id: "operations-overview",
        filters: {
          search: ["critical"],
          sort: ["priority:asc"],
        },
      });
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "operations",
          kind: "situation",
          source_key: "situation-1",
        },
        {
          type: "azure",
          resource_id:
            "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/hub-1",
        },
      ]);
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      expect(context.snapshot.evidence).toHaveLength(
        Math.min(context.snapshot.evidence.length, COPILOT_SNAPSHOT_LIMITS.evidenceRows),
      );
      expect(context.starterQuestions).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            specialistId: "incident",
            tool: "incidents",
          }),
          expect.objectContaining({
            specialistId: "executive_summary",
          }),
        ]),
      );
      expect(
        context.starterQuestions.find(
          (starter) => starter.specialistId === "executive_summary",
        ),
      ).not.toHaveProperty("tool");
      expect(
        context.starterQuestions.filter(
          (starter) => starter.specialistId === "executive_summary",
        ),
      ).toHaveLength(1);
    });

    it("preserves Network selection, tab filters, pagination coverage, freshness, and read-only hints", () => {
      const context = buildNetworkCopilotContext({
        ...corePageInput,
        filters: { tab: ["gaps"] },
        sort: { severity: "desc" },
        coverage: [
          {
            key: "gaps",
            visibleCount: 100,
            totalCount: 340,
            truncated: true,
          },
          {
            key: "rule_findings",
            visibleCount: 100,
            totalCount: 620,
            truncated: true,
          },
        ],
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "network",
        page_id: "network-topology",
        filters: {
          tab: ["gaps"],
          sort: ["severity:desc"],
        },
        selected_resources: [
          {
            resource_id:
              "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.network/virtualnetworks/hub-1",
            resource_type: "Microsoft.Network/virtualNetworks",
            name: "Hub-1",
          },
        ],
        freshness: [
          {
            source: "network",
            observed_at: "2026-09-07T09:00:00Z",
            status: "partial",
          },
          {
            source: "situations",
            observed_at: "2026-09-07T10:00:00Z",
            status: "fresh",
          },
        ],
      });
      expect(context.coverage).toEqual({
        gaps: {
          visible_count: 100,
          total_count: 340,
          complete: false,
          truncated: true,
        },
        rule_findings: {
          visible_count: 100,
          total_count: 620,
          complete: false,
          truncated: true,
        },
      });
      expect(context.uncertainty).toEqual([
        "gaps coverage is truncated",
        "rule_findings coverage is truncated",
        "network freshness is partial",
      ]);
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "network"
        && !/write|update|delete|execute/i.test(starter.tool ?? ""),
      )).toBe(true);
    });

    it("preserves Compliance policy/resource evidence, aggregate coverage, selection, and governance hints", () => {
      const context = buildComplianceCopilotContext({
        ...corePageInput,
        filters: {
          policy: ["Approved landing zone"],
          selected: ["policy-1"],
        },
        sort: { severity: "desc" },
        records: [
          {
            identity: "policy-1",
            namespace: "compliance",
            kind: "policy_violation",
            source: "compliance/violations",
            selected: true,
            observedAt: "2026-09-07T10:00:00Z",
            data: {
              policy: "Approved landing zone",
              resource: "payroll-sql",
              severity: "critical",
            },
          },
          {
            identity: "deviation-1",
            namespace: "compliance",
            kind: "governed_deviation",
            source: "compliance/deviations",
            observedAt: "2026-09-07T09:00:00Z",
            data: {
              control: "private-access",
              resource: "payroll-sql",
              status: "open",
            },
          },
        ],
        coverage: [
          {
            key: "violations",
            visibleCount: 2,
            totalCount: 7,
            truncated: true,
          },
        ],
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "governance",
        page_id: "compliance-posture",
        filters: {
          policy: ["Approved landing zone"],
          selected: ["policy-1"],
          sort: ["severity:desc"],
        },
      });
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "compliance",
          kind: "policy_violation",
          source_key: "policy-1",
        },
      ]);
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "compliance",
                kind: "policy_violation",
                source_key: "policy-1",
              },
              mutation_authorized: false,
              selected: true,
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              coverage: {
                visible_count: 2,
                total_count: 7,
                complete: false,
                truncated: true,
              },
            }),
          }),
        ]),
      );
      expect(context.starterQuestions).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            specialistId: "governance",
            tool: "risk_context",
          }),
          expect.objectContaining({
            specialistId: "network",
            tool: "firewall_nsg_gaps",
          }),
        ]),
      );
    });

    it("never marks stale, partial, or unavailable observations as actionable", () => {
      const context = buildComplianceCopilotContext({
        ...corePageInput,
        records: corePageInput.records.map((record) => ({
          ...record,
          data: { ...record.data, actionable: true },
        })),
        sourceStatuses: corePageInput.sourceStatuses.map((source) => ({
          ...source,
          status: "stale" as const,
        })),
      });

      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false
        && row.data.mutation_authorized === false,
      )).toBe(true);
    });

    it("projects long Compliance identities into stable bounded keys without losing selection", () => {
      const longIdentity = `peering:${"remote-vnet/".repeat(16)}`;
      const input = {
        scope: {},
        policyName: "Approved landing zone",
        selectedId: longIdentity,
        violations: [{
          id: longIdentity,
          type: "peering",
          severity: "high",
          title: "Unapproved peering",
          detail: "The peering bypasses the approved hub.",
          resource: "hub-vnet",
          application: "Payments",
          businessService: "Checkout",
          owner: "Network",
          affectedTraffic: "Spoke to spoke",
          vulnerabilityExposure: "Unknown",
          remediation: "Route through the approved hub.",
        }],
        governedDeviations: [],
        evidence: [],
        sourceEnvelopes: {},
      };

      const context = buildComplianceCopilotContext(input);
      const repeated = buildComplianceCopilotContext(input);
      const selected = context.selectedEntities[0];

      expect(selected).toMatchObject({
        type: "domain",
        namespace: "compliance",
        kind: "policy_violation",
      });
      expect(selected?.type === "domain" ? selected.source_key.length : 0).toBeLessThanOrEqual(256);
      expect(context.snapshot.filters.selected).toEqual([
        selected?.type === "domain" ? selected.source_key : "",
      ]);
      expect(context.selectedEntities).toEqual(repeated.selectedEntities);
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({ selected: true }),
          }),
        ]),
      );
    });

    it("retains the latest evidence timestamp when live observation metadata is absent", () => {
      const context = buildOverviewCopilotContext({
        scope: {},
        situations: {
          data: [],
          evidence: [
            {
              source_engine: "ARG",
              source_table: "resources",
              timestamp: "2026-09-07T10:00:00Z",
              confidence: "high",
              freshness: "fresh",
            },
            {
              source_engine: "ARG",
              source_table: "resources",
              timestamp: "2026-09-07T11:00:00Z",
              confidence: "high",
              freshness: "fresh",
            },
          ],
          scope: {},
        },
        network: null,
        vulnerabilities: null,
        connections: null,
      });

      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          {
            source: "situations",
            observed_at: "2026-09-07T11:00:00Z",
            status: "fresh",
          },
        ]),
      );
    });

    it("derives deterministic domain identities when loaded rows omit their IDs", () => {
      const input = {
        ...corePageInput,
        records: [{
          identity: " ",
          namespace: "network",
          kind: "network_gap",
          source: "network/gaps",
          selected: true,
          data: {
            title: "Missing route",
            resource: "hub-vnet",
          },
        }],
        evidence: [],
      };

      const context = buildNetworkCopilotContext(input);
      const repeated = buildNetworkCopilotContext(input);
      const selected = context.selectedEntities[0];

      expect(selected).toMatchObject({
        type: "domain",
        namespace: "network",
        kind: "network_gap",
      });
      expect(selected?.type === "domain" ? selected.source_key : "").toMatch(/^anonymous:/);
      expect(context.selectedEntities).toEqual(repeated.selectedEntities);
      expect(context.snapshot.evidence).toEqual(repeated.snapshot.evidence);
    });

    it("marks unavailable page collections incomplete and empty-evidence sources unavailable", () => {
      const emptyEnvelope = {
        data: [],
        evidence: [],
        scope: {},
        knowledge_version: "empty",
        pagination: { offset: 0, limit: 100, total: 0, next_offset: null },
      };
      const context = buildOverviewCopilotContext({
        scope: {},
        situations: emptyEnvelope,
        network: null,
        vulnerabilities: null,
        connections: null,
      });

      expect(context.coverage).toEqual({
        connections: {
          visible_count: 0,
          total_count: 0,
          complete: false,
          truncated: false,
        },
        situations: {
          visible_count: 0,
          total_count: 0,
          complete: true,
          truncated: false,
        },
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "situations", status: "unavailable" }),
          expect.objectContaining({ source: "connections", status: "unavailable" }),
        ]),
      );
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            section: "coverage",
            status: "unavailable",
            data: expect.objectContaining({
              source_key: "connections",
            }),
          }),
        ]),
      );
    });

    it("trims low-priority evidence deterministically to the snapshot byte limit", () => {
      const records = Array.from({ length: COPILOT_SNAPSHOT_LIMITS.evidenceRows }, (_, index) => ({
        identity: `record-${index.toString().padStart(3, "0")}`,
        namespace: "operations",
        kind: "situation",
        source: "situations/visible",
        priority: index,
        data: {
          title: `Situation ${index}`,
          detail: "x".repeat(900),
        },
      }));
      const input = {
        ...corePageInput,
        records,
        evidence: [],
      };

      const context = buildOverviewCopilotContext(input);
      const repeated = buildOverviewCopilotContext(input);

      expect(new TextEncoder().encode(JSON.stringify(context.snapshot)).length)
        .toBeLessThanOrEqual(COPILOT_SNAPSHOT_LIMITS.snapshotBytes);
      expect(context.snapshot.evidence.length).toBeLessThan(records.length);
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        repeated.snapshot.evidence.map((row) => row.evidence_id),
      );
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            section: "coverage",
          }),
        ]),
      );
    });
  });

  describe("exposure, CVE detail, and situations Copilot page adapters", () => {
    const exposureInput = {
      scope: { subscription: ["sub-a"] },
      summary: {
        value: {
          cve_count: 12,
          affected_asset_count: 5,
          affected_business_service_count: 3,
          critical_count: 4,
          reachable_server_count: 2,
          internet_exposed_count: 1,
        },
        loadedCount: 1,
        totalCount: 1,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T10:00:00Z",
        evidence: [
          {
            source_engine: "Fabric",
            source_table: "exposure_summary",
            timestamp: "2026-09-07T10:00:00Z",
            confidence: "high" as const,
            freshness: "fresh" as const,
          },
        ],
      },
      patchPriorities: {
        value: [
          {
            priority_id: "patch-1",
            kb_id: "KB5001",
            cve_ids: ["CVE-2026-0001"],
            priority_score: 92,
            affected_server_count: 8,
            recommended_action: "Deploy KB5001",
          },
          {
            priority_id: "patch-2",
            kb_id: "KB5002",
            cve_ids: ["CVE-2026-0002"],
            priority_score: 71,
            affected_server_count: 3,
            recommended_action: "Deploy KB5002",
          },
        ],
        loadedCount: 2,
        totalCount: 6,
        freshness: "partial" as const,
        available: true,
        observedAt: "2026-09-07T09:30:00Z",
      },
      assets: {
        value: [
          {
            asset_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            name: "vm-1",
            resource_type: "Microsoft.Compute/virtualMachines",
            business_service: "Payments",
            application: "Ledger",
            cve_count: 4,
            critical_count: 2,
          },
        ],
        loadedCount: 1,
        totalCount: 3,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T09:00:00Z",
      },
      riskExceptions: {
        value: [],
        loadedCount: 0,
        totalCount: 0,
        freshness: "unavailable" as const,
        available: false,
      },
    };

    it("preserves exposure vulnerability/asset/patch identities, partial coverage, and unavailable-vs-empty status", () => {
      const context = buildExposureCopilotContext(exposureInput);
      const reordered = buildExposureCopilotContext({
        ...exposureInput,
        patchPriorities: {
          ...exposureInput.patchPriorities,
          value: [...exposureInput.patchPriorities.value].reverse(),
        },
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "exposure",
      });
      // Patch identity is canonical non-ARM; asset identity is canonical ARM.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "vulnerability",
                kind: "patch_priority",
                source_key: "patch-1",
              },
              actionable: false,
              mutation_authorized: false,
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "azure",
                resource_id:
                  "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage).toMatchObject({
        patch_priorities: {
          visible_count: 2,
          total_count: 6,
          complete: false,
          truncated: true,
        },
        assets: {
          visible_count: 1,
          total_count: 3,
          complete: false,
          truncated: true,
        },
        risk_exceptions: {
          visible_count: 0,
          total_count: 0,
          complete: false,
          truncated: false,
        },
      });
      // Deterministic evidence identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      // Unavailable source is distinct from a healthy empty result.
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "risk_exceptions", status: "unavailable" }),
          expect.objectContaining({ source: "patch_priorities", status: "partial" }),
        ]),
      );
      expect(context.uncertainty).toEqual(
        expect.arrayContaining([
          "patch_priorities coverage is truncated",
          "assets coverage is truncated",
        ]),
      );
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "vulnerability"
        && !/write|update|delete|execute|remediate/i.test(starter.tool ?? ""))).toBe(true);
    });

    const cveInput = {
      scope: { subscription: ["sub-a"] },
      cveId: "CVE-2026-0001",
      cve: {
        cve_id: "CVE-2026-0001",
        title: "Critical RCE",
        description: "Remote code execution",
        severity: "critical",
        cvss: { version: "3.1", base_score: 9.8, vector: "AV:N", severity: "critical" },
        associated_kbs: ["KB5001", "KB5002"],
        epss_score: 0.7,
        is_known_exploited: true,
      },
      findings: {
        rows: [
          {
            exposure_id: "exp-1",
            target_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            weakness_id: "CVE-2026-0001",
            business_service: "Payments",
            application: "Ledger",
            severity: "critical",
            missing_kb: "KB5001",
            reachable: true,
          },
        ],
        loadedCount: 1,
        totalCount: 5,
        available: true,
        freshness: "fresh" as const,
        observedAt: "2026-09-07T10:00:00Z",
      },
      attack: {
        graph: {
          cve_id: "CVE-2026-0001",
          nodes: [
            { id: "origin", kind: "origin" as const, label: "Internet" },
            { id: "vm-1", kind: "server" as const, label: "vm-1", reachable: true },
          ],
          edges: [{ source: "origin", target: "vm-1", label: "reaches" }],
          reachable_server_count: 1,
          internet_exposed: true,
        },
        available: true,
        freshness: "fresh" as const,
        observedAt: "2026-09-07T10:00:00Z",
      },
      sources: [
        { key: "nvd", freshness: "fresh" as const, available: true, observedAt: "2026-09-07T08:00:00Z" },
        { key: "epss", freshness: "partial" as const, available: true, observedAt: "2026-09-07T07:00:00Z" },
        { key: "kev", freshness: "fresh" as const, available: true, observedAt: "2026-09-07T06:00:00Z" },
        { key: "msrc", freshness: "unavailable" as const, available: false },
      ],
      filters: { weakness_id: ["CVE-2026-0001"], page: ["1"] },
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "cve_findings",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("carries the canonical non-ARM CVE identity, KB/finding identities, source freshness, and pagination coverage", () => {
      const context = buildCveDetailCopilotContext(cveInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "cve:CVE-2026-0001",
      });
      // The CVE itself is a canonical non-ARM (domain) selected identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "vulnerability",
          kind: "cve",
          source_key: "CVE-2026-0001",
        },
      ]);
      // CVE is not an ARM resource, so it must not leak into selected_resources.
      expect(context.snapshot.selected_resources).toEqual([]);
      // KB identities are retained.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "vulnerability",
                kind: "kb",
                source_key: "KB5001",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage.findings).toMatchObject({
        visible_count: 1,
        total_count: 5,
        complete: false,
        truncated: true,
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "nvd", status: "fresh" }),
          expect.objectContaining({ source: "epss", status: "partial" }),
          expect.objectContaining({ source: "msrc", status: "unavailable" }),
        ]),
      );
      expect(context.snapshot.filters).toMatchObject({
        weakness_id: ["CVE-2026-0001"],
        page: ["1"],
      });
      expect(context.starterQuestions.length).toBeGreaterThan(0);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("distinguishes an unavailable CVE provider from a healthy empty finding set", () => {
      const context = buildCveDetailCopilotContext({
        ...cveInput,
        findings: {
          ...cveInput.findings,
          rows: [],
          loadedCount: 0,
          totalCount: 0,
          available: true,
        },
        attack: {
          ...cveInput.attack,
          graph: null,
          available: false,
          freshness: "unavailable" as const,
        },
      });

      expect(context.coverage.findings).toMatchObject({
        visible_count: 0,
        total_count: 0,
        complete: true,
        truncated: false,
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "attack_path", status: "unavailable" }),
        ]),
      );
    });

    it("omits attack-path context when the page does not supply an attack section", () => {
      const context = buildCveDetailCopilotContext({ ...cveInput, attack: undefined });

      expect(context.coverage).not.toHaveProperty("attack_path");
      expect(context.snapshot.freshness.some((item) => item.source === "attack_path")).toBe(false);
      expect(context.snapshot.evidence.some((item) =>
        JSON.stringify(item).includes("attack_path"))).toBe(false);
      expect(context.starterQuestions.some((starter) =>
        starter.tool === "cve_attack_path")).toBe(false);
    });


    const situationsInput = {
      scope: { subscription: ["sub-a"] },
      situations: [
        {
          situation_id: "situation://p1",
          resource_id: "situation://p1",
          title: "Database unavailable",
          situation_type: "service_health",
          lifecycle_state: "open",
          severity: "critical",
          priority: "P1" as const,
          scope: { subscription: ["sub-a"] },
          owner: "SRE",
          support_team: "Platform",
          affected_resource_ids: ["/subscriptions/sub-a/db"],
          linked_evidence_ids: [],
          started_at: "2026-08-25T01:00:00Z",
          last_observed_at: "2026-08-25T01:00:00Z",
          evidence_state: "corroborated",
          warnings: [],
          contradiction_ids: [],
          unknowns: [],
          run_id: "run-1",
        },
      ],
      query: "payments",
      priority: "P1" as const,
      page: 1,
      pageSize: 25,
      totalCount: 40,
      nextOffset: 50,
      selectedSituationId: "situation://p1",
      available: true,
      observedAt: "2026-08-25T01:00:00Z",
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "situations",
          timestamp: "2026-08-25T01:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("preserves situation filters, selected identity, source trust, and visible/total pagination", () => {
      const context = buildSituationsCopilotContext(situationsInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "incident",
        page_id: "situations",
        filters: {
          query: ["payments"],
          priority: ["P1"],
          page: ["1"],
        },
      });
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "operations",
          kind: "situation",
          source_key: "situation://p1",
        },
      ]);
      expect(context.coverage.situations).toMatchObject({
        visible_count: 1,
        total_count: 40,
        complete: false,
        truncated: true,
      });
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "operations",
                kind: "situation",
                source_key: "situation://p1",
              },
              selected: true,
            }),
          }),
        ]),
      );
      expect(context.starterQuestions.length).toBeGreaterThan(0);
    });

    it("keeps an unavailable situations provider distinct from an empty authorized queue", () => {
      const unavailable = buildSituationsCopilotContext({
        ...situationsInput,
        situations: [],
        totalCount: 0,
        nextOffset: null,
        selectedSituationId: null,
        available: false,
        evidence: [],
      });
      const empty = buildSituationsCopilotContext({
        ...situationsInput,
        situations: [],
        totalCount: 0,
        nextOffset: null,
        selectedSituationId: null,
        available: true,
        evidence: [],
      });

      expect(unavailable.coverage.situations.complete).toBe(false);
      expect(empty.coverage.situations.complete).toBe(true);
      expect(unavailable.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "situations", status: "unavailable" }),
        ]),
      );
    });
  });

  describe("remediation Copilot page adapter", () => {
    type RemediationContext = ReturnType<typeof buildRemediationCopilotContext>;
    const planRow = (ctx: RemediationContext) =>
      ctx.snapshot.evidence.find((row) => row.data.claim_type === "remediation_plan");
    const historicalRows = (ctx: RemediationContext) =>
      ctx.snapshot.evidence.filter((row) => row.data.claim_type === "historical_finding");

    const remediationInput = {
      scope: { subscription: ["sub-a"] },
      selectedPlan: {
        plan_id: "plan-1",
        action_id: "controlled-patch-recovery",
        action_version: "version-1",
        title: "Patch payroll database",
        status: "Draft - Approval Required",
        family: "patch",
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        resource_type: "Microsoft.Compute/virtualMachines",
        resource_name: "vm-1",
        snapshot_hash: "snapshot-hash-1",
      },
      eligibility: {
        plan_executable: false,
        plan_ineligibility_reason: "not_approved",
        can_operate: false,
        operate_ineligible_reason: "approval_not_current",
        can_approve: true,
        approval_current: false,
        approval_status: "none",
        has_executable_preview: true,
        recommended_step: "approve",
      },
      requirements: [
        {
          policy_id: "change-control",
          role: "Change Manager",
          stage: "Planning",
          satisfied: false,
          unmet_reason: "pending",
        },
      ],
      execution: null,
      evidence: [
        {
          source_engine: "ARG",
          source_table: "securityresources",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
      historicalEvidence: [
        {
          key: "thread-finding-1",
          summary: "Earlier thread said this was already runnable",
          observedAt: "2026-09-01T00:00:00Z",
        },
      ],
      coverage: { visiblePlanCount: 2, totalPlanCount: 6 },
      sourceStatuses: [
        {
          source: "plans",
          availability: "available" as const,
          freshness: "fresh",
          observedAt: "2026-09-07T10:00:00Z",
        },
        { source: "assessment", availability: "degraded" as const, freshness: "stale" },
      ],
    };

    it("binds current server plan identity, eligibility, coverage, and freshness, labeling carried history non-current", () => {
      const context = buildRemediationCopilotContext(remediationInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "remediation",
        page_id: "remediation",
      });
      // Selected plan carried with current, read-only server eligibility facts.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "remediation_plan",
              current: true,
              actionable: false,
              mutation_authorized: false,
              plan_executable: false,
              can_operate: false,
              can_approve: true,
              approval_current: false,
              approval_status: "none",
              has_executable_preview: true,
              recommended_step: "approve",
            }),
          }),
        ]),
      );
      // Plan resource identity is a canonical ARM entity.
      expect(planRow(context)?.data.entity).toMatchObject({
        type: "azure",
        resource_id:
          "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
      });
      // Approval requirement lifecycle is carried as current context.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "approval_requirement",
              current: true,
              satisfied: false,
              role: "Change Manager",
            }),
          }),
        ]),
      );
      // Historical carried evidence is explicitly non-current and inert.
      expect(historicalRows(context)).toHaveLength(1);
      expect(historicalRows(context).every((row) =>
        row.data.current === false
        && row.data.actionable === false
        && row.data.mutation_authorized === false)).toBe(true);
      // Visible/total plan coverage and degraded freshness are projected.
      expect(context.coverage).toMatchObject({
        plans: { visible_count: 2, total_count: 6, complete: false, truncated: true },
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "assessment", status: "stale" }),
        ]),
      );
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["plans coverage is truncated"]),
      );
    });

    it("lets current server eligibility override historical thread context", () => {
      const withoutHistory = buildRemediationCopilotContext({
        ...remediationInput,
        historicalEvidence: [],
      });
      const withStaleOperableClaim = buildRemediationCopilotContext({
        ...remediationInput,
        historicalEvidence: [
          {
            key: "thread-finding-1",
            summary: "Copilot previously reported can_operate:true",
            observedAt: "2026-09-01T00:00:00Z",
          },
          {
            key: "thread-finding-2",
            summary: "approved earlier in the thread",
            observedAt: "2026-09-02T00:00:00Z",
          },
        ],
      });

      // Eligibility facts come only from the current server projection.
      expect(planRow(withStaleOperableClaim)?.data).toMatchObject({
        can_operate: false,
        can_approve: true,
        approval_current: false,
        plan_executable: false,
      });
      expect(planRow(withStaleOperableClaim)?.data.can_operate).toEqual(
        planRow(withoutHistory)?.data.can_operate,
      );
      // No carried history row is ever actionable or mutation-authorized.
      expect(historicalRows(withStaleOperableClaim).every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("exposes no Copilot mutation path across plan, approval, execution, or history evidence", () => {
      const context = buildRemediationCopilotContext({
        ...remediationInput,
        execution: {
          execution_id: "RME-1",
          status: "running",
          retryable: false,
          cancellable: false,
          supersedable: false,
          remaining_attempts: 2,
        },
      });

      expect(context.snapshot.evidence.length).toBeGreaterThan(0);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
      // Execution state is descriptive, current, and non-authorizing.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "remediation_execution",
              current: true,
              status: "running",
              actionable: false,
              mutation_authorized: false,
            }),
          }),
        ]),
      );
      // Advisory starter hints only: no approve/execute/run/write tool.
      expect(context.starterQuestions.length).toBeGreaterThan(0);
      expect(context.starterQuestions.every((starter) =>
        starter.specialistId === "remediation"
        && !/approve|execute|run|write|update|delete|remediate|cancel|retry|supersede/i.test(
          starter.tool ?? "",
        ))).toBe(true);
    });

    it("retains deterministic cited server evidence independent of optional narration", () => {
      const context = buildRemediationCopilotContext(remediationInput);
      expect(context.snapshot.evidence.some((row) =>
        row.data.claim_type === "source_observation")).toBe(true);
      expect(context.snapshot.evidence.some((row) =>
        row.data.claim_type === "remediation_plan")).toBe(true);
    });

    it("keeps a bounded context when no plan is selected yet", () => {
      const context = buildRemediationCopilotContext({
        ...remediationInput,
        selectedPlan: null,
        eligibility: null,
        requirements: [],
        execution: null,
        historicalEvidence: [],
        coverage: { visiblePlanCount: 0, totalPlanCount: 0 },
      });
      expect(context.snapshot.page_kind).toBe("remediation");
      expect(planRow(context)).toBeUndefined();
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });
  });

  describe("defender posture, KB detail, and patch priority Copilot page adapters", () => {
    type CoreContext = ReturnType<typeof buildDefenderPostureCopilotContext>;
    const rowByClaim = (ctx: CoreContext, claim: string) =>
      ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

    const defenderInput = {
      scope: { subscription: ["sub-a"] },
      selectedAssetId:
        "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
      overview: {
        value: {
          active_alert_count: 7,
          critical_alert_count: 2,
          attack_path_count: 3,
          unhealthy_recommendation_count: 11,
          vulnerable_container_image_count: 4,
          container_image_cve_count: 19,
        },
        loadedCount: 1,
        totalCount: 1,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T10:00:00Z",
        evidence: [
          {
            source_engine: "ARG",
            source_table: "securityresources",
            timestamp: "2026-09-07T10:00:00Z",
            confidence: "high" as const,
            freshness: "fresh" as const,
          },
        ],
      },
      secureScore: {
        value: { current: 42, max: 60, percentage: 70 },
        loadedCount: 1,
        totalCount: 1,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T09:45:00Z",
      },
      findings: {
        value: [
          {
            assessment_id: "assess-1",
            asset_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            asset_name: "vm-1",
            resource_type: "Microsoft.Compute/virtualMachines",
            defender_plan: "Servers",
            status: "Unhealthy",
            severity: "High",
            recommendation: "Enable endpoint protection",
            business_service: "Payments",
            last_assessed_at: "2026-09-07T09:00:00Z",
          },
        ],
        loadedCount: 1,
        totalCount: 5,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T09:00:00Z",
      },
      alerts: {
        value: [
          { id: "alert-1", title: "Suspicious sign-in", severity: "High", status: "Active" },
        ],
        loadedCount: 1,
        totalCount: 7,
        freshness: "partial" as const,
        available: true,
        observedAt: "2026-09-07T08:00:00Z",
      },
      attackPaths: {
        value: [
          { id: "path-1", title: "Internet to DB", potentialImpact: "Data exfiltration", nodeCount: 4 },
        ],
        loadedCount: 1,
        totalCount: 3,
        freshness: "fresh" as const,
        available: true,
        observedAt: "2026-09-07T08:30:00Z",
      },
      containers: {
        value: [],
        loadedCount: 0,
        totalCount: 0,
        freshness: "unavailable" as const,
        available: false,
      },
      evidence: [],
    };

    it("binds selected Defender asset, posture aggregates, coverage, and unavailable-vs-empty status", () => {
      const context = buildDefenderPostureCopilotContext(defenderInput);
      const reordered = buildDefenderPostureCopilotContext({
        ...defenderInput,
        findings: {
          ...defenderInput.findings,
          value: [...defenderInput.findings.value].reverse(),
        },
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "defender-posture",
      });
      // Selected finding asset is a canonical ARM selected entity.
      expect(context.selectedEntities).toEqual([
        {
          type: "azure",
          resource_id:
            "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
        },
      ]);
      // Posture aggregate carried as descriptive, non-actionable evidence.
      expect(rowByClaim(context, "defender_overview")[0]?.data).toMatchObject({
        active_alert_count: 7,
        critical_alert_count: 2,
        attack_path_count: 3,
        unhealthy_recommendation_count: 11,
        actionable: false,
        mutation_authorized: false,
      });
      // Visible/total coverage across sections; empty is not truncated.
      expect(context.coverage).toMatchObject({
        findings: { visible_count: 1, total_count: 5, complete: false, truncated: true },
        alerts: { visible_count: 1, total_count: 7, complete: false, truncated: true },
        attack_paths: { visible_count: 1, total_count: 3, complete: false, truncated: true },
        containers: { visible_count: 0, total_count: 0, complete: false, truncated: false },
      });
      // Unavailable container feed is distinct from a healthy empty result.
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "containers", status: "unavailable" }),
          expect.objectContaining({ source: "alerts", status: "partial" }),
          expect.objectContaining({ source: "findings", status: "fresh" }),
        ]),
      );
      // Deterministic identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      // No definitive safety claim: everything non-actionable/non-authorized.
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
      // Advisory specialist hints only.
      expect(context.starterQuestions.length).toBeGreaterThan(0);
      expect(context.starterQuestions.every((starter) =>
        ["vulnerability", "remediation"].includes(starter.specialistId)
        && !/write|update|delete|execute|remediate|approve|run/i.test(starter.tool ?? ""))).toBe(true);
    });

    const kbInput = {
      scope: { subscription: ["sub-a"] },
      kbId: "KB5001",
      kb: {
        kb_id: "KB5001",
        title: "September cumulative update",
        product: "Windows Server 2022",
        severity: "critical",
        published_at: "2026-09-01T00:00:00Z",
        target_date: "2026-09-30",
        cve_ids: ["CVE-2026-0001", "CVE-2026-0002"],
        affected_servers: ["srv-1", "srv-2"],
        affected_server_count: 137,
        affected_servers_truncated: true,
        affected_business_services: ["Payments"],
      },
      findings: {
        rows: [
          {
            target_id:
              "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
            server_id: "srv-1",
            cve_id: "CVE-2026-0001",
            product_name: "Windows Server 2022",
            target_date: "2026-09-30",
            application: "Ledger",
            business_service: "Payments",
            severity: "critical",
            reachable: true,
          },
        ],
        loadedCount: 1,
        totalCount: 4,
        available: true,
        freshness: "fresh" as const,
        observedAt: "2026-09-07T10:00:00Z",
      },
      sources: [
        { key: "msrc", freshness: "fresh" as const, available: true, observedAt: "2026-09-07T08:00:00Z" },
        { key: "nvd", freshness: "partial" as const, available: true, observedAt: "2026-09-07T07:00:00Z" },
        { key: "epss", freshness: "unavailable" as const, available: false },
      ],
      filters: { target_kind: ["server"], page: ["1"] },
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "kb_findings",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "high" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("carries the canonical non-ARM KB identity, CVE/machine identities, freshness, and coverage", () => {
      const context = buildKbDetailCopilotContext(kbInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "kb:KB5001",
      });
      // KB is a canonical non-ARM (domain) selected identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "vulnerability",
          kind: "kb",
          source_key: "KB5001",
        },
      ]);
      // KB must not leak into scope-validated resource fields.
      expect(context.snapshot.selected_resources).toEqual([]);
      // CVE identities retained.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              product: "Windows Server 2022",
              published_at: "2026-09-01T00:00:00Z",
              target_date: "2026-09-30",
              affected_server_count: 137,
              affected_servers_truncated: true,
            }),
          }),
          expect.objectContaining({
            data: expect.objectContaining({
              entity: {
                type: "domain",
                namespace: "vulnerability",
                kind: "cve",
                source_key: "CVE-2026-0001",
              },
            }),
          }),
          // Affected machine finding is a canonical ARM identity.
          expect.objectContaining({
            data: expect.objectContaining({
              product_name: "Windows Server 2022",
              target_date: "2026-09-30",
              entity: {
                type: "azure",
                resource_id:
                  "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage.findings).toMatchObject({
        visible_count: 1,
        total_count: 4,
        complete: false,
        truncated: true,
      });
      // Lifecycle enrichment freshness downgrades; unavailable distinct.
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "msrc", status: "fresh" }),
          expect.objectContaining({ source: "nvd", status: "partial" }),
          expect.objectContaining({ source: "epss", status: "unavailable" }),
        ]),
      );
      expect(context.snapshot.filters).toMatchObject({ target_kind: ["server"], page: ["1"] });
      const canonical = normalizeCopilotSnapshotV2(context.snapshot);
      expect(canonical.filters).toEqual({
        page: ["1"],
        target_kind: ["server"],
      });
      expect(canonical.query).toBe("");
      expect(canonical.generation_id).toMatch(/^generation:[a-f0-9]{64}$/);
      // Patch specialist hints, never mutating.
      expect(context.starterQuestions.every((starter) =>
        ["vulnerability", "remediation"].includes(starter.specialistId)
        && !/write|update|delete|execute|remediate|approve|run/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("distinguishes an unavailable KB provider from a healthy empty finding set", () => {
      const unavailable = buildKbDetailCopilotContext({ ...kbInput, kb: null });
      expect(unavailable.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "kb", status: "unavailable" }),
        ]),
      );
      const empty = buildKbDetailCopilotContext({
        ...kbInput,
        findings: { ...kbInput.findings, rows: [], loadedCount: 0, totalCount: 0 },
      });
      expect(empty.coverage.findings).toMatchObject({
        visible_count: 0,
        total_count: 0,
        complete: true,
        truncated: false,
      });
    });

    const patchInput = {
      scope: { subscription: ["sub-a"] },
      rows: [
        {
          exposure_id: "exp-1",
          target_id:
            "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
          weakness_id: "CVE-2026-0001",
          missing_kb: "KB5001",
          server_id: "srv-1",
          application: "Ledger",
          business_service: "Payments",
          severity: "critical",
          priority_score: 92,
          recommendation: "Deploy KB5001",
          sla_state: "overdue",
          sla_overdue: true,
        },
        {
          exposure_id: "exp-2",
          target_id: "srv-2",
          weakness_id: "CVE-2026-0002",
          missing_kb: "KB5002",
          severity: "high",
          priority_score: 71,
          sla_state: "open",
          sla_overdue: false,
        },
      ],
      loadedCount: 2,
      totalCount: 8,
      available: true,
      freshness: "partial" as const,
      observedAt: "2026-09-07T09:30:00Z",
      selectedId: "exp-1",
      filters: { source_family: ["patch"], page: ["1"] },
      sort: { priority_score: "desc" as const },
      evidence: [
        {
          source_engine: "Fabric",
          source_table: "patch_priorities",
          timestamp: "2026-09-07T09:30:00Z",
          confidence: "high" as const,
          freshness: "aging" as const,
        },
      ],
      sourceStatuses: [
        { source: "patch_priorities", freshness: "partial", observedAt: "2026-09-07T09:30:00Z" },
      ],
    };

    it("binds patch priority KB/CVE/machine identities, SLA evidence, freshness, and truncation", () => {
      const context = buildPatchPrioritiesCopilotContext(patchInput);
      const reordered = buildPatchPrioritiesCopilotContext({
        ...patchInput,
        rows: [...patchInput.rows].reverse(),
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "vulnerability",
        page_id: "patch-priorities",
      });
      // Selected patch row with a canonical ARM machine identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "azure",
          resource_id:
            "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
        },
      ]);
      // KB/CVE evidence and SLA facts retained and non-actionable.
      const selectedPatch = rowByClaim(context, "patch_priority").find(
        (row) => row.data.exposure_id === "exp-1",
      );
      expect(selectedPatch?.data).toMatchObject({
        missing_kb: "KB5001",
        weakness_id: "CVE-2026-0001",
        priority_score: 92,
        sla_overdue: true,
        actionable: false,
        mutation_authorized: false,
      });
      expect(context.coverage.patch_priorities).toMatchObject({
        visible_count: 2,
        total_count: 8,
        complete: false,
        truncated: true,
      });
      expect(context.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "patch_priorities", status: "partial" }),
        ]),
      );
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["patch_priorities coverage is truncated"]),
      );
      // Deterministic identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      expect(context.starterQuestions.every((starter) =>
        ["vulnerability", "remediation"].includes(starter.specialistId)
        && !/write|update|delete|execute|remediate|approve|run/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });
  });

  describe("changes and predeploy Copilot page adapters", () => {
    type CoreContext = ReturnType<typeof buildChangesCopilotContext>;
    const rowByClaim = (ctx: CoreContext, claim: string) =>
      ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

    const changesInput = {
      scope: { subscription: ["sub-a"] },
      changes: [
        {
          event_id: "evt-1",
          incident_id: "inc-1",
          incident_title: "Payment latency spike",
          event_type: "deployment_change",
          summary: "Deployed ledger v42",
          source: "github",
          timestamp: "2026-09-07T10:00:00Z",
          business_services: ["Payments"],
        },
        {
          event_id: "evt-2",
          incident_id: "inc-2",
          incident_title: "DNS flap",
          event_type: "config_change",
          summary: "Updated firewall rule",
          source: "terraform",
          timestamp: "2026-09-07T09:00:00Z",
          business_services: ["Networking"],
        },
      ],
      loadedCount: 2,
      totalCount: 6,
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-09-07T10:00:00Z",
      selectedId: "evt-1",
      filters: { event_type: ["change"], page: ["1"] },
      evidence: [
        {
          source_engine: "Situations",
          source_table: "incident_timeline",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "medium" as const,
          freshness: "fresh" as const,
        },
      ],
      sourceStatuses: [
        { source: "changes", freshness: "fresh", observedAt: "2026-09-07T10:00:00Z" },
      ],
    };

    it("binds correlated change identities, proximity basis, coverage, and cross-domain hints", () => {
      const context = buildChangesCopilotContext(changesInput);
      const reordered = buildChangesCopilotContext({
        ...changesInput,
        changes: [...changesInput.changes].reverse(),
      });

      expect(context.snapshot).toMatchObject({
        page_kind: "incident",
        page_id: "changes",
      });
      // Change correlation is a stable domain identity.
      const selectedChange = rowByClaim(context, "change_correlation").find(
        (row) => row.data.event_id === "evt-1",
      );
      expect(selectedChange?.data).toMatchObject({
        entity: {
          type: "domain",
          namespace: "change",
          kind: "change_correlation",
          source_key: "evt-1",
        },
        incident_id: "inc-1",
        event_type: "deployment_change",
        // Correlation is not causation: proximity only, never confirmed.
        correlation_basis: "temporal_proximity",
        confirmed: false,
        actionable: false,
        mutation_authorized: false,
      });
      expect(context.coverage.changes).toMatchObject({
        visible_count: 2,
        total_count: 6,
        complete: false,
        truncated: true,
      });
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["changes coverage is truncated"]),
      );
      // Deterministic identities regardless of input order.
      expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
        reordered.snapshot.evidence.map((row) => row.evidence_id),
      );
      // Cross-domain starters: change list can select change plus
      // incident/remediation specialists, and none mutate state.
      const specialists = new Set(context.starterQuestions.map((s) => s.specialistId));
      expect(specialists.has("incident")).toBe(true);
      expect(specialists.has("remediation")).toBe(true);
      expect(context.starterQuestions.every((starter) =>
        ["incident", "remediation", "vulnerability"].includes(starter.specialistId)
        && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    const predeployInput = {
      scope: { subscription: ["sub-a"] },
      change: {
        change_id: "chg-1",
        title: "Scale payments API",
        author: "release-bot",
        source: "terraform_plan",
        target_environment: "prod",
        resource_change_count: 3,
      },
      simulation: {
        highest_severity: "high",
        simulated_domains: ["compute", "network"],
        by_severity: { high: 1, medium: 2 },
        effect_count: 3,
        confirmed_outcome: false,
      },
      risk: {
        score: 68,
        level: "elevated",
        confidence: "medium",
        confirmed_cause: false,
      },
      cab: {
        verdict: "review_required",
        risk_level: "elevated",
        required_approvals: ["Change Manager"],
        confirmed_cause: false,
      },
      impactedResources: [
        {
          resource_id:
            "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
          resource_name: "vm-1",
          business_service: "Payments",
          environment: "prod",
          relationship: "depends_on",
        },
      ],
      impactedTotalCount: 5,
      impactedTruncated: true,
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-09-07T10:00:00Z",
      unknowns: ["Downstream DNS effect not simulated"],
      evidence: [
        {
          source_engine: "Assessment",
          source_table: "change_assessment",
          timestamp: "2026-09-07T10:00:00Z",
          confidence: "medium" as const,
          freshness: "fresh" as const,
        },
      ],
    };

    it("carries predeploy simulation/risk/CAB as predicted, never observed, with impacted-resource coverage", () => {
      const context = buildPredeployCopilotContext(predeployInput);

      expect(context.snapshot).toMatchObject({
        page_kind: "governance",
        page_id: "predeploy",
      });
      // Proposed change is the selected domain identity.
      expect(context.selectedEntities).toEqual([
        {
          type: "domain",
          namespace: "change",
          kind: "proposed_change",
          source_key: "chg-1",
        },
      ]);
      // Simulation/risk/CAB are explicitly predicted, not observed outcomes.
      const simulation = rowByClaim(context, "change_simulation")[0]?.data;
      expect(simulation).toMatchObject({
        highest_severity: "high",
        confirmed_outcome: false,
        predicted: true,
        observed: false,
        actionable: false,
        mutation_authorized: false,
      });
      const risk = rowByClaim(context, "change_risk")[0]?.data;
      expect(risk).toMatchObject({ score: 68, confirmed_cause: false, predicted: true, observed: false });
      const cab = rowByClaim(context, "cab_recommendation")[0]?.data;
      expect(cab).toMatchObject({
        verdict: "review_required",
        confirmed_cause: false,
        predicted: true,
        observed: false,
      });
      // Impacted resource is a canonical ARM identity.
      expect(context.snapshot.evidence).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            data: expect.objectContaining({
              claim_type: "impacted_resource",
              entity: {
                type: "azure",
                resource_id:
                  "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
              },
            }),
          }),
        ]),
      );
      expect(context.coverage.impacted_resources).toMatchObject({
        visible_count: 1,
        total_count: 5,
        complete: false,
        truncated: true,
      });
      expect(context.uncertainty).toEqual(
        expect.arrayContaining(["impacted_resources coverage is truncated"]),
      );
      // Cross-domain hints reach incident/remediation specialists; none mutate.
      const specialists = new Set(context.starterQuestions.map((s) => s.specialistId));
      expect(specialists.has("remediation")).toBe(true);
      expect(context.starterQuestions.every((starter) =>
        !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
      expect(context.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });

    it("keeps healthy-empty predeploy distinct from unavailable assessment state", () => {
      const emptyInput = {
        ...predeployInput,
        change: null,
        simulation: null,
        risk: null,
        cab: null,
        impactedResources: [],
        impactedTotalCount: 0,
        impactedTruncated: false,
      };
      const healthyEmpty = buildPredeployCopilotContext({
        ...emptyInput,
        available: true,
        freshness: "fresh" as const,
      });
      const unavailable = buildPredeployCopilotContext({
        ...emptyInput,
        available: false,
        freshness: "unavailable" as const,
      });
      expect(healthyEmpty.snapshot.page_id).toBe("predeploy");
      expect(rowByClaim(healthyEmpty, "proposed_change")).toHaveLength(0);
      expect(healthyEmpty.coverage.impacted_resources.complete).toBe(true);
      expect(unavailable.coverage.impacted_resources.complete).toBe(false);
      expect(healthyEmpty.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "assessment", status: "fresh" }),
        ]),
      );
      expect(unavailable.snapshot.freshness).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ source: "assessment", status: "unavailable" }),
        ]),
      );
      expect(unavailable.snapshot.evidence.every((row) =>
        row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    });
  });

  it("matches the server bounds exactly", () => {
    expect(COPILOT_SNAPSHOT_LIMITS).toEqual({
      snapshotBytes: 128 * 1024,
      selectedEntities: 50,
      evidenceRows: 200,
      evidenceRowBytes: 8 * 1024,
      freshnessRecords: 32,
      evidenceCitations: 32,
      materialClaims: 200,
    });
  });

  it("normalizes an integrated remediation snapshot to the strict v2 wire shape", () => {
      const legacy = buildRemediationCopilotContext({
        ...corePageInput,
        filters: { view: ["remediation"] },
      }).snapshot;

      const normalized = normalizeCopilotSnapshotV2(legacy);

      expect(normalized).toMatchObject({
        version: "2",
        page_kind: "remediation",
        page_id: "remediation",
        coverage: {
          visible_count: 2,
          total_count: 5,
          complete: false,
        },
        selected_entities: expect.any(Array),
        filters: { view: ["remediation"] },
        query: "",
        generation_id: expect.stringMatching(/^generation:[a-f0-9]{64}$/),
        material_claims: expect.arrayContaining([
          expect.objectContaining({
            evidence_refs: [expect.stringMatching(/^evidence:/)],
            requires_complete_coverage: false,
          }),
        ]),
      });
      expect(normalized).not.toHaveProperty("scope");
      expect(normalized).not.toHaveProperty("question");
      expect(normalized.evidence.every((row) =>
        row.actionable === false
        && row.citations.length === 0
        && Boolean(row.entity)
        && Boolean(row.source_key))).toBe(true);
    });

  it.each([
    ["/", "resource", "operations-overview", "overview"],
    ["/network", "network", "network-topology", "network"],
    ["/compliance", "governance", "compliance-posture", "compliance"],
    ["/exposure", "vulnerability", "exposure", "exposure"],
    ["/exposure/cves/[id]", "vulnerability", "cve:CVE-2026-0001", "cve_detail"],
    ["/exposure/defender-posture", "vulnerability", "defender-posture", "defender_posture"],
    ["/exposure/kbs/[id]", "vulnerability", "kb:KB5000001", "kb_detail"],
    ["/exposure/patch-priorities", "vulnerability", "patch-priorities", "patch_priorities"],
    ["/situations", "incident", "situations", "situations"],
    ["/situations/[id]", "incident", "situation:situation-1", "situation_detail"],
    ["/changes", "incident", "changes", "changes"],
    ["/changes/predeploy", "governance", "predeploy", "changes_predeploy"],
    ["/connections", "resource", "connections", "connections"],
    ["/connections/fabric", "resource", "fabric-medallion", "connections_fabric"],
    ["/governance", "governance", "governance", "governance"],
    ["/identity", "governance", "identity", "identity"],
    ["/finops", "governance", "finops", "finops"],
    ["/remediation", "remediation", "remediation", "remediation"],
    ["/resource-health", "resource", "resource-health", "resource_health"],
    ["/services", "resource", "services", "services"],
    ["/services/[name]", "resource", "service:payments", "service_detail"],
    ["/twin", "network", "twin", "twin"],
  ] satisfies Array<[string, CopilotPageKind, string, CopilotPageKindV2]>)(
    "maps free-form legacy adapter output for %s to exact v2 page kind %s",
    (route, legacyPageKind, pageId, expectedPageKind) => {
      const legacy: CopilotPageSnapshot = {
        version: "1",
        page_kind: legacyPageKind,
        page_id: pageId,
        selected_resources: [],
        filters: {},
        freshness: [],
        scope: { declared: { subscription: ["sub-a"] }, authorized: true },
        evidence: [],
        question: "Tell me what matters on this page.",
        rechecks: [],
      };

      expect(normalizeCopilotSnapshotV2(legacy).page_kind).toBe(expectedPageKind);
      expect(COPILOT_ROUTE_DISPOSITIONS[route]).toMatchObject({
        kind: "integrated",
        pageKind: expectedPageKind,
      });
    },
  );

  it("keeps the inventory adapter's exact v2 page kind without a routing hint", () => {
    const inventory = buildInventoryCopilotContext(baseInput).snapshot;

    expect(normalizeCopilotSnapshotV2(inventory).page_kind).toBe("inventory");
    expect(COPILOT_ROUTE_DISPOSITIONS["/inventory"]).toMatchObject({
      kind: "integrated",
      pageKind: "inventory",
    });
  });

  it("does not fabricate legacy coverage from arbitrary evidence rows", () => {
    const legacy: CopilotPageSnapshot = {
      version: "1",
      page_kind: "resource",
      page_id: "services",
      selected_resources: [],
      filters: {},
      freshness: [],
      scope: { declared: { subscription: ["sub-a"] }, authorized: true },
      evidence: [{
        evidence_id: "service:one",
        section: "services",
        status: "ok",
        data: { name: "payments" },
      }],
      question: "Summarize this page.",
      rechecks: [],
    };

    expect(normalizeCopilotSnapshotV2(legacy).coverage).toEqual({
      visible_count: 0,
      total_count: 0,
      complete: false,
    });
  });

  it.each([
      [127, true],
      [128, true],
      [129, false],
    ])(
      "enforces the shared source character boundary at %i characters",
      (sourceLength, accepted) => {
        const snapshot = buildInventoryCopilotContext(baseInput).snapshot;
        snapshot.evidence[0] = {
          ...snapshot.evidence[0],
          source: "界".repeat(sourceLength),
        };
        const action = () => normalizeCopilotSnapshotV2(snapshot);
        if (accepted) expect(action).not.toThrow();
        else expect(action).toThrow(/source/i);
      },
    );

  it.each([
      [8, true],
      [9, true],
      [10, false],
    ])(
      "enforces the shared 8191/8192/8193-byte UTF-8 row boundary",
      (suffixLength, accepted) => {
        const snapshot = buildInventoryCopilotContext(baseInput).snapshot;
        snapshot.evidence[0] = {
          ...snapshot.evidence[0],
          data: { blob: `${"😀".repeat(681)}${"x".repeat(suffixLength)}` },
        };
        const action = () => normalizeCopilotSnapshotV2(snapshot);
        if (accepted) expect(action).not.toThrow();
        else expect(action).toThrow(/evidence row/i);
      },
    );

  it.each([
      [COPILOT_SNAPSHOT_LIMITS.evidenceRows - 1, true],
      [COPILOT_SNAPSHOT_LIMITS.evidenceRows, true],
      [COPILOT_SNAPSHOT_LIMITS.evidenceRows + 1, false],
    ])(
      "enforces the shared evidence-list structural boundary at %i rows",
      (rowCount, accepted) => {
        const base = buildInventoryCopilotContext(baseInput).snapshot;
        const template = base.evidence[0];
        const snapshot = {
          ...base,
          coverage: {
            visible_count: rowCount,
            total_count: rowCount,
            complete: true,
          },
          evidence: Array.from({ length: rowCount }, (_, index) => ({
            ...template,
            evidence_id: `row-${index}`,
            source_key: `row-${index}`,
            entity: {
              type: "domain" as const,
              namespace: "inventory",
              kind: "row",
              source_key: `row-${index}`,
            },
          })),
        };
        const action = () => normalizeCopilotSnapshotV2(snapshot);
        if (accepted) expect(action).not.toThrow();
        else expect(action).toThrow(/evidence rows/i);
      },
    );
  it("builds the complete strict v2 wire contract without authority fields", () => {
    const context = buildInventoryCopilotContext(baseInput);

    expect(context.requestedScope).toEqual({
      subscription: ["sub-a"],
    });
    expect(context.snapshot).toMatchObject({
      version: "2",
      page_kind: "inventory",
      page_id: "inventory:os",
      coverage: {
        visible_count: 2,
        total_count: 4,
        complete: false,
      },
      material_claims: [],
    });
    expect(context.snapshot).not.toHaveProperty("authorized");
    expect(context.snapshot.selected_entities).toEqual([
      {
        type: "domain",
        namespace: "inventory",
        kind: "os_group",
        source_key: "Windows Server|2019",
      },
    ]);
    expect(context.snapshot.evidence[0]).toMatchObject({
      source_key: expect.any(String),
      entity: expect.objectContaining({ type: expect.any(String) }),
      claim_type: expect.any(String),
      citations: [],
      selected: expect.any(Boolean),
      direct: true,
      actionable: false,
      severity: "unknown",
      quality: "high",
    });
    expect(context.snapshot.evidence[0].data.inventory_context).toEqual({
      tab: "os",
      filters: { lifecycle: "supported", search: "windows" },
      sort: { os_name: "asc" },
      offset: 0,
      limit: 50,
    });
    expect(
      context.snapshot.evidence.find((item) => item.selected)?.data.selected,
    ).toBe(true);
    expect(context.uncertainty).toEqual([
      "visible subset is incomplete",
      "arc freshness is partial",
    ]);
    expect(context.starterQuestions[0]).toMatchObject({
      specialistId: "inventory_data_health",
      tool: "inventory_resources",
      toolArguments: {},
    });
  });

  it("emits discriminated canonical Azure and non-Azure entities", () => {
    const snapshot = buildInventoryCopilotContext(baseInput).snapshot;
    const domain = snapshot.evidence.find(
      (item) => item.source === "inventory/os_observations",
    );
    const azure = snapshot.evidence.find(
      (item) => item.source === "inventory/resource_observations",
    );

    expect(domain?.entity).toEqual({
      type: "domain",
      namespace: "inventory",
      kind: "os_group",
      source_key: "Windows Server|2019",
    });
    expect(domain?.resource_id).toBe("");
    expect(azure?.entity).toEqual({
      type: "azure",
      resource_id:
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.app/containerapps/app-1",
    });
    expect(azure?.resource_id).toBe(
      "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.app/containerapps/app-1",
    );
  });

  it("matches the backend stable evidence key algorithm", () => {
    expect(
      canonicalEvidenceStableId({
        source: "inventory/os_observations",
        sourceKey: "Windows Server|2019",
        entity: {
          type: "domain",
          namespace: "inventory",
          kind: "os_group",
          source_key: "Windows Server|2019",
        },
        claimType: "os_group",
      }),
    ).toBe("evidence:8260f36a5239818a9fbe280261d162e5");
    expect(
      canonicalEvidenceStableId({
        source: "inventory/os_observations",
        sourceKey: "Straße",
        entity: {
          type: "domain",
          namespace: "inventory",
          kind: "os_group",
          source_key: "Straße",
        },
        claimType: "os_group",
      }),
    ).toBe("evidence:5a5a89948c9154eb1044111a3cc48a88");
    expect(
      canonicalEvidenceStableId({
        source: "inventory/resource_observations",
        sourceKey: "ẞ",
        entity: {
          type: "azure",
          resource_id:
            "/subscriptions/SUB-A/resourceGroups/Straße/providers/Microsoft.Test/widgets/ẞ",
        },
        claimType: "azure_group",
      }),
    ).toBe("evidence:691f8afa04ab5d7e4dd94f41aade18e1");
  });

  it("keeps stable keys and serialization unchanged across reorder and refresh", () => {
    const first = buildInventoryCopilotContext(baseInput);
    const reordered = buildInventoryCopilotContext({
      ...baseInput,
      records: [...records]
        .reverse()
        .map((record) => ({
          ...record,
          observedAt: "2026-09-06T10:00:00Z",
        })),
      sourceStatuses: [...baseInput.sourceStatuses].reverse(),
    });

    expect(first.snapshot.evidence.map((item) => item.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((item) => item.evidence_id),
    );
    expect(first.snapshot.evidence.map((item) => item.source_key)).toEqual(
      reordered.snapshot.evidence.map((item) => item.source_key),
    );
    const withoutObservationTimes = (value: string) =>
      value.replaceAll(/2026-(08-25|09-06)T\d{2}:00:00Z/g, "OBSERVED");
    expect(
      withoutObservationTimes(serializeCopilotSnapshot(first.snapshot)),
    ).toBe(
      withoutObservationTimes(serializeCopilotSnapshot(reordered.snapshot)),
    );
  });

  it("preserves pagination mismatch and unavailable source uncertainty", () => {
    const context = buildInventoryCopilotContext({
      ...baseInput,
      records: records.slice(0, 1),
      totalCount: 20,
      offset: 10,
      limit: 10,
      sourceStatuses: [
        {
          source: "arc",
          status: "unavailable",
        },
      ],
    });

    expect(context.snapshot.coverage).toEqual({
      visible_count: 1,
      total_count: 20,
      complete: false,
    });
    expect(context.snapshot.freshness).toEqual([
      {
        source: "inventory/os_observations",
        observed_at: "unknown",
        status: "unavailable",
      },
    ]);
    expect(context.uncertainty).toEqual([
      "visible subset is incomplete",
      "arc freshness is unavailable",
    ]);
  });

  it("serializes object keys deterministically regardless of insertion order", () => {
    const left = buildInventoryCopilotContext({
      ...baseInput,
      records: [{
        ...records[0],
        data: { zed: 1, "éclair": 2, alpha: 3 },
      }],
      totalCount: 1,
    }).snapshot;
    const right = buildInventoryCopilotContext({
      ...baseInput,
      records: [{
        ...records[0],
        data: { alpha: 3, "éclair": 2, zed: 1 },
      }],
      totalCount: 1,
    }).snapshot;

    expect(serializeCopilotSnapshot(left)).toBe(serializeCopilotSnapshot(right));
  });

  it("preserves contradictory values as stable conflict variants", () => {
    const conflicting = [
      {
        ...records[0],
        data: { ...records[0].data, lifecycle_status: "supported" },
      },
      {
        ...records[0],
        data: { ...records[0].data, lifecycle_status: "unsupported" },
      },
    ];

    const snapshot = buildInventoryCopilotContext({
      ...baseInput,
      records: conflicting,
      totalCount: conflicting.length,
    }).snapshot;

    expect(snapshot.evidence).toHaveLength(2);
    expect(new Set(snapshot.evidence.map((item) => item.evidence_id)).size).toBe(
      2,
    );
    expect(new Set(snapshot.evidence.map((item) => item.source_key))).toEqual(
      new Set(["Windows Server|2019"]),
    );
    expect(new Set(snapshot.evidence.map((item) => item.claim_type))).toEqual(
      new Set(["os_group"]),
    );
    expect(
      snapshot.evidence.filter((item) => item.data.selected === true),
    ).toHaveLength(1);
  });

  it("retains bounded filter context when the visible page is empty", () => {
    const snapshot = buildInventoryCopilotContext({
      ...baseInput,
      records: [],
      totalCount: 0,
    }).snapshot;

    expect(snapshot.coverage).toEqual({
      visible_count: 0,
      total_count: 0,
      complete: true,
    });
    expect(snapshot.evidence).toHaveLength(1);
    expect(snapshot.evidence[0]).toMatchObject({
      source: "inventory/os_observations",
      status: "empty",
      claim_type: "page_context",
      data: {
        inventory_context: {
          filters: { lifecycle: "supported", search: "windows" },
          sort: { os_name: "asc" },
          offset: 0,
          limit: 50,
        },
        selected: false,
      },
    });
  });

  it("merges exact duplicates independently of input order", () => {
    const duplicate = {
      ...records[0],
      status: "denied" as const,
      observedAt: "2026-08-25T09:00:00Z",
    };
    const stronger = {
      ...records[0],
      status: "ok" as const,
      observedAt: "2026-08-25T10:00:00Z",
    };
    const build = (items: InventoryCopilotRecord[]) =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: items,
        totalCount: 1,
      }).snapshot.evidence;

    expect(build([duplicate, stronger])).toEqual(build([stronger, duplicate]));
    expect(build([duplicate, stronger])).toMatchObject([
      {
        status: "denied",
        observed_at: "2026-08-25T10:00:00Z",
      },
    ]);

    const uppercase = {
      ...records[0],
      identity: "KEY",
      source: "INVENTORY/OS_OBSERVATIONS",
      data: { value: true },
    };
    const lowercase = {
      ...records[0],
      identity: "key",
      source: "inventory/os_observations",
      data: { value: true },
    };
    const buildCaseVariants = (items: InventoryCopilotRecord[]) =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: items,
        selectedIdentity: "KEY",
        totalCount: 1,
      }).snapshot.evidence;

    expect(buildCaseVariants([uppercase, lowercase])).toEqual(
      buildCaseVariants([lowercase, uppercase]),
    );
    expect(buildCaseVariants([uppercase, lowercase])).toMatchObject([
      { selected: true, data: { selected: true } },
    ]);
  });

  it("rejects invalid coverage and every server-side size bound", () => {
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        totalCount: 1,
      }),
    ).toThrow(/visible count cannot exceed total count/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: Array.from(
          { length: COPILOT_SNAPSHOT_LIMITS.evidenceRows + 1 },
          (_, index) => ({
            ...records[0],
            identity: `row-${index}`,
          }),
        ),
        totalCount: COPILOT_SNAPSHOT_LIMITS.evidenceRows + 1,
      }),
    ).toThrow(/evidence rows/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [
          {
            ...records[0],
            data: {
              blob: "x".repeat(
                COPILOT_SNAPSHOT_LIMITS.evidenceRowBytes + 1,
              ),
            },
          },
        ],
        totalCount: 1,
      }),
    ).toThrow(/evidence row/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [
          {
            ...records[0],
            data: { values: Array.from({ length: 1_500 }, () => 1e-7) },
          },
        ],
        totalCount: 1,
      }),
    ).toThrow(/evidence row/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        sourceStatuses: Array.from(
          { length: COPILOT_SNAPSHOT_LIMITS.freshnessRecords + 1 },
          (_, index) => ({
            source: `source-${index}`,
            observedAt: "2026-08-25T10:00:00Z",
            status: "fresh",
          }),
        ),
      }),
    ).toThrow(/freshness records/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [{ ...records[0], source: "x".repeat(129) }],
      }),
    ).toThrow(/evidence source/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [{ ...records[0], identity: "x".repeat(257) }],
      }),
    ).toThrow(/source key/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        filters: Object.fromEntries(
          Array.from({ length: 17 }, (_, index) => [`filter-${index}`, "value"]),
        ),
      }),
    ).toThrow(/inventory filters/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        filters: { search: "x".repeat(161) },
      }),
    ).toThrow(/inventory selector filter search/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        records: [{
          ...records[0],
          data: {
            ...records[0].data,
            os_name: "x".repeat(121),
          },
        }],
      }),
    ).toThrow(/inventory selector os_name/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        filters: {
          os_name: "x".repeat(117),
          os_version: "y".repeat(117),
        },
      }),
    ).toThrow(/resource selector/i);
    expect(() =>
      buildInventoryCopilotContext({
        ...baseInput,
        tab: "azure",
        records: [{
          ...records[1],
          data: {
            resource_type: `microsoft.test/${"x".repeat(100)}`,
            sku: "s".repeat(60),
            tier: "t".repeat(60),
          },
        }],
        selectedIdentity: "vm-1",
        totalCount: 1,
      }),
    ).toThrow(/resource selector/i);
  });
});

describe("connections, Fabric medallion, and governance Copilot page adapters", () => {
  type CoreContext = ReturnType<typeof buildConnectionsCopilotContext>;
  const rowByClaim = (ctx: CoreContext, claim: string) =>
    ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

  const connectionsInput = {
    scope: { subscription: ["sub-a"] },
    connections: [
      {
        connection_id: "prod",
        name: "Production",
        subscription_id: "00000000-0000-0000-0000-000000000001",
        business_service: "Payments",
        environment: "prod",
        criticality: "critical",
        health_status: "healthy",
        sync_status: "succeeded",
        sync_record_count: 12700,
        last_successful_sync_at: "2026-09-07T10:00:00Z",
        is_active: true,
      },
      {
        connection_id: "staging",
        name: "Staging",
        subscription_id: "00000000-0000-0000-0000-000000000002",
        business_service: "Payments",
        environment: "staging",
        criticality: "standard",
        health_status: "degraded",
        sync_status: "failed",
        sync_record_count: 0,
        last_successful_sync_at: null,
        is_active: true,
      },
    ],
    loadedCount: 2,
    totalCount: 5,
    available: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    selectedConnectionId: "prod",
    filters: { view: ["subscriptions"], page: ["1"] },
    evidence: [
      {
        source_engine: "Connections",
        source_table: "subscription_connections",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds connection source identities, capacity, deployment-blocked state, coverage, and inventory hints", () => {
    const context = buildConnectionsCopilotContext(connectionsInput);
    const reordered = buildConnectionsCopilotContext({
      ...connectionsInput,
      connections: [...connectionsInput.connections].reverse(),
    });

    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "connections",
    });
    // Each connection is a stable non-ARM source identity, never leaked into a
    // scope-validated Azure resource field.
    const selected = rowByClaim(context, "subscription_connection").find(
      (row) => row.data.connection_id === "prod",
    );
    expect(selected?.resource_id).toBeUndefined();
    expect(selected?.data).toMatchObject({
      entity: {
        type: "domain",
        namespace: "connection",
        kind: "subscription_connection",
        source_key: "prod",
      },
      health_status: "healthy",
      sync_status: "succeeded",
      record_count: 12700,
      deployment_blocked: false,
      selected: true,
      actionable: false,
      mutation_authorized: false,
    });
    // A failed sync is a distinct deployment-blocked state.
    const blocked = rowByClaim(context, "subscription_connection").find(
      (row) => row.data.connection_id === "staging",
    );
    expect(blocked?.data.deployment_blocked).toBe(true);
    expect(context.coverage.connections).toMatchObject({
      visible_count: 2,
      total_count: 5,
      complete: false,
      truncated: true,
    });
    // Deterministic identities regardless of input order.
    expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((row) => row.evidence_id),
    );
    // Inventory & Data Health hints stay exact manifest IDs and never mutate.
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "inventory_data_health"
      && starter.tool === "inventory_resources")).toBe(true);
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
  });

  it("distinguishes a healthy-empty connection registry from an unavailable one", () => {
    const healthyEmpty = buildConnectionsCopilotContext({
      ...connectionsInput,
      connections: [],
      loadedCount: 0,
      totalCount: 0,
      selectedConnectionId: null,
      available: true,
      freshness: "fresh" as const,
    });
    expect(healthyEmpty.coverage.connections).toMatchObject({
      visible_count: 0,
      total_count: 0,
      complete: true,
      truncated: false,
    });
    expect(healthyEmpty.uncertainty).not.toEqual(
      expect.arrayContaining(["connections freshness is unavailable"]),
    );

    const unavailable = buildConnectionsCopilotContext({
      ...connectionsInput,
      connections: [],
      loadedCount: 0,
      totalCount: 0,
      selectedConnectionId: null,
      available: false,
      freshness: "unavailable" as const,
    });
    expect(unavailable.coverage.connections.complete).toBe(false);
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["connections freshness is unavailable"]),
    );
  });

  const fabricInput = {
    scope: { subscription: ["sub-a"] },
    subscriptionId: "00000000-0000-0000-0000-000000000001",
    layers: [
      { layer: "bronze" as const, healthy: 4, total: 4 },
      { layer: "silver" as const, healthy: 2, total: 3 },
      { layer: "gold" as const, healthy: 0, total: 0 },
    ],
    manifest: [
      {
        projection_name: "inventory_gold",
        disposition: "active",
        compatibility_version: "v2",
        subscription_id: "00000000-0000-0000-0000-000000000001",
      },
    ],
    manifestTotalCount: 3,
    governance: {
      ownership_gap_count: 2,
      tag_gap_count: 1,
      referential_integrity_blockers: 0,
    },
    capacity: { status: "active", state: "Active", capacity_name: "cap-1" },
    semanticReadiness: { status: "ready" },
    dataAgentReadiness: { status: "not_configured", configured: false },
    lineageRef: "fabric://lineage/inventory",
    available: true,
    deploymentBlocked: false,
    freshness: "partial" as const,
    observedAt: "2026-09-07T09:30:00Z",
    evidence: [
      {
        source_engine: "Fabric",
        source_table: "medallion_health",
        timestamp: "2026-09-07T09:30:00Z",
        confidence: "medium" as const,
        freshness: "aging" as const,
      },
    ],
    sourceStatuses: [
      { source: "fabric_medallion", freshness: "partial", observedAt: "2026-09-07T09:30:00Z" },
    ],
  };

  it("binds medallion layer, manifest, governance, and readiness evidence with partial freshness", () => {
    const context = buildFabricMedallionCopilotContext(fabricInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "fabric-medallion",
    });
    const silver = rowByClaim(context, "medallion_layer").find(
      (row) => row.data.layer === "silver",
    );
    expect(silver?.data).toMatchObject({
      entity: { type: "domain", namespace: "fabric", kind: "medallion_layer", source_key: "silver" },
      healthy: 2,
      total: 3,
      actionable: false,
      mutation_authorized: false,
    });
    // Gold layer is healthy-empty (0/0), never an outage.
    const gold = rowByClaim(context, "medallion_layer").find((row) => row.data.layer === "gold");
    expect(gold?.data).toMatchObject({ healthy: 0, total: 0 });
    expect(rowByClaim(context, "fabric_manifest").length).toBe(1);
    expect(rowByClaim(context, "fabric_governance")[0]?.data).toMatchObject({
      ownership_gap_count: 2,
      tag_gap_count: 1,
      referential_integrity_blockers: 0,
    });
    expect(rowByClaim(context, "fabric_capacity")[0]?.data).toMatchObject({
      status: "active",
      data_agent_configured: false,
    });
    expect(context.coverage.manifest).toMatchObject({
      visible_count: 1,
      total_count: 3,
      truncated: true,
    });
    // Partial freshness is surfaced as uncertainty, not hidden.
    expect(context.uncertainty).toEqual(
      expect.arrayContaining(["fabric_medallion freshness is partial"]),
    );
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "inventory_data_health"
      && starter.tool === "inventory_resources")).toBe(true);
  });

  it("keeps deployment-blocked capacity distinct from an unavailable Fabric provider", () => {
    const blocked = buildFabricMedallionCopilotContext({
      ...fabricInput,
      layers: [
        { layer: "bronze" as const, healthy: 0, total: 0 },
        { layer: "silver" as const, healthy: 0, total: 0 },
        { layer: "gold" as const, healthy: 0, total: 0 },
      ],
      capacity: { status: "paused", state: "Paused", capacity_name: "cap-1" },
      deploymentBlocked: true,
      available: true,
      freshness: "fresh" as const,
      sourceStatuses: [
        { source: "fabric_medallion", availability: "blocked", freshness: "unknown" },
      ],
    });
    expect(blocked.uncertainty).toEqual(
      expect.arrayContaining(["fabric_medallion is deployment-blocked"]),
    );
    expect(rowByClaim(blocked, "fabric_capacity")[0]?.data.deployment_blocked).toBe(true);

    const unavailable = buildFabricMedallionCopilotContext({
      ...fabricInput,
      layers: [],
      manifest: [],
      manifestTotalCount: 0,
      governance: null,
      capacity: null,
      semanticReadiness: null,
      dataAgentReadiness: null,
      available: false,
      deploymentBlocked: false,
      freshness: "unavailable" as const,
      sourceStatuses: [
        { source: "fabric_medallion", availability: "unavailable", freshness: "unknown" },
      ],
    });
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["fabric_medallion freshness is unavailable"]),
    );
    expect(unavailable.uncertainty).not.toEqual(
      expect.arrayContaining(["fabric_medallion is deployment-blocked"]),
    );
  });

  const governanceInput = {
    scope: { subscription: ["sub-a"] },
    roles: [
      { role_id: "operator", name: "Operator", permissions: ["read"] },
      { role_id: "admin", name: "Administrator", permissions: ["admin", "read"] },
    ],
    rolesTotalCount: 4,
    policies: [
      { section: "onboarding_policy", setting_count: 3 },
      { section: "retention_policy", setting_count: 2 },
    ],
    accessReviewAudiences: ["security", "finance"],
    auditExportKinds: ["identity", "exposure"],
    settingsAvailable: true,
    audiencesAvailable: true,
    kindsAvailable: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    evidence: [
      {
        source_engine: "Governance",
        source_table: "enterprise_settings",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds governance roles, policies, audiences, and export kinds with bounded totals", () => {
    const context = buildGovernanceCopilotContext(governanceInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "governance",
      page_id: "governance",
    });
    const adminRole = rowByClaim(context, "governance_role").find(
      (row) => row.data.role_id === "admin",
    );
    expect(adminRole?.data).toMatchObject({
      entity: { type: "domain", namespace: "governance", kind: "governance_role", source_key: "admin" },
      privileged: true,
      actionable: false,
      mutation_authorized: false,
    });
    expect(rowByClaim(context, "governance_policy").length).toBe(2);
    // Access-review audiences are the identity-collaboration evidence.
    expect(rowByClaim(context, "access_review_audience").length).toBe(2);
    expect(rowByClaim(context, "audit_export_kind").length).toBe(2);
    expect(context.coverage.roles).toMatchObject({
      visible_count: 2,
      total_count: 4,
      truncated: true,
    });
    // Governance starters stay within the governance specialist and never mutate.
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "governance"
      && ["business_service_context", "application_context", "risk_context", "impact_context"].includes(starter.tool ?? "")
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
  });

  it("treats settings, audiences, and export kinds as independent optional sources", () => {
    const context = buildGovernanceCopilotContext({
      ...governanceInput,
      accessReviewAudiences: [],
      auditExportKinds: [],
      audiencesAvailable: false,
      kindsAvailable: false,
    });
    // Settings remain usable even when review/export enrichment is unavailable.
    expect(rowByClaim(context, "governance_role").length).toBe(2);
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "access_reviews freshness is unavailable",
        "audit_exports freshness is unavailable",
      ]),
    );
    expect(context.uncertainty).not.toEqual(
      expect.arrayContaining(["settings freshness is unavailable"]),
    );
  });
});

describe("identity, FinOps, and resource-health Copilot page adapters", () => {
  type CoreContext = ReturnType<typeof buildIdentityCopilotContext>;
  const rowByClaim = (ctx: CoreContext, claim: string) =>
    ctx.snapshot.evidence.filter((row) => row.data.claim_type === claim);

  const identityInput = {
    scope: { subscription: ["sub-a"] },
    summary: {
      principal_count: 42,
      privileged_principal_count: 3,
      stale_assignment_count: 5,
      non_human_principal_count: 8,
      assignment_count: 120,
    },
    principals: [
      {
        principal_id: "11111111-1111-1111-1111-111111111111",
        principal_type: "User",
        privileged: true,
        stale: false,
        widest_scope_breadth: "subscription",
        assignment_count: 6,
        roles: ["Owner", "Contributor"],
      },
      {
        principal_id: "22222222-2222-2222-2222-222222222222",
        principal_type: "ServicePrincipal",
        privileged: false,
        stale: true,
        widest_scope_breadth: "resource_group",
        assignment_count: 1,
        roles: ["Reader"],
      },
    ],
    principalsTotalCount: 42,
    owners: [
      {
        principal_id: "33333333-3333-3333-3333-333333333333",
        principal_type: "User",
        subscription_id: "00000000-0000-0000-0000-000000000001",
        scope_breadth: "subscription",
        stale: false,
      },
    ],
    ownersTotalCount: 1,
    staleAccess: [
      {
        assignment_id: "assign-1",
        principal_id: "22222222-2222-2222-2222-222222222222",
        role: "Reader",
        privileged: false,
      },
    ],
    staleTotalCount: 5,
    spnCredentials: [
      {
        credential_id: "cred-1",
        connection_name: "Production",
        rotation_status: "expiring_soon",
        days_to_expiry: 12,
        issues_count: 1,
      },
    ],
    spnTotalCount: 2,
    available: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    selectedPrincipalId: "11111111-1111-1111-1111-111111111111",
    filters: { view: ["principals"] },
    evidence: [
      {
        source_engine: "Governance",
        source_table: "identity_assignments",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds principal, owner, access-review, and SPN identities as scope-safe domain identities", () => {
    const context = buildIdentityCopilotContext(identityInput);
    const reordered = buildIdentityCopilotContext({
      ...identityInput,
      principals: [...identityInput.principals].reverse(),
    });

    expect(context.snapshot).toMatchObject({
      page_kind: "governance",
      page_id: "identity",
    });
    // Every principal is a non-ARM domain identity: the principal id is never
    // leaked into a scope-validated Azure resource field (T-11-29 redaction).
    const principalRows = rowByClaim(context, "identity_principal");
    expect(principalRows.length).toBe(2);
    expect(principalRows.every((row) => row.resource_id === undefined)).toBe(true);
    expect(principalRows.every((row) =>
      (row.data.entity as { type: string }).type === "domain")).toBe(true);
    const selected = principalRows.find(
      (row) => (row.data.entity as { source_key: string }).source_key
        === "11111111-1111-1111-1111-111111111111",
    );
    expect(selected?.data).toMatchObject({
      entity: {
        type: "domain",
        namespace: "identity",
        kind: "identity_principal",
        source_key: "11111111-1111-1111-1111-111111111111",
      },
      principal_type: "User",
      privileged: true,
      widest_scope_breadth: "subscription",
      selected: true,
      actionable: false,
      mutation_authorized: false,
    });
    expect(rowByClaim(context, "subscription_owner").length).toBe(1);
    expect(rowByClaim(context, "stale_access").length).toBe(1);
    expect(rowByClaim(context, "spn_credential").length).toBe(1);
    expect(context.coverage.principals).toMatchObject({
      visible_count: 2,
      total_count: 42,
      truncated: true,
    });
    // Deterministic identities regardless of input order.
    expect(context.snapshot.evidence.map((row) => row.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((row) => row.evidence_id),
    );
    // Identity hints stay within the identity_access specialist and never mutate.
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "identity_access"
      && ["business_service_context", "application_context", "risk_context", "search"].includes(starter.tool ?? "")
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
  });

  it("distinguishes an unavailable identity provider from a healthy-empty scope", () => {
    const healthyEmpty = buildIdentityCopilotContext({
      ...identityInput,
      principals: [],
      owners: [],
      staleAccess: [],
      spnCredentials: [],
      principalsTotalCount: 0,
      ownersTotalCount: 0,
      staleTotalCount: 0,
      spnTotalCount: 0,
      selectedPrincipalId: null,
      available: true,
      freshness: "fresh" as const,
    });
    expect(healthyEmpty.coverage.principals).toMatchObject({
      visible_count: 0,
      total_count: 0,
      complete: true,
    });
    expect(healthyEmpty.uncertainty).not.toEqual(
      expect.arrayContaining(["identity freshness is unavailable"]),
    );

    const unavailable = buildIdentityCopilotContext({
      ...identityInput,
      principals: [],
      owners: [],
      staleAccess: [],
      spnCredentials: [],
      principalsTotalCount: 0,
      ownersTotalCount: 0,
      staleTotalCount: 0,
      spnTotalCount: 0,
      selectedPrincipalId: null,
      available: false,
      freshness: "unavailable" as const,
    });
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["identity freshness is unavailable"]),
    );
  });

  const finopsInput = {
    scope: { subscription: ["sub-a"] },
    summary: {
      identified_annual_savings: 125000,
      currency: "USD",
      savings_opportunity_count: 10,
      quantified_opportunity_count: 7,
      waste_item_count: 4,
      actual_spend: 98000,
      actual_spend_currency: "USD",
      actual_spend_period_start: "2026-08-01",
      actual_spend_period_end: "2026-08-31",
      unavailable_metrics: [
        { metric: "forecast_spend", reason: "Cost Management forecast not enabled" },
      ],
    },
    dimension: "business_service",
    attribution: [
      {
        dimension: "business_service",
        group: "Payments",
        identified_annual_savings: 60000,
        savings_opportunity_count: 4,
        waste_item_count: 2,
      },
    ],
    attributionTotalCount: 3,
    opportunities: [
      {
        recommendation_id: "rec-1",
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        problem: "Right-size underused VM",
        impact: "high",
        annual_savings: 24000,
        currency: "USD",
        owner: "team-payments",
        business_service: "Payments",
      },
      {
        recommendation_id: "rec-2",
        problem: "Unquantified recommendation",
        impact: "medium",
        annual_savings: null,
        currency: "USD",
        business_service: "Networking",
      },
    ],
    opportunitiesTotalCount: 10,
    waste: [
      {
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/disks/disk-1",
        resource_type: "Microsoft.Compute/disks",
        reason: "unattached",
        annual_savings: 1200,
        currency: "USD",
        owner: "team-payments",
      },
    ],
    wasteTotalCount: 4,
    available: true,
    freshness: "fresh" as const,
    observedAt: "2026-09-07T10:00:00Z",
    evidence: [
      {
        source_engine: "Advisor",
        source_table: "cost_recommendations",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds FinOps attribution, opportunity, and waste with currency, window, totals, and uncertainty", () => {
    const context = buildFinOpsCopilotContext(finopsInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "governance",
      page_id: "finops",
    });
    // Cost summary carries currency and observation window.
    const summary = rowByClaim(context, "finops_summary")[0]?.data;
    expect(summary).toMatchObject({
      currency: "USD",
      actual_spend_period_start: "2026-08-01",
      actual_spend_period_end: "2026-08-31",
      actionable: false,
      mutation_authorized: false,
    });
    // A quantified opportunity resource is a canonical ARM identity.
    const opportunity = rowByClaim(context, "savings_opportunity").find(
      (row) => row.data.recommendation_id === "rec-1",
    );
    expect(opportunity?.data.entity).toEqual({
      type: "azure",
      resource_id:
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
    });
    // A null saving is preserved as "not quantified", never coerced to zero.
    const unquantified = rowByClaim(context, "savings_opportunity").find(
      (row) => row.data.recommendation_id === "rec-2",
    );
    expect(unquantified?.data.annual_savings).toBeNull();
    expect(rowByClaim(context, "cost_attribution").length).toBe(1);
    expect(rowByClaim(context, "waste_item").length).toBe(1);
    expect(context.coverage.opportunities).toMatchObject({
      visible_count: 2,
      total_count: 10,
      truncated: true,
    });
    // Genuinely unavailable metrics are surfaced as uncertainty.
    expect(context.uncertainty).toEqual(
      expect.arrayContaining(["forecast_spend is unavailable: Cost Management forecast not enabled"]),
    );
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "finops"
      && ["business_service_context", "application_context", "risk_context", "search"].includes(starter.tool ?? "")
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
  });

  const healthInput = {
    scope: { subscription: ["sub-a"] },
    resources: [
      {
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
        resource_name: "vm-1",
        resource_type: "Microsoft.Compute/virtualMachines",
        status: "critical",
        cpu_percent: 94.2,
        memory_percent: null,
        disk_free_percent: null,
        observed_at: "2026-09-07T10:00:00Z",
        unavailable_metrics: ["memory_percent", "disk_free_percent"],
        series_point_count: 12,
      },
      {
        resource_id:
          "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.HybridCompute/machines/arc-1",
        resource_name: "arc-1",
        resource_type: "Microsoft.HybridCompute/machines",
        status: "healthy",
        cpu_percent: 21.0,
        memory_percent: 40.0,
        disk_free_percent: 55.0,
        observed_at: "2026-09-07T10:00:00Z",
        unavailable_metrics: [],
        series_point_count: 12,
      },
    ],
    loadedCount: 2,
    totalCount: 2,
    summary: { total: 2, critical: 1, warning: 0, healthy: 1, unknown: 0 },
    available: true,
    cached: true,
    observedAt: "2026-09-07T10:00:00Z",
    freshness: "fresh" as const,
    unavailableMetrics: ["memory_percent", "disk_free_percent"],
    warnings: ["No Log Analytics workspace discovered for guest counters"],
    selectedResourceId:
      "/subscriptions/SUB-A/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/vm-1",
    evidence: [
      {
        source_engine: "AzureMonitor",
        source_table: "resource_metrics",
        timestamp: "2026-09-07T10:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds resource-health identities, observation windows, and missing-series status", () => {
    const context = buildResourceHealthCopilotContext(healthInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "resource-health",
    });
    // Each resource is a canonical ARM identity.
    const resourceRows = rowByClaim(context, "resource_utilization");
    expect(resourceRows.length).toBe(2);
    const selected = context.snapshot.evidence.find(
      (row) => row.resource_id ===
        "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1",
    );
    expect(selected?.data).toMatchObject({
      claim_type: "resource_utilization",
      status: "critical",
      series_point_count: 12,
      actionable: false,
      mutation_authorized: false,
    });
    // Missing series/metrics are stated, never fabricated as zero.
    expect(selected?.data.unavailable_metrics).toEqual(["memory_percent", "disk_free_percent"]);
    expect(context.coverage.resources).toMatchObject({
      visible_count: 2,
      total_count: 2,
      complete: true,
    });
    // Page-level missing metrics surface as uncertainty.
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "memory_percent series is unavailable",
        "disk_free_percent series is unavailable",
      ]),
    );
    expect(context.starterQuestions.every((starter) =>
      starter.specialistId === "resource_health_observability"
      && ["incidents", "impact_context", "search"].includes(starter.tool ?? "")
      && !/write|update|delete|execute|remediate|approve|run|deploy/i.test(starter.tool ?? ""))).toBe(true);
  });

  it("keeps an unavailable resource-health provider distinct from an empty scope", () => {
    const unavailable = buildResourceHealthCopilotContext({
      ...healthInput,
      resources: [],
      loadedCount: 0,
      totalCount: 0,
      summary: { total: 0, critical: 0, warning: 0, healthy: 0, unknown: 0 },
      unavailableMetrics: [],
      warnings: [],
      selectedResourceId: null,
      available: false,
      cached: false,
      freshness: "unavailable" as const,
    });
    expect(unavailable.uncertainty).toEqual(
      expect.arrayContaining(["resource_health freshness is unavailable"]),
    );

    const empty = buildResourceHealthCopilotContext({
      ...healthInput,
      resources: [],
      loadedCount: 0,
      totalCount: 0,
      summary: { total: 0, critical: 0, warning: 0, healthy: 0, unknown: 0 },
      unavailableMetrics: [],
      warnings: [],
      selectedResourceId: null,
      available: true,
      cached: false,
      freshness: "fresh" as const,
    });
    expect(empty.coverage.resources).toMatchObject({
      visible_count: 0,
      total_count: 0,
      complete: true,
    });
    expect(empty.uncertainty).not.toEqual(
      expect.arrayContaining(["resource_health freshness is unavailable"]),
    );
  });
});

describe("situation detail and service Copilot page adapters", () => {
  const situationDetailInput = {
    scope: { subscription: ["sub-a"] },
    situationId: "situation://one",
    situation: {
      situation_id: "situation://one",
      title: "Database exposure",
      severity: "high",
      priority: "P2",
      lifecycle_state: "open",
      situation_type: "exposure",
      owner: "Security",
      support_team: "Platform",
      evidence_state: "contradictory",
      affected_resource_ids: [
        "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
      ],
      unknowns: ["Service ownership is not known."],
      started_at: "2026-08-25T01:00:00Z",
      last_observed_at: "2026-08-25T01:05:00Z",
    },
    evidence: [
      {
        evidence_id: "evidence://one",
        source_family: "defender",
        source_object_id: "defender-1",
        assertion: "Database exposure detected",
        quality: "contradictory",
        availability: "available",
        freshness: "fresh",
        observed_at: "2026-08-25T01:00:00Z",
        resource_ids: [
          "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
        ],
      },
    ],
    links: [
      {
        link_id: "link://one",
        entity_type: "Exposure",
        entity_id: "exposure-1",
        relation: "relates_to",
        quality: "unresolved",
      },
    ],
    sourceStatuses: [
      { source_family: "defender", availability: "available", freshness: "fresh", observed_at: "2026-08-25T01:00:00Z" },
      { source_family: "policy", availability: "unavailable", freshness: "unknown", observed_at: "" },
    ],
    auditEvents: [
      { event_id: "audit://one", actor: "system:ingestion", action: "evidence.ingested", timestamp: "2026-08-25T01:05:00Z" },
    ],
    auditAvailable: true,
    available: true,
    observedAt: "2026-08-25T01:05:00Z",
    citations: [
      {
        source_engine: "Fabric",
        source_table: "situations",
        timestamp: "2026-08-25T01:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds situation identity, timeline, evidence trust, affected resources, and links", () => {
    const context = buildSituationDetailCopilotContext(situationDetailInput);

    expect(context.snapshot).toMatchObject({
      page_kind: "incident",
      page_id: "situation:situation://one",
    });
    expect(context.selectedEntities).toEqual([
      {
        type: "domain",
        namespace: "operations",
        kind: "situation",
        source_key: "situation://one",
      },
    ]);
    // Affected resource is retained as a canonical (normalized) ARM entity.
    expect(context.snapshot.evidence.some((row) =>
      row.resource_id
        === "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.sql/servers/db")).toBe(true);
    // Evidence source trust is retained per row.
    expect(context.snapshot.evidence.some((row) =>
      row.data.source_family === "defender" && row.data.quality === "contradictory")).toBe(true);
    // Every row is forced non-actionable / non-mutation-authorized.
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
    expect(context.coverage.evidence).toMatchObject({ visible_count: 1, complete: true });
    expect(context.coverage.links).toMatchObject({ visible_count: 1 });
    expect(context.starterQuestions.length).toBeGreaterThan(0);
    expect(context.starterQuestions.every((q) => q.specialistId === "incident")).toBe(true);
  });

  it("keeps an unavailable source distinct from a fresh source and retains stale freshness", () => {
    const context = buildSituationDetailCopilotContext(situationDetailInput);
    expect(context.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "defender", status: "fresh" }),
        expect.objectContaining({ source: "policy", status: "unavailable" }),
      ]),
    );
  });

  it("distinguishes an unavailable situation record from an authorized empty detail", () => {
    const unavailable = buildSituationDetailCopilotContext({
      ...situationDetailInput,
      situation: null,
      evidence: [],
      links: [],
      auditEvents: [],
      available: false,
      citations: [],
    });
    expect(unavailable.coverage.evidence).toMatchObject({ visible_count: 0, complete: false });
  });

  const servicesInput = {
    scope: { subscription: ["sub-a"] },
    services: [
      {
        name: "Payments",
        environments: ["prod"],
        subscriptionCount: 2,
        situationCount: 3,
        criticalCount: 1,
        healthRisk: 2,
        operationalState: "Critical attention",
      },
      {
        name: "Billing",
        environments: ["prod", "staging"],
        subscriptionCount: 1,
        situationCount: 0,
        criticalCount: 0,
        healthRisk: 0,
        operationalState: "No active situation",
      },
    ],
    visibleCount: 2,
    totalCount: 5,
    filters: { state: ["Critical attention"] },
    connectionsAvailable: true,
    incidentsAvailable: true,
    connectionsObservedAt: "2026-08-25T01:00:00Z",
    incidentsObservedAt: "2026-08-25T01:00:00Z",
    connectionsFreshness: "fresh" as const,
    incidentsFreshness: "fresh" as const,
    evidence: [
      {
        source_engine: "connections",
        source_table: "subscription_connections",
        timestamp: "2026-08-25T01:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds visible services with ownership/health facts, filters, and honest total coverage", () => {
    const context = buildServicesCopilotContext(servicesInput);
    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "services",
      filters: { state: ["Critical attention"] },
    });
    expect(context.snapshot.evidence.some((row) =>
      row.data.service === "Payments" && row.data.situation_count === 3 && row.data.critical_count === 1)).toBe(true);
    expect(context.coverage.services).toMatchObject({
      visible_count: 2,
      total_count: 5,
      complete: false,
      truncated: true,
    });
    expect(context.starterQuestions.every((q) => q.specialistId === "resource_health_observability")).toBe(true);
  });

  it("keeps an unavailable services catalog distinct from an authorized empty catalog", () => {
    const unavailable = buildServicesCopilotContext({
      ...servicesInput,
      services: [],
      visibleCount: 0,
      totalCount: 0,
      connectionsAvailable: false,
      incidentsAvailable: false,
      evidence: [],
    });
    const empty = buildServicesCopilotContext({
      ...servicesInput,
      services: [],
      visibleCount: 0,
      totalCount: 0,
      evidence: [],
    });
    expect(unavailable.coverage.services.complete).toBe(false);
    expect(empty.coverage.services.complete).toBe(true);
    expect(unavailable.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "connections", status: "unavailable" }),
      ]),
    );
  });

  const serviceDetailInput = {
    scope: { subscription: ["sub-a"] },
    name: "Payments",
    context: {
      subject: {
        entity_type: "business_service",
        name: "Payments",
        owner: "Payments SRE",
        support_team: "Platform",
        criticality: "high",
        environment: "prod",
      },
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-08-25T01:00:00Z",
      sections: ["context", "topology"],
    },
    risk: {
      subject: { entity_type: "business_service", name: "Payments" },
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-08-25T01:00:00Z",
      sections: ["aggregated_risk"],
    },
    impact: {
      subject: { entity_type: "business_service", name: "Payments" },
      available: true,
      freshness: "fresh" as const,
      observedAt: "2026-08-25T01:00:00Z",
      sections: ["dependency_impact"],
    },
    dependencies: [
      {
        id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
        name: "payments-db",
        relation: "depends_on",
        resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Sql/servers/db",
      },
      { id: "app:PaymentsApi", name: "Payments API", relation: "serves" },
    ],
    evidence: [
      {
        source_engine: "graph",
        source_table: "business_service",
        timestamp: "2026-08-25T01:00:00Z",
        confidence: "high" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds selected service identity, ownership, dependencies, and cited evidence", () => {
    const context = buildServiceDetailCopilotContext(serviceDetailInput);
    expect(context.snapshot).toMatchObject({
      page_kind: "resource",
      page_id: "service:Payments",
    });
    expect(context.selectedEntities).toEqual([
      {
        type: "domain",
        namespace: "operations",
        kind: "business_service",
        source_key: "Payments",
      },
    ]);
    // The canonical ARM dependency is retained as a normalized azure entity.
    expect(context.snapshot.evidence.some((row) =>
      row.resource_id
        === "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.sql/servers/db")).toBe(true);
    // The non-ARM dependency stays a domain entity.
    expect(context.snapshot.evidence.some((row) =>
      row.data.relation === "serves"
      && (row.data.entity as { type?: string } | undefined)?.type === "domain")).toBe(true);
    expect(context.snapshot.evidence.some((row) => row.data.owner === "Payments SRE")).toBe(true);
    expect(context.starterQuestions.every((q) => q.specialistId === "resource_health_observability")).toBe(true);
    expect(context.starterQuestions.some((q) => q.label.includes("Payments"))).toBe(true);
  });

  it("keeps an unavailable service section distinct from a fresh one", () => {
    const context = buildServiceDetailCopilotContext({
      ...serviceDetailInput,
      risk: { ...serviceDetailInput.risk, available: false, freshness: "unavailable" as const },
    });
    expect(context.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "context", status: "fresh" }),
        expect.objectContaining({ source: "risk", status: "unavailable" }),
      ]),
    );
  });
});

describe("operational twin Copilot page adapter", () => {
  const twinInput = {
    scope: { subscription: ["sub-a"] },
    twinId: "operational-twin",
    version: "v1",
    previousVersion: "v0",
    observedAt: "2026-01-01T10:00:00Z",
    liveObservedAt: "2026-01-01T10:00:00Z",
    confidence: "medium",
    entities: [
      {
        id: "resource:vm-payroll-1",
        kind: "resource",
        name: "payroll-vm",
        version: "r1",
        state: "current",
        confidence: "high",
        business_service: "Payroll",
        resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/payroll-vm",
      },
      { id: "business_service:Payroll", kind: "business_service", name: "Payroll", version: "b1", state: "current", confidence: "high" },
    ],
    entitiesTotal: 4,
    relationships: [
      { id: "rel-1", source: "resource:vm-payroll-1", target: "business_service:Payroll", type: "supports", confidence: "high", supported: true },
    ],
    relationshipsTotal: 3,
    timeline: [
      { timestamp: "2026-01-01T10:00:00Z", type: "vulnerability_observed", entity: "vulnerability:CVE-2026-0001", summary: "CVE-2026-0001 observed" },
    ],
    timelineTotal: 5,
    traversal: {
      resource_id: "vm-payroll-1",
      path: [
        { id: "resource:vm-payroll-1", kind: "resource", name: "payroll-vm" },
        { id: "business_service:Payroll", kind: "business_service", name: "Payroll" },
      ],
      business_consequence: ["Payroll", "Payroll API"],
    },
    scenario: {
      scenario: "firewall_failure",
      target: "vm-payroll-1",
      likely_impact: "Traffic inspection and hub dependencies degrade.",
      risk_delta: 20,
      impacted_count: 4,
      assumptions: ["Operator validation required"],
    },
    selectedResourceId: "vm-payroll-1",
    available: true,
    freshness: "fresh" as const,
    unsupportedRelationships: ["experimental_edge"],
    staleTemporalEvidence: ["previous revision v0"],
    evidence: [
      {
        source_engine: "twin",
        source_table: "live",
        timestamp: "2026-01-01T10:00:00Z",
        confidence: "medium" as const,
        freshness: "fresh" as const,
      },
    ],
  };

  it("binds twin entity, relationship, timeline, traversal, and scenario identities with provenance", () => {
    const context = buildTwinCopilotContext(twinInput);
    expect(context.snapshot).toMatchObject({
      page_kind: "network",
      page_id: "twin",
    });
    // The selected resource carries a canonical ARM id, so it is retained as a
    // scope-validated azure identity (not a domain guess).
    expect(context.selectedEntities).toEqual([
      {
        type: "azure",
        resource_id: "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/payroll-vm",
      },
    ]);
    // A canonical ARM entity is retained as an azure identity.
    expect(context.snapshot.evidence.some((row) =>
      row.resource_id
        === "/subscriptions/sub-a/resourcegroups/rg/providers/microsoft.compute/virtualmachines/payroll-vm")).toBe(true);
    // Relationship identity and provenance are retained.
    expect(context.snapshot.evidence.some((row) =>
      row.data.type === "supports" && row.data.source === "resource:vm-payroll-1")).toBe(true);
    // Scenario projection is marked hypothetical, never observed reality.
    expect(context.snapshot.evidence.some((row) =>
      row.data.scenario === "firewall_failure" && row.data.observed === false)).toBe(true);
    // Observed entities are distinguished from scenario projections.
    expect(context.snapshot.evidence.some((row) =>
      row.data.name === "payroll-vm" && row.data.observed === true)).toBe(true);
    expect(context.starterQuestions.every((q) => q.specialistId === "network")).toBe(true);
    expect(context.snapshot.evidence.every((row) =>
      row.data.actionable === false && row.data.mutation_authorized === false)).toBe(true);
  });

  it("exposes visible/total/truncated coverage for bounded graph and traversal results", () => {
    const context = buildTwinCopilotContext(twinInput);
    expect(context.coverage.entities).toMatchObject({
      visible_count: 2,
      total_count: 4,
      complete: false,
      truncated: true,
    });
    expect(context.coverage.relationships).toMatchObject({
      visible_count: 1,
      total_count: 3,
      truncated: true,
    });
    expect(context.coverage.timeline).toMatchObject({
      visible_count: 1,
      total_count: 5,
      truncated: true,
    });
  });

  it("keeps unsupported relationships and stale temporal evidence uncertain rather than asserted", () => {
    const context = buildTwinCopilotContext(twinInput);
    expect(context.uncertainty).toEqual(
      expect.arrayContaining([
        "experimental_edge is not a supported twin relationship; treat as uncertain",
        "previous revision v0 is historical evidence and is not asserted as current",
      ]),
    );
  });

  it("distinguishes an unavailable twin from an empty authorized twin", () => {
    const unavailable = buildTwinCopilotContext({
      ...twinInput,
      entities: [],
      entitiesTotal: 0,
      relationships: [],
      relationshipsTotal: 0,
      timeline: [],
      timelineTotal: 0,
      traversal: null,
      scenario: null,
      unsupportedRelationships: [],
      staleTemporalEvidence: [],
      available: false,
      evidence: [],
    });
    const empty = buildTwinCopilotContext({
      ...twinInput,
      entities: [],
      entitiesTotal: 0,
      relationships: [],
      relationshipsTotal: 0,
      timeline: [],
      timelineTotal: 0,
      traversal: null,
      scenario: null,
      unsupportedRelationships: [],
      staleTemporalEvidence: [],
      available: true,
      evidence: [],
    });
    expect(unavailable.coverage.entities.complete).toBe(false);
    expect(empty.coverage.entities.complete).toBe(true);
    expect(unavailable.snapshot.freshness).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "twin", status: "unavailable" }),
      ]),
    );
  });
});

const APP_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "app");

function discoverRoutePageFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...discoverRoutePageFiles(full));
    } else if (entry.name === "page.tsx") {
      found.push(full);
    }
  }
  return found;
}

function routePathForFile(file: string): string {
  const relative_dir = relative(APP_DIR, dirname(file)).split(sep).join("/");
  return relative_dir === "" ? "/" : `/${relative_dir}`;
}

describe("28-route Copilot disposition gate (COP-02, COP-03)", () => {
  const discoveredRoutes = discoverRoutePageFiles(APP_DIR)
    .map(routePathForFile)
    .sort();
  const registeredRoutes = Object.keys(COPILOT_ROUTE_DISPOSITIONS).sort();

  it("discovers exactly the 28 reviewed route files on disk", () => {
    expect(discoveredRoutes).toHaveLength(28);
  });

  it("makes the registry route inventory equal the filesystem inventory exactly", () => {
    // Bidirectional: no absent disposition (filesystem route missing from the
    // registry) and no extra disposition (registry route with no page file).
    expect(registeredRoutes).toEqual(discoveredRoutes);
  });

  it("gives every discovered route exactly one disposition", () => {
    for (const route of discoveredRoutes) {
      expect(
        COPILOT_ROUTE_DISPOSITIONS[route],
        `route ${route} has no reviewed Copilot disposition`,
      ).toBeDefined();
    }
    expect(new Set(registeredRoutes).size).toBe(registeredRoutes.length);
  });

  it("matches the resolved research disposition table counts", () => {
    const counts = { integrated: 0, dedicated: 0, redirect: 0, excluded: 0 };
    for (const route of registeredRoutes) {
      counts[COPILOT_ROUTE_DISPOSITIONS[route].kind] += 1;
    }
    expect(counts).toEqual({ integrated: 23, dedicated: 3, redirect: 1, excluded: 1 });
  });

  it("names /copilot, /investigate, and /agents as the dedicated surfaces", () => {
    const dedicated = registeredRoutes
      .filter((route) => COPILOT_ROUTE_DISPOSITIONS[route].kind === "dedicated")
      .sort();
    expect(dedicated).toEqual(["/agents", "/copilot", "/investigate"]);
  });

  it("redirects /vulnerabilities to the exact Patch priorities destination", () => {
    const disposition = COPILOT_ROUTE_DISPOSITIONS["/vulnerabilities"];
    expect(disposition).toEqual({
      kind: "redirect",
      target: "/exposure/patch-priorities",
    });
    // The alias route resolves to an integrated adapter only via the canonical
    // Exposure product, so no second adapter is registered for it.
    expect(Object.prototype.hasOwnProperty.call(CORE_COPILOT_PAGE_ADAPTERS, "/vulnerabilities")).toBe(false);
  });

  it("excludes /search as the single reasoned exclusion with a stable-evidence reason", () => {
    const excluded = registeredRoutes.filter(
      (route) => COPILOT_ROUTE_DISPOSITIONS[route].kind === "excluded",
    );
    expect(excluded).toEqual(["/search"]);
    const disposition = COPILOT_ROUTE_DISPOSITIONS["/search"];
    expect(
      disposition.kind === "excluded" && /evidence/i.test(disposition.reason),
    ).toBe(true);
  });

  it("anchors every integrated route on a declared Copilot page kind", () => {
    for (const route of registeredRoutes) {
      const disposition = COPILOT_ROUTE_DISPOSITIONS[route];
      if (disposition.kind === "integrated") {
        expect(typeof disposition.pageKind, `${route} lacks a page kind`).toBe("string");
        expect(disposition.pageKind.length).toBeGreaterThan(0);
      }
    }
  });

  it("keeps copilotPageDisposition backward compatible for integrated routes", () => {
    expect(copilotPageDisposition("/")).toBe("integrated");
    expect(copilotPageDisposition("/inventory")).toBe("integrated");
    expect(copilotPageDisposition("/twin")).toBe("integrated");
  });
});
