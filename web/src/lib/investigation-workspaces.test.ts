import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./api-client";
import { investigationWorkspacesApi, investigationWorkspaceHref, type InvestigationTeamWorkspace } from "./investigation-workspaces";
import { SCOPE_DIMENSIONS } from "./scope";

vi.mock("./api-client", () => ({ apiRequest: vi.fn().mockResolvedValue({ data: {} }) }));
const request = vi.mocked(apiRequest);
const id = `wrk-${"a".repeat(32)}`;
const view = { title: "Payments", entry_type: "BusinessService" as const, subject: "Payments", mode: "engineer" as const };
const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, [`${dimension}-a`, `${dimension}-b`]]));

function queryAt(index: number) {
  const query = request.mock.calls[index][1]?.query;
  if (!(query instanceof URLSearchParams)) throw new Error("Expected canonical repeated scope parameters");
  return query;
}

describe("team Investigation client contracts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("preserves all scope dimensions, known identity and strict request shape on creation", async () => {
    const signal = new AbortController().signal;
    await investigationWorkspacesApi.create(id, view, scope, signal);
    const [url, options] = request.mock.calls[0];
    expect(url).toBe("/investigation-workspaces");
    expect(options).toMatchObject({ method: "POST", body: { workspace_id: id, view }, signal });
    for (const dimension of SCOPE_DIMENSIONS) expect(queryAt(0).getAll(dimension)).toEqual(scope[dimension]);
  });

  it("pins an explicit historical read and does not send a mutation", async () => {
    const signal = new AbortController().signal;
    await investigationWorkspacesApi.read(id, scope, 3, signal);
    const [url, options] = request.mock.calls[0];
    expect(url).toBe(`/investigation-workspaces/${id}`);
    expect(queryAt(0).get("revision")).toBe("3");
    expect(options?.signal).toBe(signal);
    expect(options).not.toHaveProperty("body");
    expect(options).not.toHaveProperty("method");
    for (const dimension of SCOPE_DIMENSIONS) expect(queryAt(0).getAll(dimension)).toEqual(scope[dimension]);
  });

  it("separates view updates from owner-only membership changes at a reviewed revision", async () => {
    await investigationWorkspacesApi.replace(id, 3, view, scope);
    await investigationWorkspacesApi.share(id, 4, ["reader"], ["editor"], scope);
    expect(request.mock.calls[0][1]?.body).toEqual({ expected_revision: 3, view });
    expect(request.mock.calls[1][0]).toBe(`/investigation-workspaces/${id}/access`);
    expect(request.mock.calls[1][1]?.body).toEqual({ expected_revision: 4, readers: ["reader"], editors: ["editor"] });
    request.mock.calls.forEach(([, options], index) => {
      expect(options?.method).toBe("PUT");
      for (const dimension of SCOPE_DIMENSIONS) expect(queryAt(index).getAll(dimension)).toEqual(scope[dimension]);
    });
  });

  it("links the selected navigation revision and stored effective scope, not the latest revision or client authority", () => {
    const revision = { revision: 2, actor: "owner", recorded_at: "2026-10-16T12:00:00Z", change: "view_updated" as const, view, readers: [], editors: [], hypotheses: [] };
    const workspace: InvestigationTeamWorkspace = {
      workspace_id: id, owner: "owner", scope, latest_revision: 4, revision,
      current_access: { readers: ["reviewer"], editors: [] }, can_edit: false, can_share: false, history: [revision],
    };
    const url = new URL(investigationWorkspaceHref(workspace), "http://localhost");
    expect(url.searchParams.get("workspace_revision")).toBe("2");
    expect(url.searchParams.get("workspace_id")).toBe(id);
    expect(url.searchParams.get("mode")).toBe("engineer");
    for (const dimension of SCOPE_DIMENSIONS) expect(url.searchParams.getAll(dimension)).toEqual(scope[dimension]);
    expect(url.searchParams.has("owner")).toBe(true);
    expect(url.searchParams.has("readers")).toBe(false);
    expect(url.searchParams.has("can_share")).toBe(false);
  });

  it("saves one browser-known hypothesis at the exact reviewed revision without provider or authority fields", async () => {
    const signal = new AbortController().signal;
    const hypothesisId = `hyp-${"b".repeat(32)}`;
    const hypothesis = {
      explanation: "Operator explanation", supporting: [], contradicting: [], unknowns: [],
      disposition: "proposed" as const, rationale: "",
    };
    await investigationWorkspacesApi.hypothesis(id, hypothesisId, 3, hypothesis, scope, signal);
    expect(request).toHaveBeenCalledOnce();
    expect(request.mock.calls[0][0]).toBe(`/investigation-workspaces/${id}/hypotheses/${hypothesisId}`);
    expect(request.mock.calls[0][1]).toMatchObject({
      method: "PUT", body: { expected_revision: 3, hypothesis }, signal,
    });
    for (const dimension of SCOPE_DIMENSIONS) expect(queryAt(0).getAll(dimension)).toEqual(scope[dimension]);
  });
});
