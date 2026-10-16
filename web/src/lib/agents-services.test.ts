import { beforeEach, describe, expect, it, vi } from "vitest";
import { multiAgentApi } from "./services";
import { SCOPE_DIMENSIONS } from "./scope";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

describe("Cached Agents runtime service client", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });
  it("preserves nine-dimensional repeated scope and cancellation using read-only GET", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, [`${dimension}-a`, `${dimension}-b`]]));
    const controller = new AbortController();
    await multiAgentApi.runtimeReadiness(scope, { signal: controller.signal });
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/agents/runtime-readiness");
    for (const [key, values] of Object.entries(scope)) expect(options.query.getAll(key)).toEqual(values);
    expect(options.signal).toBe(controller.signal);
    expect(options.method).toBeUndefined();
    expect(options.body).toBeUndefined();
  });
});
