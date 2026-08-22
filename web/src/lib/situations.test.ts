import { describe, expect, it } from "vitest";
import { rankSituations, toSituationSummary } from "@/lib/situations";
import { createIncidentFixture } from "@/test/incident-fixture";

describe("Situation ranking", () => {
  it("maps incident evidence into the operator-facing summary", () => {
    const situation = toSituationSummary(createIncidentFixture());

    expect(situation).toMatchObject({
      id: "INC-1001",
      priority: "P1",
      owner: "Payroll Product",
      supportTeam: "Finance SRE",
      cause: "Database capacity exhausted after deployment",
      confidence: 0.91,
    });
    expect(situation.latestChange?.summary).toMatch(/release/i);
  });

  it("ranks critical situations ahead of lower-severity incidents", () => {
    const medium = createIncidentFixture({
      incident_id: "INC-2002",
      title: "Secondary warning",
      severity: "medium",
      started_at: "2025-03-01T11:00:00Z",
    });
    medium.business_impact.risk_score = 100;

    const ranked = rankSituations([medium, createIncidentFixture()]);

    expect(ranked.map((item) => item.id)).toEqual(["INC-1001", "INC-2002"]);
  });
});
