import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const api = vi.hoisted(() => ({
  exposureFacets: vi.fn(),
  exposureItems: vi.fn(),
  summary: vi.fn(),
  patchPriorities: vi.fn(),
  assetExposures: vi.fn(),
  defenderOverview: vi.fn(),
  slaCompliance: vi.fn(),
  riskExceptions: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  buildCopilotSnapshot: (input: Record<string, unknown>) => input,
  copilotEvidenceRows: () => [],
  vulnerabilityApi: api,
}));

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
    api.exposureFacets.mockResolvedValue(facetEnvelope());
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

  it("renders every Overview section from two bounded SQL requests", async () => {
    render(<ScopeProvider><ExposurePage /></ScopeProvider>);

    expect(await screen.findByLabelText("Current exposure findings value")).toHaveTextContent("77857");
    expect(screen.getByLabelText("Critical findings value")).toHaveTextContent("2548");
    expect(screen.getByLabelText("High findings value")).toHaveTextContent("29035");
    expect(screen.getByLabelText("Container image findings value")).toHaveTextContent("77857");
    expect(screen.getByLabelText("Defender image findings value")).toHaveTextContent("77857");
    expect(screen.getByLabelText("Indeterminate SLA findings value")).toHaveTextContent("77857");
    expect(screen.getByText("CVE-2026-0001")).toBeInTheDocument();
    expect(screen.queryByText("Exposure intelligence is unavailable")).not.toBeInTheDocument();

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
    expect(within(preview).getByRole("link", { name: "Open CVE-2026-0001" })).toHaveAttribute(
      "href",
      `/exposure/cves/CVE-2026-0001?generation=${generation}&origin=%2Fexposure`,
    );
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
});
