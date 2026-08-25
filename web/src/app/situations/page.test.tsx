import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { list } = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/services", () => ({
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

function response(data = rows) {
  return {
    data,
    evidence: [],
    scope: { subscription: ["sub-a"] },
    pagination: { offset: 0, limit: 25, total: data.length, next_offset: null },
  };
}

describe("durable Situation queue", () => {
  beforeEach(() => {
    list.mockReset();
    list.mockResolvedValue(response());
  });

  it("loads durable rows, filters by search and priority, and exposes pagination", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "P1" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith({}, "database", "P1", 0, 25));
  });

  it("renders an error instead of an empty all-clear state", async () => {
    list.mockRejectedValueOnce(new Error("provider unavailable"));
    render(<ScopeProvider><SituationsPage /></ScopeProvider>);

    expect(await screen.findByText("Situation intelligence is unavailable")).toBeInTheDocument();
    expect(screen.getByText(/will not present an empty queue as an all-clear/)).toBeInTheDocument();
  });
});
