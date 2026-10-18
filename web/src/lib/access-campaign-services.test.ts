import { describe, expect, it, vi } from "vitest";
import { governanceApi } from "./services";

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: api.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

describe("exact-scope advisory campaign transport", () => {
  it("preserves all nine dimensions, explicit bodies, aborts and safe identifiers", async () => {
    api.request.mockReset();
    const scope = { subscription: ["a", "b"], subscription_connection: ["conn"], business_service: ["payments"],
      application: ["api"], environment: ["prod"], owner: ["finance"], support_team: ["sre"], region: ["eastus"], criticality: ["high"] };
    const signal = new AbortController().signal;
    const address = { campaign_id: "a/b", expected_revision: 7 };
    const create = { title: "Review", audience: "auditor" as const, reviewer_subject: "reader", due_at: "2026-11-01T12:00:00Z", expected_revision: 7 };
    const decide = { ...address, principal_id: "p", recommendation: "investigate" as const, reason: "Confirm owner" };
    await governanceApi.campaigns(scope, signal);
    await governanceApi.campaign(scope, address.campaign_id, signal);
    await governanceApi.createCampaign(scope, create, signal);
    await governanceApi.decideCampaign(scope, decide, signal);
    await governanceApi.closeCampaign(scope, "complete", { ...address, reason: "Reviewed" }, signal);
    await governanceApi.removeCampaign(scope, address, signal);
    for (const [, request] of api.request.mock.calls) {
      Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
      expect(request.signal).toBe(signal);
    }
    expect(api.request.mock.calls[1][0]).toBe("/governance/access-campaigns/a%2Fb");
    expect(api.request.mock.calls[2][1].body).toEqual(create);
    expect(api.request.mock.calls[3][1].body).toEqual(decide);
    expect(api.request.mock.calls[4][0]).toBe("/governance/access-campaigns/complete");
    expect(api.request.mock.calls[5][1].body).toEqual(address);
  });
});
