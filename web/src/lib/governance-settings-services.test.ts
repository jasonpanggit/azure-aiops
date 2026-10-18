import { beforeEach, describe, expect, it, vi } from "vitest";
import { governanceApi } from "./services";

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: api.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

describe("enterprise-wide settings transport", () => {
  beforeEach(() => api.request.mockReset());
  it("preserves all read scope dimensions and aborts independently", async () => {
    const scope = { subscription: ["a", "b"], subscription_connection: ["conn"], business_service: ["Payments"],
      application: ["API"], environment: ["prod"], owner: ["Finance"], support_team: ["SRE"], region: ["eastus"], criticality: ["high"] };
    const signal = new AbortController().signal;
    await governanceApi.settings(scope, signal);
    const [path, request] = api.request.mock.calls[0];
    expect(path).toBe("/governance/settings");
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(signal);
    expect(request.body).toBeUndefined();
  });
  it("sends only explicit reviewed metadata and patch, never misleading inventory scope", async () => {
    const signal = new AbortController().signal;
    const body = { expected_revision: 7, reason: "Reviewed", changes: { retention_policy: { audit_log_days: 30 } } };
    await governanceApi.updateSettings(body, signal);
    expect(api.request).toHaveBeenCalledWith("/governance/settings", { method: "PATCH", body, signal });
  });
});
