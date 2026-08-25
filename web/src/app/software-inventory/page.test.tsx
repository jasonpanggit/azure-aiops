import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { os, osGroup } = vi.hoisted(() => ({
  os: vi.fn(),
  osGroup: vi.fn(),
}));

vi.mock("@/lib/services", () => ({ inventoryApi: { os, osGroup } }));

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
});
