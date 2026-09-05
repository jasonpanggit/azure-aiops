import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import { ApiError } from "@/lib/types";
import { CopilotDrawer } from "./CopilotDrawer";

const { investigateContext } = vi.hoisted(() => ({ investigateContext: vi.fn() }));
const { investigateCanonical } = vi.hoisted(() => ({ investigateCanonical: vi.fn() }));
vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return { ...actual, copilotApi: { ...actual.copilotApi, investigateContext } };
});
vi.mock("@/lib/copilot/page-adapters", async () => {
  const actual = await vi.importActual<typeof import("@/lib/copilot/page-adapters")>("@/lib/copilot/page-adapters");
  return { ...actual, investigateCanonical };
});

const snapshot = {
  version: "1" as const,
  page_kind: "network" as const,
  page_id: "network-topology",
  selected_resources: [],
  filters: { tab: ["gaps"] },
  freshness: [{ source: "ARG", observed_at: "2026-01-01T00:00:00Z", status: "fresh" as const }],
  scope: { declared: { subscription: ["sub-1"] }, authorized: true },
  evidence: [{ evidence_id: "network:gap:1", section: "network", data: { finding: "Firewall bypass" }, status: "ok" as const }],
  question: "default",
  rechecks: [],
};

describe("CopilotDrawer", () => {
  it("submits the exact typed page snapshot and renders deterministic citations", async () => {
    investigateContext.mockResolvedValue({
      data: {
        page_kind: "network",
        page_id: "network-topology",
        snapshot_hash: "hash",
        stages: ["validated", "deterministic"],
        findings: [{
          finding_id: "NET-FW-001:network:gap:1",
          resource_ids: [],
          check_id: "NET-FW-001",
          policy_id: "NET-FW-001",
          source_status: "ok",
          status: "verified",
          summary: "Firewall bypass",
          evidence_refs: ["network:gap:1"],
          confidence: "high",
          uncertainty: [],
          stale: false,
          next_check: "Recheck network:gap:1",
          actionable: true,
        }],
        tool_calls: [],
        synthesis_mode: "deterministic",
        synthesis_agent: "",
        synthesis: null,
        warnings: [],
      },
      evidence: [],
      warnings: [],
    });
    render(
      <ScopeProvider>
        <CopilotDrawer open onClose={vi.fn()} contextLabel="Network" snapshot={snapshot} starterQuestions={[]} />
      </ScopeProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "What is wrong?" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    await waitFor(() => expect(investigateContext).toHaveBeenCalledWith({ ...snapshot, question: "What is wrong?" }));
    expect(await screen.findByText("Verified finding")).toBeInTheDocument();
    expect(screen.getByText(/Foundry narration was not produced/)).toBeInTheDocument();
  });

  it("renders a duplicated backend warning only once", async () => {
    const warning = "Foundry narration unavailable; deterministic findings returned";
    investigateContext.mockResolvedValue({
      data: {
        findings: [],
        tool_calls: [],
        synthesis_mode: "deterministic",
        warnings: [warning],
      },
      evidence: [],
      warnings: [warning],
    });
    render(
      <ScopeProvider>
        <CopilotDrawer open onClose={vi.fn()} contextLabel="Network" snapshot={snapshot} starterQuestions={[]} />
      </ScopeProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "What is wrong?" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() => expect(investigateContext).toHaveBeenCalled());
    expect(screen.getAllByText(warning)).toHaveLength(1);
  });

  it("does not repeat narrated findings as cards", async () => {
    investigateContext.mockResolvedValue({
      data: {
        findings: [{
          finding_id: "NET-FW-001:network:gap:1",
          resource_ids: [],
          check_id: "NET-FW-001",
          policy_id: "NET-FW-001",
          source_status: "ok",
          status: "verified",
          summary: "Firewall bypass",
          evidence_refs: ["network:gap:1"],
          confidence: "high",
          uncertainty: [],
          stale: false,
          next_check: "Recheck network:gap:1",
          actionable: true,
        }],
        tool_calls: [],
        synthesis_mode: "foundry",
        synthesis_agent: "aiops-network-agent",
        synthesis: {
          mode: "foundry",
          narration: "UAT cannot reach PROD on the evidence available.",
        },
        warnings: [],
      },
      evidence: [],
      warnings: [],
    });
    render(
      <ScopeProvider>
        <CopilotDrawer open onClose={vi.fn()} contextLabel="Network" snapshot={snapshot} starterQuestions={[]} />
      </ScopeProvider>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Can UAT reach PROD?" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));

    expect(await screen.findByText("UAT cannot reach PROD on the evidence available.")).toBeInTheDocument();
    expect(screen.queryByText("Verified finding")).not.toBeInTheDocument();
    expect(screen.queryByText("Firewall bypass")).not.toBeInTheDocument();
  });

  it("renders cited deterministic fallback with explicit coverage and uncertainty", async () => {
    investigateCanonical.mockResolvedValue({
      data: {
        contract_version: "1",
        status: "partial",
        policy_status: "fallback",
        fallback_reason: "planner_unavailable",
        selected_specialists: ["inventory_data_health"],
        selected_tools: ["inventory_resources"],
        tool_results: [{
          call_id: "0:0:inventory_data_health:inventory_resources",
          specialist_id: "inventory_data_health",
          tool: "inventory_resources",
          status: "ok",
          data: { resources: [{ name: "app-1" }] },
          evidence: [],
          warning: "",
        }],
        uncertainty: ["visible subset is incomplete", "arc freshness is partial"],
        coverage: { visible_count: 1, total_count: 4, complete: false },
        citations: [{
          citation_id: "inventory:azure:stable",
          source: "inventory/resource_observations",
          status: "ok",
          observed_at: "2026-08-25T10:00:00Z",
          resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.App/containerApps/app-1",
        }],
        thread_id: "thr-0123456789abcdef0123456789abcdef",
        thread_revision: 1,
        mutation_authorized: false,
      },
      evidence: [],
      warnings: [],
    });
    const inventorySnapshot = {
      version: "2" as const,
      page_kind: "inventory" as const,
      page_id: "inventory" as const,
      coverage: { visible_count: 1, total_count: 4, complete: false },
      freshness: [],
      evidence: [],
    };

    render(
      <ScopeProvider>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Inventory"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={inventorySnapshot}
          starterQuestions={[{
            label: "Review inventory health",
            specialistId: "inventory_data_health",
            tool: "inventory_resources",
            toolArguments: {},
          }]}
        />
      </ScopeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));

    expect(await screen.findByText("Showing governed results directly because optional narration is unavailable.")).toBeInTheDocument();
    expect(screen.getByText("1 of 4 visible records")).toBeInTheDocument();
    expect(screen.getByText("visible subset is incomplete")).toBeInTheDocument();
    expect(screen.getByText("inventory:azure:stable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();
  });

  it("restores only the opaque server thread ID across remount", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const threadId = "thr-0123456789abcdef0123456789abcdef";
    investigateCanonical.mockResolvedValue({
      data: {
        contract_version: "1",
        status: "empty",
        policy_status: "fallback",
        fallback_reason: "planner_unavailable",
        selected_specialists: ["inventory_data_health"],
        selected_tools: ["inventory_resources"],
        tool_results: [],
        uncertainty: [],
        coverage: { visible_count: 0, total_count: 0, complete: true },
        citations: [],
        thread_id: threadId,
        thread_revision: 1,
        mutation_authorized: false,
      },
      evidence: [],
      warnings: [],
    });
    const inventorySnapshot = {
      version: "2" as const,
      page_kind: "inventory" as const,
      page_id: "inventory" as const,
      coverage: { visible_count: 0, total_count: 0, complete: true },
      freshness: [],
      evidence: [],
    };
    const props = {
      open: true,
      onClose: vi.fn(),
      contextLabel: "Inventory",
      requestedScope: { subscription: ["sub-a"] },
      snapshot: inventorySnapshot,
      starterQuestions: [{ label: "Review inventory health" }],
    };

    const first = render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(1));
    first.unmount();

    expect(window.sessionStorage).toHaveLength(1);
    expect(window.sessionStorage.getItem("aiops.copilot.thread.inventory")).toBe(threadId);

    render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).toMatchObject({ thread_id: threadId });
  });

  it("clears an expired opaque thread so retry starts a new server thread", async () => {
    investigateCanonical.mockClear();
    const expiredThread = "thr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const replacementThread = "thr-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    window.sessionStorage.setItem("aiops.copilot.thread.inventory", expiredThread);
    investigateCanonical
      .mockRejectedValueOnce(new ApiError(
        404,
        "not_found",
        "Investigation thread not found",
        { field: "thread_id" },
      ))
      .mockResolvedValueOnce({
        data: {
          contract_version: "1",
          status: "empty",
          policy_status: "fallback",
          fallback_reason: "planner_unavailable",
          selected_specialists: ["inventory_data_health"],
          selected_tools: ["inventory_resources"],
          tool_results: [],
          uncertainty: [],
          coverage: { visible_count: 0, total_count: 0, complete: true },
          citations: [],
          thread_id: replacementThread,
          thread_revision: 1,
          mutation_authorized: false,
        },
        evidence: [],
        warnings: [],
      });
    const inventorySnapshot = {
      version: "2" as const,
      page_kind: "inventory" as const,
      page_id: "inventory" as const,
      coverage: { visible_count: 0, total_count: 0, complete: true },
      freshness: [],
      evidence: [],
    };

    render(
      <ScopeProvider>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Inventory"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={inventorySnapshot}
          starterQuestions={[{ label: "Review inventory health" }]}
        />
      </ScopeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    expect(await screen.findByText("Investigation thread not found")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("aiops.copilot.thread.inventory")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).not.toHaveProperty("thread_id");
    expect(window.sessionStorage.getItem("aiops.copilot.thread.inventory")).toBe(replacementThread);
  });
});
