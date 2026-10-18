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
  it("separates exact-ID admission, metadata reads and cooperative stop with complete scope", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, [`${dimension}-a`, `${dimension}-b`]]));
    const id = `job-${"a".repeat(32)}`;
    const controller = new AbortController();
    await multiAgentApi.startJob(id, "Review network", scope, 20);
    await multiAgentApi.job(id, scope, { signal: controller.signal });
    await multiAgentApi.stopJob(id, scope);
    const [admit, read, stop] = mock.request.mock.calls;
    expect(admit[0]).toBe("/agents/investigation-jobs");
    expect(admit[1].body).toEqual({ job_id: id, objective: "Review network", timeout_seconds: 20 });
    expect(admit[1].method).toBe("POST");
    expect(read[0]).toBe(`/agents/investigation-jobs/${id}`);
    expect(read[1].signal).toBe(controller.signal);
    expect(read[1].method).toBeUndefined();
    expect(read[1].body).toBeUndefined();
    expect(stop[0]).toBe(`/agents/investigation-jobs/${id}/stop`);
    expect(stop[1].method).toBe("POST");
    expect(stop[1].body).toBeUndefined();
    for (const [, options] of [admit, read, stop]) {
      for (const [key, values] of Object.entries(scope)) expect(options.query.getAll(key)).toEqual(values);
    }
  });
});
