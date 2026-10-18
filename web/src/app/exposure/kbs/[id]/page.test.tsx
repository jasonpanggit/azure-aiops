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
  reviews: vi.fn(),
  createReview: vi.fn(),
  observations: vi.fn(),
  captureObservation: vi.fn(),
  exposureOverview: vi.fn(),
  exposureItems: vi.fn(),
}));
const copilot = vi.hoisted(() => ({
  inputs: [] as Array<Record<string, unknown>>,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/exposure/kbs/KB600001",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.params,
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: authorizedScope }),
}));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>(
    "@/lib/services",
  );
  return {
    ...actual,
    kbApi: { detail: api.detail, reviews: api.reviews, createReview: api.createReview,
      observations: api.observations, captureObservation: api.captureObservation },
    vulnerabilityApi: {
      ...actual.vulnerabilityApi,
      exposureOverview: api.exposureOverview,
      exposureItems: api.exposureItems,
    },
  };
});

vi.mock("@/lib/copilot/page-adapters", async () => {
  const actual = await vi.importActual<typeof import("@/lib/copilot/page-adapters")>(
    "@/lib/copilot/page-adapters",
  );
  return {
    ...actual,
    buildKbDetailCopilotContext: (
      input: Parameters<typeof actual.buildKbDetailCopilotContext>[0],
    ) => {
      copilot.inputs.push(input as unknown as Record<string, unknown>);
      return actual.buildKbDetailCopilotContext(input);
    },
  };
});

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

function kbEnvelope(
  msrcStatus = "succeeded",
  publishedAt = "2026-08-01",
  nvdStatus = "succeeded",
) {
  const degraded = msrcStatus === "failed" || nvdStatus === "failed";
  return {
    data: {
      snapshot: {
        completeness: "complete",
        freshness: "fresh",
        as_of: "2026-09-06T08:00:00Z",
      },
      kb_id: "KB600001",
      title: "Contoso kernel security update",
      severity: "Critical",
      published_at: publishedAt,
      cve_ids: ["CVE-2026-0001"],
      cves: [{
        cve_id: "CVE-2026-0001",
        title: "Kernel remote execution",
        severity: "Critical",
        cvss: { base_score: 9.8 as number | null, vector: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", severity: "Critical" },
        epss_score: 0.73,
        epss_percentile: 0.92,
        is_known_exploited: true,
        kev_due_date: "2026-08-22",
      }],
      enrichment: {
        status: degraded ? "degraded" : "complete",
        complete: !degraded,
        stale: false,
        expected_count: 2,
        available_count: 2 - Number(msrcStatus === "failed") - Number(nvdStatus === "failed"),
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
          "nvd:CVE-2026-0001": {
            source: "nvd",
            identifier: "CVE-2026-0001",
            status: nvdStatus,
            stale: false,
            has_last_known_good: false,
            safe_error_code: nvdStatus === "failed" ? "provider_unavailable" : "",
            source_at: "2026-09-06T07:35:00Z",
          },
          "epss:CVE-2026-0001": {
            source: "epss",
            identifier: "CVE-2026-0001",
            status: "succeeded",
            stale: false,
            has_last_known_good: true,
            source_at: "2026-09-06T07:36:00Z",
          },
          "kev:CVE-2026-0001": {
            source: "kev",
            identifier: "CVE-2026-0001",
            status: "succeeded",
            stale: false,
            has_last_known_good: true,
            source_at: "2026-09-06T07:37:00Z",
          },
        },
      },
      affected_servers: ["server-1"],
      affected_server_count: 137,
      affected_servers_truncated: true,
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
    copilot.inputs.length = 0;
    navigation.params = new URLSearchParams(
      "subscription=sub-1&q=kernel&severity=critical&page_size=25&origin=%2Fexposure%2Fdefender-posture&row=exposure-1&scroll=320&generation=generation-25",
    );
    api.detail.mockResolvedValue(kbEnvelope());
    api.reviews.mockResolvedValue({ data: { schema_version: 1, actor: "reader", kb_id: "KB600001", scope: authorizedScope, revision: 0, reviews: [] },
      scope: authorizedScope, evidence: [], warnings: [] });
    api.observations.mockResolvedValue({ data: { schema_version: 1, actor: "reader", kb_id: "KB600001", scope: authorizedScope, revision: 0, observations: [] },
      scope: authorizedScope, evidence: [], warnings: [] });
    api.exposureOverview.mockResolvedValue(overviewEnvelope());
    api.exposureItems.mockResolvedValue(findingsEnvelope());
  });

  it("renders metadata, MSRC associations, and findings as independent evidence sections", async () => {
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    for (const heading of ["Update identity and release", "Associated CVEs", "Affected assets"]) {
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(api.detail).toHaveBeenCalledTimes(1);
    const copilotInput = copilot.inputs.at(-1) as {
      kb: { affected_server_count: number; affected_servers_truncated: boolean };
      sources: Array<{ key: string }>;
    };
    expect(copilotInput.kb).toMatchObject({
      affected_server_count: 137,
      affected_servers_truncated: true,
    });
    expect(copilotInput.sources).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: "msrc" }),
        expect.objectContaining({ key: "nvd" }),
      ]),
    );
    expect(screen.getByText(/1 of 2 connections represented/)).toBeInTheDocument();
    expect(screen.getAllByText(/1 of 2 represented/).length).toBeGreaterThanOrEqual(2);
    // Excluded counts/reasons come from each section's own contract now, not
    // the shared overview — only "Affected assets" (findings) carries its
    // own completeness with excluded connections in this fixture.
    const affectedAssetsSection = screen.getByRole("region", { name: "Affected assets section" });
    expect(within(affectedAssetsSection).getAllByText(/1 excluded/).length).toBeGreaterThanOrEqual(1);
    expect(
      within(affectedAssetsSection).getByText("AUM East connection unavailable"),
    ).toBeInTheDocument();
    const associatedCvesSection = screen.getByRole("region", { name: "Associated CVEs section" });
    expect(associatedCvesSection.querySelector(".source-section-coverage")?.textContent ?? "").not.toMatch(
      /excluded/,
    );
    expect(screen.getByText("2026-08-01")).toBeInTheDocument();
    expect(screen.getByText("73.0% EPSS")).toBeInTheDocument();
    expect(screen.getByText(/KEV listed · due 2026-08-22/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open CVE-2026-0001" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Showing 1–1 of 3 findings · 1 loaded")).toBeInTheDocument();
  });

  it("keeps the update hierarchy in accessible reading order", async () => {
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    await screen.findByRole("heading", { name: "Update identity and release" });
    const headings = screen.getAllByRole("heading").map((heading) => heading.textContent);
    const expectedOrder = [
      "Update identity and release",
      "Installation and missing posture",
      "Associated CVEs",
      "Affected assets",
      "Governed remediation handoff",
      "Source freshness",
    ];
    const positions = expectedOrder.map((heading) => headings.indexOf(heading));
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((left, right) => left - right));
  });

  it("opens read-only Copilot without duplicating detail or remediation requests", async () => {
    const user = userEvent.setup();
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    await user.click(
      await screen.findByRole("button", {
        name: "Ask Copilot about KB600001",
      }),
    );

    expect(api.detail).toHaveBeenCalledTimes(1);
    expect(navigation.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: /Operations Copilot/i })).toBeInTheDocument();
  });

  it("canonicalizes a numeric KB route for detail and findings requests", async () => {
    render(<KbDetailPage params={{ id: "600001" }} />);

    await screen.findByRole("heading", { name: "Update identity and release" });
    expect(api.detail).toHaveBeenCalledWith(
      "KB600001",
      expect.anything(),
      expect.anything(),
    );
    expect(api.exposureItems).toHaveBeenCalledWith(
      expect.objectContaining({
        filters: expect.objectContaining({ weakness_id: "KB600001" }),
      }),
      expect.anything(),
    );
  });

  it("keeps metadata and findings usable when MSRC associations are unavailable", async () => {
    api.detail.mockResolvedValue(kbEnvelope("failed"));
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("MSRC CVE associations is unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("Contoso kernel security update").length).toBeGreaterThan(0);
    expect(screen.getByText("server-1")).toBeInTheDocument();
  });

  it("degrades aggregate context when NVD metadata is unavailable", async () => {
    const unavailableNvd = kbEnvelope("succeeded", "2026-08-01", "failed");
    unavailableNvd.data.cves[0].cvss.base_score = null;
    unavailableNvd.data.cves[0].cvss.vector = "";
    api.detail.mockResolvedValue(unavailableNvd);
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("Unavailable operational context")).toBeInTheDocument();
    expect(screen.getByText("CVSS unavailable")).toBeInTheDocument();
  });

  it("does not present unknown Silver freshness as current", async () => {
    const unknownFreshness = kbEnvelope();
    unknownFreshness.data.snapshot.freshness = "unknown";
    api.detail.mockResolvedValue(unknownFreshness);
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("Partial operational context")).toBeInTheDocument();
  });

  it("does not reload KB detail when a finding-only filter changes", async () => {
    const user = userEvent.setup();
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(
      (await screen.findAllByText("Contoso kernel security update")).length,
    ).toBeGreaterThan(0);
    await user.selectOptions(screen.getByLabelText("Target kind"), "server");

    await waitFor(() => expect(api.exposureItems).toHaveBeenCalledTimes(2));
    expect(api.detail).toHaveBeenCalledTimes(1);
  });

  it("bounds Copilot freshness by source family for many associated CVEs", async () => {
    const manyCves = kbEnvelope();
    manyCves.data.enrichment.sources = {
      ...manyCves.data.enrichment.sources,
      ...Object.fromEntries(
        Array.from({ length: 64 }, (_, index) => [
          `nvd:CVE-2026-${String(index).padStart(4, "0")}`,
          {
            source: "nvd",
            identifier: `CVE-2026-${String(index).padStart(4, "0")}`,
            status: index === 63 ? "failed" : "succeeded",
            stale: false,
            has_last_known_good: index !== 63,
            safe_error_code: index === 63 ? "provider_unavailable" : "",
            source_at: "2026-09-06T07:35:00Z",
          },
        ]),
      ),
    };
    api.detail.mockResolvedValue(manyCves);

    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("Unavailable operational context")).toBeInTheDocument();
    const copilotInput = copilot.inputs.at(-1) as {
      sources: Array<{ key: string; freshness: string }>;
    };
    expect(copilotInput.sources).toHaveLength(5);
    expect(copilotInput.sources).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: "silver_patch_snapshot" }),
        expect.objectContaining({ key: "msrc" }),
        expect.objectContaining({ key: "nvd", freshness: "unavailable" }),
        expect.objectContaining({ key: "epss" }),
        expect.objectContaining({ key: "kev" }),
      ]),
    );
  });

  it("shows partial and unknown-safe metadata without inventing zero", async () => {
    const partial = overviewEnvelope();
    partial.data.contract.completeness.state = "partial";
    partial.data.completeness.state = "partial";
    api.exposureOverview.mockResolvedValue(partial);
    api.detail.mockResolvedValue(kbEnvelope("succeeded", ""));
    render(<KbDetailPage params={{ id: "KB600001" }} />);

    expect(await screen.findByText("Partial operational context")).toBeInTheDocument();
    const releaseDate = screen.getByText("Release date").closest("div");
    expect(releaseDate).not.toBeNull();
    expect(within(releaseDate!).getByText("—")).toBeInTheDocument();
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

    const back = await screen.findByRole("link", { name: "Back to Defender exposure" });
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
      name: "Associated CVEs section",
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

  it("does not promote filtered finding counts into distinct missing targets or per-CVE applicability", async () => {
    render(<KbDetailPage params={{ id: "KB600001" }} />);
    const value = await screen.findByLabelText("Missing targets value");
    await waitFor(() => expect(value).toHaveTextContent("137"));
    expect(screen.getByText("Per-CVE target mapping unreported")).toBeVisible();
    expect(screen.getByText("Latest KB snapshot missing / installation-failed targets; not filtered finding rows")).toBeVisible();
    const section = screen.getByRole("region", { name: "KB update evidence" });
    expect(within(section).getByText(/Whole-snapshot status counts are unavailable/)).toBeVisible();
    expect(within(section).getByText("Unknown; no product identifiers recorded")).toBeVisible();
    expect(within(section).getByRole("link", { name: "Microsoft support article for KB600001" })).toHaveAttribute("href", "https://support.microsoft.com/help/600001");
    expect(within(section).getByText(/Unknown is not “no prerequisites”/)).toBeVisible();
  });

  it("rejects metadata for another KB instead of rendering plausible update evidence", async () => {
    const wrong = kbEnvelope(); wrong.data.kb_id = "KB9999999"; api.detail.mockResolvedValueOnce(wrong);
    render(<KbDetailPage params={{ id: "KB600001" }} />);
    expect((await screen.findAllByText(/KB evidence does not match/)).length).toBeGreaterThan(0);
    expect(screen.queryByText("Contoso kernel security update")).not.toBeInTheDocument();
    expect(screen.getByText("server-1")).toBeVisible(); // Independent authorized findings remain available.
  });

  it("remounts local target filters when the effective URL scope changes", async () => {
    const user = userEvent.setup();
    const view = render(<KbDetailPage params={{ id: "KB600001" }} />);
    await screen.findByRole("heading", { name: "Affected assets" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by Target kind" }), "container_image");
    await waitFor(() => expect(api.exposureItems.mock.calls.at(-1)?.[0].filters.target_kind).toBe("container_image"));
    const narrowed = { ...kbEnvelope(), scope: { subscription: ["sub-1"], environment: ["prod"] } };
    api.detail.mockResolvedValue(narrowed);
    navigation.params = new URLSearchParams("subscription=sub-1&environment=prod&generation=generation-25");
    view.rerender(<KbDetailPage params={{ id: "KB600001" }} />);
    await waitFor(() => expect(api.exposureItems.mock.calls.at(-1)?.[0].scope).toEqual({ subscription: ["sub-1"], environment: ["prod"] }));
    expect(api.exposureItems.mock.calls.at(-1)?.[0].filters.target_kind).toBeUndefined();
    await waitFor(() => expect(copilot.inputs.at(-1)?.scope).toEqual({ subscription: ["sub-1"], environment: ["prod"] }));
  });

  it("shows exact snapshot status counts and sampled observations without inventing dependency facts", async () => {
    const value = kbEnvelope("failed");
    api.detail.mockResolvedValueOnce({ ...value, data: { ...value.data, generation: "silver-patch:one",
      affected_server_count: 103, installation_status_counts: { observed_targets: 1000, missing: 100, installation_failed: 3, installed: 800, other: 97 },
      target_status_observations: [{ target_id: "sampled-server", status: "installation_failed", observed_at: "2026-09-06T07:00:00Z" }],
      target_status_observations_truncated: true, update_guidance: { source: "msrc", product_ids: ["recorded-product-one"], dependency_capability: "not_collected" },
    } });
    render(<KbDetailPage params={{ id: "KB600001" }} />);
    const section = await screen.findByRole("region", { name: "KB update evidence" });
    expect(await within(section).findByText("800")).toBeVisible();
    expect(within(section).getByText("recorded-product-one")).toBeVisible();
    expect(within(section).getByText(/failed; not marked stale; last-known-good absent/)).toBeVisible();
    expect(within(section).getByText("Unknown; no provider relationship graph is available")).toBeVisible();
    await userEvent.click(within(section).getByText("Inspect sampled target status observations"));
    expect(within(section).getByText(/sampled-server: installation_failed/)).toBeVisible();
    expect(within(section).getByText(/1 loaded \/ 1000 observed targets; sample is truncated/)).toBeVisible();
    expect(within(section).getByText(/not proof that this portal executed an update/)).toBeVisible();
  });
});
