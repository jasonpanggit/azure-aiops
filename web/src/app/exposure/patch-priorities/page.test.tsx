import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ExposureRefreshState } from "@/lib/types";

const navigation = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
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
  useRouter: () => ({ replace: navigation.replace, push: navigation.push }),
  useSearchParams: () => navigation.params,
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: { subscription: ["sub-1"] } }),
}));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>(
    "@/lib/services",
  );
  return {
    ...actual,
    vulnerabilityApi: api,
    remediationApi: {
      exposureHandoffs: api.exposureHandoffs,
    },
  };
});

import PatchPrioritiesPage from "./page";

const SERVER_ID =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/server-1";

function exposureEnvelope(refresh?: ExposureRefreshState) {
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
      ...(refresh ? { refresh } : {}),
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
          finding_title:
            "2026-09 Cumulative Update for Windows Server 2022 (KB600001)",
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
    expect(
      await screen.findByText(
        "2026-09 Cumulative Update for Windows Server 2022 (KB600001)",
      ),
    ).toBeInTheDocument();
    expect(api.exposureItems).toHaveBeenCalledTimes(1);
    expect(api.exposureHandoffs).not.toHaveBeenCalled();
    expect(api.riskExceptions).not.toHaveBeenCalled();
    expect(api.exposureItems).toHaveBeenCalledWith(
      expect.objectContaining({
        scope: { subscription: ["sub-1"] },
        filters: expect.objectContaining({
          search: "kernel",
          severity: "critical",
          target_kind: "server",
          source_family: "aum",
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
    expect(
      screen.getByRole("link", {
        name: "Open governed remediation for KB600001",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Risk exceptions" }),
    ).not.toBeInTheDocument();
    expect(
      api.exposureItems.mock.calls.every(
        ([request]) =>
          request.filters.target_kind === "server" &&
          request.filters.source_family === "aum",
      ),
    ).toBe(true);
  });

  it("loads container mode only with the Defender source", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&target_kind=container_image",
    );
    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    expect(api.exposureItems).toHaveBeenCalledTimes(1);
    expect(api.exposureItems).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: expect.objectContaining({
          target_kind: "container_image",
          source_family: "defender_image",
        }),
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
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

  it("switches to truthful server-backed VM and container image views", async () => {
    const user = userEvent.setup();
    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    await user.click(screen.getByRole("button", { name: "By VM" }));
    const vmUrl = new URL(
      String(navigation.replace.mock.lastCall?.[0]),
      "https://example.test",
    );
    expect(vmUrl.pathname).toBe("/exposure/patch-priorities");
    expect(vmUrl.searchParams.get("view")).toBe("vm");
    expect(vmUrl.searchParams.get("target_kind")).toBe("server");
    expect(vmUrl.searchParams.get("sort_by")).toBe("target_id");
    expect(vmUrl.searchParams.get("sort_direction")).toBe("asc");
    expect(vmUrl.searchParams.has("cursor")).toBe(false);

    await user.click(
      screen.getByRole("button", { name: "By container image" }),
    );
    const containerUrl = new URL(
      String(navigation.replace.mock.lastCall?.[0]),
      "https://example.test",
    );
    expect(containerUrl.searchParams.get("view")).toBe("container");
    expect(containerUrl.searchParams.get("target_kind")).toBe(
      "container_image",
    );
    expect(containerUrl.searchParams.get("sort_by")).toBe("target_id");
  });

  it("loads a direct VM view with VM-first presentation and canonical query semantics", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&view=vm&page_size=25",
    );
    render(<PatchPrioritiesPage />);

    expect(
      await screen.findByRole("heading", { name: "Patch priorities by VM" }),
    ).toBeInTheDocument();
    expect(api.exposureItems).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: expect.objectContaining({ target_kind: "server" }),
        sort: { field: "target_id", direction: "asc" },
        pageSize: 25,
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(
      screen.getByRole("region", { name: "VM patch priorities table" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "VM-organized patch priorities" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "VM" })).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Missing patch" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Filter by Target kind" }))
      .not.toBeInTheDocument();
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

    const detail = screen.getByRole("link", { name: "KB600001" });
    const detailUrl = new URL(detail.getAttribute("href")!, "https://example.test");
    expect(detailUrl.pathname).toBe("/exposure/kbs/KB600001");
    expect(detailUrl.searchParams.get("origin")).toBe(
      "/exposure/patch-priorities",
    );
    expect(detailUrl.searchParams.get("row")).toBe(
      "exposure-server-1-kb600001",
    );
    expect(detailUrl.searchParams.get("generation")).toBe("generation-17");
    expect(detailUrl.searchParams.has("cursor")).toBe(false);
  });

  it("keeps current rows while a canonical server filter request is pending", async () => {
    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    fireEvent.change(
      screen.getByRole("searchbox", {
        name: "Search patches and vulnerabilities",
      }),
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

  it("shows LKG rows and polls while a scoped background refresh runs", async () => {
    vi.useFakeTimers();
    try {
      api.exposureItems.mockResolvedValue(
        exposureEnvelope({
          state: "refreshing",
          refreshing: true,
          last_success_at: "2026-09-06T08:00:00Z",
        }),
      );

      render(<PatchPrioritiesPage />);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(screen.getByText("KB600001")).toBeInTheDocument();
      expect(
        screen.getByText(/Refreshing patch priorities in the background/),
      ).toHaveTextContent("2026-09-06T08:00:00Z");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(3_000);
      });
      expect(api.exposureItems).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows a failed-refresh warning while preserving LKG rows", async () => {
    api.exposureItems.mockResolvedValue(
      exposureEnvelope({
        state: "failed",
        refreshing: false,
        last_success_at: "2026-09-06T08:00:00Z",
        last_failure_at: "2026-09-14T05:00:00Z",
        failure_code: "refresh_backoff",
      }),
    );

    render(<PatchPrioritiesPage />);

    expect(await screen.findByText("KB600001")).toBeInTheDocument();
    expect(
      screen.getByText(/The background patch refresh failed/),
    ).toHaveTextContent("2026-09-06T08:00:00Z");
  });

  it("shows the persisted refresh timestamp after completion", async () => {
    api.exposureItems.mockResolvedValue(
      exposureEnvelope({
        state: "succeeded",
        refreshing: false,
        last_success_at: "2026-09-14T05:00:00Z",
      }),
    );

    render(<PatchPrioritiesPage />);

    expect(
      await screen.findByText(
        "Patch priorities refreshed 2026-09-14T05:00:00Z.",
      ),
    ).toBeInTheDocument();
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
      "/exposure/patch-priorities?subscription=sub-1&target_kind=server&source_family=aum&active=true",
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

    screen.getByRole("button", { name: "By patch" }).focus();
    expect(screen.getByRole("button", { name: "By patch" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "By VM" })).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: "By container image" }),
    ).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("searchbox", {
        name: "Search patches and vulnerabilities",
      }),
    ).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("checkbox", {
        name: "Include already-installed / resolved findings",
      }),
    ).toHaveFocus();
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

  it("fails closed for container findings without SQL-backed governed handoff evidence", async () => {
    navigation.params.set("target_kind", "container_image");
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

    render(<PatchPrioritiesPage />);

    expect(await screen.findByText("CVE-2026-0002")).toBeInTheDocument();
    expect(api.exposureHandoffs).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("link", {
        name: "Open governed container review for CVE-2026-0002",
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("No safe container action")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /execute|rebuild|deploy/i }),
    ).not.toBeInTheDocument();
  });

  it("canonicalizes contradictory target and source URL filters", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&target_kind=server&source_family=defender_image",
    );

    render(<PatchPrioritiesPage />);
    await screen.findByText("KB600001");

    expect(api.exposureItems).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: expect.objectContaining({
          target_kind: "server",
          source_family: "aum",
        }),
      }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
