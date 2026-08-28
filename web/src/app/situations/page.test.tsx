import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import { useScope } from "@/lib/scope-context";

const { list } = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/services", () => ({
  buildCopilotSnapshot: (input: Record<string, unknown>) => input,
  copilotEvidenceRows: () => [],
  situationsApi: { list },
}));

import SituationsPage from "./page";

const rows = [
  {
    situation_id: "situation://p1",
    resource_id: "situation://p1",
    title: "Database unavailable",
    situation_type: "service_health",
    lifecycle_state: "open",
    severity: "critical",
    priority: "P1",
    scope: { subscription: ["sub-a"] },
    owner: "SRE",
    support_team: "Platform",
    affected_resource_ids: ["/subscriptions/sub-a/db"],
    linked_evidence_ids: [],
    started_at: "2026-08-25T01:00:00Z",
    last_observed_at: "2026-08-25T01:00:00Z",
    evidence_state: "unknown",
    warnings: [],
    contradiction_ids: [],
    unknowns: [],
    run_id: "run-1",
  },
];

function response(data = rows, pagination: Partial<{ offset: number; limit: number; total: number; next_offset: number | null }> = {}) {
  return {
    data,
    evidence: [],
    scope: { subscription: ["sub-a"] },
    pagination: { offset: 0, limit: 25, total: data.length, next_offset: null, ...pagination },
  };
}

function ScopeHarness() {
  const { setScope } = useScope();
  return <button type="button" onClick={() => setScope({ subscription: ["sub-b"] })}>Change scope</button>;
}

describe("durable Situation queue", () => {
  beforeEach(() => {
    list.mockReset();
    list.mockResolvedValue(response());
  });

  it("shows loading while the durable queue request is pending", () => {
    list.mockImplementationOnce(() => new Promise(() => {}));
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    expect(screen.getByText("Loading Situation queue")).toBeInTheDocument();
  });

  it("loads durable rows and filters by search plus every priority", async () => {
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    expect(await screen.findByText("Database unavailable")).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith({}, "", "", 0, 25);
    expect(screen.getByText("Showing 1–1 of 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Database unavailable" })).toHaveAttribute(
      "href",
      "/situations/situation%3A%2F%2Fp1",
    );

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "database" } });
    await waitFor(() => expect(list).toHaveBeenLastCalledWith({}, "database", "", 0, 25));
    for (const value of ["P1", "P2", "P3"]) {
      fireEvent.click(screen.getByRole("button", { name: value }));
      await waitFor(() => expect(list).toHaveBeenLastCalledWith({}, "database", value, 0, 25));
    }
  });

  it("navigates paginated durable rows with next and previous controls", async () => {
    const secondPage = { ...rows[0], situation_id: "situation://p2", resource_id: "situation://p2", title: "Cache degraded" };
    list
      .mockResolvedValueOnce(response(rows, { total: 26, next_offset: 25 }))
      .mockResolvedValueOnce(response([secondPage], { offset: 25, total: 26, next_offset: null }))
      .mockResolvedValueOnce(response(rows, { total: 26, next_offset: 25 }));
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    expect(await screen.findByText("Showing 1–1 of 26")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Cache degraded")).toBeInTheDocument();
    expect(screen.getByText("Showing 26–26 of 26")).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith({}, "", "", 25, 25);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith({}, "", "", 0, 25));
  });

  it("distinguishes an empty authorized scope from an empty filtered result", async () => {
    list.mockResolvedValueOnce(response([]));
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    expect(await screen.findByText("No active situations in this scope")).toBeInTheDocument();
    expect(screen.getByText(/No durable situation records are currently available/)).toBeInTheDocument();

    list.mockResolvedValueOnce(response([]));
    fireEvent.click(screen.getByRole("button", { name: "P1" }));
    expect(await screen.findByText("No situations match these filters")).toBeInTheDocument();
    expect(screen.getByText("Adjust the priority or search criteria. This result reflects the current operating scope.")).toBeInTheDocument();
  });

  it("reloads on scope change and replaces prior rows only after the new response", async () => {
    let resolveScoped: ((value: ReturnType<typeof response>) => void) | undefined;
    const scopedResponse = new Promise<ReturnType<typeof response>>((resolve) => { resolveScoped = resolve; });
    list.mockImplementation((scope) => scope.subscription ? scopedResponse : Promise.resolve(response()));
    render(<ScopeProvider><ScopeHarness /><SituationsPage /></ScopeProvider>);

    expect(await screen.findByText("Database unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change scope" }));
    expect(screen.getByText("Loading Situation queue")).toBeInTheDocument();
    expect(screen.queryByText("Database unavailable")).not.toBeInTheDocument();
    resolveScoped?.(response([{ ...rows[0], title: "Scoped database outage" }]));
    expect(await screen.findByText("Scoped database outage")).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith({ subscription: ["sub-b"] }, "", "", 0, 25);
  });

  it("renders an error instead of an empty all-clear state", async () => {
    list.mockRejectedValueOnce(new Error("provider unavailable"));
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    expect(await screen.findByText("Situation intelligence is unavailable")).toBeInTheDocument();
    expect(screen.getByText(/will not present an empty queue as an all-clear/)).toBeInTheDocument();
  });

  it("keeps the Investigate row action keyboard reachable and activatable", async () => {
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    const action = await screen.findByRole("link", { name: "Investigate Database unavailable" });
    action.focus();
    expect(document.activeElement).toBe(action);
    fireEvent.keyDown(action, { key: "Enter", code: "Enter" });
    action.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(action);
    expect(action).toHaveAttribute("href", "/situations/situation%3A%2F%2Fp1");
  });
});
