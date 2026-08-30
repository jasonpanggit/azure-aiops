import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { create, getConnection, health, list, mapMetadata, updateConnection } = vi.hoisted(() => ({
  create: vi.fn(),
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
}));

import ConnectionsPage from "./page";

function renderConnectionsPage() {
  return render(
    <ScopeProvider>
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
    list.mockResolvedValue(emptyEnvelope);
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
