import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/types";

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams(
    "subscription=sub-1&q=kernel&severity=critical&sort_by=severity&sort_direction=asc&page_size=25&origin=%2Fexposure%2Fpatch-priorities&row=exposure-1&scroll=640&generation=generation-25",
  ),
  replace: vi.fn(),
}));

const authorizedScope = vi.hoisted(() => ({ subscription: ["sub-1"] }));

const api = vi.hoisted(() => ({
  cve: vi.fn(),
  attackPath: vi.fn(),
  exposureOverview: vi.fn(),
  exposureItems: vi.fn(),
  acceptRisk: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/exposure/cves/CVE-2026-0001",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.params,
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: authorizedScope }),
}));

vi.mock("@azure/msal-react", () => ({
  useMsal: () => ({
    accounts: [{ username: "operator@example.com", name: "Operations User" }],
  }),
}));

vi.mock("@/lib/services", () => ({
  vulnerabilityApi: api,
  buildCopilotSnapshot: (input: unknown) => input,
  copilotEvidenceRows: () => [],
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

vi.mock("@/components/ui/CopilotDrawerButton", () => ({
  CopilotDrawerButton: ({ onClick, label }: { onClick: () => void; label: string }) => (
    <button type="button" onClick={onClick}>{label}</button>
  ),
}));

import CveDetailPage from "./page";

function contract(
  state: "complete" | "partial" | "stale" | "unavailable" = "complete",
) {
  return {
    version: "1.0.0",
    query: {
      scope: { subscription: ["sub-1"] },
      generation: "generation-25",
      filters: [{ field: "weakness_id", operator: "eq", value: "CVE-2026-0001" }],
      sort: { field: "priority_score", direction: "desc" },
      target_kind: "all",
    },
    counts: {
      unit: "findings",
      returned: 2,
      represented: 2,
      total: 4,
      excluded: 2,
    },
    units: { cvss: "score", epss: "percent", finding_count: "count" },
    completeness: {
      state,
      represented_connections: 1,
      expected_connections: 2,
      represented: 2,
      total: 4,
      excluded: 2,
      excluded_reasons: [
        "Defender West connection unavailable",
        "server-3 excluded: authorization changed",
      ],
    },
    freshness: {
      state: state === "stale" ? "stale" : "current",
      as_of: "2026-09-06T08:00:00Z",
      source_family: "aum",
      threshold_seconds: 3600,
    },
    evidence_refs: [{ source_family: "aum", source_id: "finding-1" }],
    deep_link_action: {
      action_id: "open_exposure_detail",
      kind: "deep_link",
      path_field: "detail_path",
      fallback_path_template: "/exposure/cves/{weakness_id}",
    },
    safe_error: null,
  };
}

function overviewEnvelope(
  state: "complete" | "partial" | "stale" | "unavailable" = "complete",
) {
  const common = contract(state);
  return {
    data: {
      total_count: 4,
      generation: "generation-25",
      applied: common.query,
      completeness: common.completeness,
      freshness: common.freshness,
      contract: common,
    },
    evidence: [{
      source_engine: "Exposure Gold",
      source_table: "gold_exposure_current",
      timestamp: "2026-09-06T08:00:00Z",
      confidence: "high",
      freshness: state === "stale" ? "stale" : "fresh",
    }],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
    pagination: { limit: 1, total: 4, next_cursor: null },
  };
}

function cveEnvelope(epssStatus = "succeeded") {
  return {
    data: {
      cve: {
        cve_id: "CVE-2026-0001",
        title: "Kernel remote execution",
        description: "A remote execution vulnerability.",
        severity: "Critical",
        cvss: { version: "3.1", base_score: 9.8, vector: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", severity: "Critical" },
        associated_kbs: ["KB600001"],
        epss_score: 0.73,
        epss_percentile: 0.92,
        is_known_exploited: true,
        kev_date_added: "2026-08-01",
        kev_due_date: "2026-08-22",
        kev_ransomware_use: "Known",
        exploit_references: [],
      },
      enrichment: {
        status: epssStatus === "failed" ? "degraded" : "complete",
        complete: epssStatus !== "failed",
        stale: false,
        expected_count: 4,
        available_count: epssStatus === "failed" ? 3 : 4,
        sources: {
          nvd: { source: "nvd", identifier: "CVE-2026-0001", status: "succeeded", stale: false, has_last_known_good: true, source_at: "2026-09-06T07:50:00Z" },
          epss: { source: "epss", identifier: "CVE-2026-0001", status: epssStatus, stale: false, has_last_known_good: false, safe_error_code: epssStatus === "failed" ? "provider_unavailable" : "" },
          kev: { source: "kev", identifier: "CVE-2026-0001", status: "succeeded", stale: false, has_last_known_good: true, source_at: "2026-09-06T07:55:00Z" },
          "msrc:KB600001": { source: "msrc", identifier: "KB600001", status: "succeeded", stale: false, has_last_known_good: true, source_at: "2026-09-06T07:45:00Z" },
        },
      },
      exploitability_signals: [],
      affected_servers: ["server-1", "server-2"],
      affected_applications: ["Checkout"],
      affected_business_services: ["Payments"],
      findings: [],
      recommended_patch: "KB600001",
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
  };
}

function findingsEnvelope() {
  const common = contract();
  return {
    data: {
      total_count: 4,
      items: [{
        exposure_id: "exposure-1",
        target_id: "server-1",
        target_kind: "server",
        weakness_id: "CVE-2026-0001",
        subscription_id: "sub-1",
        connection_ids: ["connection-a"],
        source_families: ["aum"],
        read_model_generation_id: "generation-25",
        completeness: "complete",
        severity: "Critical",
        missing_kb: "KB600001",
        business_service: "Payments",
      }],
      next_cursor: null,
      generation: "generation-25",
      applied: common.query,
      completeness: common.completeness,
      freshness: common.freshness,
      contract: common,
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
    pagination: { limit: 25, total: 4, next_cursor: null },
  };
}

function attackEnvelope() {
  return {
    data: {
      cve_id: "CVE-2026-0001",
      nodes: [
        { id: "attacker:internet", kind: "origin", label: "Internet" },
        { id: "server:server-1", kind: "server", label: "server-1" },
      ],
      edges: [{ source: "attacker:internet", target: "server:server-1", label: "internet" }],
      reachable_server_count: 1,
      internet_exposed: true,
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
  };
}

function renderPage() {
  return render(
    <FluentProvider theme={webLightTheme}>
      <CveDetailPage params={{ id: "CVE-2026-0001" }} />
    </FluentProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("CVE detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&severity=critical&sort_by=severity&sort_direction=asc&page_size=25&origin=%2Fexposure%2Fpatch-priorities&row=exposure-1&scroll=640&generation=generation-25",
    );
    api.exposureOverview.mockResolvedValue(overviewEnvelope());
    api.exposureItems.mockResolvedValue(findingsEnvelope());
    api.cve.mockResolvedValue(cveEnvelope());
    api.attackPath.mockResolvedValue(attackEnvelope());
    api.acceptRisk.mockResolvedValue({
      data: {
        exception_id: "exception-25",
        cve_id: "CVE-2026-0001",
        server_id: "",
        reason: "Compensating control",
        approved_by: "operator@example.com",
        created_at: "2026-09-06T08:05:00Z",
        expires_at: "",
      },
    });
  });

  it("renders all six sections with conservative completeness and unknown-safe values", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Scoped findings" })).toBeInTheDocument();
    for (const heading of ["Attack path", "NVD and CVSS", "EPSS", "CISA KEV", "KB mapping"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText(/1 of 2 connections represented/).length).toBeGreaterThanOrEqual(6);
    expect(screen.getAllByText(/2 excluded/).length).toBeGreaterThanOrEqual(6);
    expect(screen.getAllByText("Defender West connection unavailable").length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText("9.8/10")).toBeInTheDocument();
    expect(screen.getByLabelText("Exploit probability value")).toHaveTextContent(/73\s*%/);
  });

  it("keeps scoped core and healthy siblings usable when EPSS is unavailable", async () => {
    api.cve.mockResolvedValue(cveEnvelope("failed"));
    renderPage();

    expect((await screen.findAllByText("server-1")).length).toBeGreaterThan(0);
    expect(screen.getByText("EPSS is unavailable")).toBeInTheDocument();
    expect(screen.getByText("9.8/10")).toBeInTheDocument();
    expect(screen.getByText("Due 2026-08-22")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "KB600001" }).length).toBeGreaterThan(0);
  });

  it("shows local loading, healthy-empty, partial, and stale states without blanking siblings", async () => {
    const attackPending = deferred<ReturnType<typeof attackEnvelope>>();
    api.attackPath.mockImplementationOnce(() => attackPending.promise);
    api.exposureOverview.mockResolvedValueOnce(overviewEnvelope("partial"));
    const cveWithoutKev = cveEnvelope();
    cveWithoutKev.data.cve.is_known_exploited = false;
    cveWithoutKev.data.cve.kev_due_date = "";
    api.cve.mockResolvedValue(cveWithoutKev);
    renderPage();

    expect(await screen.findByText("Loading Attack path")).toBeInTheDocument();
    expect(screen.getByText("Unavailable operational context")).toBeInTheDocument();
    expect(screen.getByText("No KEV entries reported by CISA KEV")).toBeInTheDocument();
    expect(screen.getAllByText("server-1").length).toBeGreaterThan(0);
    await act(async () => {
      attackPending.resolve(attackEnvelope());
    });
  });

  it("keeps attack-path last-known-good visible after a failed local retry", async () => {
    api.exposureOverview.mockResolvedValue(overviewEnvelope("stale"));
    const user = userEvent.setup();
    renderPage();

    const region = await screen.findByRole("region", { name: "Attack path section" });
    expect(within(region).getByText(/Showing last successful Attack path data/)).toBeInTheDocument();
    api.attackPath.mockRejectedValueOnce(new Error("Defender graph refresh unavailable"));
    await user.click(within(region).getByRole("button", { name: "Retry Attack path" }));
    expect(
      await within(region).findByText(/Defender graph refresh unavailable/),
    ).toBeInTheDocument();
    expect(within(region).getByText(/Showing last successful Attack path data/)).toBeInTheDocument();
  });

  it("preserves canonical collection context through CVE, KB, and Back links", async () => {
    renderPage();

    const back = await screen.findByRole("link", { name: "Back to Patch priorities" });
    const backUrl = new URL(back.getAttribute("href")!, "https://aiops.example");
    expect(backUrl.pathname).toBe("/exposure/patch-priorities");
    expect(backUrl.searchParams.get("q")).toBe("kernel");
    expect(backUrl.searchParams.get("generation")).toBe("generation-25");
    expect(backUrl.searchParams.get("row")).toBe("exposure-1");
    expect(backUrl.searchParams.get("scroll")).toBe("640");
    expect(backUrl.searchParams.has("cursor")).toBe(false);

    const kb = screen.getAllByRole("link", { name: "KB600001" })[0];
    const kbUrl = new URL(kb.getAttribute("href")!, "https://aiops.example");
    expect(kbUrl.pathname).toBe("/exposure/kbs/KB600001");
    expect(kbUrl.searchParams.get("origin")).toBe("/exposure/patch-priorities");
    expect(kbUrl.searchParams.get("q")).toBe("kernel");
    expect(kbUrl.searchParams.get("row")).toBe("exposure-1");
  });

  it("rejects unsafe origins and offers a generation restart without losing authorized filters", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&origin=https%3A%2F%2Fevil.example%2Fsteal&generation=generation-old",
    );
    api.exposureOverview.mockRejectedValueOnce(
      new ApiError(409, "conflict", "Exposure generation expired", {
        restart_required: true,
        reason_code: "exposure_generation_expired",
        generation: "generation-old",
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const back = await screen.findByRole("link", { name: "Back to Patch priorities" });
    expect(new URL(back.getAttribute("href")!, "https://aiops.example").pathname).toBe(
      "/exposure/patch-priorities",
    );
    await user.click(await screen.findByRole("button", { name: "Restart results" }));
    expect(navigation.replace).toHaveBeenCalledWith(
      expect.stringMatching(/^\/exposure\/cves\/CVE-2026-0001\?.*q=kernel/),
      { scroll: false },
    );
    expect(navigation.replace).toHaveBeenCalledWith(
      expect.not.stringContaining("generation=generation-old"),
      { scroll: false },
    );
    expect(navigation.replace).toHaveBeenCalledWith(
      expect.stringContaining("origin=%2Fexposure%2Fpatch-priorities"),
      { scroll: false },
    );
  });

  it("keeps local retry focus when a failed section recovers", async () => {
    api.cve.mockResolvedValue(cveEnvelope("failed"));
    const user = userEvent.setup();
    renderPage();

    const epss = await screen.findByRole("region", { name: "EPSS section" });
    const retry = within(epss).getByRole("button", { name: "Retry EPSS" });
    retry.focus();
    const recovery = deferred<ReturnType<typeof cveEnvelope>>();
    api.cve.mockImplementationOnce(() => recovery.promise);
    await user.click(retry);
    await waitFor(() => {
      expect(document.activeElement).toHaveAccessibleName("Retry EPSS");
      expect(document.activeElement).toHaveAttribute("aria-busy", "true");
    });
    recovery.resolve(cveEnvelope());
    await waitFor(() =>
      expect(screen.getByLabelText("Exploit probability value")).toHaveTextContent(/73\s*%/),
    );
  });

  it("opens the governed risk dialog with exact represented scope and session identity", async () => {
    const user = userEvent.setup();
    renderPage();

    const invoker = await screen.findByRole("button", {
      name: "Record risk exception",
    });
    await user.click(invoker);

    const dialog = screen.getByRole("dialog", { name: "Record risk exception" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("CVE-2026-0001")).toBeInTheDocument();
    expect(within(dialog).getByText(/1 loaded target.*2 excluded/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/Generation generation-25/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Session approver")).toHaveValue(
      "operator@example.com",
    );
    expect(within(dialog).getByLabelText("Session approver")).toHaveAttribute("readonly");
    expect(within(dialog).queryByLabelText("Approved by")).not.toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByLabelText("Reason")).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Keep reviewing" }));
    await waitFor(() => expect(invoker).toHaveFocus());
  });

  it("keeps entered risk context and focuses explicit API or audit failure", async () => {
    api.acceptRisk.mockRejectedValueOnce(
      new Error("Exposure audit is unavailable; risk exception was not created"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", {
      name: "Record risk exception",
    }));
    await user.type(
      screen.getByLabelText("Reason"),
      "Compensating network control is active",
    );
    fireEvent.change(screen.getByLabelText("Expiry (optional)"), {
      target: { value: "2026-10-01T09:30" },
    });
    await user.click(screen.getByRole("button", { name: "Record exception" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Risk exception was not recorded");
    expect(alert).toHaveTextContent("Exposure audit is unavailable");
    expect(alert).toHaveFocus();
    expect(screen.getByLabelText("Reason")).toHaveValue(
      "Compensating network control is active",
    );
    expect(screen.getByLabelText("Expiry (optional)")).toHaveValue(
      "2026-10-01T09:30",
    );
    expect(api.acceptRisk).toHaveBeenCalledWith({
      cve_id: "CVE-2026-0001",
      reason: "Compensating network control is active",
      expires_at: expect.stringMatching(/^2026-10-01T\d{2}:30:00\.000Z$/),
    });
  });

  it("reports an audited success separately when post-record refresh fails", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Scoped findings" });
    api.acceptRisk.mockResolvedValueOnce({
      data: {
        exception_id: "AUD-25",
        cve_id: "CVE-2026-0001",
        server_id: "",
        reason: "Temporary exception",
        approved_by: "operator@example.com",
        created_at: "2026-09-06T08:05:00Z",
        expires_at: "",
        can_revoke: false,
      },
    });
    api.exposureItems.mockRejectedValueOnce(new Error("Refresh unavailable"));

    await user.click(screen.getByRole("button", {
      name: "Record risk exception",
    }));
    await user.type(screen.getByLabelText("Reason"), "Temporary exception");
    await user.click(screen.getByRole("button", { name: "Record exception" }));

    const summary = await screen.findByRole("status", {
      name: "Risk exception result",
    });
    expect(summary).toHaveTextContent("Risk exception recorded");
    expect(summary).toHaveTextContent("Audit ID: AUD-25");
    expect(summary).toHaveTextContent(
      "Exception recorded; updated exposure counts could not be refreshed",
    );
    expect(summary).toHaveFocus();
    expect(
      screen.queryByRole("button", { name: "Revoke risk exception" }),
    ).not.toBeInTheDocument();
  });
});
