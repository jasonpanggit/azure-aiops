import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/types";

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  params: new URLSearchParams(
    "subscription=sub-1&q=kernel&severity=critical&page_size=25&sort_by=severity&sort_direction=asc&target=server-1&drawer=evidence&generation=generation-17",
  ),
}));

const api = vi.hoisted(() => ({
  exposureItems: vi.fn(),
  exposureHandoffs: vi.fn(),
  patchPriorities: vi.fn(),
  slaCompliance: vi.fn(),
  exposures: vi.fn(),
  riskExceptions: vi.fn(),
  revokeRiskException: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/exposure/patch-priorities",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.params,
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: { subscription: ["sub-1"] } }),
}));

vi.mock("@/lib/services", () => ({
  vulnerabilityApi: api,
  remediationApi: {
    exposureHandoffs: api.exposureHandoffs,
  },
}));

import PatchPrioritiesPage from "./page";

const SERVER_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/server-1";

function exposureEnvelope() {
  const contract = {
    version: "1.0.0",
    query: {
      scope: { subscription: ["sub-1"] },
      generation: "generation-17",
      filters: [
        { field: "search", operator: "contains", value: "kernel" },
        { field: "severity", operator: "eq", value: "critical" },
      ],
      sort: { field: "severity", direction: "asc" },
      target_kind: "all",
    },
    counts: {
      unit: "findings",
      returned: 2,
      represented: 5,
      total: 7,
      excluded: 2,
    },
    units: {
      priority_score: "score",
      sla_age: "seconds",
      sla_due_at: "timestamp",
      rank: "ordinal",
    },
    completeness: {
      state: "partial",
      represented_connections: 1,
      expected_connections: 2,
      represented: 5,
      total: 7,
      excluded: 2,
      excluded_reasons: ["Defender West connection unavailable"],
    },
    freshness: {
      state: "stale",
      as_of: "2026-09-06T08:00:00Z",
      source_family: "aum",
      threshold_seconds: 3600,
    },
    evidence_refs: [
      {
        source_family: "aum",
        source_id: "aum-server-1-kb600001",
        observed_at: "2026-09-06T08:00:00Z",
      },
    ],
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
      total_count: 7,
      items: [
        {
          exposure_id: "exposure-server-1-kb600001",
          target_id: SERVER_ID,
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
          evidence_refs: [{ source_id: "aum-server-1-kb600001" }],
        },
        {
          exposure_id: "exposure-image-1-cve-2026-0002",
          target_id: `sha256:${"a".repeat(64)}`,
          target_kind: "container_image",
          weakness_id: "CVE-2026-0002",
          weakness_kind: "cve",
          subscription_id: "sub-1",
          connection_ids: ["connection-defender"],
          source_families: ["defender"],
          source_family: "defender",
          read_model_generation_id: "generation-17",
          completeness: "partial",
          severity: "High",
          priority_score: 72,
          recommendation: "Review the deployed image",
          current_state: "active",
          sla_state: "indeterminate",
          sla_age_seconds: null,
          sla_target_seconds: null,
          sla_due_at: null,
          sla_overdue: null,
          detail_path: "/exposure/cves/CVE-2026-0002",
          governed_action_id: "",
          execution_eligible: false,
          evidence_refs: [{ source_id: "defender-image-1" }],
        },
      ],
      next_cursor: "opaque-next",
      generation: "generation-17",
      applied: {
        scope: { subscription: ["sub-1"] },
        filters: contract.query.filters,
        sort: contract.query.sort,
      },
      completeness: contract.completeness,
      freshness: contract.freshness,
      contract,
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-17",
    pagination: { limit: 25, total: 7, next_cursor: "opaque-next" },
  };
}

describe("Patch priorities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&severity=critical&page_size=25&sort_by=severity&sort_direction=asc&target=server-1&drawer=evidence&generation=generation-17",
    );
    api.exposureItems.mockResolvedValue(exposureEnvelope());
    api.exposureHandoffs.mockResolvedValue({
      data: { cases: [], read_only: true, execution_transition: false },
      evidence: [],
      warnings: [],
      scope: { subscription: ["sub-1"] },
      knowledge_version: "generation-17",
    });
    api.patchPriorities.mockResolvedValue({ data: [] });
    api.slaCompliance.mockResolvedValue({ data: null });
    api.exposures.mockResolvedValue({ data: [] });
    api.riskExceptions.mockResolvedValue({ data: [] });
  });

  it("loads the canonical server query and renders unit-correct uncertainty and coverage", async () => {
    render(<PatchPrioritiesPage />);

    expect(await screen.findByText("KB600001")).toBeInTheDocument();
    expect(api.exposureItems).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: { subscription: ["sub-1"] },
        filters: expect.objectContaining({
          search: "kernel",
          severity: "critical",
        }),
        sort: { field: "severity", direction: "asc" },
        pageSize: 25,
        target: "server-1",
        drawer: "evidence",
        generation: "generation-17",
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByText("SLA age 2 days")).toBeInTheDocument();
    expect(screen.getByText("SLA age unknown")).toBeInTheDocument();
    expect(screen.getByText("Priority score 91/100")).toBeInTheDocument();
    expect(screen.getByText(/5 represented findings/)).toBeInTheDocument();
    expect(screen.getByText(/2 excluded findings/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Showing 1 of 2 connections represented. Results and totals exclude unavailable connections.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Showing 5 of 2 connections represented. Results and totals exclude unavailable connections.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Defender West connection unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Showing 1–2 of 7 findings · 2 loaded"),
    ).toBeInTheDocument();
  });

  it("commits filter, sort, and opaque-cursor changes to the canonical URL", async () => {
    const user = userEvent.setup();
    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Filter by Target kind" }),
      "server",
    );
    expect(navigation.replace).toHaveBeenLastCalledWith(
      expect.stringMatching(
        /^\/exposure\/patch-priorities\?.*target_kind=server/,
      ),
      { scroll: false },
    );

    await user.click(
      screen.getByRole("button", { name: "Sort by operational priority" }),
    );
    expect(navigation.replace).toHaveBeenLastCalledWith(
      expect.not.stringContaining("sort_by=severity"),
      { scroll: false },
    );

    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(navigation.replace).toHaveBeenLastCalledWith(
      expect.stringContaining("cursor=opaque-next"),
      { scroll: false },
    );
  });

  it("preserves canonical Exposure state in the governed remediation return context", async () => {
    render(<PatchPrioritiesPage />);

    const handoff = await screen.findByRole("link", {
      name: /Open governed remediation for KB600001/,
    });
    const url = new URL(handoff.getAttribute("href")!, "https://example.test");

    expect(url.pathname).toBe("/remediation");
    expect(url.searchParams.get("resource_key")).toBe(SERVER_ID);
    expect(url.searchParams.get("generation")).toBe("generation-17");
    expect(url.searchParams.get("return_to")).toContain(
      "/exposure/patch-priorities?",
    );
    expect(url.searchParams.get("return_to")).toContain("q=kernel");
    expect(url.searchParams.get("return_focus")).toBe(
      "exposure-server-1-kb600001",
    );
  });

  it("keeps current rows while a canonical server filter request is pending", async () => {
    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    fireEvent.change(
      screen.getByRole("searchbox", { name: "Search exposure" }),
      { target: { value: "openssl" } },
    );

    await waitFor(() =>
      expect(navigation.replace).toHaveBeenCalledWith(
        expect.stringContaining("q=openssl"),
        { scroll: false },
      ),
    );
    expect(screen.getByText("KB600001")).toBeInTheDocument();
  });

  it("restores focus to the originating target after the canonical result loads", async () => {
    render(<PatchPrioritiesPage />);

    const row = await screen.findByRole("row", { name: /KB600001/ });
    await waitFor(() => expect(row).toHaveFocus());
  });

  it("shows an explicit generation restart and clears stale cursor state", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&cursor=opaque-expired&cursor_back=opaque-prior&page=3&generation=generation-old",
    );
    api.exposureItems.mockRejectedValueOnce(
      new ApiError(409, "conflict", "Exposure generation expired", {
        restart_required: true,
        reason_code: "exposure_generation_expired",
        generation: "generation-old",
      }),
    );
    const user = userEvent.setup();
    render(<PatchPrioritiesPage />);

    expect(
      await screen.findByText(
        /The retained Exposure generation expired\. Restart from the first page/,
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Restart results" }));
    expect(navigation.replace).toHaveBeenLastCalledWith(
      "/exposure/patch-priorities?subscription=sub-1",
      { scroll: false },
    );
  });

  it("provides a labeled responsive region and logical keyboard order", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&severity=critical&page_size=25&sort_by=severity&sort_direction=asc",
    );
    const user = userEvent.setup();
    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    const region = screen.getByRole("region", {
      name: "Patch priorities table",
    });
    expect(region).toHaveClass("exposure-responsive-table");
    expect(
      screen.getByRole("table", {
        name: "Scoped patch and vulnerability priorities",
      }),
    ).toBeInTheDocument();

    screen.getByRole("searchbox", { name: "Search exposure" }).focus();
    expect(screen.getByRole("searchbox", { name: "Search exposure" })).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("combobox", { name: "Filter by Target kind" }),
    ).toHaveFocus();
    await user.tab();
    expect(region).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: "Sort by operational priority" }),
    ).toHaveFocus();
  });

  it("uses the governed container case for review handoff and never exposes execution", async () => {
    const envelope = exposureEnvelope();
    envelope.data.items = [envelope.data.items[1]];
    envelope.data.total_count = 1;
    envelope.data.contract.counts = {
      ...envelope.data.contract.counts,
      returned: 1,
      represented: 1,
      total: 1,
      excluded: 0,
    };
    api.exposureItems.mockResolvedValue(envelope);
    api.exposureHandoffs.mockResolvedValue({
      data: {
        cases: [
          {
            handoff_id: "exposure-handoff:generation-17:exposure-image-1-cve-2026-0002",
            exposure_id: "exposure-image-1-cve-2026-0002",
            resource_key: `sha256:${"a".repeat(64)}`,
            weakness_key: "CVE-2026-0002",
            target_kind: "container_image",
            read_model_generation_id: "generation-17",
            outcome: "review_handoff",
            outcome_reason: "Exact digest evidence is ready for governed review.",
            direct_execution_supported: false,
            review_handoff: { target_kind: "container_image" },
          },
        ],
        read_only: true,
        execution_transition: false,
      },
      evidence: [],
      warnings: [],
      scope: { subscription: ["sub-1"] },
      knowledge_version: "generation-17",
    });

    render(<PatchPrioritiesPage />);

    const link = await screen.findByRole("link", {
      name: "Open governed container review for CVE-2026-0002",
    });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining(
        "handoff=exposure-handoff%3Ageneration-17%3Aexposure-image-1-cve-2026-0002",
      ),
    );
    expect(screen.getByText("Nothing executes from Exposure.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /execute|rebuild|deploy/i }),
    ).not.toBeInTheDocument();
  });

  it("records partial bulk revoke outcomes and retains failed and unattempted selections", async () => {
    api.riskExceptions.mockResolvedValue({
      data: [
        {
          exception_id: "risk-1",
          cve_id: "CVE-2026-0001",
          server_id: SERVER_ID,
          reason: "Compensating control",
          approved_by: "security@example.com",
          created_at: "2026-09-01T00:00:00Z",
          expires_at: "2026-10-01T00:00:00Z",
        },
        {
          exception_id: "risk-2",
          cve_id: "CVE-2026-0002",
          server_id: SERVER_ID,
          reason: "Maintenance window",
          approved_by: "security@example.com",
          created_at: "2026-09-01T00:00:00Z",
          expires_at: "2026-10-01T00:00:00Z",
        },
        {
          exception_id: "risk-3",
          cve_id: "CVE-2026-0003",
          server_id: SERVER_ID,
          reason: "Vendor review",
          approved_by: "security@example.com",
          created_at: "2026-09-01T00:00:00Z",
          expires_at: "2026-10-01T00:00:00Z",
        },
      ],
      evidence: [],
      warnings: [],
      scope: { subscription: ["sub-1"] },
      knowledge_version: "generation-17",
    });
    api.revokeRiskException
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error("Audit store unavailable"));
    const user = userEvent.setup();
    render(<PatchPrioritiesPage />);

    await screen.findByText("risk-1");
    await user.click(
      screen.getByRole("checkbox", {
        name: "Select all 3 risk exceptions on this page",
      }),
    );
    const invoker = screen.getByRole("button", {
      name: "Revoke 3 selected risk exceptions",
    });
    await user.click(invoker);
    expect(
      screen.getByRole("heading", { name: "Revoke 3 risk exceptions" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Revoke exceptions" }));

    expect(
      await screen.findByText(
        "1 revoked, 1 failed, 1 not attempted. Failed and unattempted items remain selected.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Audit ID:/)).toHaveTextContent("risk-1");
    expect(api.revokeRiskException).toHaveBeenCalledTimes(2);

    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(invoker).toHaveFocus());
    expect(
      screen.getByRole("checkbox", { name: /Select risk exception risk-2/ }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /Select risk exception risk-3/ }),
    ).toBeChecked();
  });
});
