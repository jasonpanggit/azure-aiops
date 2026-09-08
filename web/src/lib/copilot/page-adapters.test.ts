import { describe, expect, it } from "vitest";
import {
  buildComplianceCopilotContext,
  buildCveDetailCopilotContext,
  buildExposureCopilotContext,
  buildInventoryCopilotContext,
  buildNetworkCopilotContext,
  buildOverviewCopilotContext,
  buildRemediationCopilotContext,
  buildSituationsCopilotContext,
  canonicalEvidenceStableId,
  CORE_COPILOT_PAGE_ADAPTERS,
  COPILOT_SNAPSHOT_LIMITS,
  copilotPageDisposition,
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
