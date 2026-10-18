import { beforeEach, describe, expect, it, vi } from "vitest";
import { situationsApi } from "./services";
const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: api.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payroll"], application: ["API"], environment: ["prod"],
  subscription_connection: ["conn-a"], owner: ["Finance"], support_team: ["Ops"], region: ["eastus"], criticality: ["high"],
};
describe("Situation response-review transport", () => {
  beforeEach(() => api.request.mockReset());
  it.each(["read", "write"])("preserves all nine scope dimensions and cancellation for %s", async action => {
    const signal = new AbortController().signal;
    const change = { expected_revision: 4, evidence_run_id: "run-1", due_at: null, reason: "Explicit removal" };
    if (action === "read") await situationsApi.deadline("situation://case/a", scope, signal);
    else await situationsApi.declareDeadline("situation://case/a", scope, change, signal);
    const [path, request] = api.request.mock.calls[0];
    expect(path).toBe("/situations/situation%3A%2F%2Fcase%2Fa/response-deadline");
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(signal);
    expect(request.body).toEqual(action === "read" ? undefined : change);
    expect(request.method).toBe(action === "read" ? undefined : "PUT");
  });
  it("passes the server deadline filter with first-page triage options", async () => {
    await situationsApi.list(scope, "", "", 0, 25, {
      owner: "", lifecycle_state: "", older_than_hours: null, sort: "default", response_deadline: "overdue",
    });
    expect(api.request.mock.calls[0][1].query.get("response_deadline")).toBe("overdue");
  });
});
