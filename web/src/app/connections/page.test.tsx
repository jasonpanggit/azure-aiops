import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const {
  create,
  fabricCapabilities,
  fabricDataset,
  fabricGovernance,
  fabricIngestionHistory,
  fabricLayers,
  fabricManifest,
  getConnection,
  health,
  list,
  mapMetadata,
  updateConnection,
} = vi.hoisted(() => ({
  create: vi.fn(),
  fabricCapabilities: vi.fn(),
  fabricDataset: vi.fn(),
  fabricGovernance: vi.fn(),
  fabricIngestionHistory: vi.fn(),
  fabricLayers: vi.fn(),
  fabricManifest: vi.fn(),
  getConnection: vi.fn(),
  health: vi.fn(),
  list: vi.fn(),
  mapMetadata: vi.fn(),
  updateConnection: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  connectionsApi: {
    create,
    get: getConnection,
    health,
    list,
    mapMetadata,
    update: updateConnection,
    validate: vi.fn(),
  },
  fabricMedallionApi: {
    layers: fabricLayers,
    dataset: fabricDataset,
    manifest: fabricManifest,
    governance: fabricGovernance,
    ingestionHistory: fabricIngestionHistory,
    capabilities: fabricCapabilities,
  },
}));

import ConnectionsPage from "./page";

function renderConnectionsPage() {
  return render(
    <ScopeProvider>
      <ConnectionsPage />
    </ScopeProvider>
  );
}

function renderConnectionsPageWithScope(subscriptionId: string) {
  return render(
    <ScopeProvider initialScope={{ subscription: [subscriptionId] }}>
      <ConnectionsPage />
    </ScopeProvider>
  );
}

const emptyEnvelope = {
  data: [],
  evidence: [],
  scope: {},
  pagination: { offset: 0, limit: 100, total: 0, next_offset: null },
};

const connection = {
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
};

describe("Connections page onboarding", () => {
  beforeEach(() => {
    create.mockReset();
    getConnection.mockReset();
    health.mockReset();
    list.mockReset();
    mapMetadata.mockReset();
    updateConnection.mockReset();
    fabricLayers.mockReset();
    fabricCapabilities.mockReset();
    fabricManifest.mockReset();
    fabricGovernance.mockReset();
    fabricIngestionHistory.mockReset();
    fabricDataset.mockReset();
    list.mockResolvedValue(emptyEnvelope);
    mockFabricHealth();
  });

  it("opens onboarding automatically for a first subscription", async () => {
    renderConnectionsPage();

    expect(await screen.findByRole("heading", { name: "Onboard an Azure subscription" })).toBeInTheDocument();
    expect(screen.getByLabelText("Client secret *")).toHaveAttribute("type", "password");
    expect(screen.getByText("Complete the onboarding form above to establish operational coverage.")).toBeInTheDocument();
  });

  it("submits a client secret for server-side Key Vault storage", async () => {
    create.mockResolvedValue({
      ...emptyEnvelope,
      data: {
        ...connection,
        validation: {
          status: "failed",
          passed: false,
          failed_required: ["spn_authentication"],
          health: { details: "credential resolution failed" },
        },
        initial_sync: {
          connection_id: "prod",
          status: "not_started",
          reason: "validation_failed",
          sync_state: { status: "pending" },
        },
      },
    });

    renderConnectionsPage();
    await screen.findByRole("heading", { name: "Onboard an Azure subscription" });

    fireEvent.change(screen.getByLabelText("Connection ID *"), { target: { value: "PROD" } });
    fireEvent.change(screen.getByLabelText("Display name *"), { target: { value: "Production" } });
    fireEvent.change(screen.getByLabelText("Subscription ID *"), { target: { value: connection.subscription_id } });
    fireEvent.change(screen.getByLabelText("Tenant ID *"), { target: { value: connection.tenant_id } });
    fireEvent.change(screen.getByLabelText("Service principal client ID *"), {
      target: { value: "00000000-0000-0000-0000-000000000003" },
    });
    fireEvent.change(screen.getByLabelText("Client secret *"), { target: { value: "secret-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Add subscription" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          connection_id: "prod",
          credential: expect.objectContaining({
            client_secret: "secret-value",
          }),
        })
      )
    );
    expect(create.mock.calls[0][0].credential.secret_ref).toBeUndefined();
    expect(await screen.findByText(/Validation failed: credential resolution failed/)).toBeInTheDocument();
  });

  it("opens onboarding from the page header action", async () => {
    list.mockResolvedValueOnce({
      ...emptyEnvelope,
      data: [connection],
    });

    renderConnectionsPage();

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Onboard an Azure subscription" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Onboard subscription" }));

    expect(screen.getByRole("heading", { name: "Onboard an Azure subscription" })).toBeInTheDocument();
  });

  it("edits the connection name and business metadata", async () => {
    list.mockResolvedValue({ ...emptyEnvelope, data: [connection] });
    getConnection.mockResolvedValue({
      ...emptyEnvelope,
      data: {
        ...connection,
        business_metadata: {
          business_service: "Payments",
          application: "Checkout",
          environment: "prod",
          project_owner: "Platform",
          support_team: "SRE",
          criticality: "critical",
          region: "eastus",
          cost_center: "CC-100",
        },
      },
    });
    updateConnection.mockResolvedValue({ ...emptyEnvelope, data: connection });
    mapMetadata.mockResolvedValue({ ...emptyEnvelope, data: connection });

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(await screen.findByRole("heading", { name: "Edit subscription connection" })).toBeInTheDocument();
    expect(screen.getAllByText(connection.subscription_id)).toHaveLength(2);
    await waitFor(() => expect(screen.getByLabelText("Connection name *")).toHaveValue("Production"));

    fireEvent.change(screen.getByLabelText("Connection name *"), { target: { value: "Production East" } });
    fireEvent.change(screen.getByLabelText("Project owner"), { target: { value: "Payments Platform" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(updateConnection).toHaveBeenCalledWith("prod", { name: "Production East" });
      expect(mapMetadata).toHaveBeenCalledWith("prod", {
        business_service: "Payments",
        application: "Checkout",
        environment: "prod",
        project_owner: "Payments Platform",
        support_team: "SRE",
        criticality: "critical",
        region: "eastus",
        cost_center: "CC-100",
      });
    });
    expect(await screen.findByText("Subscription connection Production East was updated.")).toBeInTheDocument();
  });

  it("automatically polls the initial sync and reports backend failures", async () => {
    create.mockResolvedValue({
      ...emptyEnvelope,
      data: {
        ...connection,
        validation: { status: "healthy", passed: true, failed_required: [], health: {} },
        initial_sync: {
          connection_id: "prod",
          status: "running",
          sync_state: { status: "running", stage: "queued", progress_pct: 0 },
        },
      },
    });
    health.mockResolvedValue({
      ...emptyEnvelope,
      data: {
        connections: [{
          connection_id: "prod",
          sync: { status: "failed", message: "Credential could not be resolved", stage_message: "Credential could not be resolved" },
        }],
      },
    });

    renderConnectionsPage();
    await screen.findByRole("heading", { name: "Onboard an Azure subscription" });
    fireEvent.change(screen.getByLabelText("Connection ID *"), { target: { value: "PROD" } });
    fireEvent.change(screen.getByLabelText("Display name *"), { target: { value: "Production" } });
    fireEvent.change(screen.getByLabelText("Subscription ID *"), { target: { value: connection.subscription_id } });
    fireEvent.change(screen.getByLabelText("Tenant ID *"), { target: { value: connection.tenant_id } });
    fireEvent.change(screen.getByLabelText("Service principal client ID *"), { target: { value: connection.tenant_id } });
    fireEvent.change(screen.getByLabelText("Client secret *"), { target: { value: "secret-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Add subscription" }));

    await waitFor(() => expect(health).toHaveBeenCalledWith("prod"));
    expect(await screen.findByText("Credential could not be resolved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Validate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
  });

  it("automatically polls health until the initial sync succeeds", async () => {
    list.mockResolvedValue(emptyEnvelope);
    create.mockResolvedValue({
      ...emptyEnvelope,
      data: {
        ...connection,
        validation: { status: "healthy", passed: true, failed_required: [], health: {} },
        initial_sync: {
          connection_id: "prod",
          status: "running",
          sync_state: { status: "running", stage: "queued", progress_pct: 0 },
        },
      },
    });
    health.mockResolvedValue({
        ...emptyEnvelope,
        data: {
          connections: [
            {
              connection_id: "prod",
              sync: { status: "succeeded", stage: "succeeded", progress_pct: 100 },
            },
          ],
        },
      });

    renderConnectionsPage();
    await screen.findByRole("heading", { name: "Onboard an Azure subscription" });
    fireEvent.change(screen.getByLabelText("Connection ID *"), { target: { value: "PROD" } });
    fireEvent.change(screen.getByLabelText("Display name *"), { target: { value: "Production" } });
    fireEvent.change(screen.getByLabelText("Subscription ID *"), { target: { value: connection.subscription_id } });
    fireEvent.change(screen.getByLabelText("Tenant ID *"), { target: { value: connection.tenant_id } });
    fireEvent.change(screen.getByLabelText("Service principal client ID *"), { target: { value: connection.tenant_id } });
    fireEvent.change(screen.getByLabelText("Client secret *"), { target: { value: "secret-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Add subscription" }));

    expect(await screen.findByText("Subscription connection validated and initial sync completed.")).toBeInTheDocument();
    expect(health).toHaveBeenCalledWith("prod");
    expect(screen.queryByRole("button", { name: "Validate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync" })).not.toBeInTheDocument();
  });
});


type Envelope<T> = {
  data: T;
  evidence: Array<{ source_engine: string; source_table: string; timestamp: string; confidence: string }>;
  scope: Record<string, string[]>;
  knowledge_version: string;
  warnings: string[];
};

function envelope<T>(data: T): Envelope<T> {
  return {
    data,
    evidence: [{ source_engine: "fabric.medallion_health", source_table: "metadata_source_status", timestamp: "2026-01-01T00:00:00Z", confidence: "high" }],
    scope: {},
    knowledge_version: "fabric-test",
    warnings: [],
  };
}

function dataset(tableName: string, availability: string, rowCount: number) {
  return {
    table_name: tableName,
    availability,
    freshness: availability === "unavailable" ? "unknown" : "fresh",
    quality: availability === "unavailable" ? "unknown" : "complete",
    row_count: rowCount,
    stale_after_seconds: 3600,
    observed_at: "2026-01-01T00:00:00Z",
    ingested_at: "2026-01-01T00:00:00Z",
    watermark: "2026-01-01T00:00:00Z",
    error: availability === "unavailable" ? "capacity paused" : "",
    lineage_ref: `lineage://${tableName}`,
  };
}

function capabilitiesFor(tableNames: string[]) {
  return envelope({
    capacity: { status: "healthy", capacity_name: "cap-aiops" },
    data_access_roles: { status: "available", total_roles: 2, roles: [] },
    maintenance: { status: "healthy", last_run_at: "2026-01-01T00:00:00Z", activity_name: "vacuum" },
    semantic_readiness: { status: "deployment-blocked", reason: "preview deployment requires manual promotion" },
    data_agent_readiness: { status: "available", configured: true },
    lineage: {
      native_lineage_url: "https://fabric.microsoft.com/workspace/workspace-abc",
      datasets: tableNames.map((table_name) => ({ table_name, status: "healthy", lineage_ref: `lineage://${table_name}`, lineage: {} })),
    },
  });
}

function mockFabricHealth(tableNames: string[] = ["bronze_resources", "silver_incidents", "gold_operational_context"]) {
  fabricLayers.mockResolvedValue(envelope({
    layers: {
      bronze: { healthy: 1, total: 1 },
      silver: { healthy: 1, total: 1 },
      gold: { healthy: 1, total: 1 },
    },
  }));
  fabricCapabilities.mockResolvedValue(capabilitiesFor(tableNames));
  fabricManifest.mockResolvedValue(envelope({ entries: [] }));
  fabricGovernance.mockResolvedValue(envelope({ ownership_gap_count: 0, tag_gap_count: 0, referential_integrity_blockers: 0, gaps: [] }));
  fabricIngestionHistory.mockResolvedValue(envelope({ runs: [] }));
  fabricDataset.mockImplementation((tableName: string) => Promise.resolve(envelope(dataset(tableName, "healthy", 12))));
}

describe("Connections page Fabric medallion tab", () => {
  beforeEach(() => {
    create.mockReset();
    getConnection.mockReset();
    health.mockReset();
    list.mockReset();
    mapMetadata.mockReset();
    updateConnection.mockReset();
    fabricLayers.mockReset();
    fabricCapabilities.mockReset();
    fabricManifest.mockReset();
    fabricGovernance.mockReset();
    fabricIngestionHistory.mockReset();
    fabricDataset.mockReset();
    list.mockResolvedValue({ ...emptyEnvelope, data: [connection] });
    mockFabricHealth();
  });

  it("switches between Subscriptions and Fabric medallion panels without rewriting subscription content", async () => {
    renderConnectionsPage();

    expect(await screen.findByText("Production")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Subscriptions" })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("tab", { name: "Fabric medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    expect(fabricPanel).toHaveAttribute("id", "fabric-medallion-panel");
    expect(within(fabricPanel).getByText("Bronze tables")).toBeInTheDocument();
    expect(within(fabricPanel).getByRole("heading", { name: /Bronze layer/i })).toBeInTheDocument();
    const subscriptionSelect = screen.getByDisplayValue(/Production/);
    expect(subscriptionSelect).toBeInTheDocument();
    expect(document.querySelector("#subscriptions-panel")).toHaveAttribute("hidden");

    fireEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));

    expect(screen.getByText("Production")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel", { name: "Subscriptions" })).not.toHaveAttribute("hidden");
  });

  it("passes subscription scope to every Fabric medallion API call", async () => {
    renderConnectionsPageWithScope(connection.subscription_id);
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    expect(within(fabricPanel).getByText("Bronze tables")).toBeInTheDocument();
    await waitFor(() => {
      expect(fabricLayers).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricManifest).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricGovernance).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricIngestionHistory).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricCapabilities).toHaveBeenCalledWith({ subscription: [connection.subscription_id] });
      expect(fabricDataset).toHaveBeenCalledWith("bronze_resources", { subscription: [connection.subscription_id] });
    });
  });

  it("isolates Bronze and Silver dataset failures while Gold data and summary metrics stay populated", async () => {
    mockFabricHealth(["bronze_resources", "silver_incidents", "gold_operational_context"]);
    fabricLayers.mockResolvedValue(envelope({
      layers: {
        bronze: { healthy: 0, total: 1 },
        silver: { healthy: 0, total: 1 },
        gold: { healthy: 1, total: 1 },
      },
    }));
    fabricDataset.mockImplementation((tableName: string) => {
      if (tableName.startsWith("gold_")) return Promise.resolve(envelope(dataset(tableName, "healthy", 140)));
      return Promise.reject(new Error(`${tableName} unavailable`));
    });

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    expect(await screen.findByText("Bronze layer health is unavailable")).toBeInTheDocument();
    expect(screen.getByText("Silver layer health is unavailable")).toBeInTheDocument();
    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    expect(within(fabricPanel).getAllByText("gold_operational_context").length).toBeGreaterThan(0);
    expect(screen.getByText("Gold tables")).toBeInTheDocument();
    expect(within(fabricPanel).getAllByText("1/1").length).toBeGreaterThan(0);
  });

  it("distinguishes healthy-empty zero rows from unavailable datasets", async () => {
    mockFabricHealth(["bronze_empty", "gold_unavailable"]);
    fabricDataset.mockImplementation((tableName: string) => {
      if (tableName === "bronze_empty") return Promise.resolve(envelope(dataset(tableName, "healthy-empty", 0)));
      return Promise.resolve(envelope(dataset(tableName, "unavailable", 0)));
    });

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    const healthyEmptyBadge = (await within(fabricPanel).findAllByText("Healthy · Empty"))[0];
    expect(healthyEmptyBadge).toHaveClass("status-success");
    expect((await within(fabricPanel).findAllByText(/0 rows \(expected\)/)).length).toBeGreaterThan(0);
    const unavailableBadge = within(fabricPanel).getAllByText("Unavailable")[0];
    expect(unavailableBadge).toHaveClass("status-critical");
    expect(unavailableBadge).not.toHaveTextContent("Healthy · Empty");
  });

  it("shows retry guidance only for failed ingestion rows and never renders inert retry buttons", async () => {
    fabricIngestionHistory.mockResolvedValue(envelope({
      runs: [
        { projection_name: "gold_operational_context", status: "failed", attempted_at: "2026-01-01T00:00:00Z", attempts: 3, retry_eligible: true, message: "warehouse timeout", source: "source-status" },
        { projection_name: "silver_incidents", status: "unavailable", attempted_at: "2026-01-01T00:00:00Z", attempts: 1, retry_eligible: false, message: "capacity paused", source: "source-status" },
      ],
    }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    expect(await screen.findByText("Ingestion failed — 3 of 3 attempts exhausted · last error: warehouse timeout")).toBeInTheDocument();
    expect(screen.getByText("Source unavailable — Fabric capacity or workspace could not be reached")).toBeInTheDocument();
    expect(screen.getByText("Retry via subscription sync")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry ingestion/i })).not.toBeInTheDocument();
  });

  it("links each subscription row to its own Fabric medallion page", async () => {
    renderConnectionsPage();

    expect(await screen.findByText("Production")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Fabric medallion" }));
    const subscriptionSelect = await screen.findByDisplayValue(
      new RegExp(`${connection.name}.*${connection.subscription_id}`)
    );
    expect(subscriptionSelect).toBeInTheDocument();
    expect(subscriptionSelect).toHaveAttribute("name", "subscriptionId");
  });

  it("explains an unpublished watermark instead of labelling it unknown", async () => {
    mockFabricHealth(["bronze_resources"]);
    fabricDataset.mockResolvedValue(envelope({ ...dataset("bronze_resources", "healthy", 4), watermark: "" }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    expect(await within(fabricPanel).findByText("Not yet published")).toBeInTheDocument();
    expect(within(fabricPanel).queryByText("watermark unknown")).not.toBeInTheDocument();
    expect(within(fabricPanel).getAllByText(/Watermark/).length).toBeGreaterThan(0);
  });

  it("renders a populated watermark as a caught-up checkpoint", async () => {
    mockFabricHealth(["bronze_resources"]);
    fabricDataset.mockResolvedValue(envelope(dataset("bronze_resources", "healthy", 4)));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    expect(await within(fabricPanel).findByText(/Caught up to/)).toBeInTheDocument();
  });

  it("groups lifecycle contracts by disposition with blockers listed first", async () => {
    fabricManifest.mockResolvedValue(envelope({
      entries: [
        { projection_name: "gold_active_one", disposition: "active", compatibility_version: "1.0.0", updated_at: "2026-01-01T00:00:00Z" },
        { projection_name: "gold_blocked_one", disposition: "deployment-blocked", compatibility_version: "1.0.0", updated_at: "2026-01-01T00:00:00Z", retired_reason: "semantic model not deployed" },
      ],
    }));

    renderConnectionsPage();
    fireEvent.click(await screen.findByRole("tab", { name: "Fabric medallion" }));

    const fabricPanel = await screen.findByRole("tabpanel", { name: "Fabric medallion" });
    expect(await within(fabricPanel).findByText("gold_blocked_one")).toBeInTheDocument();
    expect(within(fabricPanel).getByText("gold_active_one")).toBeInTheDocument();
    expect(within(fabricPanel).getByText(/semantic model not deployed/)).toBeInTheDocument();

    const names = within(fabricPanel)
      .getAllByText(/^gold_(blocked|active)_one$/)
      .map((node) => node.textContent);
    expect(names.indexOf("gold_blocked_one")).toBeLessThan(names.indexOf("gold_active_one"));
  });
});
