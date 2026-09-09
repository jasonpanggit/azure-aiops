import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams(
    "subscription=sub-1&q=kernel&severity=critical&page_size=25&origin=%2Fexposure%2Fdefender-posture&row=exposure-1&scroll=320&generation=generation-25",
  ),
  replace: vi.fn(),
}));
const authorizedScope = vi.hoisted(() => ({ subscription: ["sub-1"] }));
const api = vi.hoisted(() => ({
  detail: vi.fn(),
  exposureOverview: vi.fn(),
  exposureItems: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/exposure/kbs/KB600001",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.params,
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: authorizedScope }),
}));

vi.mock("@/lib/services", () => ({
  kbApi: { detail: api.detail },
  vulnerabilityApi: {
    exposureOverview: api.exposureOverview,
    exposureItems: api.exposureItems,
  },
  buildCopilotSnapshot: (input: Record<string, unknown>) => input,
}));

import KbDetailPage from "./page";

function commonContract(
  state: "complete" | "partial" | "stale" | "unavailable" = "complete",
) {
  return {
    version: "1.0.0",
    query: {
      scope: { subscription: ["sub-1"] },
      generation: "generation-25",
      filters: [{ field: "weakness_id", operator: "eq", value: "KB600001" }],
      sort: { field: "priority_score", direction: "desc" },
      target_kind: "all",
    },
    counts: { unit: "findings", returned: 1, represented: 2, total: 3, excluded: 1 },
    units: { finding_count: "count" },
    completeness: {
      state,
      represented_connections: 1,
      expected_connections: 2,
      represented: 2,
      total: 3,
      excluded: 1,
      excluded_reasons: ["AUM East connection unavailable"],
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
      fallback_path_template: "/exposure/kbs/{weakness_id}",
    },
    safe_error: null,
  };
}

function overviewEnvelope() {
  const contract = commonContract();
  return {
    data: {
      total_count: 3,
      generation: "generation-25",
      applied: contract.query,
      completeness: contract.completeness,
      freshness: contract.freshness,
      contract,
    },
    evidence: [{
      source_engine: "Exposure Gold",
      source_table: "gold_exposure_current",
      timestamp: "2026-09-06T08:00:00Z",
      confidence: "high",
      freshness: "fresh",
    }],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
    pagination: { limit: 1, total: 3, next_cursor: null },
  };
}

function kbEnvelope(msrcStatus = "succeeded", publishedAt = "2026-08-01") {
  return {
    data: {
      kb_id: "KB600001",
      title: "Contoso kernel security update",
      severity: "Critical",
      published_at: publishedAt,
      cve_ids: ["CVE-2026-0001"],
      cves: [{
        cve_id: "CVE-2026-0001",
        title: "Kernel remote execution",
        severity: "Critical",
        cvss: { base_score: 9.8, vector: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", severity: "Critical" },
      }],
      enrichment: {
        status: msrcStatus === "failed" ? "degraded" : "complete",
        complete: msrcStatus !== "failed",
        stale: false,
        expected_count: 4,
        available_count: msrcStatus === "failed" ? 3 : 4,
        sources: {
          "msrc:KB600001": {
            source: "msrc",
            identifier: "KB600001",
            status: msrcStatus,
            stale: false,
            has_last_known_good: false,
            safe_error_code: msrcStatus === "failed" ? "provider_unavailable" : "",
            source_at: "2026-09-06T07:40:00Z",
          },
        },
      },
      affected_servers: ["server-1"],
      affected_business_services: ["Payments"],
      findings: [],
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
  };
}

function findingsEnvelope() {
  const contract = commonContract();
  return {
    data: {
      total_count: 3,
      items: [{
        exposure_id: "exposure-1",
        target_id: "server-1",
        target_kind: "server",
        weakness_id: "KB600001",
        subscription_id: "sub-1",
        connection_ids: ["connection-a"],
        source_families: ["aum"],
        read_model_generation_id: "generation-25",
        completeness: "complete",
        cve_id: "CVE-2026-0001",
        severity: "Critical",
        business_service: "Payments",
      }],
      next_cursor: null,
      generation: "generation-25",
      applied: contract.query,
      completeness: contract.completeness,
      freshness: contract.freshness,
      contract,
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-25",
    pagination: { limit: 25, total: 3, next_cursor: null },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("KB detail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&severity=critical&page_size=25&origin=%2Fexposure%2Fdefender-posture&row=exposure-1&scroll=320&generation=generation-25",
    );
    api.detail.mockResolvedValue(kbEnvelope());
    api.exposureOverview.mockResolvedValue(overviewEnvelope());
    api.exposureItems.mockResolvedValue(findingsEnvelope());
  });

  it("renders metadata, MSRC associations, and findings as independent evidence sections", async () => {
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    for (const heading of ["KB metadata", "MSRC CVE associations", "Affected findings"]) {
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText(/1 of 2 connections represented/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(/1 excluded/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("AUM East connection unavailable").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("Published 2026-08-01")).toBeInTheDocument();
    expect(screen.getByText("Showing 1–1 of 3 findings · 1 loaded")).toBeInTheDocument();
  });

  it("keeps metadata and findings usable when MSRC associations are unavailable", async () => {
    api.detail.mockResolvedValue(kbEnvelope("failed"));
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("MSRC CVE associations is unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("Contoso kernel security update").length).toBeGreaterThan(0);
    expect(screen.getByText("server-1")).toBeInTheDocument();
  });

  it("shows partial and unknown-safe metadata without inventing zero", async () => {
    const partial = overviewEnvelope();
    partial.data.contract.completeness.state = "partial";
    partial.data.completeness.state = "partial";
    api.exposureOverview.mockResolvedValue(partial);
    api.detail.mockResolvedValue(kbEnvelope("succeeded", ""));
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("Partial operational context")).toBeInTheDocument();
    expect(screen.getByLabelText("Published value")).toHaveTextContent("—");
    expect(screen.getByText("server-1")).toBeInTheDocument();
  });

  it("keeps sibling metadata visible while findings load and proves healthy empty", async () => {
    const pendingFindings = deferred<ReturnType<typeof findingsEnvelope>>();
    api.exposureItems.mockImplementationOnce(() => pendingFindings.promise);
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("Loading Affected findings")).toBeInTheDocument();
    expect(screen.getAllByText("Contoso kernel security update").length).toBeGreaterThan(0);

    const empty = findingsEnvelope();
    empty.data.items = [];
    empty.data.total_count = 0;
    empty.data.contract.counts = {
      ...empty.data.contract.counts,
      returned: 0,
      represented: 0,
      total: 0,
      excluded: 0,
    };
    pendingFindings.resolve(empty);
    expect(
      await screen.findByText("No findings reported by Affected findings"),
    ).toBeInTheDocument();
  });

  it("preserves safe parent and CVE round-trip context", async () => {
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    const back = await screen.findByRole("link", { name: "Back to Defender posture" });
    const backUrl = new URL(back.getAttribute("href")!, "https://aiops.example");
    expect(backUrl.pathname).toBe("/exposure/defender-posture");
    expect(backUrl.searchParams.get("q")).toBe("kernel");
    expect(backUrl.searchParams.get("row")).toBe("exposure-1");
    expect(backUrl.searchParams.get("scroll")).toBe("320");

    const cve = screen.getAllByRole("link", { name: "CVE-2026-0001" })[0];
    const cveUrl = new URL(cve.getAttribute("href")!, "https://aiops.example");
    expect(cveUrl.pathname).toBe("/exposure/cves/CVE-2026-0001");
    expect(cveUrl.searchParams.get("origin")).toBe("/exposure/defender-posture");
    expect(cveUrl.searchParams.get("generation")).toBe("generation-25");
  });

  it("defaults direct and unsafe links to Patch priorities without an open redirect", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&origin=https%3A%2F%2Fevil.example%2Fsteal",
    );
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    const back = await screen.findByRole("link", { name: "Back to Patch priorities" });
    const url = new URL(back.getAttribute("href")!, "https://aiops.example");
    expect(url.pathname).toBe("/exposure/patch-priorities");
    expect(url.hostname).toBe("aiops.example");
  });

  it("retains retry focus and current siblings while MSRC reloads", async () => {
    api.detail.mockResolvedValue(kbEnvelope("failed"));
    const user = userEvent.setup();
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    const region = await screen.findByRole("region", {
      name: "MSRC CVE associations section",
    });
    const retry = await within(region).findByRole("button", {
      name: "Retry MSRC CVE associations",
    });
    retry.focus();
    const recovery = deferred<ReturnType<typeof kbEnvelope>>();
    api.detail.mockImplementationOnce(() => recovery.promise);
    await user.click(retry);
    await waitFor(() => {
      expect(retry).toHaveFocus();
      expect(retry).toHaveAttribute("aria-busy", "true");
    });
    expect(screen.getByText("server-1")).toBeInTheDocument();
    recovery.resolve(kbEnvelope());
    expect((await screen.findAllByRole("link", { name: "CVE-2026-0001" })).length).toBeGreaterThan(0);
  });
});
