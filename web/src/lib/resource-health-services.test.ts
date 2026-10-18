import { beforeEach, describe, expect, it, vi } from "vitest";
import { resourceHealthApi } from "./services";

const mock = vi.hoisted(() => ({
  request: vi.fn<(path: string, options: {
    query: URLSearchParams; signal?: AbortSignal; method?: string; body?: unknown;
  }) => Promise<unknown>>(),
}));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["Portal"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Platform"],
  support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};
const resourceId = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a";

describe("Resource Health retention client", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });

  it("preserves all repeated scope dimensions, resource identity and read cancellation", async () => {
    const controller = new AbortController();
    await resourceHealthApi.history(resourceId, scope, { signal: controller.signal });
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/resource-health/resource/history");
    expect(options.query.get("resource_id")).toBe(resourceId);
    Object.entries(scope).forEach(([key, values]) => expect(options.query.getAll(key)).toEqual(values));
    expect(options.signal).toBe(controller.signal);
    expect(options.body).toBeUndefined();
    expect(options.method).toBeUndefined();
  });

  it("sends only the reviewed revision, never browser measurements", async () => {
    const controller = new AbortController();
    await resourceHealthApi.captureHistory(resourceId, scope, 17, { signal: controller.signal });
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/resource-health/resource/history");
    expect(options.method).toBe("POST");
    expect(options.body).toEqual({ expected_revision: 17 });
    expect(options.query.get("resource_id")).toBe(resourceId);
    Object.entries(scope).forEach(([key, values]) => expect(options.query.getAll(key)).toEqual(values));
    expect(options.signal).toBe(controller.signal);
  });
});
