import { describe, expect, it } from "vitest";
import type { Envelope, SemanticContext } from "../types";
import { serviceBrief, serviceDependencies, serviceDependencyHref, serviceSourceState } from "../service-brief";

const context = (sections: Record<string, unknown> = {}): SemanticContext => ({
  subject: { entity_type: "BusinessService", name: "Checkout" }, sections,
});
const envelope = (data = context()): Envelope<SemanticContext> => ({
  data, evidence: [], scope: {}, knowledge_version: "service-test", warnings: [],
});
const resourceId = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm";

describe("service evidence adapters", () => {
  it("does not claim freshness from HTTP success, rejects failed sources, and preserves stale evidence", () => {
    expect(serviceSourceState(envelope())).toMatchObject({ available: true, state: "partial", fresh: false });
    expect(serviceSourceState(null)).toMatchObject({ available: false, state: "unavailable" });
    const response = envelope();
    response.data.source_status = { graph: "unavailable", registry: "ok" };
    response.evidence = [{ source_engine: "graph", source_table: "services", timestamp: "2026-10-16T10:00:00Z", confidence: "high", freshness: "fresh" }];
    expect(serviceSourceState(response).state).toBe("partial");
    response.data.source_status = { graph: "ok" };
    expect(serviceSourceState(response).state).toBe("fresh");
    response.data.source_status = { graph: "pending" };
    expect(serviceSourceState(response).state).toBe("partial");
    response.data.source_status = { graph: "ok" };
    response.data.graph_freshness = "stale";
    expect(serviceSourceState(response).state).toBe("stale");
    delete response.data.graph_freshness;
    response.evidence[0].freshness = "stale";
    expect(serviceSourceState(response).state).toBe("stale");
    expect(serviceSourceState(response, new Error("No source"))).toMatchObject({ available: false });
    response.data.source_status = { graph: "deferred", registry: "empty" };
    expect(serviceSourceState(response).available).toBe(false);
  });

  it("reads real object projections, top-level impact arrays and legacy strings without guessing types", () => {
    const data = { ...context({
      applications: [{ entity_type: "Application", name: "Checkout app" }, { entity_type: "Application", name: "Checkout app" }],
      dependencies: [{ entity_type: "Application", name: "Payments" }, "legacy-name"],
      infrastructure: [resourceId],
      impacted_resources: [],
    }), impacted_resources: [{ name: "VM", entity_type: "Resource", resource_id: resourceId }] };
    const rows = serviceDependencies(data);
    expect(rows).toHaveLength(5);
    expect(rows.find(row => row.name === "legacy-name")).toMatchObject({ entityType: "", identity: "name-only" });
    expect(rows.filter(row => row.resourceId === resourceId)).toHaveLength(2);
    expect(serviceDependencies(context({ dependencies: [null, false, 123, { owner: "not an entity" }, ""] }))).toEqual([]);
  });

  it("retains counts beyond the UI cap and separate relationships to the same named entity", () => {
    const data = context({
      dependencies: Array.from({ length: 80 }, (_, i) => ({ entity_type: "Application", name: `App ${i}` })),
      applications: [{ entity_type: "Application", name: "App 0" }],
    });
    expect(serviceDependencies(data)).toHaveLength(81);
  });

  it("preserves every scope dimension on supported links and leaves unsupported identities unlinked", () => {
    const scope = { subscription: ["sub-a"], owner: ["SRE"], environment: ["prod"] };
    const data = context({ dependencies: [
      { entity_type: "Application", name: "Pay & cart" }, { entity_type: "BusinessService", name: "A/B%" },
      { entity_type: "Service", name: "Unsupported" }, { entity_type: "Resource", name: "vm", resource_id: resourceId },
      "raw name",
    ] });
    const rows = serviceDependencies(data);
    expect(serviceDependencyHref(rows[0], scope)).toContain("value=Pay+%26+cart");
    expect(serviceDependencyHref(rows[0], scope)).toContain("owner=SRE");
    expect(serviceDependencyHref(rows[1], scope)).toContain("/services/A%2FB%25?");
    expect(serviceDependencyHref(rows[2], scope)).toBeNull();
    const asset = new URL(serviceDependencyHref(rows[3], scope)!, "https://fixture.invalid");
    expect(asset.pathname).toBe("/inventory/assets");
    expect(Object.fromEntries(asset.searchParams)).toMatchObject({ subscription: "sub-a", owner: "SRE", environment: "prod", resource_id: resourceId });
    expect(serviceDependencyHref(rows[4], scope)).toBeNull();
    expect(serviceDependencyHref({ ...rows[0], name: "bad\nname" }, scope)).toBeNull();
  });

  it("projects known ownership and numeric risk facts only; unknown and invalid scores stay unknown", () => {
    const data = { ...context(), subject: { ...context().subject, owner: "SRE", support_team: "", criticality: "high" } };
    const risk = { ...context(), risk: { score: 27, level: "Moderate", factors: { missing_owner: 0, security_findings: 20, invalid: "20", negative: -1 } } };
    expect(serviceBrief(data, risk)).toMatchObject({ owner: "SRE", supportTeam: "", riskScore: 27, factors: [["missing_owner", 0], ["security_findings", 20]] });
    for (const score of [-1, 101, NaN, 2.5, "20", null]) {
      expect(serviceBrief(data, { ...risk, risk: { score } }).riskScore).toBeNull();
    }
    expect(serviceBrief().owner).toBe("");
  });
});
