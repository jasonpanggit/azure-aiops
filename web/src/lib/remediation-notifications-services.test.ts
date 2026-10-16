import { beforeEach, describe, expect, it, vi } from "vitest";
import { remediationApi } from "./services";
const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: api.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["API"], environment: ["prod"],
  subscription_connection: ["conn-a"], owner: ["Finance"], support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};
describe("stored verification notification transport", () => {
  beforeEach(() => api.request.mockReset());
  it.each(["", "attention", "complete", "cancelled"] as const)("preserves all scope dimensions and read-only %s filtering", async kind => {
    const signal = new AbortController().signal;
    await remediationApi.notifications(scope, kind, 25, signal);
    const [path, request] = api.request.mock.calls[0];
    expect(path).toBe("/remediation/verification-inbox");
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.query.get("kind")).toBe(kind || null);
    expect(request.query.get("offset")).toBe("25");
    expect(request.query.get("limit")).toBe("25");
    expect(request.signal).toBe(signal);
    expect(request.method).toBeUndefined(); expect(request.body).toBeUndefined();
  });
});
