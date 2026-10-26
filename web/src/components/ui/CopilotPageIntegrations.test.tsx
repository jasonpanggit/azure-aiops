import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { buildCopilotSnapshot, copilotEvidenceRows } from "@/lib/services";
import { COPILOT_ROUTE_DISPOSITIONS } from "@/lib/copilot/page-adapters";

const APP_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "app");

function routeSourceFor(route: string): string {
  return readFileSync(join(APP_DIR, route === "/" ? "" : route, "page.tsx"), "utf8");
}

describe("integrated route launcher coverage (COP-02)", () => {
  const routes = Object.entries(COPILOT_ROUTE_DISPOSITIONS);

  it("renders the shared CopilotDrawerButton entry point on every integrated route", () => {
    const integrated = routes.filter(([, disposition]) => disposition.kind === "integrated");
    expect(integrated).toHaveLength(23);
    for (const [route] of integrated) {
      expect(
        routeSourceFor(route),
        `${route} must render the shared Copilot entry point`,
      ).toContain("CopilotDrawerButton");
    }
  });

  it("provides the shared PageHeader on every integrated route", () => {
    for (const [route, disposition] of routes) {
      if (disposition.kind !== "integrated") continue;
      expect(routeSourceFor(route), `${route} must render the shared PageHeader`)
        .toContain("<PageHeader");
    }
  });

  it("keeps exactly one page-owned insight outside the drawer", () => {
    for (const [route, disposition] of routes) {
      if (disposition.kind !== "integrated") continue;
      const component = route === "/network" ? "TopologyInsights" : "CopilotInsights";
      expect(
        routeSourceFor(route).match(new RegExp(`<${component}\\b`, "g")),
        `${route} must own exactly one insight`,
      ).toHaveLength(1);
    }
    const drawer = readFileSync(join(APP_DIR, "..", "components", "ui", "CopilotDrawer.tsx"), "utf8");
    expect(drawer).not.toContain("<CopilotInsights");
    expect(drawer).not.toContain("<TopologyInsights");
  });

  it("keeps dedicated, redirect, and excluded routes free of an embedded launcher", () => {
    const nonIntegrated = routes.filter(([, disposition]) => disposition.kind !== "integrated");
    expect(nonIntegrated).toHaveLength(6);
    expect(nonIntegrated.map(([route]) => route)).toContain("/inventory/assets");
    for (const [route] of nonIntegrated) {
      expect(
        routeSourceFor(route),
        `${route} must not embed the shared Copilot launcher`,
      ).not.toContain("CopilotDrawerButton");
    }
  });
});

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

  it("keeps non-Azure page identifiers out of scope-validated resource ID fields", () => {
    const snapshot = buildCopilotSnapshot({
      pageKind: "vulnerability",
      pageId: "cve:CVE-2026-0001",
      scope: { subscription: ["sub-1"] },
      selectedResources: [{ resource_id: "CVE-2026-0001", resource_type: "CVE", name: "CVE-2026-0001" }],
      evidence: [
        {
          evidence_id: "cve:visible:0",
          resource_id: "CVE-2026-0001",
          section: "cve",
          status: "ok",
          data: { cve_id: "CVE-2026-0001" },
        },
      ],
    });

    expect(snapshot.selected_resources).toEqual([]);
    expect(snapshot.evidence[0].resource_id).toBeUndefined();
    expect(snapshot.evidence[0].data.resource_id).toBe("CVE-2026-0001");
    expect(snapshot.evidence[0].data.cve_id).toBe("CVE-2026-0001");
  });
});
