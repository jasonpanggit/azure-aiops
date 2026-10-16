import { beforeEach, describe, expect, it, vi } from "vitest";
import { twinApi } from "./services";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mock.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["Portal"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Platform"],
  support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};
const baseline = "a".repeat(32), candidate = "b".repeat(32);

describe("retained Twin client evidence boundary", () => {
  beforeEach(() => { mock.request.mockReset(); mock.request.mockResolvedValue({ data: {} }); });

  it.each(["read", "capture", "remove", "compare", "scenarios"])("preserves exact scope, cancellation and minimal %s payload", async action => {
    const controller = new AbortController();
    if (action === "read") await twinApi.snapshots(scope, controller.signal);
    else if (action === "capture") await twinApi.captureSnapshot(scope, 7, controller.signal);
    else if (action === "remove") await twinApi.removeSnapshot(scope, baseline, 7, controller.signal);
    else if (action === "compare") await twinApi.compareSnapshots(scope, baseline, candidate, controller.signal);
    else await twinApi.retainedScenarios(scope, baseline, "route_change", "patch_deployment", "resource:/exact/vm", controller.signal);
    const [path, request] = mock.request.mock.calls[0];
    const suffix = action === "remove" ? "/remove" : action === "compare" ? "/compare" : action === "scenarios" ? `/${baseline}/scenarios` : "";
    expect(path).toBe(`/twin/snapshots${suffix}`);
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(controller.signal);
    expect(request.body).toEqual(action === "capture" ? { expected_revision: 7 } : action === "remove" ? { snapshot_id: baseline, expected_revision: 7 } : undefined);
    expect(request.method).toBe(["capture", "remove"].includes(action) ? "POST" : undefined);
    if (action === "compare") {
      expect(request.query.get("baseline_id")).toBe(baseline);
      expect(request.query.get("candidate_id")).toBe(candidate);
    }
    if (action === "scenarios") {
      expect(request.query.get("left")).toBe("route_change");
      expect(request.query.get("right")).toBe("patch_deployment");
      expect(request.query.get("target")).toBe("resource:/exact/vm");
    }
  });
});
