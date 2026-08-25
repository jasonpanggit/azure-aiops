import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { os, osGroup, software, softwareGroup, lifecycleReview, confirmLifecycle, mappings, approveMapping, rejectMapping } = vi.hoisted(() => ({
  os: vi.fn(),
  osGroup: vi.fn(),
  software: vi.fn(),
  softwareGroup: vi.fn(),
  lifecycleReview: vi.fn(),
  confirmLifecycle: vi.fn(),
  mappings: vi.fn(),
  approveMapping: vi.fn(),
  rejectMapping: vi.fn(),
}));

vi.mock("@/lib/services", () => ({ inventoryApi: { os, osGroup, software, softwareGroup, lifecycleReview, confirmLifecycle, mappings, approveMapping, rejectMapping } }));

import SoftwareInventoryPage from "./page";

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

describe("Software Inventory OS tracer", () => {
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
    render(<ScopeProvider><SoftwareInventoryPage /></ScopeProvider>);

    expect((await screen.findAllByText("Windows Server")).length).toBe(2);
    expect(screen.getByText("EOL date needs review")).toBeInTheDocument();
    expect(screen.getByText(/Arc source is partial/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /View machines for Windows Server 2019/ }));
    expect(await screen.findByText("web-01")).toBeInTheDocument();
    expect(osGroup).toHaveBeenCalledWith("Windows Server|2019", {});
  });

  it("renders canonical installed software and exact linked details", async () => {
    render(<ScopeProvider><SoftwareInventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Installed Software" }));

    expect(await screen.findByText("7-Zip")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /View machines for 7-Zip 19.00/ }));
    expect(await screen.findByText(/exact resource join/)).toBeInTheDocument();
    expect(screen.getByText(/Raw: 7-Zip v19.00 v19.00/)).toBeInTheDocument();
    expect(softwareGroup).toHaveBeenCalledWith("7-Zip|19.00", {});
  });

  it("shows all EOL candidate citations and confirms an explicit choice", async () => {
    render(<ScopeProvider><SoftwareInventoryPage /></ScopeProvider>);
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
    render(<ScopeProvider><SoftwareInventoryPage /></ScopeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Installed Software" }));

    expect(await screen.findByText(/Widget Suite v1.0/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve mapping" }));

    expect(approveMapping).toHaveBeenCalledWith("software-map://review-1", 0, {});
  });
});
