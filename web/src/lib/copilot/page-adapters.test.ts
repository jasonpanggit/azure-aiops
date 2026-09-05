import { describe, expect, it } from "vitest";
import {
  buildInventoryCopilotContext,
  copilotPageDisposition,
  type InventoryCopilotRecord,
} from "./page-adapters";

const records: InventoryCopilotRecord[] = [
  {
    identity: "Windows Server|2019",
    kind: "os_group",
    source: "inventory/os_observations",
    observedAt: "2026-08-25T10:00:00Z",
    data: { os_name: "Windows Server", os_version: "2019", machine_count: 2 },
  },
  {
    identity: "microsoft.app:containerapps|Unknown|Unknown",
    kind: "azure_group",
    source: "inventory/resource_observations",
    observedAt: "2026-08-25T10:00:00Z",
    resourceId: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.App/containerApps/app-1",
    data: { resource_type: "microsoft.app/containerapps", resource_count: 1 },
  },
];

describe("inventory Copilot page adapter", () => {
  it("has an explicit integrated route disposition", () => {
    expect(copilotPageDisposition("/inventory")).toBe("integrated");
  });

  it("builds a strict v2 snapshot with filters, coverage, freshness, and typed hints", () => {
    const context = buildInventoryCopilotContext({
      scope: { subscription: ["sub-a"] },
      tab: "os",
      filters: { search: "windows", lifecycle: "supported" },
      records,
      selectedIdentity: "Windows Server|2019",
      totalCount: 4,
      sourceStatuses: [
        { source: "azure_vm", observedAt: "2026-08-25T10:00:00Z", status: "fresh" },
        { source: "arc", observedAt: "2026-08-25T09:00:00Z", status: "partial" },
      ],
    });

    expect(context.requestedScope).toEqual({ subscription: ["sub-a"] });
    expect(context.snapshot).toMatchObject({
      version: "2",
      page_kind: "inventory",
      page_id: "inventory",
      coverage: { visible_count: 2, total_count: 4, complete: false },
    });
    const selected = context.snapshot.evidence.find((item) => item.data.selected);
    expect(selected?.resource_id).toMatch(/^inventory:\/\/os_group\//);
    expect(context.snapshot.evidence.some((item) => item.resource_id === records[1].resourceId)).toBe(true);
    expect(context.starterQuestions[0]).toMatchObject({
      specialistId: "inventory_data_health",
      tool: "inventory_resources",
      toolArguments: {},
    });
  });

  it("keeps evidence IDs stable across record reorder and retains non-Azure identities", () => {
    const input = {
      scope: { subscription: ["sub-a"] },
      tab: "os" as const,
      filters: {},
      totalCount: 2,
      sourceStatuses: [],
    };
    const first = buildInventoryCopilotContext({ ...input, records });
    const reordered = buildInventoryCopilotContext({ ...input, records: [...records].reverse() });

    expect(first.snapshot.evidence.map((item) => item.evidence_id)).toEqual(
      reordered.snapshot.evidence.map((item) => item.evidence_id),
    );
    const nonAzure = first.snapshot.evidence.find((item) => item.source === "inventory/os_observations");
    expect(nonAzure?.resource_id).toContain("Windows%20Server%7C2019");
  });

  it("keeps complete coverage independent from stale source freshness", () => {
    const context = buildInventoryCopilotContext({
      scope: {},
      tab: "os",
      filters: {},
      records,
      totalCount: records.length,
      sourceStatuses: [{
        source: "arc",
        observedAt: "2026-08-25T09:00:00Z",
        status: "stale",
      }],
    });

    expect(context.snapshot.coverage.complete).toBe(true);
    expect(context.snapshot.freshness).toEqual([{
      source: "arc",
      observed_at: "2026-08-25T09:00:00Z",
      status: "stale",
    }]);
  });
});
