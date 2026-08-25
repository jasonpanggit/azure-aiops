import { describe, expect, it } from "vitest";
import { durableSituationSummary } from "./situations";
import type { DurableSituation } from "./types";

describe("durable situation workbench adapter", () => {
  it("keeps durable identity, priority, scope, and qualified trust state", () => {
    const situation: DurableSituation = {
      situation_id: "situation://one",
      resource_id: "situation://one",
      title: "VM changed",
      situation_type: "resource_change",
      lifecycle_state: "open",
      severity: "high",
      priority: "P2",
      scope: { subscription: ["sub-a"], business_service: ["Retail"] },
      owner: "",
      support_team: "",
      affected_resource_ids: ["/subscriptions/sub-a/vm"],
      linked_evidence_ids: [],
      started_at: "2026-08-25T00:00:00Z",
      last_observed_at: "2026-08-25T00:01:00Z",
      evidence_state: "contradictory",
      warnings: ["Evidence conflicts"],
      contradiction_ids: ["evidence://two"],
      unknowns: [],
      run_id: "run-1",
    };

    const summary = durableSituationSummary(situation);
    expect(summary.id).toBe(situation.situation_id);
    expect(summary.cause).toBe("Evidence conflicts");
    expect(summary.businessServices).toEqual(["Retail"]);
  });
});
