import { beforeEach, describe, expect, it, vi } from "vitest";
import { networkApi } from "./services";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["Portal"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Platform"],
  support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};

describe("Retained topology service client", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });

  it.each(["read", "capture", "compare"])("preserves exact scope and cancellation for %s", async action => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    if (action === "read") await networkApi.topologyHistory(scope, options);
    else if (action === "capture") await networkApi.captureTopology(scope, 7, options);
    else await networkApi.compareTopology(scope, "earlier", "later", 50, options);
    const [path, request] = mock.request.mock.calls[0];
    expect(path).toBe(`/network/topology/history${action === "compare" ? "/compare" : ""}`);
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(controller.signal);
    expect(request.body).toEqual(action === "capture" ? { expected_revision: 7 } : undefined);
    expect(request.method).toBe(action === "capture" ? "POST" : undefined);
    if (action === "compare") {
      expect(request.query.get("baseline_id")).toBe("earlier");
      expect(request.query.get("target_id")).toBe("later");
      expect(request.query.get("offset")).toBe("50");
      expect(request.query.get("limit")).toBe("50");
    }
  });
});
