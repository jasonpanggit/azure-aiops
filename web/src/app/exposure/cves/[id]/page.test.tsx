import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type Envelope,
  type ExposureCursorPagination,
  type ExposureExternalCatalog,
  type ExposureExternalCatalogItem,
} from "@/lib/types";

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
  exposureExternalCatalog: vi.fn(),
  acceptRisk: vi.fn(),
  cveEvidence: vi.fn(),
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

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>(
    "@/lib/services",
  );
  return {
    ...actual,
    vulnerabilityApi: api,
    copilotEvidenceRows: () => [],
  };
});

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: ({
    open,
    contextLabel,
  }: {
    open: boolean;
    contextLabel: string;
  }) =>
    open ? (
      <div role="dialog" aria-label={`Copilot for ${contextLabel}`} />
    ) : null,
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

function externalCatalogEnvelope(
  epssStatus = "succeeded",
  kevPresent = true,
): Envelope<
  ExposureExternalCatalog<ExposureExternalCatalogItem>,
  ExposureCursorPagination
> {
  const detail = cveEnvelope().data.cve;
  return {
    data: {
      contract_version: "1.0.0",
      catalog_scope: "external_public_metadata",
      environment_membership_included: false,
      generation: "generation-25",
      item: {
        cve_id: detail.cve_id,
        sources: {
          nvd: {
            source: "nvd",
            identifier: detail.cve_id,
            status: "succeeded",
            stale: false,
            has_last_known_good: true,
            safe_error_code: "",
            attempted_at: "2026-09-06T08:00:00Z",
            succeeded_at: "2026-09-06T08:00:00Z",
            source_at: "2026-09-06T07:50:00Z",
            enriched_at: "2026-09-06T08:00:00Z",
            payload: detail,
          },
          epss: {
            source: "epss",
            identifier: detail.cve_id,
            status: epssStatus,
            stale: false,
            has_last_known_good: epssStatus === "succeeded",
            safe_error_code: epssStatus === "succeeded" ? "" : "provider_unavailable",
            attempted_at: "2026-09-06T08:00:00Z",
            succeeded_at: "2026-09-06T08:00:00Z",
            source_at: "2026-09-06T07:55:00Z",
            enriched_at: "2026-09-06T08:00:00Z",
            payload: epssStatus === "succeeded"
              ? {
                  epss_score: detail.epss_score,
                  epss_percentile: detail.epss_percentile,
                }
              : null,
          },
          kev: {
            source: "kev",
            identifier: detail.cve_id,
            status: "succeeded",
            stale: false,
            has_last_known_good: true,
            safe_error_code: "",
            attempted_at: "2026-09-06T08:00:00Z",
            succeeded_at: "2026-09-06T08:00:00Z",
            source_at: "2026-09-06T07:55:00Z",
            enriched_at: "2026-09-06T08:00:00Z",
            payload: kevPresent
              ? {
                  kev_date_added: detail.kev_date_added,
                  kev_due_date: detail.kev_due_date,
                  kev_ransomware_use: detail.kev_ransomware_use,
                }
              : {},
          },
          "msrc:KB600001": {
            source: "msrc",
            identifier: "KB600001",
            status: "succeeded",
            stale: false,
            has_last_known_good: true,
            safe_error_code: "",
            attempted_at: "2026-09-06T08:00:00Z",
            succeeded_at: "2026-09-06T08:00:00Z",
            source_at: "2026-09-06T07:45:00Z",
            enriched_at: "2026-09-06T08:00:00Z",
            payload: { kb_id: "KB600001", cve_ids: [detail.cve_id] },
          },
        },
      },
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
    authorizedScope.subscription = ["sub-1"];
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&severity=critical&sort_by=severity&sort_direction=asc&page_size=25&origin=%2Fexposure%2Fpatch-priorities&row=exposure-1&scroll=640&generation=generation-25",
    );
    api.exposureOverview.mockResolvedValue(overviewEnvelope());
    api.exposureItems.mockResolvedValue(findingsEnvelope());
    api.cve.mockResolvedValue(cveEnvelope());
    api.exposureExternalCatalog.mockResolvedValue(externalCatalogEnvelope());
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
    api.cveEvidence.mockResolvedValue({ data: { schema_version: 1, actor: "reader", scope: { subscription: ["sub-1"] },
      cve_id: "CVE-2026-0001", revision: 0, receipts: [] }, scope: { subscription: ["sub-1"] }, evidence: [], warnings: [] });
  });

  it("uses one SQL catalog read and skips server attack paths for container images", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&target_kind=container_image&source_family=defender_image&generation=generation-25",
    );
    const findings = findingsEnvelope();
    findings.data.items[0].target_kind = "container_image";
    api.exposureItems.mockResolvedValue(findings);

    renderPage();

    expect(await screen.findByText("9.8/10")).toBeInTheDocument();
    expect(api.exposureExternalCatalog).toHaveBeenCalledTimes(1);
    expect(api.exposureExternalCatalog).toHaveBeenCalledWith(
      "CVE-2026-0001",
      authorizedScope,
      expect.objectContaining({
        generation: "generation-25",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(api.cve).not.toHaveBeenCalled();
    expect(api.attackPath).not.toHaveBeenCalled();
    const attack = screen.getByRole("region", { name: "Attack path section" });
    expect(within(attack).getByText("Not applicable")).toBeInTheDocument();
    expect(
      within(attack).getByText(
        "Attack paths are not applicable to container image targets.",
      ),
    ).toBeInTheDocument();
    expect(within(attack).queryByText("Attack path is unavailable")).not.toBeInTheDocument();
    expect(screen.getByLabelText("EPSS value")).toHaveTextContent(/73.0\s*%/);
    expect(screen.getByLabelText("CISA KEV value")).toHaveTextContent("Listed");
    expect(screen.getAllByRole("link", { name: "KB600001" }).length).toBeGreaterThan(0);
  });

  it("renders a healthy-empty no-supported-path state for legacy attack-path 404s", async () => {
    api.attackPath.mockRejectedValueOnce(
      Object.assign(new Error("Not found"), { status: 404 }),
    );

    renderPage();

    const attack = await screen.findByRole("region", { name: "Attack path section" });
    expect(
      within(attack).getByText(
        "No supported paths reported by Attack path",
      ),
    ).toBeInTheDocument();
    expect(within(attack).queryByText("Attack path is unavailable")).not.toBeInTheDocument();
  });

  it("keeps genuine attack-path provider failures unavailable", async () => {
    api.attackPath.mockRejectedValueOnce(new Error("Provider unavailable"));

    renderPage();

    const attack = await screen.findByRole("region", { name: "Attack path section" });
    expect(within(attack).getByText("Attack path is unavailable")).toBeInTheDocument();
    expect(
      within(attack).queryByText("No supported paths reported by Attack path"),
    ).not.toBeInTheDocument();
  });

  it("opens Copilot when catalog metadata is unavailable", async () => {
    api.exposureExternalCatalog.mockRejectedValue(
      new Error("Catalog metadata unavailable"),
    );
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("NVD and CVSS is unavailable")).toBeInTheDocument();

    await user.click(
      await screen.findByRole("button", {
        name: "Ask Copilot about CVE-2026-0001",
      }),
    );

    expect(
      screen.getByRole("dialog", { name: "Copilot for CVE-2026-0001" }),
    ).toBeInTheDocument();
    expect(api.exposureExternalCatalog).toHaveBeenCalledTimes(1);
    expect(api.acceptRisk).not.toHaveBeenCalled();
  });

  it("keeps missing EPSS unknown and aggregates all KB source failures", async () => {
    const catalog = externalCatalogEnvelope();
    catalog.data.item.sources.epss.payload = {};
    const nvdPayload = catalog.data.item.sources.nvd.payload;
    if (nvdPayload) {
      nvdPayload.cvss = {
        version: "",
        base_score: 0,
        vector: "",
        severity: "Unknown",
      };
    }
    catalog.data.item.sources["msrc:KB600002"] = {
      ...catalog.data.item.sources["msrc:KB600001"],
      identifier: "KB600002",
      status: "failed",
      has_last_known_good: false,
      safe_error_code: "provider_unavailable",
      payload: { kb_id: "KB600002", cve_ids: ["CVE-2026-0001"] },
    };
    api.exposureExternalCatalog.mockResolvedValue(catalog);

    renderPage();

    expect(await screen.findByLabelText("EPSS value")).toHaveTextContent("—");
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
    const nvd = screen.getByRole("region", { name: "CVSS technical disclosure section" });
    const baseScore = within(nvd).getByText("Base score").closest("div");
    expect(baseScore).not.toBeNull();
    expect(within(baseScore!).getByText("—")).toBeInTheDocument();
    expect(within(nvd).queryByText("0.0/10")).not.toBeInTheDocument();
    expect(screen.getByText("MSRC KB mapping is unavailable")).toBeInTheDocument();
  });

  it("does not claim an empty KB mapping when durable MSRC status is missing", async () => {
    const catalog = externalCatalogEnvelope();
    const nvdPayload = catalog.data.item.sources.nvd.payload;
    if (nvdPayload) nvdPayload.associated_kbs = [];
    delete catalog.data.item.sources["msrc:KB600001"];
    api.exposureExternalCatalog.mockResolvedValue(catalog);

    renderPage();

    expect(await screen.findByText("MSRC KB mapping is unavailable")).toBeInTheDocument();
    expect(
      screen.queryByText("No KB mappings reported by MSRC KB mapping"),
    ).not.toBeInTheDocument();
  });

  it("presents an empty KB mapping only after a fresh successful MSRC result", async () => {
    const catalog = externalCatalogEnvelope();
    const nvdPayload = catalog.data.item.sources.nvd.payload;
    if (nvdPayload) nvdPayload.associated_kbs = [];
    catalog.data.item.sources["msrc:KB600001"] = {
      ...catalog.data.item.sources["msrc:KB600001"],
      identifier: "",
      payload: {},
    };
    api.exposureExternalCatalog.mockResolvedValue(catalog);

    renderPage();

    expect(
      await screen.findByText("No KB mappings reported by MSRC KB mapping"),
    ).toBeInTheDocument();
    expect(screen.queryByText("MSRC KB mapping is unavailable")).not.toBeInTheDocument();
  });

  it("renders all six sections with conservative completeness and unknown-safe values", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Executive risk summary" })).toBeInTheDocument();
    for (const heading of [
      "Affected assets and workload coverage",
      "Risk-specific remediation guidance",
      "Attack path",
      "Findings",
      "Related KBs",
      "CVSS technical disclosure",
      "Source freshness",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText(/1 of 2 connections represented/)).toBeInTheDocument();
    expect(screen.getAllByText(/1 of 2 represented/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/2 excluded/).length).toBeGreaterThanOrEqual(2);
    // "excluded"/"total" must come from each section's own contract, not the
    // shared CVE-wide overview — sections without their own count (e.g.
    // Attack path) should not display it at all.
    const attackSection = screen.getByRole("region", { name: "Attack path section" });
    expect(attackSection.querySelector(".source-section-coverage")?.textContent ?? "").not.toMatch(
      /excluded|4 total/,
    );
    expect(screen.getByLabelText("CVSS value")).toHaveTextContent(/9.8\s*\/10/);
    expect(screen.getByLabelText("EPSS value")).toHaveTextContent(/73.0\s*%/);
    expect(screen.getByText("1 mapped service")).toBeInTheDocument();
  });

  it("keeps the decision hierarchy in accessible reading order", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Executive risk summary" });
    const headings = screen.getAllByRole("heading").map((heading) => heading.textContent);
    const expectedOrder = [
      "Executive risk summary",
      "Affected assets and workload coverage",
      "Risk-specific remediation guidance",
      "Attack path",
      "Findings",
      "Related KBs",
      "CVSS technical disclosure",
      "Source freshness",
    ];
    const positions = expectedOrder.map((heading) => headings.indexOf(heading));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((left, right) => left - right));
  });

  it("uses the CVSS radar as the executive summary visual without duplicating it", async () => {
    renderPage();

    const summary = await screen.findByRole("region", {
      name: "Executive risk summary",
    });
    expect(
      within(summary).getByRole("img", { name: /CVSS vector radar chart/i }),
    ).toBeInTheDocument();
    const summaryRow = summary.querySelector(".exposure-risk-summary-body");
    expect(summaryRow).not.toBeNull();
    expect(summaryRow?.nextElementSibling).toHaveClass("exposure-key-facts");
    expect(
      within(
        screen.getByRole("region", { name: "CVSS technical disclosure section" }),
      ).queryByRole("img"),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: /CVSS vector radar chart/i })).toHaveLength(1);
  });

  it("keeps scoped core and healthy siblings usable when EPSS is unavailable", async () => {
    api.exposureExternalCatalog.mockResolvedValue(externalCatalogEnvelope("failed"));
    renderPage();

    expect((await screen.findAllByText("server-1")).length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "EPSS source status" })).toHaveTextContent("Unavailable");
    expect(screen.getByLabelText("CVSS value")).toHaveTextContent("9.8");
    expect(screen.getByLabelText("CISA KEV value")).toHaveTextContent("Listed");
    expect(screen.getAllByRole("link", { name: "KB600001" }).length).toBeGreaterThan(0);
  });

  it("renders provider-declared partial metadata as partial rather than stale", async () => {
    const catalog = externalCatalogEnvelope();
    catalog.data.item.sources.epss.status = "partial";
    catalog.data.item.sources.epss.has_last_known_good = true;
    api.exposureExternalCatalog.mockResolvedValue(catalog);

    renderPage();

    const epss = await screen.findByRole("region", { name: "EPSS source status" });
    expect(epss).toHaveTextContent("Partial");
    expect(epss).not.toHaveTextContent("Last known good");
  });

  it("shows local loading, healthy-empty, partial, and stale states without blanking siblings", async () => {
    const attackPending = deferred<ReturnType<typeof attackEnvelope>>();
    api.attackPath.mockImplementationOnce(() => attackPending.promise);
    api.exposureOverview.mockResolvedValueOnce(overviewEnvelope("partial"));
    api.exposureExternalCatalog.mockResolvedValue(externalCatalogEnvelope("succeeded", false));
    renderPage();

    expect(await screen.findByText("Loading Attack path")).toBeInTheDocument();
    expect(screen.getByText("Unavailable operational context")).toBeInTheDocument();
    expect(screen.getByLabelText("CISA KEV value")).toHaveTextContent("Not listed");
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
    expect(
      await within(region).findByText(/Showing last successful Attack path data/),
    ).toBeInTheDocument();
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
    api.exposureExternalCatalog.mockResolvedValue(externalCatalogEnvelope("failed"));
    const user = userEvent.setup();
    renderPage();

    const epss = await screen.findByRole("region", { name: "EPSS source status" });
    const retry = within(epss).getByRole("button", { name: "Retry EPSS" });
    retry.focus();
    const recovery = deferred<ReturnType<typeof externalCatalogEnvelope>>();
    api.exposureExternalCatalog.mockImplementationOnce(() => recovery.promise);
    await user.click(retry);
    await waitFor(() => {
      expect(document.activeElement).toHaveAccessibleName("Retry EPSS");
      expect(document.activeElement).toHaveAttribute("aria-busy", "true");
    });
    recovery.resolve(externalCatalogEnvelope());
    await waitFor(() =>
      expect(screen.getByLabelText("EPSS value")).toHaveTextContent(/73.0\s*%/),
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

  it("separates public fix associations from loaded asset applicability", async () => {
    renderPage();
    const matrix = await screen.findByRole("region", { name: "CVE fix evidence matrix" });
    await within(matrix).findByRole("table");
    expect(within(matrix).getByText("Unknown; no product identifiers recorded")).toBeVisible();
    expect(within(matrix).getByText(/1 loaded rows explicitly name this KB/)).toBeVisible();
    expect(within(matrix).getByText(/Applicability is unverified. Confirm product/)).toBeVisible();
    expect(screen.getByText(/None. Catalog associations do not establish applicability/)).toBeVisible();
    fireEvent.click(within(matrix).getByText("Inspect mapped targets for KB600001"));
    expect(within(matrix).getByText(/server: server-1; finding exposure-1/)).toBeVisible();
    const link = within(matrix).getByRole("link", { name: "KB600001" });
    const destination = new URL(link.getAttribute("href")!, "http://localhost");
    expect(destination.searchParams.get("generation")).toBe("generation-25");
    expect(destination.searchParams.get("subscription")).toBe("sub-1");
  });

  it("displays recorded product identifiers with stale source status, never invented versions", async () => {
    const catalog = externalCatalogEnvelope();
    const source = catalog.data.item.sources["msrc:KB600001"];
    source.payload = { ...source.payload, product_ids: ["product-a", "product-b"] };
    source.stale = true;
    api.exposureExternalCatalog.mockResolvedValue(catalog);
    api.exposureItems.mockResolvedValue({ ...findingsEnvelope(), data: { ...findingsEnvelope().data,
      items: [{ ...findingsEnvelope().data.items[0], missing_kb: undefined }] } });
    renderPage();
    const matrix = await screen.findByRole("region", { name: "CVE fix evidence matrix" });
    await within(matrix).findByRole("table");
    expect(within(matrix).getByText("product-a, product-b")).toBeVisible();
    expect(within(matrix).getByText(/MSRC KB600001: succeeded; stale/)).toBeVisible();
    expect(within(matrix).getByText(/1 loaded findings have no recorded per-row KB association/)).toBeVisible();
    expect(within(matrix).getByText(/verified fixed versions are not supplied/)).toBeVisible();
  });

  it.each(["generation", "scope", "cve"])("refuses a mixed %s fix matrix", async damage => {
    const catalog = externalCatalogEnvelope();
    if (damage === "generation") catalog.data.generation = "other-generation";
    else if (damage === "scope") catalog.scope = { subscription: ["other"] };
    else catalog.data.item.cve_id = "CVE-2026-9999";
    api.exposureExternalCatalog.mockResolvedValue(catalog);
    renderPage();
    const matrix = await screen.findByRole("region", { name: "CVE fix evidence matrix" });
    expect(await within(matrix).findByText(/Fix evidence is unavailable until/)).toBeVisible();
    expect(within(matrix).queryByRole("table")).not.toBeInTheDocument();
  });

  it("remounts local finding state when the authorized scope changes", async () => {
    const view = renderPage();
    await screen.findByRole("heading", { name: "Findings" });
    navigation.params = new URLSearchParams("generation=generation-25");
    authorizedScope.subscription = ["sub-2"];
    view.rerender(<FluentProvider theme={webLightTheme}><CveDetailPage params={{ id: "CVE-2026-0001" }} /></FluentProvider>);
    await waitFor(() => expect(api.exposureItems.mock.lastCall?.[0].scope).toEqual({ subscription: ["sub-2"] }));
    expect(api.exposureExternalCatalog.mock.lastCall?.[1]).toEqual({ subscription: ["sub-2"] });
    const matrix = await screen.findByRole("region", { name: "CVE fix evidence matrix" });
    expect(within(matrix).queryByRole("table")).not.toBeInTheDocument();
  });

  it("reports an audited success separately when post-record refresh fails", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Findings" });
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
