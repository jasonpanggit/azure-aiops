import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const {
  fabricCapabilities,
  fabricDataset,
  fabricGovernance,
  fabricIngestionHistory,
  fabricLayers,
  fabricManifest,
  list,
  replace,
  searchParams,
} = vi.hoisted(() => ({
  fabricCapabilities: vi.fn(),
  fabricDataset: vi.fn(),
  fabricGovernance: vi.fn(),
  fabricIngestionHistory: vi.fn(),
  fabricLayers: vi.fn(),
  fabricManifest: vi.fn(),
  list: vi.fn(),
  replace: vi.fn(),
  searchParams: { current: new URLSearchParams() },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => searchParams.current,
}));

vi.mock("@/lib/services", () => ({
  buildCopilotSnapshot: (input: unknown) => input,
  connectionsApi: { list },
  fabricMedallionApi: {
    layers: fabricLayers,
    dataset: fabricDataset,
    manifest: fabricManifest,
    governance: fabricGovernance,
    ingestionHistory: fabricIngestionHistory,
    capabilities: fabricCapabilities,
  },
}));

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

function envelope<T>(data: T) {
  return {
    data,
    evidence: [{ source_engine: "fabric.medallion_health", source_table: "metadata_source_status", timestamp: "2026-01-01T00:00:00Z", confidence: "high" }],
    scope: {},
    knowledge_version: "fabric-test",
  };
}

function renderPage() {
  return render(
    <ScopeProvider>
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
    fabricManifest.mockResolvedValue(envelope({ entries: [] }));
    fabricGovernance.mockResolvedValue(envelope({ ownership_gap_count: 0, tag_gap_count: 0, referential_integrity_blockers: 0, gaps: [] }));
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
});
