import { beforeEach, describe, expect, it, vi } from "vitest";
import { serviceReliabilityApi } from "./services";

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: api.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payroll"], application: ["API"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Finance"],
  support_team: ["Ops"], region: ["eastus"], criticality: ["high"],
};

describe("component reliability transport", () => {
  beforeEach(() => api.request.mockReset());
  it.each(["objectives", "components", "save", "remove", "metrics"])("preserves exact scope and minimal %s input", async action => {
    const signal = new AbortController().signal;
    const objective = { resource_id: "/exact/component", success_target_basis_points: 9990, window_hours: 24 as const };
    if (action === "objectives") await serviceReliabilityApi.objectives(scope, signal);
    else if (action === "components") await serviceReliabilityApi.components(scope, "Payroll", 25, signal);
    else if (action === "save") await serviceReliabilityApi.save(scope, objective, 7, signal);
    else if (action === "remove") await serviceReliabilityApi.remove(scope, objective.resource_id, 7, signal);
    else await serviceReliabilityApi.metrics(scope, objective.resource_id, signal);
    const [path, request] = api.request.mock.calls[0];
    expect(path).toBe(`/service-reliability/${action === "save" ? "objectives" : action === "remove" ? "objectives/remove" : action}`);
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(signal);
    expect(request.method).toBe(action === "save" ? "PUT" : action === "remove" ? "POST" : undefined);
    expect(request.body).toEqual(action === "save" ? { ...objective, expected_revision: 7 } : action === "remove" ? { resource_id: objective.resource_id, expected_revision: 7 } : undefined);
    if (action === "metrics") expect(request.query.get("resource_id")).toBe(objective.resource_id);
    if (action === "components") expect([request.query.get("q"), request.query.get("offset"), request.query.get("limit")]).toEqual(["Payroll", "25", "25"]);
  });
});
