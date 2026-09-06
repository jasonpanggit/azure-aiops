import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { exposureItems, targets, runs } = vi.hoisted(() => ({
  exposureItems: vi.fn(),
  targets: vi.fn(),
  runs: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  vulnerabilityApi: { exposureItems },
  patchingApi: { targets, runs },
}));

import { PatchInventory } from "./PatchInventory";

const envelope = <T,>(data: T, warnings: string[] = []) => ({
  data,
  evidence: [],
  scope: {},
  warnings,
  knowledge_version: "graph-1",
});

const VM_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1";
function commonEnvelope(
  items: Record<string, unknown>[],
  options: { state?: string; nextCursor?: string | null } = {},
) {
  const state = options.state ?? "partial";
  const contract = {
    version: "1.0.0",
    query: {
      scope: { subscription: ["sub-1"] },
      generation: "generation-17",
      filters: [],
      sort: { field: "priority_score", direction: "desc" },
      target_kind: "all",
    },
    counts: {
      unit: "findings",
      returned: items.length,
      represented: items.length,
      total: items.length + 1,
      excluded: 1,
    },
    units: {
      priority_score: "score",
      sla_age: "seconds",
      sla_due_at: "timestamp",
      rank: "ordinal",
    },
    completeness: {
      state,
      represented_connections: 1,
      expected_connections: 2,
      represented: items.length,
      total: items.length + 1,
      excluded: 1,
      excluded_reasons: ["AUM west retained from last-known-good"],
    },
    freshness: {
      state: "stale",
      as_of: "2026-09-06T08:00:00Z",
      source_family: "aum",
      threshold_seconds: 3600,
    },
    evidence_refs: [{ source_family: "aum", source_id: "aum-evidence-1" }],
    deep_link_action: {
      action_id: "open_exposure_detail",
      kind: "deep_link",
      path_field: "detail_path",
      fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
    },
    safe_error: null,
  };
  return {
    data: {
      items,
      total_count: items.length + 1,
      next_cursor: options.nextCursor ?? null,
      generation: "generation-17",
      applied: contract.query,
      completeness: contract.completeness,
      freshness: contract.freshness,
      contract,
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-17",
    pagination: {
      limit: 50,
      total: items.length + 1,
      next_cursor: options.nextCursor ?? null,
    },
  };
}

function exposure(overrides: Record<string, unknown> = {}) {
  return {
    exposure_id: "exposure-server-1-kb600001",
    target_id: VM_ID,
    target_kind: "server",
    weakness_id: "KB600001",
    weakness_kind: "kb",
    subscription_id: "sub-1",
    connection_ids: ["connection-aum"],
    source_families: ["aum"],
    source_family: "aum",
    read_model_generation_id: "generation-17",
    completeness: "complete",
    severity: "Critical",
    priority_score: 91,
    recommendation: "Install KB600001",
    current_state: "missing",
    sla_state: "overdue",
    sla_age_seconds: 172800,
    sla_target_seconds: 86400,
    sla_due_at: "2026-09-05T08:00:00Z",
    sla_overdue: true,
    detail_path: "/exposure/kbs/KB600001",
    governed_action_id: "controlled-patch-recovery",
    execution_eligible: true,
    evidence_refs: [{ source_id: "aum-evidence-1" }],
    package_name: "linux-kernel",
    package_version: "6.8.0",
    ...overrides,
  };
}

describe("PatchInventory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runs.mockResolvedValue(envelope([]));
    exposureItems.mockResolvedValue(commonEnvelope([exposure()]));
  });

  it("renders patch inventory from the common server envelope and never loads the legacy target aggregate", async () => {
    render(<PatchInventory scope={{}} />);

    expect(await screen.findByText("KB600001")).toBeInTheDocument();
    expect(exposureItems).toHaveBeenCalled();
    expect(targets).not.toHaveBeenCalled();
    expect(screen.getByText("Server")).toBeInTheDocument();
    expect(screen.getByText("linux-kernel 6.8.0")).toBeInTheDocument();
    expect(screen.getByText("SLA age 2 days")).toBeInTheDocument();
    expect(screen.getByText("Due Sep 5, 2026")).toBeInTheDocument();
    expect(screen.getByText("Rank 1")).toBeInTheDocument();
    expect(screen.getByText(/AUM west retained from last-known-good/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open governed remediation/ })).toHaveAttribute(
      "href",
      expect.stringContaining(`resource_key=${encodeURIComponent(VM_ID)}`),
    );
  });

  it("keeps indeterminate SLA unknown instead of displaying a fabricated zero age", async () => {
    exposureItems.mockResolvedValue(
      commonEnvelope([
        exposure({
          sla_state: "indeterminate",
          sla_age_seconds: null,
          sla_target_seconds: null,
          sla_due_at: null,
          sla_overdue: null,
        }),
      ]),
    );
    render(<PatchInventory scope={{}} />);

    expect(await screen.findByText("SLA age unknown")).toBeInTheDocument();
    expect(screen.queryByText("SLA age 0 days")).not.toBeInTheDocument();
    expect(screen.getByText("Due date unknown")).toBeInTheDocument();
  });

  it("renders container findings as review-only evidence instead of executable patches", async () => {
    exposureItems.mockResolvedValue(
      commonEnvelope([
        exposure({
          exposure_id: "exposure-container-1",
          target_id: `sha256:${"a".repeat(64)}`,
          target_kind: "container_image",
          weakness_id: "CVE-2026-0002",
          weakness_kind: "cve",
          source_families: ["defender"],
          source_family: "defender",
          package_name: "openssl",
          package_version: "3.0.1",
          governed_action_id: "",
          execution_eligible: false,
          review_handoff: {
            outcome: "review_handoff",
            href: "/remediation?handoff=exposure-container-1",
          },
        }),
      ]),
    );

    render(<PatchInventory scope={{}} />);

    expect(await screen.findByText("Container image")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open governed container review" }),
    ).toHaveAttribute("href", "/remediation?handoff=exposure-container-1");
    expect(
      screen.queryByRole("link", { name: /execute|install|upgrade/i }),
    ).not.toBeInTheDocument();
  });

  it("isolates historical run failure and keeps current Exposure findings usable", async () => {
    runs.mockRejectedValue(new Error("Historical runs unavailable"));
    exposureItems.mockResolvedValue(
      commonEnvelope([exposure()], { state: "complete" }),
    );

    render(<PatchInventory scope={{}} />);
    expect(await screen.findByText("KB600001")).toBeInTheDocument();
    expect(
      screen.getByText("Historical patch runs is unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry Historical patch runs" }),
    ).toBeEnabled();
  });
});
