import { describe, expect, it } from "vitest";
import { connectionReviewReasons, overviewHref, overviewPosture } from "../overview";
import type { SubscriptionConnection } from "../types";

const overviewConnection: SubscriptionConnection = {
  connection_id: "fixture-connection", name: "Fixture connection", tenant_id: "fixture-tenant",
  subscription_id: "fixture-sub", scope_key: "fixture", is_active: true, business_service: "Payments",
  environment: "prod", owner: "Fixture owner", criticality: "high", sync_status: "succeeded",
  health_status: "healthy", last_successful_sync_at: "2026-10-16T00:00:00Z",
};

describe("Overview explanations", () => {
  it("exposes exact incumbent weights without treating connections as a score input", () => {
    const result = overviewPosture(1, 2, 3);
    expect(result.score).toBe(56);
    expect(result.rawDeduction).toBe(44);
    expect(result.contributors.map(row => row.deduction)).toEqual([18, 14, 12]);
  });
  it("floors only the displayed score and retains raw contributions", () => {
    expect(overviewPosture(10, 0, 0)).toMatchObject({ score: 0, rawDeduction: 180 });
    expect(overviewPosture(0, 0, 0).score).toBe(100);
  });
  it.each([undefined, -1, 0.1, NaN, Infinity])("withholds missing or invalid counts (%s)", count => {
    expect(overviewPosture(count, 0, 0).score).toBeNull();
    expect(overviewPosture(0, count, 0).score).toBeNull();
    expect(overviewPosture(0, 0, count).score).toBeNull();
  });
  it("preserves multi-value scope and encodes a connection bookmark as data", () => {
    const href = overviewHref("/connections", { owner: ["A&B", "C"], environment: ["prod"] }, "id&owner=admin");
    const params = new URL(href, "http://local").searchParams;
    expect(params.getAll("owner")).toEqual(["A&B", "C"]);
    expect(params.get("connection")).toBe("id&owner=admin");
    expect(params.get("tab")).toBe("subscriptions");
  });
  it("classifies only explicit registry readiness as ready", () => {
    expect(connectionReviewReasons(overviewConnection)).toEqual([]);
    expect(connectionReviewReasons({ ...overviewConnection, health_status: "unknown" })).toContain("Registry health: unknown");
    expect(connectionReviewReasons({ ...overviewConnection, is_active: false })).toContain("Connection disabled");
    expect(connectionReviewReasons({ ...overviewConnection, sync_status: "running" })).toContain("Sync: running");
    expect(connectionReviewReasons({ ...overviewConnection, owner: null, business_service: "", environment: "" }))
      .toEqual(["Business service unmapped", "Owner unmapped", "Environment unmapped"]);
    expect(connectionReviewReasons({ ...overviewConnection, last_successful_sync_at: "invalid" })).toContain("Successful-sync time unreported");
  });
});
