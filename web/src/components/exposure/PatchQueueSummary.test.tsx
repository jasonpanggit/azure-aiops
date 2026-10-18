import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_EXPOSURE_SORT, type ExposureQueryState } from "@/lib/exposure-query-state";
import { PatchQueueSummary } from "./PatchQueueSummary";

const api = vi.hoisted(() => ({ exposureFacets: vi.fn() }));
vi.mock("@/lib/services", () => ({ vulnerabilityApi: api }));
const query: ExposureQueryState = {
  scope: { subscription: ["sub-a"] }, filters: { severity: "critical", active: true },
  sort: DEFAULT_EXPOSURE_SORT, pageSize: 25, page: 1, cursor: null, cursorHistory: [], target: "", drawer: "", generation: "gen-one",
};
const response = () => ({
  data: { generation: "gen-one", total_count: 100, facets: { severity: [{ value: "critical", count: 100 }], sla_state: [{ value: "overdue", count: 30 }] },
    contract: { query: { scope: query.scope, generation: "gen-one" }, counts: { returned: 0, total: 100 }, completeness: { state: "partial" }, freshness: { state: "reported", as_of: "2026-10-17T00:00:00Z" }, safe_error: null } },
  scope: query.scope, evidence: [], warnings: [],
});
describe("Whole-query patch aggregates", () => {
  beforeEach(() => { vi.clearAllMocks(); api.exposureFacets.mockResolvedValue(response()); });
  it("uses authoritative total rather than cursor page rows and preserves filters/generation", async () => {
    render(<PatchQueueSummary query={query} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("row", { name: "severity critical 100" })).toBeVisible();
    expect(within(table).getByRole("row", { name: "sla_state Not represented in this vocabulary 70" })).toBeVisible();
    expect(within(table).getByRole("row", { name: "target_kind Vocabulary unavailable Unknown" })).toBeVisible();
    expect(api.exposureFacets).toHaveBeenCalledWith(query, ["severity", "sla_state", "target_kind", "current_state"], expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText(/not distinct machines/)).toBeVisible();
  });
  it("does not refetch whole-query counts for cursor-only movement", async () => {
    const view = render(<PatchQueueSummary query={query} />);
    await screen.findByRole("table");
    view.rerender(<PatchQueueSummary query={{ ...query, cursor: "opaque-next", page: 2, cursorHistory: [""] }} />);
    expect(api.exposureFacets).toHaveBeenCalledTimes(1);
  });
  it("exposes independent failure without a fabricated zero", async () => {
    api.exposureFacets.mockRejectedValueOnce(new Error("Facet source unavailable"));
    render(<PatchQueueSummary query={query} />);
    expect(await screen.findByText(/Facet source unavailable/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it.each(["generation", "scope", "counts"])("rejects mismatched %s", async damage => {
    const result = response();
    if (damage === "generation") result.data.generation = "other";
    else if (damage === "scope") result.scope = { subscription: ["other"] };
    else result.data.facets.severity[0].count = 101;
    api.exposureFacets.mockResolvedValueOnce(result);
    render(<PatchQueueSummary query={query} />);
    await screen.findByText(damage === "counts" ? /counts are inconsistent/ : /do not match/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
