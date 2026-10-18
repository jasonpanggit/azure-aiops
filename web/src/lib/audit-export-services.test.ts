import { beforeEach, describe, expect, it, vi } from "vitest";
import { governanceApi } from "./services";

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: api.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

describe("personal exact-scope audit capture transport", () => {
  beforeEach(() => api.request.mockReset());
  it("preserves all nine dimensions and abort signals for every independent operation", async () => {
    const scope = { subscription: ["a", "b"], subscription_connection: ["conn"], business_service: ["Payments"],
      application: ["API"], environment: ["prod"], owner: ["Finance"], support_team: ["SRE"], region: ["eastus"], criticality: ["high"] };
    const signal = new AbortController().signal;
    await governanceApi.retainedExports(scope, signal);
    await governanceApi.captureExport(scope, "identity", 7, signal);
    await governanceApi.retainedExport(scope, "a/b", signal);
    await governanceApi.removeExport(scope, "a/b", 8, signal);
    for (const [, request] of api.request.mock.calls) {
      Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
      expect(request.signal).toBe(signal);
    }
    expect(api.request.mock.calls.map(([path]) => path)).toEqual([
      "/governance/exports/retained", "/governance/exports/retained",
      "/governance/exports/retained/a%2Fb", "/governance/exports/retained/remove",
    ]);
    expect(api.request.mock.calls[1][1].body).toEqual({ kind: "identity", expected_revision: 7 });
    expect(api.request.mock.calls[3][1].body).toEqual({ export_id: "a/b", expected_revision: 8 });
    expect(api.request.mock.calls[0][1].body).toBeUndefined();
  });
});
