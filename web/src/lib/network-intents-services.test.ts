import { beforeEach, describe, expect, it, vi } from "vitest";
import { networkApi } from "./services";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["Portal"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Platform"],
  support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};
const declaration = {
  test_id: "check-a", name: "No public access", source: "10.0.0.1", destination: "Internet",
  port: 443, protocol: "Tcp" as const, expected_verdict: "denied" as const,
};

describe("Network saved intents client", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });

  it.each(["read", "save", "run"])("preserves nine repeated dimensions and cancellation for %s", async (action) => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    if (action === "read") await networkApi.intents(scope, options);
    else if (action === "save") await networkApi.saveIntents(scope, 9, [declaration], options);
    else await networkApi.runIntents(scope, 9, options);
    const [path, request] = mock.request.mock.calls[0];
    expect(path).toBe(action === "run" ? "/network/intents/run" : "/network/intents");
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(controller.signal);
    expect(request.method).toBe(action === "save" ? "PUT" : action === "run" ? "POST" : undefined);
    expect(request.body).toEqual(action === "save"
      ? { expected_revision: 9, tests: [declaration] }
      : action === "run" ? { expected_revision: 9 } : undefined);
  });
});
