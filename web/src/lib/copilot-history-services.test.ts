import { beforeEach, describe, expect, it, vi } from "vitest";
import { askCanonicalInvestigation, copilotApi } from "./services";
import { SCOPE_DIMENSIONS } from "./scope";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));

describe("Copilot history and interrupt transport contracts", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });
  it("serializes exact selected continuity with its reviewed revision and admission key", async () => {
    await askCanonicalInvestigation("New turn", {}, { requestKey: "key", continuation: { threadId: "exact", threadRevision: 7 } });
    expect(mock.request.mock.calls[0][1].body).toMatchObject({ question: "New turn", request_key: "key", thread_id: "exact", expected_thread_revision: 7 });
  });
  it("transmits explicit same-key admission while preserving keyless existing callers", async () => {
    await askCanonicalInvestigation("Review evidence", {}, { requestKey: "exact-key" });
    expect(mock.request.mock.calls[0][1].body.request_key).toBe("exact-key");
    await askCanonicalInvestigation("Review evidence");
    expect(mock.request.mock.calls[1][1].body).not.toHaveProperty("request_key");
  });
  it("reads exact receipt under all nine dimensions without a write or automatic retry", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(name => [name, [`${name}-a`, `${name}-b`]]));
    const signal = new AbortController().signal;
    await copilotApi.requestReceipt("key/path", scope, signal);
    const [path, options] = mock.request.mock.calls[0];
    expect(path).toBe("/copilot/requests/key%2Fpath");
    expect(options.signal).toBe(signal);
    expect(options.method).toBeUndefined();
    expect(options.body).toBeUndefined();
    for (const name of SCOPE_DIMENSIONS) expect(options.query.getAll(name)).toEqual(scope[name]);
    expect(mock.request).toHaveBeenCalledTimes(1);
  });
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
