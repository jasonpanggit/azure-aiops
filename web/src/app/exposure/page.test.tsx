import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";
import { parseExposureQueryState } from "@/lib/exposure-query-state";
import { SCOPE_DIMENSIONS } from "@/lib/scope";

const navigation = vi.hoisted(() => ({
  push: vi.fn(),
  search: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push }),
  useSearchParams: () => navigation.search,
}));

const api = vi.hoisted(() => ({
  exposureFacets: vi.fn(),
  exposureHistory: vi.fn(),
  exposureRecovery: vi.fn(),
  exposureItems: vi.fn(),
  summary: vi.fn(),
  patchPriorities: vi.fn(),
  assetExposures: vi.fn(),
  defenderOverview: vi.fn(),
  slaCompliance: vi.fn(),
  riskExceptions: vi.fn(),
}));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return {
    buildCopilotSnapshot: actual.buildCopilotSnapshot,
    copilotEvidenceRows: () => [],
    vulnerabilityApi: api,
  };
});

import ExposurePage from "./page";

const generation = "exposure-gold-4d85d1e59c660c2636edf8ce";
const completeness = {
  state: "partial" as const,
  represented: 77_857,
  total: 77_857,
  excluded: 0,
};
const freshness = {
  state: "reported",
  as_of: "2026-09-10T04:48:09Z",
  source_family: "defender_image",
  threshold_seconds: 1_800,
};
const applied = {
  scope: {},
  filters: [],
  sort: { field: "priority_score" as const, direction: "desc" as const },
};
const contract = {
  version: "1.0.0",
  query: { ...applied, generation, target_kind: "all" as const },
  counts: { unit: "findings", returned: 1, represented: 77_857, total: 77_857, excluded: 0 },
  units: { finding_count: "count", priority_score: "score" },
  completeness,
  freshness,
  evidence_refs: [],
  deep_link_action: {
    action_id: "open_exposure_detail",
    kind: "deep_link" as const,
    path_field: "detail_path",
    fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
  },
  safe_error: null,
};

function envelope<T>(data: T) {
  return {
    data,
    evidence: [{
      source_engine: "fabric_sql",
      source_table: "gold_exposure_facts",
      timestamp: freshness.as_of,
      confidence: "high",
    }],
    warnings: [],
    scope: {},
    knowledge_version: generation,
    pagination: { limit: 5, total: 77_857, next_cursor: null },
  };
}

function facetEnvelope() {
  return envelope({
    total_count: 77_857,
    generation,
    applied,
    completeness,
    freshness,
    contract,
    facets: {
      severity: [
        { value: "Critical", count: 2_548 },
        { value: "High", count: 29_035 },
        { value: "Medium", count: 35_255 },
        { value: "Low", count: 9_606 },
        { value: "Unknown", count: 1_413 },
      ],
      target_kind: [{ value: "container_image", count: 77_857 }],
      source_family: [{ value: "defender_image", count: 77_857 }],
      sla_state: [{ value: "indeterminate", count: 77_857 }],
      completeness: [{ value: "unknown", count: 77_857 }],
      current_state: [{ value: "active", count: 77_857 }],
    },
    items: itemsEnvelope().data.items,
  });
}

function itemsEnvelope() {
  return envelope({
    total_count: 77_857,
    generation,
    applied,
    completeness,
    freshness,
    contract,
    next_cursor: null,
    items: [{
      exposure_id: "exposure-1",
      target_id: "target-1",
      target_kind: "container_image",
      weakness_id: "CVE-2026-0001",
      weakness_kind: "cve",
      severity: "Critical",
      source_family: "defender_image",
      current_state: "active",
      sla_state: "indeterminate",
      priority_score: 100,
      recommendation: "Update the affected image",
      detail_path: "/exposure/cves/CVE-2026-0001",
      subscription_id: "sub-1",
      connection_ids: [],
      source_families: [],
      read_model_generation_id: generation,
      completeness: "unknown",
    }],
  });
}

describe("ExposurePage bounded read model", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.search = new URLSearchParams();
    api.exposureFacets.mockResolvedValue(facetEnvelope());
    api.exposureHistory.mockResolvedValue(envelope({ schema_version: 1, actor: "reader", scope: {}, revision: 0, observations: [] }));
    api.exposureRecovery.mockResolvedValue(envelope({ schema_version: 1, actor: "reader", scope: {}, revision: 0, events: [], candidates: [] }));
    api.exposureItems.mockRejectedValue(new Error("exposureItems must not be called"));
    for (const method of [
      "summary",
      "patchPriorities",
      "assetExposures",
      "defenderOverview",
      "slaCompliance",
      "riskExceptions",
    ] as const) {
      api[method].mockRejectedValue(new Error(`${method} must not be called`));
    }
  });

  it("renders every Overview section from one atomic bounded SQL request", async () => {
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);

    expect(await screen.findByLabelText("Current exposure findings value")).toHaveTextContent("77857");
    expect(screen.getByLabelText("Critical findings value")).toHaveTextContent("2548");
    expect(screen.getByLabelText("High findings value")).toHaveTextContent("29035");
    expect(screen.getByLabelText("Container image findings value")).toHaveTextContent("77857");
    expect(screen.getByLabelText("Defender image findings value")).toHaveTextContent("77857");
    expect(screen.getByLabelText("Indeterminate SLA findings value")).toHaveTextContent("77857");
    expect(screen.getByText("CVE-2026-0001")).toBeInTheDocument();
    expect(screen.queryByText("Exposure intelligence is unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText(/77,857 of.*connections represented/)).not.toBeInTheDocument();

    expect(api.exposureFacets).toHaveBeenCalledTimes(1);
    expect(api.exposureItems).not.toHaveBeenCalled();
    for (const method of [
      "summary",
      "patchPriorities",
      "assetExposures",
      "defenderOverview",
      "slaCompliance",
      "riskExceptions",
    ] as const) {
      expect(api[method]).not.toHaveBeenCalled();
    }
  });

  it("reports whole-page unavailability when the atomic bounded read fails", async () => {
    api.exposureFacets.mockRejectedValue(new Error("Facets unavailable"));
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);

    expect(await screen.findByText("Exposure intelligence is unavailable")).toBeInTheDocument();
  });

  it("requests the exact bounded facet vocabulary", async () => {
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    await waitFor(() => expect(api.exposureFacets).toHaveBeenCalled());

    expect(api.exposureFacets.mock.calls[0][1]).toEqual([
      "severity",
      "target_kind",
      "source_family",
      "sla_state",
      "completeness",
      "current_state",
    ]);
  });

  it("keeps the priority detail link generation-bound", async () => {
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    const preview = await screen.findByLabelText("Priority preview state");
    const href = within(preview).getByRole("link", { name: "Open CVE-2026-0001" }).getAttribute("href")!;
    const link = new URL(href, "http://localhost");
    expect(link.pathname).toBe("/exposure/cves/CVE-2026-0001");
    expect(link.searchParams.get("generation")).toBe(generation);
    expect(link.searchParams.get("origin")).toBe("/exposure");
    expect(link.searchParams.get("row")).toBe("exposure-1");
  });

  it("does not include other Defender families in the image metric", async () => {
    const response = facetEnvelope();
    response.data.facets.source_family.push({ value: "defender_posture", count: 12 });
    api.exposureFacets.mockResolvedValue(response);
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);

    expect(await screen.findByLabelText("Defender image findings value")).toHaveTextContent("77857");
  });

  it("recognizes canonical Azure Update Manager source names", async () => {
    const response = facetEnvelope();
    response.data.facets.source_family.push({
      value: "azure_update_manager_missing",
      count: 24,
    });
    api.exposureFacets.mockResolvedValue(response);
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);

    expect(await screen.findByLabelText("Update Manager findings value")).toHaveTextContent("24");
  });

  it("keeps indeterminate SLA evidence out of an all-clear gauge", async () => {
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    expect(await screen.findByText("SLA rate unavailable")).toBeVisible();
    expect(screen.queryByRole("img", { name: /Overdue findings:/ })).not.toBeInTheDocument();
  });

  it("divides overdue only by explicitly classified findings", async () => {
    const response = facetEnvelope();
    response.data.facets.sla_state = [
      { value: "overdue", count: 5 }, { value: "within_sla", count: 5 },
      { value: "indeterminate", count: 90 }, { value: "not_overdue", count: 10 },
    ];
    api.exposureFacets.mockResolvedValue(response);
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    expect(await screen.findByRole("img", { name: "Overdue findings: 50 out of 100, High" })).toBeVisible();
    expect(screen.getByText(/5 overdue \/ 10 classified findings. 100 unclassified findings excluded/)).toBeVisible();
  });

  it("does not turn an absent severity vocabulary into zero known findings", async () => {
    const response = facetEnvelope();
    Reflect.deleteProperty(response.data.facets, "severity");
    api.exposureFacets.mockResolvedValue(response);
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    expect(await screen.findByLabelText("Critical findings value")).not.toHaveTextContent("0");
    expect(screen.getByLabelText("High findings value")).not.toHaveTextContent("0");
  });

  it.each(["generation=", "generation=one&generation=two", "generation=invalid%2Fgeneration", "subscription=%0A"])(
    "rejects malformed bookmarks before reads: %s", async query => {
      navigation.search = new URLSearchParams(query);
      render(<ScopeProvider><ExposurePage /></ScopeProvider>);
      expect(await screen.findByText("Exposure bookmark unavailable")).toBeVisible();
      expect(api.exposureFacets).not.toHaveBeenCalled();
    },
  );

  it("rejects an out-of-selection scope instead of reading another partition", async () => {
    navigation.search = new URLSearchParams({ subscription: "outside" });
    render(<ScopeProvider initialScope={{ subscription: ["selected"] }}><ExposurePage /></ScopeProvider>);
    expect(await screen.findByText("Exposure bookmark unavailable")).toBeVisible();
    expect(api.exposureFacets).not.toHaveBeenCalled();
  });

  it("keeps all nine narrowed dimensions and generation on reads and child collections/details", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, [`${dimension}-one`, `${dimension}-two`]]));
    for (const dimension of SCOPE_DIMENSIONS) for (const value of scope[dimension]) navigation.search.append(dimension, value);
    navigation.search.set("generation", generation);
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    await screen.findByText("CVE-2026-0001");
    expect(api.exposureFacets.mock.calls[0][0]).toMatchObject({ scope, generation });
    for (const name of ["Open Patch priorities", "Open Defender exposure", "Review priorities", "Open CVE-2026-0001"]) {
      const href = screen.getByRole("link", { name }).getAttribute("href")!;
      const query = new URL(href, "http://localhost").searchParams;
      for (const dimension of SCOPE_DIMENSIONS) expect(query.getAll(dimension)).toEqual(scope[dimension]);
      expect(query.get("generation")).toBe(generation);
      expect(parseExposureQueryState(query, { authorizedScope: {} }).scope).toEqual(scope);
    }
  });

  it("hides prior partition findings synchronously when a bookmark changes", async () => {
    navigation.search = new URLSearchParams({ subscription: "first" });
    const rendered = render(<ScopeProvider><ExposurePage /></ScopeProvider>);
    await screen.findByText("CVE-2026-0001");
    api.exposureFacets.mockReturnValueOnce(new Promise(() => {}));
    navigation.search = new URLSearchParams({ subscription: "second" });
    rendered.rerender(<ScopeProvider><ExposurePage /></ScopeProvider>);
    expect(screen.queryByText("CVE-2026-0001")).not.toBeInTheDocument();
    await waitFor(() => expect(api.exposureFacets.mock.calls.at(-1)?.[0].scope).toEqual({ subscription: ["second"] }));
  });
});
