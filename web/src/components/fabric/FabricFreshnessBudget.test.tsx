import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FabricFreshnessBudget } from "./FabricFreshnessBudget";
import type { FabricFreshnessBudget as Budget } from "@/lib/types";

function budget(): Budget {
  return {
    evaluated_at: "2026-10-17T12:00:00Z", clock: "metadata_status_ingested_then_observed_then_timestamp",
    state: "fresh", threshold_seconds: 1800, cadence_minutes: 10, slo_multiplier: 3,
    policy: "table_override", source_count: 1, known_clock_count: 1,
    worst_known_age_seconds: 600, remaining_seconds: 1200,
    sources: [{ scope: { subscription_connection: ["conn-one"] }, status_at: "2026-10-17T11:50:00Z",
      state: "fresh", age_seconds: 600, remaining_seconds: 1200 }],
  };
}

describe("Fabric server-evaluated freshness budget", () => {
  it("discloses static evaluation, configured threshold, source clocks and limitations", () => {
    render(<FabricFreshnessBudget budget={budget()} />);
    expect(screen.getByText("Freshness budget: 20 min remaining")).toBeInTheDocument();
    expect(screen.getByText(/30 min limit = 10 min cadence × 3/)).toHaveTextContent("Table override");
    expect(screen.getByText(/1\/1 source clocks usable/)).toBeInTheDocument();
    expect(screen.getByText(/does not verify resource-data freshness/)).toHaveTextContent("Headroom is fixed at the evaluation time");
    expect(screen.getByText("subscription_connection: conn-one")).toBeInTheDocument();
  });

  it("distinguishes unknown, stale, and exactly exhausted headroom", () => {
    const value = budget();
    value.sources[0] = { ...value.sources[0], state: "unknown", status_at: "", age_seconds: null, remaining_seconds: null };
    Object.assign(value, { state: "unknown", known_clock_count: 0, worst_known_age_seconds: null, remaining_seconds: null });
    const view = render(<FabricFreshnessBudget budget={value} />);
    expect(screen.getByText("Freshness budget: Unknown headroom")).toBeInTheDocument();
    expect(screen.getByText(/Unknown age \(missing, invalid, unzoned, or future clock\)/)).toBeInTheDocument();
    const stale = budget();
    Object.assign(stale, { state: "stale", worst_known_age_seconds: 3600, remaining_seconds: -1800 });
    Object.assign(stale.sources[0], { state: "stale", age_seconds: 3600, remaining_seconds: -1800 });
    view.rerender(<FabricFreshnessBudget budget={stale} />);
    expect(screen.getByText("Freshness budget: 30 min over budget")).toBeInTheDocument();
    Object.assign(stale, { state: "fresh", worst_known_age_seconds: 1800, remaining_seconds: 0 });
    Object.assign(stale.sources[0], { state: "fresh", age_seconds: 1800, remaining_seconds: 0 });
    view.rerender(<FabricFreshnessBudget budget={stale} />);
    expect(screen.getByText("Freshness budget: At budget boundary")).toBeInTheDocument();
  });

  it("renders no status rows as unknown, not full headroom", () => {
    const value = { ...budget(), sources: [], source_count: 0, known_clock_count: 0,
      state: "unknown" as const, remaining_seconds: null, worst_known_age_seconds: null };
    render(<FabricFreshnessBudget budget={value} />);
    expect(screen.getByText("No source-status rows recorded.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("discloses a display limit without dropping sources from the aggregate", () => {
    const value = budget();
    value.sources = Array.from({ length: 21 }, (_, index) => ({
      ...value.sources[0], scope: { subscription_connection: [`conn-${index}`] },
    }));
    value.source_count = value.known_clock_count = 21;
    render(<FabricFreshnessBudget budget={value} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(20);
    expect(screen.getByText(/Showing 20 of 21 source budgets/)).toHaveTextContent("aggregate evaluates all");
  });

  it.each([
    { threshold_seconds: -1 }, { threshold_seconds: Number.NaN }, { threshold_seconds: 1200 },
    { source_count: 2 }, { known_clock_count: 0 }, { state: "stale" },
    { remaining_seconds: 3000 }, { worst_known_age_seconds: 0 }, { evaluated_at: "invalid" },
  ])("surfaces inconsistent budget instead of implying success: %j", override => {
    render(<FabricFreshnessBudget budget={{ ...budget(), ...override } as Budget} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Freshness budget is inconsistent");
    expect(screen.queryByText(/Freshness budget: .*remaining/)).not.toBeInTheDocument();
  });

  it("makes an older server's absent budget explicit", () => {
    render(<FabricFreshnessBudget />);
    expect(screen.getByText("Freshness budget unavailable from this response.")).toBeInTheDocument();
  });
});
