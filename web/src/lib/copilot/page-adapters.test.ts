import { describe, expect, it } from "vitest";
import {
  buildInventoryCopilotContext,
  canonicalEvidenceStableId,
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
        source: "arc",
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
  });
});
