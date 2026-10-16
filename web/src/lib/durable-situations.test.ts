import { describe, expect, it } from "vitest";
import { durableSituationSummary, situationEntityHref } from "./situations";
import type { DurableSituation, DurableSituationLink } from "./types";

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

  describe("resolved Situation entity navigation", () => {
    const link: DurableSituationLink = { link_id: "link", situation_id: "situation", entity_type: "Application",
      entity_id: "Payments & billing", relation: "affected", quality: "resolved", provenance: {} };
    it("preserves exact encoded identity and current scope without granting authority", () => {
      const href = situationEntityHref(link, { subscription: ["sub-a"] });
      expect(href).toBe("/investigate?subscription=sub-a&type=Application&value=Payments+%26+billing");
      expect(situationEntityHref({ ...link, entity_type: "BusinessService", entity_id: "Retail / prod" }, {}))
        .toBe("/services/Retail%20%2F%20prod");
      expect(situationEntityHref({ ...link, entity_type: "CVE", entity_id: "CVE-2026-12345" }, {}))
        .toBe("/exposure/cves/CVE-2026-12345");
      expect(situationEntityHref({ ...link, entity_type: "SubscriptionConnection", entity_id: "prod" }, {}))
        .toBe("/connections?connection=prod");
    });
    it.each([
      { quality: "unresolved" }, { quality: "degraded" }, { entity_type: "UnsupportedEntity" },
      { entity_type: "CVE", entity_id: "https://evil.example" }, { entity_id: "bad\u0000" },
      { entity_id: "" }, { entity_id: "x".repeat(2049) },
    ])("does not turn unverified or malformed identities into destinations (%j)", patch => {
      expect(situationEntityHref({ ...link, ...patch }, {})).toBeNull();
    });
  });
});
