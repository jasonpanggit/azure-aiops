import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import { ApiError } from "@/lib/types";

const { os, osGroup, software, softwareGroup, narrative, lifecycleReview, confirmLifecycle, mappings, approveMapping, rejectMapping } = vi.hoisted(() => ({
  os: vi.fn(),
  osGroup: vi.fn(),
  software: vi.fn(),
  softwareGroup: vi.fn(),
  narrative: vi.fn(),
  lifecycleReview: vi.fn(),
  confirmLifecycle: vi.fn(),
  mappings: vi.fn(),
  approveMapping: vi.fn(),
  rejectMapping: vi.fn(),
}));

vi.mock("@/lib/services", () => ({ inventoryApi: { os, osGroup, software, softwareGroup, narrative, lifecycleReview, confirmLifecycle, mappings, approveMapping, rejectMapping } }));

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
    os.mockResolvedValue(envelope(collection));
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

    expect((await screen.findAllByText("Windows Server")).length).toBe(2);
    expect(screen.getByText("EOL date needs review")).toBeInTheDocument();
    expect(screen.getByText(/Arc source is partial/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /View machines for Windows Server 2019/ }));
    expect(await screen.findByText("web-01")).toBeInTheDocument();
    expect(osGroup).toHaveBeenCalledWith("Windows Server|2019", {});
  });

  it("renders canonical installed software and exact linked details", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));

    expect(await screen.findByText("7-Zip")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /View machines for 7-Zip 19.00/ }));
    expect(await screen.findByText(/exact resource join/)).toBeInTheDocument();
    expect(screen.getByText("7-Zip v19.00")).toBeInTheDocument();
    expect(softwareGroup).toHaveBeenCalledWith("7-Zip|19.00", {});
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

  it("keeps the two-tab boundary and shows authorized export context for exact lookup", async () => {
    render(<ScopeProvider><InventoryPage /></ScopeProvider>);

    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "OS Inventory" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: "Installed Software" }));
    expect(screen.getByRole("tab", { name: "Installed Software" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Subscription")).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /View machines for 7-Zip 19.00/ }));

    expect(await screen.findByRole("button", { name: "Export CSV (1 row)" })).toBeInTheDocument();
    expect(screen.getByText(/Exports only the exact rows returned/)).toBeInTheDocument();
    expect(screen.getByText(/Log Analytics · ready/)).toBeInTheDocument();
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(screen.getByText("sub-a")).toBeInTheDocument();
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
    expect(screen.getByText(/You do not need the Hermes semantic graph or operations agent/)).toBeInTheDocument();
    expect(screen.getByText("uv run hermes-arg sync --config config.yaml")).toBeInTheDocument();
    expect(screen.getByText(/HERMES_INVENTORY_FIXTURE=tests\/fixtures\/mock_inventory_arg.json/)).toBeInTheDocument();
  });
});
