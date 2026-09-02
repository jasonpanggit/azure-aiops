import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { targets, runs } = vi.hoisted(() => ({
  targets: vi.fn(),
  runs: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  patchingApi: { targets, runs },
}));

import { PatchInventory } from "./PatchInventory";

const envelope = <T,>(data: T, warnings: string[] = []) => ({
  data,
  evidence: [],
  scope: {},
  warnings,
  knowledge_version: "graph-1",
});

const VM_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1";
const AKS_ID = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks1";

function patch(overrides: Record<string, unknown> = {}) {
  return {
    patch_id: "KB600001",
    title: "Cumulative security update",
    classification: "Security",
    severity: "Critical",
    cve_ids: ["CVE-2026-0001"],
    reboot_required: true,
    published_at: "2026-01-01T00:00:00Z",
    source: "derived:open-findings",
    node_pool: "",
    current_version: "",
    target_version: "",
    ...overrides,
  };
}

function target(overrides: Record<string, unknown> = {}) {
  return {
    target_id: VM_ID,
    name: "vm1",
    inventory_kind: "Azure VM",
    resource_type: "microsoft.compute/virtualmachines",
    subscription_id: "sub-1",
    subscription_connection: "",
    resource_group: "rg",
    environment: "prod",
    business_service: "Payments",
    application: "",
    owner: "",
    region: "eastus",
    criticality: "",
    os_family: "Windows",
    reachable: true,
    internet_exposed: false,
    cve_count: 3,
    critical_count: 1,
    overdue_count: 1,
    max_days_open: 40,
    available_patches: [patch()],
    patchable: true,
    blocked_reason: "",
    requires_node_pool: false,
    operation: "install_patches",
    ...overrides,
  };
}

describe("PatchInventory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    runs.mockResolvedValue(envelope([]));
  });

  it("lists patch readiness and hands the governed target context to remediation", async () => {
    targets.mockResolvedValue(envelope([target()]));

    render(<PatchInventory scope={{}} />);

    expect(await screen.findByText("vm1")).toBeInTheDocument();
    expect(screen.getAllByText("Azure VM").length).toBeGreaterThan(0);
    const handoff = screen.getByRole("link", { name: "Open governed remediation" });
    expect(handoff).toHaveAttribute(
      "href",
      `/remediation?resource_key=${encodeURIComponent(VM_ID)}&kb=KB600001&business_service=Payments`
    );
    expect(screen.queryByRole("button", { name: /Install|Trigger|Bulk/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Reason/)).not.toBeInTheDocument();
  });

  it("keeps AKS inventory read-only and routes the selected version into governance", async () => {
    targets.mockResolvedValue(
      envelope([
        target({
          target_id: AKS_ID,
          name: "aks1",
          inventory_kind: "AKS node",
          operation: "node_image_upgrade",
          requires_node_pool: true,
          available_patches: [patch({ patch_id: "latest", title: "Upgrade to latest node image" })],
        }),
      ])
    );
    const user = userEvent.setup();
    render(<PatchInventory scope={{}} />);

    await user.click(await screen.findByRole("button", { name: "Choose updates" }));
    await user.click(screen.getByRole("radio", { name: /latest/ }));
    const handoff = screen.getByRole("link", { name: "Open governed remediation" });
    expect(handoff).toHaveAttribute("href", expect.stringContaining("kb=latest"));
    expect(screen.queryByRole("textbox", { name: /agent pool/i })).not.toBeInTheDocument();
  });

  it("restricts AKS node image upgrades to a single version", async () => {
    targets.mockResolvedValue(
      envelope([
        target({
          target_id: AKS_ID,
          name: "aks1",
          inventory_kind: "AKS node",
          operation: "node_image_upgrade",
          available_patches: [
            patch({ patch_id: "latest", title: "Latest node image" }),
            patch({ patch_id: "AKSUbuntu-2204-202601", title: "Pinned node image" }),
          ],
        }),
      ])
    );

    const user = userEvent.setup();
    render(<PatchInventory scope={{}} />);

    await user.click(await screen.findByRole("button", { name: "Choose updates" }));
    const options = screen.getAllByRole("radio");
    await user.click(options[0]);
    await user.click(options[1]);

    // Selecting a second version replaces the first rather than adding to it.
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open governed remediation" })).toBeInTheDocument();
  });

  it("surfaces the unconfigured-adapter warning", async () => {
    targets.mockResolvedValue(
      envelope([target()], ["No patch execution adapter is configured; patch runs can be validated (dry run) but not submitted to Azure."])
    );

    render(<PatchInventory scope={{}} />);
    expect(await screen.findByText(/No patch execution adapter is configured/)).toBeInTheDocument();
  });
});
