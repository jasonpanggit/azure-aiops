import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import { ApiError } from "@/lib/types";

const { os, osGroup, software, softwareGroup, paas, paasGroup, resources, narrative, lifecycleReview, confirmLifecycle, mappings, approveMapping, rejectMapping } = vi.hoisted(() => ({
  os: vi.fn(),
  osGroup: vi.fn(),
  software: vi.fn(),
  softwareGroup: vi.fn(),
  paas: vi.fn(),
  paasGroup: vi.fn(),
  resources: vi.fn(),
  narrative: vi.fn(),
  lifecycleReview: vi.fn(),
  confirmLifecycle: vi.fn(),
  mappings: vi.fn(),
  approveMapping: vi.fn(),
  rejectMapping: vi.fn(),
}));

vi.mock("@/lib/services", () => ({ inventoryApi: { os, osGroup, software, softwareGroup, paas, paasGroup, resources, narrative, lifecycleReview, confirmLifecycle, mappings, approveMapping, rejectMapping } }));

const { downloadCsv } = vi.hoisted(() => ({ downloadCsv: vi.fn() }));
vi.mock("@/lib/csv", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/csv")>()),
  downloadCsv,
}));

const { investigateCanonical } = vi.hoisted(() => ({ investigateCanonical: vi.fn() }));
vi.mock("@/lib/copilot/page-adapters", async () => {
  const actual = await vi.importActual<typeof import("@/lib/copilot/page-adapters")>("@/lib/copilot/page-adapters");
  return { ...actual, investigateCanonical };
});

import InventoryPage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [{ source_engine: "InventoryService", source_table: "inventory/os_observations", timestamp: "2026-08-25T10:00:00Z", confidence: "high", freshness: "fresh" }],
  scope: {},
  warnings: [],
});

const collection = {
  groups: [{
    key: "Windows Server|2019",
    os_name: "Windows Server",
    os_version: "2019",
    machine_count: 2,
    source_types: ["arc", "azure_vm"],
    lifecycle_status: "Supported",
    support_end: "2030-01-01",
    days_remaining: 1000,
    review_required: false,
  }, {
    key: "Windows Server|2099-preview",
    os_name: "Windows Server",
    os_version: "2099-preview",
    machine_count: 1,
    source_types: ["azure_vm"],
    lifecycle_status: "Unknown",
    support_end: null,
    days_remaining: null,
    review_required: true,
  }],
  source_status: {
    azure_vm: { source_type: "azure_vm", state: "ready", observed_at: "", query_version: "v1", row_count: 3, error: "" },
    arc: { source_type: "arc", state: "partial", observed_at: "", query_version: "v1", row_count: 2, error: "timeout" },
  },
  observed_at: "2026-08-25T10:00:00Z",
  query_version: "v1",
  generation_id: "generation-1",
  requested_scope: {},
};

describe("Inventory OS tracer", () => {
  beforeEach(() => {
    investigateCanonical.mockResolvedValue({
      data: {
        contract_version: "1",
        status: "partial",
        policy_status: "fallback",
        fallback_reason: "planner_unavailable",
        selected_specialists: ["inventory_data_health"],
        selected_tools: ["inventory_resources"],
        tool_results: [],
        uncertainty: ["visible subset is incomplete"],
        coverage: { visible_count: 2, total_count: 120, complete: false },
        citations: [],
        thread_id: "thr-0123456789abcdef0123456789abcdef",
        thread_revision: 1,
        mutation_authorized: false,
      },
      evidence: [],
      warnings: [],
    });
    downloadCsv.mockClear();
    os.mockResolvedValue(envelope(collection));
    resources.mockResolvedValue({
      ...envelope({ resources: [], family_availability: {}, requested_scope: {}, query_version: "inventory-resources-v1" }),
      pagination: { offset: 0, limit: 500, total: 0, next_offset: null },
    });
    paas.mockResolvedValue(envelope({
      groups: [{
        key: "microsoft.app:containerapps|Unknown|Unknown",
        resource_type: "microsoft.app/containerapps",
        sku: "",
        tier: "",
        resource_count: 5,
      }],
      source_status: {},
      observed_at: "2026-08-25T10:00:00Z",
      query_version: "inventory-resources-v1",
      generation_id: "gen-1",
      requested_scope: {},
    }));
    paasGroup.mockResolvedValue(envelope({
      group: {
        key: "microsoft.app:containerapps|Unknown|Unknown",
        resource_type: "microsoft.app/containerapps",
        sku: "",
        tier: "",
        resource_count: 5,
      },
      resources: [{
        resource_id: "/subscriptions/sub-1/resourceGroups/rg-1/providers/Microsoft.App/containerApps/app-1",
        resource_name: "app-1",
        resource_type: "microsoft.app/containerapps",
        family: "paas",
        tenant_id: "tenant-1",
        subscription_id: "sub-1",
        resource_group: "rg-1",
        location: "australiaeast",
        sku: "",
        tier: "",
        runtime: "",
        provisioning_state: "Succeeded",
        os_name: "",
        os_version: "",
        observed_at: "2026-08-25T10:00:00Z",
        query_version: "inventory-resources-v1",
        tags: {},
      }],
      source_status: {},
      observed_at: "2026-08-25T10:00:00Z",
      query_version: "inventory-resources-v1",
      generation_id: "gen-1",
      requested_scope: {},
    }));
    osGroup.mockResolvedValue(envelope({
      group: collection.groups[0],
      machines: [{
        resource_id: "vm-1",
        machine_name: "web-01",
        source_type: "azure_vm",
        os_name: "Windows Server",
        os_version: "2019",
        subscription_id: "sub-a",
        resource_group: "rg-prod",
        environment: "prod",
        observed_at: "2026-08-25T10:00:00Z",
        evidence: [],
        source_status: "ready",
        lifecycle_status: "Supported",
        support_end: "2030-01-01",
        days_remaining: 1000,
        review_required: false,
      }],
    }));
    software.mockResolvedValue(envelope({
      groups: [{
        key: "7-Zip|19.00",
        software_name: "7-Zip",
        software_version: "19.00",
        install_count: 1,
        source_types: ["azure_vm"],
        linked_count: 1,
        unlinked_count: 0,
        publishers: ["Igor Pavlov"],
      }],
      source_status: {
        logs: { source_type: "logs", state: "ready", observed_at: "", query_version: "v1", row_count: 1, error: "" },
      },
      observed_at: "2026-08-25T10:00:00Z",
      query_version: "v1",
      generation_id: "generation-1",
      requested_scope: {},
    }));
    narrative.mockResolvedValue(envelope({
      fact_summary: "3 machines across 2 OS groups. EOL risk: 0 expired, 0 expiring within 90 days, 3 supported, 0 needs review.",
      fact_items: [
        { label: "Machines", value: "3" },
        { label: "EOL risk", value: "0 expired, 0 expiring within 90 days, 3 supported, 0 needs review" },
      ],
      narrated_summary: null,
      narrated_by: "",
      model: "",
      confidence: "medium",
      citations: [{
        source_engine: "InventoryService",
        source_table: "inventory/os_observations",
        timestamp: "2026-08-25T10:00:00Z",
        reference: "",
      }],
      source_status: collection.source_status,
      requested_scope: { dimensions: ["subscription"] },
      status: "fact_only",
    }));
    softwareGroup.mockResolvedValue(envelope({
      group: {
        key: "7-Zip|19.00",
        software_name: "7-Zip",
        software_version: "19.00",
        install_count: 1,
        source_types: ["azure_vm"],
        linked_count: 1,
        unlinked_count: 0,
        publishers: ["Igor Pavlov"],
      },
      machines: [{
        software_name: "7-Zip",
        software_version: "19.00",
        canonical_name: "7-Zip",
        canonical_version: "19.00",
        canonical_identity: "7-Zip|19.00",
        raw_software_name: "7-Zip v19.00",
        raw_software_version: "v19.00",
        raw_identity: { name: "7-Zip v19.00", version: "v19.00" },
        resource_id: "vm-1",
        machine_name: "web-01",
        computer: "web-01",
        source_computer_id: "agent-web-01",
        source_type: "azure_vm",
        join_status: "linked",
        resource_join_status: "linked",
        subscription_id: "sub-a",
        resource_group: "rg-prod",
        environment: "prod",
        publisher: "Igor Pavlov",
        software_type: "Package",
        observed_at: "2026-08-25T10:00:00Z",
        time_generated: "2026-08-25T10:00:00Z",
        evidence: [],
      }],
      source_status: {
        logs: { source_type: "logs", state: "ready", observed_at: "", query_version: "v1", row_count: 1, error: "" },
      },
      observed_at: "2026-08-25T10:00:00Z",
      query_version: "v1",
      generation_id: "generation-1",
      requested_scope: {},
    }));
    mappings.mockResolvedValue(envelope({
      mappings: [{
        mapping_id: "software-map://review-1",
        raw_name: "Widget Suite",
        raw_version: "v1.0",
        publisher: "Acme",
        raw_identity: { name: "Widget Suite", version: "v1.0", publisher: "Acme" },
        canonical_name: "Widget",
        canonical_version: "1.0",
        canonical_identity: "Widget|1.0",
        method: "ai",
        confidence: 0.91,
        status: "suggested",
        provenance: { model: "approved-normalizer" },
        source_timestamp: "2026-08-26T00:00:00Z",
        scope_predicate: { subscription: ["sub-a"] },
        revision: 0,
        reason: "",
        created_at: "2026-08-26T00:00:00Z",
        updated_at: "2026-08-26T00:00:00Z",
      }],
      repository_revision: 1,
      requested_scope: {},
    }));
    approveMapping.mockResolvedValue(envelope({
      ...({ mapping_id: "software-map://review-1", status: "approved", revision: 1 } as object),
    }));
    rejectMapping.mockResolvedValue(envelope({
      ...({ mapping_id: "software-map://review-1", status: "rejected", revision: 1 } as object),
    }));
    lifecycleReview.mockResolvedValue(envelope({
      normalized_os_key: "windows server|2099-preview",
      os_name: "Windows Server",
      os_version: "2099-preview",
      status: "review_required",
      catalog_revision: 0,
      classification: {
        status: "Unknown",
        support_end: null,
        days_remaining: null,
        support_channel: "mainstream",
        confidence: 0,
        evidence: ["No authoritative lifecycle entry matches Windows Server 2099-preview."],
      },
      candidates: [{
        candidate_id: "eol-candidate-1",
        date: "2030-01-01",
        source_kind: "official_vendor",
        citation: "https://learn.microsoft.com/en-us/lifecycle/products/windows-server-2099-preview",
        retrieved_at: "2026-08-26T00:00:00Z",
        extracted_claim: "Official vendor claim",
        confidence: 0.8,
        support_channel: "mainstream",
      }],
      provenance: null,
    }));
    confirmLifecycle.mockResolvedValue(envelope({
      normalized_os_key: "windows server|2099-preview",
      os_name: "Windows Server",
      os_version: "2099-preview",
      status: "confirmed",
      catalog_revision: 1,
      classification: {
        status: "Supported",
        support_end: "2030-01-01",
        days_remaining: 1000,
        support_channel: "mainstream",
        confidence: 1,
        evidence: ["confirmed"],
      },
      candidates: [],
      provenance: { reviewer: "operator@example.com" },
    }));
  });

  it("renders grouped OS rows, status warnings, review state, and scoped drill-down", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect((await screen.findAllByText("Windows Server")).length).toBe(3);
    expect(screen.getByText("EOL date needs review")).toBeInTheDocument();
    expect(screen.getByText(/Arc source is partial/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /View machines for Windows Server 2019/ }));
    expect(await screen.findByText("web-01")).toBeInTheDocument();
    expect(osGroup).toHaveBeenCalledWith("Windows Server|2019", {}, 0, 25);
  });

  it("submits the visible filtered inventory through the canonical drawer", async () => {
    os.mockResolvedValue({
      ...envelope(collection),
      pagination: { offset: 0, limit: 20, total: 120, next_offset: 20 },
    });
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    fireEvent.change(await screen.findByPlaceholderText("Name or version"), {
      target: { value: "2099" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask Copilot about inventory" }));
    fireEvent.click(await screen.findByRole("button", { name: /Review visible inventory health/ }));

    await waitFor(() => expect(investigateCanonical).toHaveBeenCalled());
    const request = investigateCanonical.mock.calls[0][0];
    expect(request).toMatchObject({
      contract_version: "1",
      requested_scope: {},
      snapshot: {
        version: "2",
        page_kind: "inventory",
        coverage: { visible_count: 1, total_count: 120, complete: false },
      },
      hint: {
        specialist_id: "inventory_data_health",
        tool: "inventory_resources",
      },
    });
    expect(request.snapshot.evidence).toHaveLength(1);
    expect(request.snapshot.evidence[0].data).toMatchObject({
      os_name: "Windows Server",
      os_version: "2099-preview",
    });
  });

  it("does not expose Copilot while inventory for a new scope is unresolved", async () => {
    investigateCanonical.mockClear();
    const scopedInventory = new Promise<never>(() => undefined);
    os
      .mockResolvedValueOnce(envelope({
        ...collection,
        requested_scope: { subscription: ["sub-a", "sub-b"] },
      }))
      .mockReturnValueOnce(scopedInventory);

    render(
      <ScopeProvider initialScope={{ subscription: ["sub-a", "sub-b"] }}>
        <InventoryPage />
      </ScopeProvider>,
    );

    expect(await screen.findByRole("button", { name: "Ask Copilot about inventory" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Subscription"), {
      target: { value: "sub-b" },
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Ask Copilot about inventory" })).not.toBeInTheDocument();
    });
    expect(investigateCanonical).not.toHaveBeenCalled();
  });

  it("uses the server-derived effective scope when RBAC narrows the browser request", async () => {
    investigateCanonical.mockClear();
    os.mockResolvedValue({
      ...envelope({
        ...collection,
        requested_scope: { subscription: ["sub-a"] },
      }),
      pagination: { offset: 0, limit: 20, total: 2, next_offset: null },
    });

    render(
      <ScopeProvider initialScope={{ subscription: ["sub-a", "sub-b"] }}>
        <InventoryPage />
      </ScopeProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Ask Copilot about inventory" }));
    fireEvent.click(await screen.findByRole("button", { name: /Review visible inventory health/ }));

    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(1));
    expect(investigateCanonical.mock.calls[0][0].requested_scope).toEqual({
      subscription: ["sub-a"],
    });
    expect(investigateCanonical.mock.calls[0][1]).toEqual({
      subscription: ["sub-a"],
    });
  });

  it("renders canonical installed software and exact linked details", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));

    expect((await screen.findAllByText("7-Zip")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /View machines for 7-Zip 19.00/ }));
    expect(await screen.findByText(/exact resource join/)).toBeInTheDocument();
    expect(screen.getByText("7-Zip v19.00")).toBeInTheDocument();
    expect(softwareGroup).toHaveBeenCalledWith("7-Zip|19.00", {}, 0, 25);
  });

  it("shows all EOL candidate citations and confirms an explicit choice", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Review EOL date" }));

    expect(await screen.findByText(/Claim: Official vendor claim/)).toBeInTheDocument();
    expect(screen.getByText("2030-01-01")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm this date" }));

    expect(confirmLifecycle).toHaveBeenCalledWith(
      "Windows Server|2099-preview",
      expect.objectContaining({
        normalized_os_key: "windows server|2099-preview",
        expected_revision: 0,
        candidate_id: "eol-candidate-1",
      }),
      {},
    );
  });

  it("renders server-owned mapping review controls and sends its revision", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));

    expect(await screen.findByText(/Widget Suite v1.0/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve mapping" }));

    expect(approveMapping).toHaveBeenCalledWith("software-map://review-1", 0, {});
  });

  it("renders deterministic facts and filters OS groups without changing the API scope", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(await screen.findByText("Inventory risk narrative")).toBeInTheDocument();
    expect(screen.getByText(/3 machines across 2 OS groups/)).toBeInTheDocument();
    expect(screen.getAllByText(/Arc · partial/).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByPlaceholderText("Name or version"), { target: { value: "2099" } });
    expect(screen.getByRole("button", { name: /View machines for Windows Server 2099-preview/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /View machines for Windows Server 2019/ })).not.toBeInTheDocument();
  });

  it("lists each narrative source once when citations have different observation timestamps", async () => {
    narrative.mockResolvedValue(envelope({
      fact_summary: "Inventory facts.",
      fact_items: [],
      narrated_summary: null,
      narrated_by: "",
      model: "",
      confidence: "medium",
      citations: [
        {
          source_engine: "Azure Monitor Logs",
          source_table: "ConfigurationData",
          timestamp: "2026-08-25T10:00:00Z",
          reference: "",
        },
        {
          source_engine: "Azure Monitor Logs",
          source_table: "ConfigurationData",
          timestamp: "2026-08-25T11:00:00Z",
          reference: "",
        },
        {
          source_engine: "Azure Resource Graph",
          source_table: "Resources",
          timestamp: "2026-08-25T11:00:00Z",
          reference: "",
        },
      ],
      source_status: collection.source_status,
      requested_scope: { dimensions: ["subscription"] },
      status: "fact_only",
    }));

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(await screen.findAllByText("Azure Monitor Logs / ConfigurationData")).toHaveLength(1);
    expect(screen.getAllByText("Azure Resource Graph / Resources")).toHaveLength(1);
  });

  it("presents a partial software source with trustworthy rows as incomplete, not unavailable", async () => {
    software.mockResolvedValue(envelope({
      groups: [{
        key: "7-Zip|19.00",
        software_name: "7-Zip",
        software_version: "19.00",
        install_count: 35,
        source_types: ["azure_vm"],
        linked_count: 35,
        unlinked_count: 0,
        publishers: ["Igor Pavlov"],
      }],
      source_status: {
        logs: { source_type: "logs", state: "partial", observed_at: "", query_version: "v1", row_count: 35, error: "one workspace timed out" },
      },
      observed_at: "2026-08-25T10:00:00Z",
      query_version: "v1",
      generation_id: "generation-1",
      requested_scope: {},
    }));

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));

    expect(await screen.findByText("Installed software source is partial")).toBeInTheDocument();
    expect(screen.getByText(/successful rows are shown, but coverage may be incomplete/)).toBeInTheDocument();
    expect(screen.queryByText("Installed software source is unavailable")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /View machines for 7-Zip 19.00/ })).toBeInTheDocument();
  });

  it("keeps a partial software source with zero trustworthy rows unavailable", async () => {
    software.mockResolvedValue(envelope({
      groups: [],
      source_status: {
        logs: { source_type: "logs", state: "partial", observed_at: "", query_version: "v1", row_count: 0, error: "all workspaces timed out" },
      },
      observed_at: "2026-08-25T10:00:00Z",
      query_version: "v1",
      generation_id: "generation-1",
      requested_scope: {},
    }));

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));

    expect(await screen.findByText("Installed software source is unavailable")).toBeInTheDocument();
    expect(screen.getByText(/rows are not presented as a successful empty result/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /View machines for/ })).not.toBeInTheDocument();
  });

  it("keeps the three-tab boundary and shows authorized export context for exact lookup", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByRole("tab", { name: "OS Inventory" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));
    expect(screen.getByRole("tab", { name: "Installed Software" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Subscription")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /View machines for 7-Zip 19.00/ }));

    expect(await screen.findByRole("button", { name: "Export CSV" })).toBeInTheDocument();
    expect(screen.getByText(/1 of 1 installations/)).toBeInTheDocument();
    expect(screen.getByText(/Log Analytics · ready/)).toBeInTheDocument();
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(screen.getByText("sub-a")).toBeInTheDocument();
  });

  it("advances the OS group table to the next page and refetches at the new offset", async () => {
    os.mockResolvedValue({
      ...envelope(collection),
      pagination: { offset: 0, limit: 20, total: 120, next_offset: 20 },
    });

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(await screen.findByText(/of 120 OS groups/)).toBeInTheDocument();
    expect(os).toHaveBeenCalledWith(expect.anything(), 0, 20);

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => expect(os).toHaveBeenCalledWith(expect.anything(), 20, 20));
  });

  it("refetches from the first offset when the operator picks a larger page size", async () => {
    os.mockResolvedValue({
      ...envelope(collection),
      pagination: { offset: 0, limit: 20, total: 120, next_offset: 20 },
    });

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(await screen.findByText(/of 120 OS groups/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: /rows per page for OS groups/i }), {
      target: { value: "100" },
    });

    await waitFor(() => expect(os).toHaveBeenCalledWith(expect.anything(), 0, 100));
  });

  it("lists Azure resources by type and drills into a group", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    fireEvent.click(screen.getByRole("tab", { name: "Azure Inventory" }));
    expect(screen.getByRole("tab", { name: "Azure Inventory" })).toHaveAttribute("aria-selected", "true");

    expect(await screen.findAllByText("Container Apps")).not.toHaveLength(0);
    expect(screen.getByText("microsoft.app/containerapps")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /View resources for Container Apps/ }));

    expect(await screen.findByText("app-1")).toBeInTheDocument();
    expect(screen.getByText("australiaeast")).toBeInTheDocument();
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(paasGroup).toHaveBeenCalledWith(
      "microsoft.app:containerapps|Unknown|Unknown",
      expect.anything(),
      0,
      25,
    );
  });

  it("submits the raw ARM resource type selected by its friendly label", async () => {
    investigateCanonical.mockClear();
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    fireEvent.click(screen.getByRole("tab", { name: "Azure Inventory" }));
    const resourceTypeFilter = await screen.findByDisplayValue("All resource types");
    expect(resourceTypeFilter).toHaveDisplayValue("All resource types");
    expect(resourceTypeFilter.querySelector("option[value='microsoft.app/containerapps']"))
      .toHaveTextContent("Container Apps");

    fireEvent.change(resourceTypeFilter, {
      target: { value: "microsoft.app/containerapps" },
    });
    fireEvent.click(await screen.findByRole("button", {
      name: "Ask Copilot about inventory",
    }));
    fireEvent.click(await screen.findByRole("button", {
      name: /Review visible inventory health/,
    }));

    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(1));
    expect(
      investigateCanonical.mock.calls[0][0].snapshot.evidence[0]
        .data.inventory_context.filters.resource_type,
    ).toBe("microsoft.app/containerapps");
  });

  it("renders the drill-down inline beneath the group row it was opened from", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    fireEvent.click(screen.getByRole("tab", { name: "Azure Inventory" }));
    const toggle = await screen.findByRole("button", { name: /View resources for Container Apps/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);

    const detailCell = await screen.findByText("app-1");
    const groupRow = toggle.closest("tr");
    const detailRow = detailCell.closest("tr.detail-row")?.parentElement?.closest("tr.detail-row")
      ?? detailCell.closest("table")?.closest("tr.detail-row");

    // The detail must be the row immediately after the group row, not appended
    // to the end of the page.
    expect(groupRow).not.toBeNull();
    expect(detailRow).not.toBeNull();
    expect(groupRow?.nextElementSibling).toBe(detailRow);
    expect(screen.getByRole("button", { name: /View resources for Container Apps/ })).toHaveAttribute("aria-expanded", "true");
  });

  it("exports every in-scope resource, following API pagination across pages", async () => {
    // The API caps `limit` at 500, so the export must keep requesting until
    // next_offset is null rather than shipping only the first page.
    resources
      .mockResolvedValueOnce({
        ...envelope({
          resources: [{
            family: "paas",
            resource_id: "/subscriptions/sub-a/app-1",
            resource_name: "app-1",
            resource_type: "microsoft.app/containerapps",
            subscription_id: "sub-a",
            resource_group: "rg-1",
            environment: "prod",
          }],
          family_availability: {},
          requested_scope: {},
          query_version: "inventory-resources-v1",
        }),
        pagination: { offset: 0, limit: 500, total: 2, next_offset: 500 },
      })
      .mockResolvedValueOnce({
        ...envelope({
          resources: [{
            family: "os",
            resource_id: "/subscriptions/sub-a/vm1",
            resource_name: "vm1",
            resource_type: "microsoft.compute/virtualmachines",
            subscription_id: "sub-a",
            resource_group: "rg-2",
            environment: "dev",
          }],
          family_availability: {},
          requested_scope: {},
          query_version: "inventory-resources-v1",
        }),
        pagination: { offset: 500, limit: 500, total: 2, next_offset: null },
      });

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("tab", { name: "Azure Inventory" }));
    fireEvent.click(await screen.findByRole("button", { name: /Export all resources/ }));

    await waitFor(() => expect(downloadCsv).toHaveBeenCalled());
    expect(resources).toHaveBeenCalledTimes(2);
    expect(resources).toHaveBeenLastCalledWith(expect.anything(), 500, 500);

    const [csv, filename] = downloadCsv.mock.calls[0];
    expect(filename).toBe("azure-inventory-all-resources.csv");
    // Both pages must survive into the export, not just the first.
    expect(csv).toContain("app-1");
    expect(csv).toContain("vm1");
  });

  it("explains how to load inventory when the API provider has no snapshot", async () => {
    const unavailable = new ApiError(
      503,
      "provider_unavailable",
      "The inventory provider is unavailable",
      { capability: "inventory", provider_state: "unavailable" },
    );
    os.mockRejectedValue(unavailable);
    software.mockRejectedValue(unavailable);
    narrative.mockRejectedValue(unavailable);
    mappings.mockRejectedValue(unavailable);

    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(await screen.findByText("Inventory data is not loaded")).toBeInTheDocument();
    expect(screen.getByText(/You do not need the AIOps semantic graph or operations agent/)).toBeInTheDocument();
    expect(screen.getByText("uv run aiops-inventory sync --config config.yaml")).toBeInTheDocument();
    expect(screen.getByText(/AIOPS_INVENTORY_FIXTURE=tests\/fixtures\/mock_inventory_arg.json/)).toBeInTheDocument();
  });
});
