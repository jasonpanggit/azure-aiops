import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { targets, runs, trigger } = vi.hoisted(() => ({
  targets: vi.fn(),
  runs: vi.fn(),
  trigger: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  patchingApi: { targets, runs, trigger },
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

  it("lists patchable servers and triggers a run with only the selected patches", async () => {
    targets.mockResolvedValue(envelope([target()]));
    trigger.mockResolvedValue(
      envelope({
        run_id: "run-1",
        target_id: VM_ID,
        inventory_kind: "Azure VM",
        operation: "install_patches",
        patch_ids: ["KB600001"],
        state: "submitted",
        requested_by: "admin@example.com",
        approved_by: "admin@example.com",
        reason: "Emergency patch",
        reboot_setting: "IfRequired",
        dry_run: true,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        provider: "dry-run",
        provider_job_id: "",
        message: "",
        subscription_id: "sub-1",
        subscription_connection: "",
        business_service: "Payments",
        environment: "prod",
        details: {},
        terminal: false,
      })
    );

    const user = userEvent.setup();
    render(<PatchInventory scope={{}} />);

    expect(await screen.findByText("vm1")).toBeInTheDocument();
    expect(screen.getAllByText("Azure VM").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Choose updates" }));
    await user.click(screen.getByRole("checkbox", { name: /KB600001/ }));

    // A reason is mandatory before the trigger unlocks.
    const install = screen.getByRole("button", { name: /Install 1 update/ });
    expect(install).toBeDisabled();

    await user.type(screen.getByRole("textbox"), "Emergency patch");
    await waitFor(() => expect(install).toBeEnabled());
    await user.click(install);

    await waitFor(() => expect(trigger).toHaveBeenCalledTimes(1));
    expect(trigger).toHaveBeenCalledWith({
      target_id: VM_ID,
      patch_ids: ["KB600001"],
      reason: "Emergency patch",
      reboot_setting: "IfRequired",
      dry_run: true,
    });
    expect(await screen.findByText("submitted")).toBeInTheDocument();
  });

  it("requires an agent pool before an AKS upgrade can be triggered", async () => {
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
    trigger.mockResolvedValue(envelope({ run_id: "run-2", state: "submitted", patch_ids: ["latest"] }));

    const user = userEvent.setup();
    render(<PatchInventory scope={{}} />);

    await user.click(await screen.findByRole("button", { name: "Choose updates" }));
    await user.click(screen.getByRole("radio", { name: /latest/ }));
    await user.type(screen.getByRole("textbox", { name: /reason/i }), "Node image refresh");

    // Without a named pool the upgrade would roll the whole cluster.
    const upgrade = screen.getByRole("button", { name: /Trigger node image upgrade/ });
    expect(upgrade).toBeDisabled();

    await user.type(screen.getByRole("textbox", { name: /agent pool/i }), "systempool");
    await waitFor(() => expect(upgrade).toBeEnabled());
    await user.click(upgrade);

    await waitFor(() => expect(trigger).toHaveBeenCalledTimes(1));
    expect(trigger.mock.calls[0][0]).toMatchObject({ node_pool: "systempool" });
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
    expect(screen.getByRole("button", { name: "Trigger node image upgrade" })).toBeInTheDocument();
  });

  it("surfaces the unconfigured-adapter warning", async () => {
    targets.mockResolvedValue(
      envelope([target()], ["No patch execution adapter is configured; patch runs can be validated (dry run) but not submitted to Azure."])
    );

    render(<PatchInventory scope={{}} />);
    expect(await screen.findByText(/No patch execution adapter is configured/)).toBeInTheDocument();
  });
});
