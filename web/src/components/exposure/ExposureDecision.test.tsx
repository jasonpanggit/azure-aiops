import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExposureFacets } from "@/lib/types";
import { DEFAULT_EXPOSURE_SORT, type ExposureQueryState } from "@/lib/exposure-query-state";
import { ExposureDecision } from "./ExposureDecision";

const query: ExposureQueryState = {
  scope: { subscription: ["sub-a"], subscription_connection: ["conn-a"] }, filters: {}, sort: DEFAULT_EXPOSURE_SORT,
  pageSize: 25, cursor: null, cursorHistory: [], page: 1, target: "", drawer: "", generation: "gen-one",
};
describe("Exposure review ordering", () => {
  it("keeps unavailable classifications unknown rather than all-clear", () => {
    render(<ExposureDecision data={null} sourceStatus="unavailable" query={query} />);
    expect(screen.getByText(/Unknown critical findings/)).toBeVisible();
    expect(screen.getByText(/Unknown findings have the exact overdue/)).toBeVisible();
    expect(screen.getByText(/SLA classification coverage is unavailable/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Inspect recovery review" })).toHaveAttribute("href", "#exposure-recovery");
  });
  it("pins exact scope and generation on actionable severity/SLA links", () => {
    render(<ExposureDecision data={null} sourceStatus="loading" query={query} />);
    for (const [label, field, value] of [["Review critical findings", "severity", "critical"], ["Review overdue findings", "sla_state", "overdue"], ["Review high findings", "severity", "high"]]) {
      const link = screen.getByRole("link", { name: label });
      const params = new URL(link.getAttribute("href")!, "http://localhost").searchParams;
      expect(params.get("subscription")).toBe("sub-a");
      expect(params.get("subscription_connection")).toBe("conn-a");
      expect(params.get("generation")).toBe("gen-one");
      expect(params.get(field)).toBe(value);
    }
  });
  it("explains incomplete SLA denominator without counting similar labels as overdue", () => {
    const completeness = { state: "partial" as const, represented_connections: 1, expected_connections: 2 };
    const freshness = { state: "reported" as const, as_of: "2026-10-17T00:00:00Z" };
    const applied = { scope: query.scope, filters: [], sort: DEFAULT_EXPOSURE_SORT };
    const data: ExposureFacets = {
      generation: "gen-one", total_count: 10,
      items: [], applied, completeness, freshness,
      facets: { severity: [{ value: "CRITICAL", count: 2 }], sla_state: [{ value: "overdue", count: 2 }, { value: "within_sla", count: 3 }, { value: "not_overdue", count: 5 }] },
      contract: {
        version: "1.0.0", query: { ...applied, generation: "gen-one", target_kind: "all" },
        counts: { unit: "findings", returned: 0, represented: 10, total: 10, excluded: 0 },
        units: { finding_count: "count" }, completeness, freshness, evidence_refs: [],
        deep_link_action: { action_id: "open_exposure_detail", kind: "deep_link", path_field: "detail_path", fallback_path_template: "/exposure/{target_kind}/{exposure_id}" },
        safe_error: null,
      },
    };
    render(<ExposureDecision data={data} sourceStatus="partial" query={query} />);
    expect(screen.getByText(/2 critical findings/)).toBeVisible();
    expect(screen.getByText(/2 findings have the exact overdue/)).toBeVisible();
    expect(screen.getByText(/5 findings lack an exact/)).toBeVisible();
    expect(screen.getByText(/Counts can overlap/)).toBeVisible();
  });
});
