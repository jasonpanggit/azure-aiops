import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import type { ScopeSelection } from "@/lib/scope";
import type { Envelope } from "@/lib/types";
import { FabricMedallionPanel, fabricEvidenceFreshness } from "@/components/fabric/medallion";

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
  freshness: "fresh" | "aging" | "stale" | "unknown" = "fresh",
  timestamp = "2026-01-01T00:00:00Z",
): Envelope<T> {
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

const capabilitySnapshot = {
  capacity: { status: "active", capacity_name: "cap" },
  data_access_roles: { status: "available" },
  maintenance: { status: "available" },
  lineage: { native_lineage_url: "https://fabric.microsoft.com/workspace/abc", datasets: [{ table_name: "bronze_resources" }] },
  semantic_readiness: { status: "available" },
  data_agent_readiness: { status: "available", configured: true },
};

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
    fabricCapabilities.mockResolvedValue(envelope(capabilitySnapshot));
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

  it("shows declared Gold contracts separately without reading or counting them as deployed datasets", async () => {
    fabricLayers.mockResolvedValue(envelope({
      layers: { bronze: { healthy: 0, total: 0 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 0 } },
      tables: { bronze: [], silver: [], gold: [] },
      gold_declarations: {
        source: "fabric.schema_registry",
        version: "2.7.0",
        tables: ["gold_exposure_facts", "gold_exposure_summaries"],
        physical_inventory: "not_collected",
      },
    }, "fabric.medallion_health", "unknown", ""));
    fabricCapabilities.mockResolvedValue(envelope({
      ...capabilitySnapshot, lineage: { datasets: [] },
    }));

    renderPage({ subscription_connection: ["prod"] });

    const declarations = await screen.findByLabelText("Declared Gold product contracts");
    fireEvent.click(within(declarations).getByText("Explore declared Gold products (source contracts only)"));
    expect(within(declarations).getByText("gold_exposure_facts")).toBeVisible();
    expect(within(declarations).getByText("gold_exposure_summaries")).toBeVisible();
    expect(within(declarations).getByText(/Physical presence, schema validation/)).toBeVisible();
    expect(within(declarations).getByText(/The Ontology Agent can propose semantic/)).toBeVisible();
    expect(await screen.findByText("No Gold datasets registered")).toBeInTheDocument();
    expect(screen.getAllByText(/Physical table absence is not verified/)).toHaveLength(3);
    expect(screen.getAllByText("0 healthy / 0 registered").length).toBeGreaterThanOrEqual(3);
    expect(fabricDataset).not.toHaveBeenCalled();
    expect(fabricDatasetContract).not.toHaveBeenCalled();
    expect(fabricLayers).toHaveBeenCalledWith({ subscription_connection: ["prod"] });
  });

  it("supports older layers responses without a Gold declaration catalog", async () => {
    renderPage();

    await screen.findByText("Reported evidence freshness");
    expect(await screen.findAllByText("1 healthy / 1 registered")).not.toHaveLength(0);
    expect(screen.queryByLabelText("Declared Gold product contracts")).not.toBeInTheDocument();
  });

  it("distinguishes zero healthy datasets from zero records or missing physical tables", async () => {
    fabricLayers.mockResolvedValue(envelope({
      layers: { bronze: { healthy: 0, total: 18 }, silver: { healthy: 0, total: 29 }, gold: { healthy: 0, total: 0 } },
    }, "fabric.medallion_health", "stale"));
    renderPage();

    await waitFor(() => {
      expect(screen.getByLabelText("Bronze tables value")).toHaveTextContent(/^18$/);
      expect(screen.getByLabelText("Silver tables value")).toHaveTextContent(/^29$/);
      expect(screen.getByLabelText("Gold tables value")).toHaveTextContent(/^0$/);
    });
    expect(screen.getByText("Registrations reported · 0 healthy · 18 not confirmed healthy")).toBeInTheDocument();
    expect(screen.getByText(/Zero healthy does not mean empty/)).toBeInTheDocument();
    expect(screen.getByText(/Gold registration counts do not establish physical absence/)).toBeInTheDocument();
    expect(screen.getByText("Recorded dataset evidence is stale")).toBeInTheDocument();
    expect(screen.getByLabelText("Bronze tables value").closest("article")).toHaveClass("metric-critical");
    expect(screen.getByLabelText("Gold tables value").closest("article")).toHaveClass("metric-default");
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

    expect(await screen.findAllByText("Production")).not.toHaveLength(0);
  });

  it("keeps unhealthy and missing responses distinct from observed stale datasets", async () => {
    fabricLayers.mockResolvedValue(envelope({
      layers: { bronze: { healthy: 0, total: 3 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 0 } },
      tables: { bronze: ["bronze_resources", "bronze_advisor", "bronze_cost_actuals"], silver: [], gold: [] },
    }));
    fabricCapabilities.mockResolvedValue(envelope({ ...capabilitySnapshot, lineage: { datasets: [] } }));
    fabricDataset.mockImplementation((table: string) => {
      if (table === "bronze_cost_actuals") return Promise.reject(new Error("Read denied"));
      return Promise.resolve(envelope({
        table_name: table, availability: table === "bronze_resources" ? "stale" : "degraded",
        freshness: "unknown", row_count: 7, quality: "degraded",
      }));
    });
    renderPage();
    expect(await screen.findByText(/1 stale in 2 returned dataset responses/)).toBeInTheDocument();
    expect(screen.getByText("Registrations reported · 0 healthy · 3 not confirmed healthy")).toBeInTheDocument();
    expect(screen.getByText(/Read denied/)).toBeInTheDocument();
    expect(screen.queryByText("Recorded dataset evidence is stale")).not.toBeInTheDocument();
  });

  it("reports selected connection success without treating attempt history as a successful sync", async () => {
    searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
    list.mockResolvedValue({
      data: [
        { ...connections[0], sync_status: "failed", last_successful_sync_at: null },
        connections[1],
      ], evidence: [], scope: {},
    });
    fabricIngestionHistory.mockResolvedValue(envelope({ runs: [
      { source: "publication", projection_name: "older-success", attempted_at: "2026-01-02T00:00:00Z", status: "succeeded", message: "" },
      { source: "source-status", projection_name: "newer-failure", attempted_at: "2026-01-03T00:00:00Z", status: "failed", message: "Collector timeout" },
      { source: "publication", projection_name: "tied-running", attempted_at: "2026-01-03T00:00:00Z", status: "running", message: "" },
      { source: "publication", projection_name: "unorderable", attempted_at: "invalid", status: "failed", message: "" },
    ] }));
    renderPage();
    const sync = await screen.findByRole("region", { name: "Connection sync reports" });
    expect(within(sync).getByText("Reported sync status: failed")).toBeInTheDocument();
    expect(within(sync).getByText("Last successful connection sync: Not reported")).toBeInTheDocument();
    expect(within(sync).queryByText("Non-production")).not.toBeInTheDocument();
    expect(within(sync).getByText(/Actual schedule and next run: not reported/)).toBeInTheDocument();
    const latest = await screen.findByRole("region", { name: "Latest recorded ingestion attempts" });
    expect(within(latest).getByText(/2 attempts at this time; 1 failed. 1 attempts/)).toBeInTheDocument();
    expect(within(latest).getByText(/Reported statuses: Failed: 1 · Running: 1/)).toBeInTheDocument();
    expect(within(latest).getByText(/Collector timeout · Source: source-status/)).toBeInTheDocument();
    expect(within(latest).queryByText("older-success")).not.toBeInTheDocument();
    expect(within(latest).getByText(/not proof of a successful connection sync/)).toBeInTheDocument();
  });

  it("reloads connection reports and health through read APIs only", async () => {
    renderPage();
    const sync = await screen.findByRole("region", { name: "Connection sync reports" });
    expect(within(sync).getAllByText(/Last successful connection sync:/)).toHaveLength(2);
    await waitFor(() => expect(fabricLayers).toHaveBeenCalledTimes(1));
    const reload = screen.getByRole("button", { name: "Reload page data" });
    expect(reload).toHaveAttribute("title", "Reload recorded status; does not start ingestion or publication");
    fireEvent.click(reload);
    await waitFor(() => {
      expect(list).toHaveBeenCalledTimes(2);
      expect(fabricLayers).toHaveBeenCalledTimes(2);
      expect(fabricIngestionHistory).toHaveBeenCalledTimes(2);
    });
  });

  it("does not order invalid timestamps or invent a failure reason", async () => {
    list.mockResolvedValue({
      data: [{ ...connections[0], last_successful_sync_at: "invalid" }], evidence: [], scope: {},
    });
    fabricIngestionHistory.mockResolvedValue(envelope({ runs: [
      { source: "", projection_name: "undated", attempted_at: "", status: "failed", message: "" },
    ] }));
    renderPage();
    expect(await screen.findByText("Last successful connection sync: Invalid timestamp reported: invalid")).toBeInTheDocument();
    const latest = await screen.findByRole("region", { name: "Latest recorded ingestion attempts" });
    expect(within(latest).getByText("Attempt time unreported")).toBeInTheDocument();
    expect(within(latest).getByText(/0 attempts at this time; 0 failed. 1 attempts/)).toBeInTheDocument();
    expect(within(latest).queryByText("undated")).not.toBeInTheDocument();
  });

  it("does not treat legacy empty manifest and governance arrays as observed absence", async () => {
    renderPage();

    expect(await screen.findByText("Fabric medallion dataset absence unverified")).toBeInTheDocument();
    expect(await screen.findByText("Governance absence unverified")).toBeInTheDocument();
    expect(screen.queryByText("No Fabric medallion datasets registered")).not.toBeInTheDocument();
    expect(screen.queryByText("No governance gaps for this scope")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Governed relationships value")).toHaveTextContent("—");
    expect(screen.getByLabelText("Governed relationships value").closest("article")).toHaveClass("metric-default");
  });

  it("renders a qualified empty observation as a last-recorded state", async () => {
    const observation = {
      state: "observed_empty",
      evidence_mode: "recorded_metadata",
      source: { engine: "fabric.test", table: "metadata_test", version: 12 },
      scope: { subscription: [connections[0].subscription_id] },
      observed_at: "2026-10-20T14:00:00Z",
      freshness: "fresh",
      reason_code: "test_observed_empty",
    };
    fabricManifest.mockResolvedValue(envelope({ entries: [], observation }));
    fabricGovernance.mockResolvedValue(envelope({
      ownership_gap_count: 0,
      tag_gap_count: 0,
      referential_integrity_blockers: 0,
      gaps: [],
      observation,
    }));
    searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
    renderPage();

    expect(await screen.findByText("No Fabric medallion datasets observed")).toBeInTheDocument();
    expect(await screen.findByText("No governance gaps observed")).toBeInTheDocument();
  });

  it("does not qualify an empty observation with unknown freshness", async () => {
    const observation = {
      state: "observed_empty",
      evidence_mode: "recorded_metadata",
      source: { engine: "fabric.test", table: "metadata_test", version: null },
      scope: {},
      observed_at: null,
      freshness: "unknown",
      reason_code: "test_freshness_unknown",
    };
    fabricManifest.mockResolvedValue(envelope({ entries: [], observation }));
    fabricGovernance.mockResolvedValue(envelope({
      ownership_gap_count: 0,
      tag_gap_count: 0,
      referential_integrity_blockers: 0,
      gaps: [],
      observation,
    }));
    renderPage();

    expect(await screen.findByText("Fabric medallion dataset absence unverified")).toBeInTheDocument();
    expect(await screen.findByText("Governance absence unverified")).toBeInTheDocument();
  });

  it("keeps populated manifest and governance evidence visible when absence is unverified", async () => {
    fabricManifest.mockResolvedValue(envelope({
      entries: [{
        projection_name: "topology_entities",
        disposition: "active",
        compatibility_version: "1",
        retired_reason: null,
        registered_at: "",
        updated_at: "",
      }],
      observation: {
        state: "unobserved",
        evidence_mode: "not_recorded",
        source: { engine: "ontology.publication_manifest", table: "metadata_publication_manifest", version: null },
        scope: {},
        observed_at: null,
        freshness: "unknown",
        reason_code: "test_scope_unverified",
      },
    }));
    fabricGovernance.mockResolvedValue(envelope({
      ownership_gap_count: 1,
      tag_gap_count: 0,
      referential_integrity_blockers: 0,
      gaps: [{ table_name: "silver_incidents", ownership_gap_count: 1, tag_gap_count: 0, referential_integrity_blockers: 0 }],
      observation: {
        state: "unobserved",
        evidence_mode: "not_recorded",
        source: { engine: "fabric.data_quality", table: "metadata_quality_reports", version: null },
        scope: {},
        observed_at: null,
        freshness: "unknown",
        reason_code: "test_scope_unverified",
      },
    }));
    renderPage();

    expect(await screen.findByText("topology_entities")).toBeInTheDocument();
    expect(screen.getByText("silver_incidents")).toBeInTheDocument();
    expect(screen.queryByText("Fabric medallion dataset absence unverified")).not.toBeInTheDocument();
    expect(screen.queryByText("Governance absence unverified")).not.toBeInTheDocument();
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

  it("shares each section read between the page and panel, including refresh", async () => {
    renderPage();
    await screen.findByText("No ingestion attempts reported");
    for (const read of [fabricLayers, fabricManifest, fabricGovernance, fabricIngestionHistory, fabricCapabilities]) {
      expect(read).toHaveBeenCalledTimes(1);
    }
    fireEvent.click(screen.getByRole("button", { name: "Reload page data" }));
    await waitFor(() => {
      for (const read of [fabricLayers, fabricManifest, fabricGovernance, fabricIngestionHistory, fabricCapabilities]) {
        expect(read).toHaveBeenCalledTimes(2);
      }
    });
  });

  it("does not infer freshness from successful responses with no evidence", async () => {
    fabricLayers.mockResolvedValue({ ...envelope({ layers: { bronze: { healthy: 1, total: 1 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 0 } } }), evidence: [] });
    fabricManifest.mockResolvedValue({ ...envelope({ entries: [] }), evidence: [] });
    fabricGovernance.mockResolvedValue({ ...envelope({ ownership_gap_count: 0, tag_gap_count: 0, referential_integrity_blockers: 0, gaps: [] }), evidence: [] });
    fabricCapabilities.mockResolvedValue({ ...envelope(capabilitySnapshot), evidence: [] });
    renderPage();
    await waitFor(() => {
      const input = buildFabricMedallionCopilotContext.mock.calls.at(-1)?.[0];
      expect(input).toMatchObject({ available: true, freshness: "partial" });
      expect(input.sourceStatuses).toHaveLength(4);
      expect(input.sourceStatuses.every((status: { freshness: string }) => status.freshness === "unknown")).toBe(true);
    });
    const evidence = screen.getByRole("region", { name: "Fabric section evidence" });
    expect(within(evidence).getAllByText("Response received · Freshness: Unknown")).toHaveLength(4);
  });

  it("keeps a stale layer visible despite HTTP success and fresh capability evidence", async () => {
    fabricLayers.mockResolvedValue(envelope({
      layers: { bronze: { healthy: 0, total: 1 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 0 } },
    }, "fabric.medallion_health", "stale"));
    fabricManifest.mockResolvedValue(envelope({ entries: [] }));
    fabricDataset.mockResolvedValue(envelope({ table_name: "bronze_resources", availability: "degraded", row_count: 5, freshness: "stale" }));
    renderPage();
    expect(await screen.findByText("At least one source clock is past target")).toBeInTheDocument();
    await waitFor(() => expect(buildFabricMedallionCopilotContext.mock.calls.at(-1)?.[0]).toMatchObject({
      available: true, freshness: "stale",
      sourceStatuses: expect.arrayContaining([expect.objectContaining({ source: "fabric/medallion-layers", freshness: "stale" })]),
    }));
  });

  it("keeps independent sections available when governance fails", async () => {
    fabricGovernance.mockRejectedValue(new Error("Synthetic governance failure"));
    renderPage();
    expect(await screen.findByText("Governance gaps are unavailable")).toBeInTheDocument();
    expect(await screen.findByText("bronze_resources")).toBeInTheDocument();
    expect(await screen.findByText("No ingestion attempts reported")).toBeInTheDocument();
    await waitFor(() => expect(buildFabricMedallionCopilotContext.mock.calls.at(-1)?.[0]).toMatchObject({
      available: false,
      sourceStatuses: expect.arrayContaining([
        { source: "fabric/governance", availability: "unavailable", freshness: "unknown" },
        expect.objectContaining({ source: "fabric/medallion-layers", availability: "available", freshness: "fresh" }),
      ]),
    }));
    expect(within(screen.getByRole("region", { name: "Fabric section evidence" })).getByText("Request failed · Freshness: Unknown")).toBeInTheDocument();
  });

  it("retains successful datasets within a partially failed layer and recovers on refresh", async () => {
    searchParams.current = new URLSearchParams({ subscription: connections[0].subscription_id });
    fabricCapabilities.mockResolvedValue(envelope({
      ...capabilitySnapshot,
      lineage: { native_lineage_url: "", datasets: [{ table_name: "bronze_resources" }, { table_name: "bronze_alerts" }] },
    }));
    fabricDataset.mockImplementation((tableName: string) => tableName === "bronze_alerts"
      ? Promise.reject(new Error("Recorded alerts read failure"))
      : Promise.resolve(envelope({ table_name: tableName, availability: "healthy", row_count: 5, freshness: "fresh" })));
    renderPage();
    const failure = await screen.findByRole("status", { name: "Bronze dataset read failures" });
    expect(within(failure).getByText("Bronze layer health is partial")).toBeInTheDocument();
    expect(within(failure).getByText(/1 of 2 registered dataset responses available/)).toBeInTheDocument();
    expect(within(failure).getByText(/Recorded alerts read failure/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect contract and diagnostics for bronze_resources" })).toBeInTheDocument();
    expect(screen.queryByText("No Bronze datasets registered")).not.toBeInTheDocument();
    expect(fabricDataset).toHaveBeenCalledWith("bronze_alerts", { subscription: [connections[0].subscription_id] });

    fabricDataset.mockImplementation((tableName: string) => Promise.resolve(envelope({
      table_name: tableName, availability: "healthy", row_count: 5, freshness: "fresh",
    })));
    fireEvent.click(screen.getByRole("button", { name: "Reload page data" }));
    expect(await screen.findByRole("button", { name: "Inspect contract and diagnostics for bronze_alerts" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Bronze dataset read failures" })).not.toBeInTheDocument();
  });

  it("keeps every dataset failure visible without reporting an empty registered layer", async () => {
    fabricDataset.mockRejectedValue(new Error("Recorded dataset failure"));
    renderPage();
    const failure = await screen.findByRole("status", { name: "Bronze dataset read failures" });
    expect(within(failure).getByText("Bronze layer health is unavailable")).toBeInTheDocument();
    expect(within(failure).getByText(/0 of 1 registered dataset responses available/)).toBeInTheDocument();
    expect(within(failure).getByText("bronze_resources")).toBeInTheDocument();
    expect(screen.queryByText("No Bronze datasets registered")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Inspect contract and diagnostics for bronze_resources/ })).not.toBeInTheDocument();
  });

  it.each([
    ["unknown", "metric-default"],
    ["disabled", "metric-default"],
    ["stale", "metric-warning"],
    ["degraded", "metric-warning"],
    ["failed", "metric-critical"],
  ])("renders %s readiness without a healthy fallback", async (status, tone) => {
    fabricCapabilities.mockResolvedValue(envelope({
      ...capabilitySnapshot,
      semantic_readiness: { status, reason: "no_recorded_semantic_model_deployment_result" },
      data_agent_readiness: { status, configured: status !== "disabled", reason: "reachability_not_verified" },
      maintenance: { status: "failed" },
    }));
    renderPage();
    const semantic = await screen.findByLabelText("Semantic model value");
    await waitFor(() => expect(semantic).toHaveTextContent(status.charAt(0).toUpperCase() + status.slice(1)));
    expect(semantic.closest("article")).toHaveClass(tone);
    expect(screen.getByLabelText("Data Agent grounding value").closest("article")).toHaveClass(tone);
    expect(screen.getByText(/configuration alone does not prove evaluation or query success/)).toBeInTheDocument();
    expect(screen.getByText(/maintenance: Failed/)).toBeInTheDocument();
    expect(screen.queryByText(/definition validated/)).not.toBeInTheDocument();
    await waitFor(() => expect(buildFabricMedallionCopilotContext.mock.calls.at(-1)?.[0]).toMatchObject({
      semanticReadiness: { status, reason: "no_recorded_semantic_model_deployment_result" },
      dataAgentReadiness: { status, configured: status !== "disabled" },
    }));
  });

  it("paginates all returned ingestion attempts without hiding failure totals", async () => {
    fabricIngestionHistory.mockResolvedValue(envelope({
      runs: Array.from({ length: 25 }, (_, index) => ({
        source: "publication",
        projection_name: `attempt-${index + 1}`,
        attempted_at: "2026-01-01T00:00:00Z",
        status: index === 24 ? "failed" : "succeeded",
        retry_eligible: index === 24,
      })),
    }));
    renderPage();
    const history = await screen.findByRole("region", { name: "Ingestion history / failed runs" });
    await waitFor(() => expect(within(history).getByText(/25 returned attempts; 1 failed/)).toBeInTheDocument());
    const attempts = within(history.querySelector(".compliance-list")!);
    expect(attempts.getByText("attempt-20")).toBeInTheDocument();
    expect(attempts.queryByText("attempt-25")).not.toBeInTheDocument();
    fireEvent.click(within(history).getByRole("button", { name: "Next page" }));
    expect(attempts.getByText("attempt-25")).toBeInTheDocument();
    expect(within(history).getByText("Retry via subscription sync")).toBeInTheDocument();
    expect(attempts.queryByText("attempt-1")).not.toBeInTheDocument();
    fireEvent.click(within(history).getByRole("button", { name: "Previous page" }));
    expect(attempts.getByText("attempt-1")).toBeInTheDocument();
  });

  it("does not infer semantic validation from a blocked deployment or an empty history", async () => {
    fabricCapabilities.mockResolvedValue(envelope({
      ...capabilitySnapshot,
      semantic_readiness: { status: "deployment-blocked", reason: "capacity_paused" },
    }));
    renderPage();
    expect(await screen.findByText("Semantic model deployment blocked — capacity_paused")).toBeInTheDocument();
    expect(await screen.findByText("No ingestion attempts reported")).toBeInTheDocument();
    expect(screen.queryByText(/All ingestion runs succeeded|definition validated/)).not.toBeInTheDocument();
  });

  it("renders separately unrecorded readiness stages without promoting configuration to proof", async () => {
    const stage = (reason_code: string) => ({
      status: "unknown", evidence_mode: "not_recorded", reason_code, last_attempt: null, last_good: null,
    });
    fabricCapabilities.mockResolvedValue(envelope({
      ...capabilitySnapshot,
      readiness_evidence: {
        projection_publication: stage("no_scoped_publication_recorder"),
        native_ontology: stage("no_recorded_native_ontology_receipt"),
        semantic_model: {
          definition_validation: stage("no_recorded_semantic_definition_validation"),
          publication: stage("no_recorded_semantic_model_publication"),
          query_qualification: stage("no_recorded_semantic_query_qualification"),
        },
      },
    }));
    renderPage();
    const region = await screen.findByRole("region", { name: "Independent Fabric readiness evidence" });
    await waitFor(() => expect(within(region).getByText("Unknown · Not recorded · no_recorded_semantic_query_qualification")).toBeInTheDocument());
    expect(within(region).getByText("Unknown · Not recorded · no_recorded_native_ontology_receipt")).toBeInTheDocument();
    expect(within(region).getAllByText(/Unknown · Not recorded/)).toHaveLength(5);
    expect(within(region).queryByText(/Succeeded|Ready|Available/)).not.toBeInTheDocument();
  });

  it("keeps legacy capability responses explicitly without independent stage evidence", async () => {
    renderPage();
    expect(await screen.findByText("Readiness stage evidence unavailable")).toBeInTheDocument();
    fireEvent.click(await screen.findByText("Inspect recorded source evidence for bronze_resources"));
    expect(screen.getByText("Recorded source evidence unavailable")).toBeVisible();
  });

  it("preserves standalone tab embedding and its independent scoped reads", async () => {
    render(<FabricMedallionPanel refreshKey={0} scope={{ environment: ["prod"] }} subscriptionId="sub-a" />);
    await screen.findByText("bronze_resources");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "fabric-medallion-tab");
    for (const read of [fabricLayers, fabricManifest, fabricGovernance, fabricIngestionHistory, fabricCapabilities]) {
      expect(read).toHaveBeenCalledTimes(1);
      expect(read).toHaveBeenCalledWith({ environment: ["prod"], subscription: ["sub-a"] });
    }
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

    describe("Fabric evidence freshness", () => {
      it("keeps missing and unknown evidence unknown, even with a timestamp", () => {
        expect(fabricEvidenceFreshness(null)).toBe("unknown");
        expect(fabricEvidenceFreshness({ evidence: [] })).toBe("unknown");
        expect(fabricEvidenceFreshness(envelope({}, "test", "unknown"))).toBe("unknown");
      });

      it("does not let a fresh item hide stale, aging or unknown evidence", () => {
        const fresh = envelope({}).evidence;
        expect(fabricEvidenceFreshness({ evidence: [...fresh, ...envelope({}, "test", "stale").evidence] })).toBe("stale");
        expect(fabricEvidenceFreshness({ evidence: [...fresh, ...envelope({}, "test", "aging").evidence] })).toBe("aging");
        expect(fabricEvidenceFreshness({ evidence: [...fresh, ...envelope({}, "test", "unknown").evidence] })).toBe("unknown");
        expect(fabricEvidenceFreshness({ evidence: fresh })).toBe("fresh");
      });
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
