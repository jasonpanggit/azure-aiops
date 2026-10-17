import { beforeEach, describe, expect, it, vi } from "vitest";
import { askCanonicalInvestigation, copilotApi } from "./services";
import { SCOPE_DIMENSIONS } from "./scope";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

describe("Copilot history and interrupt transport contracts", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });
  it("discovers a read-only authorized page with scope and cancellation", async () => {
    const controller = new AbortController();
    await copilotApi.retainedThreads({ owner: ["a", "b"] }, 2, controller.signal);
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/copilot/threads");
    expect(options.query.getAll("owner")).toEqual(["a", "b"]);
    expect(options.query.get("page")).toBe("2");
    expect(options.signal).toBe(controller.signal);
    expect(options.method).toBeUndefined();
    expect(options.body).toBeUndefined();
  });
  it("pins a retained read to the reviewed revision", async () => {
    await copilotApi.retainedHistory("thread", {}, { expectedRevision: 3 });
    expect(mock.request.mock.calls[0][1].query.get("expected_revision")).toBe("3");
  });
  it("reads one encoded identity with repeated nine-dimensional scope and AbortSignal", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(key => [key, [`${key}-a`, `${key}-b`]]));
    const controller = new AbortController();
    await copilotApi.retainedHistory("thr/id", scope, { signal: controller.signal });
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/copilot/threads/thr%2Fid/history");
    for (const [key, values] of Object.entries(scope)) expect(options.query.getAll(key)).toEqual(values);
    expect(options.signal).toBe(controller.signal);
    expect(options.method).toBeUndefined();
    expect(options.body).toBeUndefined();
  });
  it("forwards browser abort without substituting a server cancel request or changing execution payload", async () => {
    const controller = new AbortController();
    await askCanonicalInvestigation("Review evidence", { subscription: ["sub-a"] }, { sessionId: "root", signal: controller.signal });
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/copilot/investigate");
    expect(options.method).toBe("POST");
    expect(options.signal).toBe(controller.signal);
    expect(options.query.getAll("subscription")).toEqual(["sub-a"]);
    expect(options.body.question).toBe("Review evidence");
    expect(mock.request).toHaveBeenCalledTimes(1);
  });
});
