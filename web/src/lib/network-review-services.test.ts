import { beforeEach, describe, expect, it, vi } from "vitest";
import { networkApi, predeployApi } from "./services";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["Portal"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Platform"],
  support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};
const reference = { kind: "gap" as const, finding_id: "gap-a", reviewed_digest: "a".repeat(64) };

describe("Network predeploy handoff service contracts", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: [] }); });
  it.each(["review", "assess", "sources", "history", "detail"])("preserves all scope dimensions for %s", async action => {
    const controller = new AbortController();
    if (action === "review") await networkApi.review(scope, reference, { signal: controller.signal });
    else if (action === "assess") await predeployApi.assess("terraform_plan", {}, "", { scope, networkReview: reference, signal: controller.signal });
    else if (action === "sources") await predeployApi.sources(scope);
    else if (action === "history") await predeployApi.assessments(scope);
    else await predeployApi.assessment("assessment-a", scope);
    const [, request] = mock.request.mock.calls[0];
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    if (action === "review" || action === "assess") expect(request.signal).toBe(controller.signal);
    if (action === "assess") expect(request.body).toEqual({ source: "terraform_plan", payload: {}, change_id: "", network_review: reference });
    if (action === "review") Object.entries(reference).forEach(([key, value]) => expect(request.query.get(key)).toBe(value));
  });

  it("leaves unlinked assessment body unchanged and preserves actual list-array shape", async () => {
    await predeployApi.assess("arm_diff", {});
    expect(mock.request.mock.calls[0][1].body).toEqual({ source: "arm_diff", payload: {}, change_id: "" });
    expect((await predeployApi.assessments(scope)).data).toEqual([]);
  });
});
