import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import type { ScopeSelection } from "@/lib/scope";
import { FabricMedallionPanel } from "@/components/fabric/medallion";

const {
  fabricCapabilities,
  fabricDataset,
  fabricDatasetContract,
  fabricGovernance,
  fabricIngestionHistory,
  fabricLayers,
  fabricManifest,
  buildFabricMedallionCopilotContext,
  list,
  replace,
  searchParams,
} = vi.hoisted(() => ({
  fabricCapabilities: vi.fn(),
  fabricDataset: vi.fn(),
  fabricDatasetContract: vi.fn(),
  fabricGovernance: vi.fn(),
  fabricIngestionHistory: vi.fn(),
  fabricLayers: vi.fn(),
  fabricManifest: vi.fn(),
  buildFabricMedallionCopilotContext: vi.fn(),
  list: vi.fn(),
  replace: vi.fn(),
  searchParams: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => searchParams.current,
}));

vi.mock("@/lib/copilot/page-adapters", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/copilot/page-adapters")>();
  buildFabricMedallionCopilotContext.mockImplementation(
    actual.buildFabricMedallionCopilotContext,
  );
  return {
    ...actual,
    buildFabricMedallionCopilotContext,
  };
});

vi.mock("@/lib/services", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/services")>();
  return {
    ...actual,
    buildCopilotSnapshot: actual.buildCopilotSnapshot,
    connectionsApi: { list },
    fabricMedallionApi: {
      layers: fabricLayers,
      dataset: fabricDataset,
      datasetContract: fabricDatasetContract,
      manifest: fabricManifest,
      governance: fabricGovernance,
      ingestionHistory: fabricIngestionHistory,
      capabilities: fabricCapabilities,
    },
  };
});

import FabricMedallionPage from "./page";

const connections = [
  {
    connection_id: "prod",
    name: "Production",
    subscription_id: "00000000-0000-0000-0000-000000000001",
    tenant_id: "00000000-0000-0000-0000-000000000002",
    scope_key: "prod",
    is_active: true,
    health_status: "healthy",
    sync_status: "succeeded",
    last_successful_sync_at: "2026-01-01T00:00:00Z",
    business_service: "Payments",
    environment: "prod",
    criticality: "critical",
  },
  {
    connection_id: "nonprod",
    name: "Non-production",
    subscription_id: "00000000-0000-0000-0000-000000000003",
    tenant_id: "00000000-0000-0000-0000-000000000002",
    scope_key: "nonprod",
    is_active: true,
    health_status: "healthy",
    sync_status: "succeeded",
    last_successful_sync_at: "2026-01-01T00:00:00Z",
    business_service: "Payments",
    environment: "dev",
    criticality: "low",
  },
];

function envelope<T>(
  data: T,
  sourceEngine = "fabric.medallion_health",
  freshness: "fresh" | "aging" | "stale" = "fresh",
  timestamp = "2026-01-01T00:00:00Z",
) {
  return {
    data,
    evidence: [{
      source_engine: sourceEngine,
      source_table: "metadata_source_status",
      timestamp,
      confidence: "high",
      freshness,
    }],
    scope: {},
    knowledge_version: "fabric-test",
  };
}

function renderPage(initialScope: ScopeSelection = {}) {
  return render(
    <ScopeProvider initialScope={initialScope}>
      <FabricMedallionPage />
    </ScopeProvider>
  );
}

describe("Per-subscription Fabric medallion page", () => {
  beforeEach(() => {
    replace.mockReset();
    list.mockReset();
    fabricLayers.mockReset();
    fabricCapabilities.mockReset();
    fabricManifest.mockReset();
    fabricGovernance.mockReset();
    fabricIngestionHistory.mockReset();
    fabricDataset.mockReset();
    fabricDatasetContract.mockReset();
    fabricDatasetContract.mockResolvedValue(envelope({
      table_name: "bronze_resources", evaluated_at: "2026-10-17T12:00:00Z",
      declared_schema: { source: "fabric.schema_registry", version: "2.7.0", status: "not_registered", fields: [] },
      deployed_schema_validation: "not_collected", producer_ownership: "not_collected", dataset_dependency_graph: "not_collected",
      source_diagnostics: [],
    }));
    buildFabricMedallionCopilotContext.mockClear();
    searchParams.current = new URLSearchParams();

    list.mockResolvedValue({
      data: connections,
      evidence: [],
      scope: {},
      pagination: { offset: 0, limit: 100, total: 2, next_offset: null },
    });
    fabricLayers.mockResolvedValue(envelope({
      layers: { bronze: { healthy: 1, total: 1 }, silver: { healthy: 1, total: 1 }, gold: { healthy: 1, total: 1 } },
    }));
    fabricCapabilities.mockResolvedValue(envelope({
      capacity: { status: "active", capacity_name: "cap" },
      data_access_roles: { status: "available" },
      maintenance: { status: "available" },
      lineage: { native_lineage_url: "https://fabric.microsoft.com/workspace/abc", datasets: [{ table_name: "bronze_resources" }] },
      semantic_readiness: { status: "available" },
      data_agent_readiness: { status: "available", configured: true },
    }));
    fabricManifest.mockResolvedValue(envelope(
      { entries: [] },
      "ontology.publication_manifest",
      "stale",
      "2025-12-01T00:00:00Z",
    ));
    fabricGovernance.mockResolvedValue(envelope(
      { ownership_gap_count: 0, tag_gap_count: 0, referential_integrity_blockers: 0, gaps: [] },
      "fabric.data_quality",
    ));
    fabricIngestionHistory.mockResolvedValue(envelope({ runs: [] }));
    fabricDataset.mockResolvedValue(envelope({ table_name: "bronze_resources", availability: "healthy", row_count: 5, freshness: "current", quality: "passing", watermark: "2026-01-01T00:00:00Z", observed_at: "2026-01-01T00:00:00Z", lineage_ref: "ref" }));
  });

  it("lists every onboarded subscription in the selector", async () => {
    renderPage();

    const selector = await screen.findByLabelText("Subscription connection");
    expect(selector).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Production/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Non-production/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All onboarded subscriptions" })).toBeInTheDocument();
  });

  it("scopes every Fabric API call to the subscription from the query string", async () => {
    searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
    renderPage();

    await waitFor(() => {
      expect(fabricLayers).toHaveBeenCalledWith({ subscription: [connections[0].subscription_id] });
      expect(fabricManifest).toHaveBeenCalledWith({ subscription: [connections[0].subscription_id] });
      expect(fabricGovernance).toHaveBeenCalledWith({ subscription: [connections[0].subscription_id] });
      expect(fabricIngestionHistory).toHaveBeenCalledWith({ subscription: [connections[0].subscription_id] });
      expect(fabricCapabilities).toHaveBeenCalledWith({ subscription: [connections[0].subscription_id] });
    });

    expect(await screen.findByText("Production")).toBeInTheDocument();
  });

  it("pushes the chosen subscription into the URL when the operator switches subscriptions", async () => {
    renderPage();

    const selector = await screen.findByLabelText("Subscription connection");
    fireEvent.change(selector, { target: { value: connections[1].subscription_id } });

    expect(replace).toHaveBeenCalledWith(
      `/connections/fabric?subscription=${encodeURIComponent(connections[1].subscription_id)}`,
      { scroll: false },
    );
  });

  it("clears the subscription filter when All onboarded subscriptions is selected", async () => {
    searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
    renderPage();

    const selector = await screen.findByLabelText("Subscription connection");
    fireEvent.change(selector, { target: { value: "" } });

    expect(replace).toHaveBeenCalledWith("/connections/fabric", { scroll: false });
  });

  it("renders medallion health outside a tabpanel so the page is directly linkable", async () => {
    renderPage();

    expect(await screen.findByRole("region", { name: "Fabric medallion health" })).toBeInTheDocument();
    expect(screen.queryByRole("tabpanel")).not.toBeInTheDocument();
    expect(screen.getByText("Bronze tables")).toBeInTheDocument();
  });

  it("retains independent Fabric page evidence and freshness in Copilot context", async () => {
    renderPage();

    await waitFor(() => {
      expect(buildFabricMedallionCopilotContext).toHaveBeenCalled();
      const input = buildFabricMedallionCopilotContext.mock.calls.at(-1)?.[0];
      expect(input).toMatchObject({
        available: true,
        freshness: "stale",
        sourceStatuses: expect.arrayContaining([
          {
            source: "fabric/medallion-layers",
            availability: "available",
            freshness: "fresh",
            observedAt: "2026-01-01T00:00:00Z",
          },
          {
            source: "fabric/manifest",
            availability: "available",
            freshness: "stale",
            observedAt: "2025-12-01T00:00:00Z",
          },
          {
            source: "fabric/governance",
            availability: "available",
            freshness: "fresh",
            observedAt: "2026-01-01T00:00:00Z",
          },
          {
            source: "fabric/capabilities",
            availability: "available",
            freshness: "fresh",
            observedAt: "2026-01-01T00:00:00Z",
          },
        ]),
      });
      expect(input && "evidence" in input
        ? input.evidence.map((item: { source_engine: string }) => item.source_engine)
        : []).toEqual(expect.arrayContaining([
        "fabric.medallion_health",
        "ontology.publication_manifest",
        "fabric.data_quality",
      ]));
    });
  });

    it("blocks a bookmarked subscription outside global scope before any Fabric reads", async () => {
      searchParams.current = new URLSearchParams({ subscription: connections[1].subscription_id });
      renderPage({ subscription: [connections[0].subscription_id] });
      expect(screen.getByText("Fabric selection is outside the current scope")).toBeInTheDocument();
      expect(fabricLayers).not.toHaveBeenCalled();
      expect(fabricDataset).not.toHaveBeenCalled();
      expect(fabricCapabilities).not.toHaveBeenCalled();
      expect(list).not.toHaveBeenCalled();
    });

    it("also blocks an embedded subscription that would broaden its caller's scope", () => {
      render(<FabricMedallionPanel refreshKey={0} scope={{ subscription: ["sub-a"] }} subscriptionId="sub-b" />);
      expect(screen.getByText("Fabric selection is outside the current scope")).toBeInTheDocument();
      expect(fabricLayers).not.toHaveBeenCalled();
    });

    it("preserves every global selector while narrowing an allowed subscription", async () => {
      searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
      const scope = { subscription: connections.map(row => row.subscription_id), environment: ["prod"], subscription_connection: ["prod"] };
      renderPage(scope);
      const effective = { ...scope, subscription: [connections[0].subscription_id] };
      await waitFor(() => expect(fabricDataset).toHaveBeenCalledWith("bronze_resources", effective));
      expect(fabricLayers).toHaveBeenCalledWith(effective);
      expect(fabricCapabilities).toHaveBeenCalledWith(effective);
    });

    it("does not convert unavailable layer counts or registration to zero or no datasets", async () => {
      fabricLayers.mockRejectedValue(new Error("Synthetic layer failure"));
      fabricCapabilities.mockRejectedValue(new Error("Synthetic capability failure"));
      renderPage();
      expect(await screen.findByText("Fabric layer counts unavailable")).toBeInTheDocument();
      expect(await screen.findByText("Bronze dataset registration unavailable")).toBeInTheDocument();
      expect(screen.getByLabelText("Bronze tables value")).toHaveTextContent("—");
      expect(screen.queryByText("No bronze datasets registered")).not.toBeInTheDocument();
      await waitFor(() => expect(buildFabricMedallionCopilotContext.mock.calls.at(-1)?.[0]).toMatchObject({
        available: false, freshness: "stale",
      }));
    });

    it("connects dataset budgets to the same scoped card and distinguishes legacy absence", async () => {
      renderPage();
      expect(await screen.findByText("Freshness budget unavailable from this response.")).toBeInTheDocument();
      expect(screen.getByText("bronze_resources")).toBeInTheDocument();
    });

    it("reads a contract only on explicit inspection, preserves scope, and returns focus on close", async () => {
      searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
      renderPage();
      const button = await screen.findByRole("button", { name: "Inspect contract and diagnostics for bronze_resources" });
      expect(fabricDatasetContract).not.toHaveBeenCalled();
      fireEvent.click(button);
      expect(await screen.findByText("No declared schema registered")).toBeInTheDocument();
      expect(fabricDatasetContract).toHaveBeenCalledWith("bronze_resources", { subscription: [connections[0].subscription_id] });
      fireEvent.click(screen.getByRole("button", { name: "Close contract" }));
      expect(screen.queryByRole("region", { name: "Dataset contract: bronze_resources" })).not.toBeInTheDocument();
      expect(button).toHaveFocus();
    });

    it("renders a server budget on its dataset card", async () => {
      fabricDataset.mockResolvedValue(envelope({
        table_name: "bronze_resources", row_count: 5, freshness: "fresh", quality: "complete",
        freshness_budget: {
          evaluated_at: "2026-10-17T12:00:00Z", clock: "metadata_status_ingested_then_observed_then_timestamp",
          state: "fresh", threshold_seconds: 600, cadence_minutes: 10, slo_multiplier: 1,
          policy: "table_override", source_count: 1, known_clock_count: 1,
          worst_known_age_seconds: 0, remaining_seconds: 600,
          sources: [{ scope: { subscription: ["sub-a"] }, status_at: "2026-10-17T12:00:00Z",
            state: "fresh", age_seconds: 0, remaining_seconds: 600 }],
        },
      }));
      renderPage();
      expect(await screen.findByText("Freshness budget: 10 min remaining")).toBeInTheDocument();
      expect(screen.getByText("Recorded quality: complete")).toBeInTheDocument();
      expect(screen.queryByText("All quality checks passed")).not.toBeInTheDocument();
    });

    it("does not expose a late old-scope dataset response after subscription navigation", async () => {
      let release = () => {};
      fabricDataset.mockReturnValueOnce(new Promise(resolve => {
        release = () => resolve(envelope({ table_name: "bronze_resources", row_count: 91 }));
      }));
      fabricDataset.mockResolvedValue(envelope({ table_name: "bronze_resources", row_count: 2 }));
      const view = renderPage();
      await waitFor(() => expect(fabricDataset).toHaveBeenCalledTimes(1));
      searchParams.current = new URLSearchParams({ subscription: connections[1].subscription_id });
      view.rerender(<ScopeProvider><FabricMedallionPage /></ScopeProvider>);
      expect(await screen.findByText(/2 rows · observation time unreported/)).toBeInTheDocument();
      await act(async () => release());
      expect(screen.queryByText(/91 rows/)).not.toBeInTheDocument();
    });
});
