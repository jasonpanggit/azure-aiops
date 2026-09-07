import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  COPILOT_THREAD_STORAGE_KEY,
  ThreadContinuityProvider,
} from "@/lib/copilot/thread-context";
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
  function canonicalSnapshot(tab: "os" | "software" | "azure") {
    return {
      version: "2" as const,
      page_kind: "inventory" as const,
      page_id: "inventory" as const,
      coverage: { visible_count: 1, total_count: 1, complete: true },
      freshness: [],
      evidence: [{
        evidence_id: `inventory:${tab}:context`,
        source: `inventory/${tab}_observations`,
        status: "ok" as const,
        observed_at: "2026-08-25T10:00:00Z",
        resource_id: `inventory://${tab}/context`,
        data: { inventory_context: { tab, filters: {} } },
      }],
    };
  }

  function canonicalResult(threadId: string, citationId: string) {
    return {
      data: {
        contract_version: "1" as const,
        status: "ok" as const,
        policy_status: "accepted" as const,
        fallback_reason: "",
        selected_specialists: ["inventory_data_health"],
        selected_tools: ["inventory_resources"],
        tool_results: [],
        uncertainty: [],
        coverage: { visible_count: 1, total_count: 1, complete: true },
        citations: [{
          citation_id: citationId,
          source: "inventory/server",
          status: "ok",
          observed_at: "2026-08-25T10:00:00Z",
          resource_id: "",
        }],
        thread_id: threadId,
        thread_revision: 1,
        mutation_authorized: false as const,
      },
      evidence: [],
      warnings: [],
    };
  }

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

  it("labels evidence age only from server-returned citation state", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const result = canonicalResult(
      "thr-44444444444444444444444444444444",
      "server:historical",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        citations: [
          {
            ...result.data.citations[0],
            citation_id: "server:historical",
            status: "historical",
          },
          {
            ...result.data.citations[0],
            citation_id: "server:revalidated",
            status: "revalidated",
          },
          {
            ...result.data.citations[0],
            citation_id: "server:current",
            status: "current",
          },
        ],
      },
    });

    render(
      <ScopeProvider>
        <ThreadContinuityProvider>
          <CopilotDrawer
            open
            onClose={vi.fn()}
            contextLabel="Inventory"
            requestedScope={{ subscription: ["sub-a"] }}
            snapshot={{
              ...canonicalSnapshot("os"),
              freshness: [{
                source: "inventory/os_observations",
                observed_at: "2026-08-25T10:00:00Z",
                status: "stale" as const,
              }],
            }}
            starterQuestions={[{ label: "Review carried evidence" }]}
          />
        </ThreadContinuityProvider>
      </ScopeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Review carried evidence/ }));

    expect(await screen.findByText("Historical evidence")).toBeInTheDocument();
    expect(screen.getByText("Revalidated evidence")).toBeInTheDocument();
    expect(screen.getByText("Current evidence")).toBeInTheDocument();
    expect(screen.getByText("server:historical")).toBeInTheDocument();
    expect(screen.getByText("server:revalidated")).toBeInTheDocument();
    expect(screen.getByText("server:current")).toBeInTheDocument();
  });

  it.each([
    ["expired", "Thread expired at 2026-09-07T00:00:00Z"],
    ["unknown", "Unknown investigation thread"],
    ["deleted", "Thread was deleted by operator-a"],
    ["mismatch", "Thread belongs to a different principal"],
  ])(
    "uses the same non-disclosing reset UI for a server-returned %s thread",
    async (reason, serverMessage) => {
      investigateCanonical.mockClear();
      window.sessionStorage.clear();
      window.sessionStorage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
        thread_id: "thr-55555555555555555555555555555555",
        thread_revision: 4,
      }));
      investigateCanonical.mockRejectedValueOnce(new ApiError(
        404,
        "not_found",
        serverMessage,
        { field: "thread_id", reason },
      ));

      render(
        <ScopeProvider>
          <ThreadContinuityProvider>
            <CopilotDrawer
              open
              onClose={vi.fn()}
              contextLabel="Inventory"
              requestedScope={{ subscription: ["sub-a"] }}
              snapshot={canonicalSnapshot("os")}
              starterQuestions={[{ label: "Continue investigation" }]}
            />
          </ThreadContinuityProvider>
        </ScopeProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: /^Continue investigation/ }));

      expect(await screen.findByText(
        "This investigation is no longer available. Start a new investigation to continue.",
      )).toBeInTheDocument();
      expect(screen.queryByText(serverMessage)).not.toBeInTheDocument();
      expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
      expect(investigateCanonical).toHaveBeenCalledWith(
        expect.objectContaining({
          thread_id: "thr-55555555555555555555555555555555",
        }),
        { subscription: ["sub-a"] },
      );
    },
  );

  it("keeps deterministic current-page evidence visible when optional narration is unavailable", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const result = canonicalResult(
      "thr-66666666666666666666666666666666",
      "server:current-page",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        status: "partial",
        policy_status: "fallback",
        fallback_reason: "narration_provider_unavailable",
        tool_results: [{
          call_id: "0:0:inventory_data_health:inventory_resources",
          specialist_id: "inventory_data_health",
          tool: "inventory_resources",
          status: "ok",
          data: { finding: "Current deterministic finding" },
          evidence: [],
          warning: "",
        }],
        uncertainty: ["Optional narration provider unavailable; deterministic evidence retained."],
        citations: [{
          ...result.data.citations[0],
          citation_id: "server:current-page",
          status: "current",
        }],
      },
    });

    render(
      <ScopeProvider>
        <ThreadContinuityProvider>
          <CopilotDrawer
            open
            onClose={vi.fn()}
            contextLabel="Inventory"
            requestedScope={{ subscription: ["sub-a"] }}
            snapshot={canonicalSnapshot("azure")}
            starterQuestions={[{ label: "Review current evidence" }]}
          />
        </ThreadContinuityProvider>
      </ScopeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Review current evidence/ }));

    expect(await screen.findByText("Current deterministic finding")).toBeInTheDocument();
    expect(screen.getByText(
      "Optional narration provider unavailable; deterministic evidence retained.",
    )).toBeInTheDocument();
    expect(screen.getByText(
      "Showing governed results directly because optional narration is unavailable.",
    )).toBeInTheDocument();
    expect(screen.getByText("Current evidence")).toBeInTheDocument();
    expect(screen.getByText("server:current-page")).toBeInTheDocument();
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
    const storedKey = window.sessionStorage.key(0);
    expect(storedKey).toMatch(/^aiops\.copilot\.thread\.inventory\./);
    expect(window.sessionStorage.getItem(storedKey!)).toBe(threadId);

    render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).toMatchObject({ thread_id: threadId });
  });

  it("clears an expired opaque thread so retry starts a new server thread", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const expiredThread = "thr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const replacementThread = "thr-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
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
    investigateCanonical.mockResolvedValueOnce({
      ...canonicalResult(expiredThread, "server:seed"),
      data: {
        ...canonicalResult(expiredThread, "server:seed").data,
        citations: [],
      },
    });
    const seeded = render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    await waitFor(() => expect(window.sessionStorage).toHaveLength(1));
    seeded.unmount();

    investigateCanonical.mockReset();
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

    render(
      <ScopeProvider>
        <CopilotDrawer {...props} />
      </ScopeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    expect(await screen.findByText("Investigation thread not found")).toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).not.toHaveProperty("thread_id");
    expect(window.sessionStorage).toHaveLength(1);
    expect(window.sessionStorage.getItem(window.sessionStorage.key(0)!)).toBe(replacementThread);
  });

  it("redacts transcript and thread when scope narrows", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    investigateCanonical.mockResolvedValue(
      canonicalResult("thr-11111111111111111111111111111111", "server:wide"),
    );
    const props = {
      open: true,
      onClose: vi.fn(),
      contextLabel: "Inventory",
      requestedScope: { subscription: ["sub-a", "sub-b"] },
      snapshot: canonicalSnapshot("os"),
      starterQuestions: [{ label: "Review inventory" }],
    };
    const view = render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    expect(await screen.findByText("server:wide")).toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(1);

    view.rerender(
      <ScopeProvider>
        <CopilotDrawer
          {...props}
          requestedScope={{ subscription: ["sub-a"] }}
        />
      </ScopeProvider>,
    );

    expect(screen.queryByText("server:wide")).not.toBeInTheDocument();
    await waitFor(() => expect(window.sessionStorage).toHaveLength(0));
    expect(screen.getByText(/Answers stay scoped/)).toBeInTheDocument();
  });

  it("redacts transcript and thread when the inventory tab changes", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    investigateCanonical.mockResolvedValue(
      canonicalResult("thr-22222222222222222222222222222222", "server:os"),
    );
    const props = {
      open: true,
      onClose: vi.fn(),
      contextLabel: "Inventory",
      requestedScope: { subscription: ["sub-a"] },
      snapshot: canonicalSnapshot("os"),
      starterQuestions: [{ label: "Review inventory" }],
    };
    const view = render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    expect(await screen.findByText("server:os")).toBeInTheDocument();

    view.rerender(
      <ScopeProvider>
        <CopilotDrawer {...props} snapshot={canonicalSnapshot("software")} />
      </ScopeProvider>,
    );

    expect(screen.queryByText("server:os")).not.toBeInTheDocument();
    await waitFor(() => expect(window.sessionStorage).toHaveLength(0));
  });

  it("ignores an in-flight response from the previous context", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    let resolveRequest: ((value: ReturnType<typeof canonicalResult>) => void) | undefined;
    investigateCanonical.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    const props = {
      open: true,
      onClose: vi.fn(),
      contextLabel: "Inventory",
      requestedScope: { subscription: ["sub-a"] },
      snapshot: canonicalSnapshot("os"),
      starterQuestions: [{ label: "Review inventory" }],
    };
    const view = render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    expect(screen.getByText(/Gathering the visible page evidence/)).toBeInTheDocument();
    view.rerender(
      <ScopeProvider>
        <CopilotDrawer {...props} snapshot={canonicalSnapshot("azure")} />
      </ScopeProvider>,
    );
    resolveRequest?.(
      canonicalResult("thr-33333333333333333333333333333333", "server:stale"),
    );

    await waitFor(() => {
      expect(screen.queryByText(/Gathering the visible page evidence/)).not.toBeInTheDocument();
    });
    expect(screen.queryByText("server:stale")).not.toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(0);
  });

  it("serializes requests within the same context", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    investigateCanonical.mockReturnValue(new Promise(() => undefined));
    const props = {
      open: true,
      onClose: vi.fn(),
      contextLabel: "Inventory",
      requestedScope: { subscription: ["sub-a"] },
      snapshot: canonicalSnapshot("os"),
      starterQuestions: [{ label: "Review inventory" }],
    };
    render(<ScopeProvider><CopilotDrawer {...props} /></ScopeProvider>);

    const starter = screen.getByRole("button", { name: /Review inventory/ });
    fireEvent.click(starter);
    fireEvent.click(starter);
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Concurrent question" },
    });
    fireEvent.keyDown(screen.getByRole("textbox"), {
      key: "Enter",
      code: "Enter",
    });

    expect(investigateCanonical).toHaveBeenCalledTimes(1);
    expect(starter).toBeDisabled();
  });
});
