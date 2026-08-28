import { describe, expect, it } from "vitest";
import { buildCopilotSnapshot, copilotEvidenceRows } from "@/lib/services";

describe("supported Copilot page contracts", () => {
  it("uses a named page kind and preserves filters, visible evidence, and source availability", () => {
    const pages = [
      ["resource", "operations-overview"],
      ["vulnerability", "exposure"],
      ["vulnerability", "cve:CVE-2026-0001"],
      ["governance", "compliance-posture"],
      ["incident", "situations"],
      ["patch", "remediation"],
    ] as const;
    for (const [pageKind, pageId] of pages) {
      const snapshot = buildCopilotSnapshot({
        pageKind,
        pageId,
        scope: { subscription: ["sub-1"] },
        filters: { source: ["inventory"] },
        evidence: copilotEvidenceRows(pageId, [], [{ family_availability: {
          vm: { state: "partial", row_count: 0, warning: "VM source unavailable" },
        } }]),
      });
      expect(snapshot.page_kind).toBe(pageKind);
      expect(snapshot.page_id).toBe(pageId);
      expect(snapshot.scope.declared.subscription).toEqual(["sub-1"]);
      expect(snapshot.filters.source).toEqual(["inventory"]);
      expect(snapshot.evidence[0].data).toHaveProperty("family_availability");
    }
  });

  it("bounds visible records rather than serializing arbitrary page state", () => {
    const rows = copilotEvidenceRows("network", [], Array.from({ length: 300 }, (_, index) => ({ id: index })));
    expect(rows).toHaveLength(200);
    expect(rows[0].data).toEqual({ id: 0 });
  });
});
