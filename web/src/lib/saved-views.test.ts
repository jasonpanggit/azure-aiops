import { beforeEach, describe, expect, it, vi } from "vitest";
import { savedViewHref, type SavedView } from "./saved-views";
import { savedViewsApi } from "./services";

const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: mocks.request, resolveApiBaseUrl: () => "http://127.0.0.1" }));
const scope = {
  subscription: ["sub-a", "sub-b"], business_service: ["Payments"], application: ["Portal"],
  environment: ["prod"], subscription_connection: ["conn-a"], owner: ["Platform"],
  support_team: ["SRE"], region: ["eastus"], criticality: ["high"],
};
const search: SavedView = { kind: "search", view_id: "search-a", name: "Search A", query: "show list of VMs", entity_type: "VirtualMachine", source: "ARG" };
const triage: SavedView = {
  kind: "situations", view_id: "triage-a", name: "Queue A", query: "Payments", priority: "P1",
  assigned_owner: "Team & owner", lifecycle_state: "open", older_than_hours: 24, sort: "oldest",
};

describe("Personal saved view continuation", () => {
  beforeEach(() => { mocks.request.mockReset(); mocks.request.mockResolvedValue({ data: {} }); });

  it.each([search, triage])("restores allowlisted first-page settings for $kind with every repeated scope dimension", view => {
    const url = new URL(savedViewHref(view, scope), "http://127.0.0.1");
    expect(url.pathname).toBe(`/${view.kind}`);
    Object.entries(scope).forEach(([key, values]) => expect(url.searchParams.getAll(key)).toEqual(values));
    expect(url.searchParams.get("q")).toBe(view.query);
    expect(url.searchParams.has("page")).toBe(false);
    expect(url.searchParams.has("offset")).toBe(false);
    expect(url.searchParams.has("view_id")).toBe(false);
    expect(url.searchParams.has("name")).toBe(false);
    if (view.kind === "search") {
      expect(url.searchParams.get("entity_type")).toBe("VirtualMachine");
      expect(url.searchParams.get("source")).toBe("ARG");
    } else {
      expect(url.searchParams.get("assigned_owner")).toBe("Team & owner");
      expect(url.searchParams.get("older_than_hours")).toBe("24");
      expect(url.searchParams.get("sort")).toBe("oldest");
    }
  });

  it("restores an empty/default queue without stale filters or a query suffix", () => {
    expect(savedViewHref({ ...triage, kind: "situations", query: "", priority: "all", assigned_owner: "", lifecycle_state: "", older_than_hours: null, sort: "default" }, {}))
      .toBe("/situations");
  });

  it.each(["read", "replace"])("preserves all scope dimensions and cancellation for %s", async action => {
    const controller = new AbortController();
    if (action === "read") await savedViewsApi.read(scope, { signal: controller.signal });
    else await savedViewsApi.replace(scope, 7, [search, triage], { signal: controller.signal });
    const [path, request] = mocks.request.mock.calls[0];
    expect(path).toBe("/saved-views");
    Object.entries(scope).forEach(([key, values]) => expect(request.query.getAll(key)).toEqual(values));
    expect(request.signal).toBe(controller.signal);
    expect(request.method).toBe(action === "read" ? undefined : "PUT");
    expect(request.body).toEqual(action === "read" ? undefined : { expected_revision: 7, views: [search, triage] });
  });
});
