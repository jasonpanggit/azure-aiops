import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  COPILOT_THREAD_STORAGE_KEY,
  ThreadContinuityProvider,
  useThreadContinuity,
} from "@/lib/copilot/thread-context";
import { ScopeProvider } from "@/lib/scope-context";
import { ApiError } from "@/lib/types";
import { CopilotDrawer } from "./CopilotDrawer";

const { investigateCanonical } = vi.hoisted(() => ({ investigateCanonical: vi.fn() }));
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

class DrawerTestLockManager {
  private readonly held = new Set<string>();

  request(
    name: string,
    _options: LockOptions,
    callback: (lock: Lock | null) => unknown,
  ): Promise<unknown> {
    if (this.held.has(name)) {
      return Promise.resolve(callback(null));
    }
    this.held.add(name);
    return Promise.resolve(callback({
      name,
      mode: "exclusive",
    } as Lock)).finally(() => {
      this.held.delete(name);
    });
  }
}

function RootContinuityMarker() {
  const continuity = useThreadContinuity();
  return (
    <output aria-label="root continuity">
      {continuity.thread?.threadId ?? "none"}
    </output>
  );
}

function TestProviders({ children }: { children: ReactNode }) {
  return (
    <ScopeProvider>
      <ThreadContinuityProvider>
        <RootContinuityMarker />
        {children}
      </ThreadContinuityProvider>
    </ScopeProvider>
  );
}

function SessionEndControl({ children }: { children: ReactNode }) {
  const continuity = useThreadContinuity();
  return (
    <>
      <output aria-label="active continuity">
        {continuity.thread?.threadId ?? "none"}
      </output>
      <output aria-label="continuity reset reason">
        {continuity.resetReason ?? "none"}
      </output>
      <button
        type="button"
        onClick={() => continuity.resetContinuity("session_end")}
      >
        End session
      </button>
      {children}
    </>
  );
}

describe("CopilotDrawer", () => {
  beforeEach(() => {
    investigateCanonical.mockReset();
    window.sessionStorage.clear();
    const lockManager = new DrawerTestLockManager();
    vi.stubGlobal("navigator", Object.create(
      globalThis.navigator,
      { locks: { configurable: true, value: lockManager } },
    ));
    vi.stubGlobal("crypto", {
      subtle: {
        digest: async (_algorithm: string, value: BufferSource) => {
          const input = new Uint8Array(value as ArrayBuffer);
          const output = new Uint8Array(32);
          input.forEach((byte, index) => {
            output[index % output.length] ^= byte;
          });
          return output.buffer;
        },
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function canonicalSnapshot(tab: "os" | "software" | "azure") {
    const sourceKey = `${tab}-context`;
    return {
      version: "2" as const,
      page_kind: "inventory" as const,
      page_id: "inventory" as const,
      coverage: { visible_count: 1, total_count: 1, complete: true },
      freshness: [],
      selected_entities: [],
      evidence: [{
        evidence_id: `inventory:${tab}:context`,
        source: `inventory/${tab}_observations`,
        status: "ok" as const,
        observed_at: "2026-08-25T10:00:00Z",
        resource_id: "",
        source_key: sourceKey,
        entity: {
          type: "domain" as const,
          namespace: "inventory",
          kind: "context",
          source_key: sourceKey,
        },
        claim_type: "inventory-context",
        citations: [],
        selected: false,
        direct: true,
        actionable: false,
        severity: "unknown" as const,
        quality: "unknown" as const,
        data: { inventory_context: { tab, filters: {} } },
      }],
      material_claims: [],
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
    const result = canonicalResult(
      "thr-ffffffffffffffffffffffffffffffff",
      "server:network",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        tool_results: [{
          call_id: "network:0",
          specialist_id: "network",
          tool: "network_topology",
          status: "ok",
          data: { finding: "Firewall bypass" },
          evidence: [],
          warning: "",
        }],
      },
    });
    render(
      <TestProviders>
        <CopilotDrawer open onClose={vi.fn()} contextLabel="Network" snapshot={snapshot} starterQuestions={[]} />
      </TestProviders>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "What is wrong?" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledWith(
      expect.objectContaining({
        question: "What is wrong?",
        snapshot: expect.objectContaining({
          version: "2",
          page_kind: "network",
        }),
      }),
      {},
    ));
    expect(await screen.findByText("Firewall bypass")).toBeInTheDocument();
    expect(screen.getByText("server:network")).toBeInTheDocument();
  });

  it("normalizes integrated legacy snapshots and submits retained revision CAS", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const threadId = "thr-dddddddddddddddddddddddddddddddd";
    window.sessionStorage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: threadId,
      thread_revision: 4,
    }));
    investigateCanonical.mockResolvedValue({
      ...canonicalResult(threadId, "server:remediation"),
      data: {
        ...canonicalResult(threadId, "server:remediation").data,
        thread_revision: 5,
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Remediation"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={{
            ...snapshot,
            page_kind: "remediation",
            page_id: "remediation",
          }}
          starterQuestions={[{ label: "Explain remediation state" }]}
        />
      </TestProviders>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("root continuity")).toHaveTextContent(threadId);
    });
    fireEvent.click(screen.getByRole("button", { name: /Explain remediation state/ }));

    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledWith(
      expect.objectContaining({
        contract_version: "1",
        thread_id: threadId,
        expected_thread_revision: 4,
        snapshot: expect.objectContaining({
          version: "2",
          page_kind: "remediation",
          page_id: "remediation",
          selected_entities: expect.any(Array),
          material_claims: [],
        }),
      }),
      { subscription: ["sub-a"] },
    ));
    const request = investigateCanonical.mock.calls.at(-1)?.[0];
    expect(request.snapshot).not.toHaveProperty("scope");
    expect(request.snapshot).not.toHaveProperty("filters");
    expect(request.snapshot).not.toHaveProperty("question");
  });

  it("preserves first-turn compatibility by omitting thread CAS fields", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    investigateCanonical.mockResolvedValue(
      canonicalResult("thr-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "server:first"),
    );

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Network"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={snapshot}
          starterQuestions={[{ label: "Start investigation" }]}
        />
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Start investigation/ }));

    await waitFor(() => expect(investigateCanonical).toHaveBeenCalled());
    const request = investigateCanonical.mock.calls.at(-1)?.[0];
    expect(request).not.toHaveProperty("thread_id");
    expect(request).not.toHaveProperty("expected_thread_revision");
    expect(request.snapshot.version).toBe("2");
  });

  it("renders a duplicated backend warning only once", async () => {
    const warning = "Foundry narration unavailable; deterministic findings returned";
    investigateCanonical.mockResolvedValue({
      ...canonicalResult(
        "thr-11111111111111111111111111111111",
        "server:warning",
      ),
      evidence: [],
      warnings: [warning, warning],
    });
    render(
      <TestProviders>
        <CopilotDrawer open onClose={vi.fn()} contextLabel="Network" snapshot={snapshot} starterQuestions={[]} />
      </TestProviders>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "What is wrong?" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));

    await waitFor(() => expect(investigateCanonical).toHaveBeenCalled());
    expect(screen.getAllByText(warning)).toHaveLength(1);
  });

  it("does not render legacy browser finding cards on canonical responses", async () => {
    investigateCanonical.mockResolvedValue(
      canonicalResult(
        "thr-22222222222222222222222222222222",
        "server:canonical-only",
      ),
    );
    render(
      <TestProviders>
        <CopilotDrawer open onClose={vi.fn()} contextLabel="Network" snapshot={snapshot} starterQuestions={[]} />
      </TestProviders>,
    );
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Can UAT reach PROD?" } });
    fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));

    expect(await screen.findByText("server:canonical-only")).toBeInTheDocument();
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
      ...canonicalSnapshot("azure"),
      coverage: { visible_count: 1, total_count: 4, complete: false },
      evidence: [],
    };

    render(
      <TestProviders>
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
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));

    expect(await screen.findByText("Showing governed results directly because optional narration is unavailable.")).toBeInTheDocument();
    expect(screen.getByText("1 of 4 visible records")).toBeInTheDocument();
    expect(screen.getByText("visible subset is incomplete")).toBeInTheDocument();
    expect(screen.getByText("inventory:azure:stable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();
  });

  it("supports isolated direct renders without making browser continuity authoritative", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    investigateCanonical.mockResolvedValue(
      canonicalResult(
        "thr-77777777777777777777777777777777",
        "server:isolated",
      ),
    );

    render(
      <ScopeProvider>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Inventory"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={canonicalSnapshot("os")}
          starterQuestions={[{ label: "Review isolated evidence" }]}
        />
      </ScopeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Review isolated evidence/ }));

    expect(await screen.findByText("server:isolated")).toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(0);
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
            status: "ok",
            observation_status: "historical",
          },
          {
            ...result.data.citations[0],
            citation_id: "server:revalidated",
            status: "ok",
            observation_status: "revalidated",
          },
          {
            ...result.data.citations[0],
            citation_id: "server:current",
            status: "ok",
            observation_status: "current",
          },
          {
            ...result.data.citations[0],
            citation_id: "server:outcome-only",
            status: "historical",
          },
        ],
      },
    });

    render(
      <TestProviders>
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
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Review carried evidence/ }));

    expect(await screen.findByText("Historical evidence")).toBeInTheDocument();
    expect(screen.getByText("Revalidated evidence")).toBeInTheDocument();
    expect(screen.getByText("Current evidence")).toBeInTheDocument();
    expect(screen.getByText("server:historical")).toBeInTheDocument();
    expect(screen.getByText("server:revalidated")).toBeInTheDocument();
    expect(screen.getByText("server:current")).toBeInTheDocument();
    expect(screen.getByText("server:outcome-only")).toBeInTheDocument();
    expect(screen.getAllByText("Historical evidence")).toHaveLength(1);
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
        <TestProviders>
          <CopilotDrawer
            open
            onClose={vi.fn()}
            contextLabel="Inventory"
            requestedScope={{ subscription: ["sub-a"] }}
            snapshot={canonicalSnapshot("os")}
            starterQuestions={[{ label: "Continue investigation" }]}
          />
        </TestProviders>,
      );
      await waitFor(() => {
        expect(screen.getByLabelText("root continuity")).toHaveTextContent(
          "thr-55555555555555555555555555555555",
        );
      });
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

  it("discards a response that resolves after the session ends", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const threadId = "thr-88888888888888888888888888888888";
    window.sessionStorage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: threadId,
      thread_revision: 2,
    }));
    let resolveRequest:
      | ((value: ReturnType<typeof canonicalResult>) => void)
      | undefined;
    investigateCanonical.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));

    render(
      <TestProviders>
        <SessionEndControl>
          <CopilotDrawer
            open
            onClose={vi.fn()}
            contextLabel="Inventory"
            requestedScope={{ subscription: ["sub-a"] }}
            snapshot={canonicalSnapshot("os")}
            starterQuestions={[{ label: "Continue before logout" }]}
          />
        </SessionEndControl>
      </TestProviders>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("active continuity")).toHaveTextContent(threadId);
    });
    fireEvent.click(screen.getByRole("button", { name: /^Continue before logout/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledWith(
      expect.objectContaining({ thread_id: threadId }),
      { subscription: ["sub-a"] },
    ));

    fireEvent.click(screen.getByRole("button", { name: "End session" }));
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();

    await act(async () => {
      resolveRequest?.(
        canonicalResult(
          "thr-99999999999999999999999999999999",
          "server:after-logout",
        ),
      );
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.queryByText(/Gathering the visible page evidence/)).not.toBeInTheDocument();
    });
    expect(screen.queryByText("server:after-logout")).not.toBeInTheDocument();
    expect(screen.getByLabelText("active continuity")).toHaveTextContent("none");
    expect(screen.getByLabelText("continuity reset reason")).toHaveTextContent("session_end");
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
  });

  it("ignores a late thread 404 without overwriting the session-end reset", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const threadId = "thr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    window.sessionStorage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: threadId,
      thread_revision: 3,
    }));
    let rejectRequest: ((reason: unknown) => void) | undefined;
    investigateCanonical.mockReturnValue(new Promise((_resolve, reject) => {
      rejectRequest = reject;
    }));

    render(
      <TestProviders>
        <SessionEndControl>
          <CopilotDrawer
            open
            onClose={vi.fn()}
            contextLabel="Inventory"
            requestedScope={{ subscription: ["sub-a"] }}
            snapshot={canonicalSnapshot("os")}
            starterQuestions={[{ label: "Continue before rejection" }]}
          />
        </SessionEndControl>
      </TestProviders>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("active continuity")).toHaveTextContent(threadId);
    });
    fireEvent.click(screen.getByRole("button", { name: /^Continue before rejection/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "End session" }));

    await act(async () => {
      rejectRequest?.(new ApiError(
        404,
        "not_found",
        "Thread belonged to another principal",
        { field: "thread_id", reason: "mismatch" },
      ));
      await Promise.resolve();
    });

    expect(screen.getByLabelText("continuity reset reason")).toHaveTextContent("session_end");
    expect(screen.queryByText(/another principal/i)).not.toBeInTheDocument();
    expect(screen.queryByText(
      "This investigation is no longer available. Start a new investigation to continue.",
    )).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
  });

  it("prevents an unmounted drawer response from replacing the next page thread", async () => {
    investigateCanonical.mockReset();
    window.sessionStorage.clear();
    const firstThread = "thr-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const secondThread = "thr-cccccccccccccccccccccccccccccccc";
    let resolveFirst:
      | ((value: ReturnType<typeof canonicalResult>) => void)
      | undefined;
    investigateCanonical
      .mockReturnValueOnce(new Promise((resolve) => {
        resolveFirst = resolve;
      }))
      .mockResolvedValueOnce(
        canonicalResult(secondThread, "server:page-b"),
      );

    function NavigationHarness({ page }: { page: "a" | "b" }) {
      const continuity = useThreadContinuity();
      return (
        <>
          <output aria-label="navigation continuity">
            {continuity.thread?.threadId ?? "none"}
          </output>
          <CopilotDrawer
            key={page}
            open
            onClose={vi.fn()}
            contextLabel={`Page ${page.toUpperCase()}`}
            requestedScope={{ subscription: ["sub-a"] }}
            snapshot={canonicalSnapshot(page === "a" ? "os" : "software")}
            starterQuestions={[{
              label: page === "a" ? "Ask from page A" : "Ask from page B",
            }]}
          />
        </>
      );
    }

    const view = render(
      <TestProviders><NavigationHarness page="a" /></TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Ask from page A/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(1));

    view.rerender(
      <TestProviders><NavigationHarness page="b" /></TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Ask from page B/ }));
    expect(await screen.findByText("server:page-b")).toBeInTheDocument();
    expect(screen.getByLabelText("navigation continuity")).toHaveTextContent(secondThread);

    await act(async () => {
      resolveFirst?.(canonicalResult(firstThread, "server:late-page-a"));
      await Promise.resolve();
    });

    expect(screen.getByLabelText("navigation continuity")).toHaveTextContent(secondThread);
    expect(screen.getByText("server:page-b")).toBeInTheDocument();
    expect(screen.queryByText("server:late-page-a")).not.toBeInTheDocument();
    expect(JSON.parse(
      window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)!,
    )).toEqual({
      thread_id: secondThread,
      thread_revision: 1,
    });
  });

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
          status: "ok",
          observation_status: "current",
        }],
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Inventory"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={canonicalSnapshot("azure")}
          starterQuestions={[{ label: "Review current evidence" }]}
        />
      </TestProviders>,
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
      ...canonicalSnapshot("os"),
      coverage: { visible_count: 0, total_count: 0, complete: true },
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

    const first = render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(1));
    first.unmount();

    expect(window.sessionStorage).toHaveLength(1);
    const storedKey = window.sessionStorage.key(0);
    expect(storedKey).toBe(COPILOT_THREAD_STORAGE_KEY);
    expect(JSON.parse(window.sessionStorage.getItem(storedKey!)!)).toEqual({
      thread_id: threadId,
      thread_revision: 1,
    });

    render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);
    await waitFor(() => {
      expect(screen.getByLabelText("root continuity")).toHaveTextContent(threadId);
    });
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
      ...canonicalSnapshot("os"),
      coverage: { visible_count: 0, total_count: 0, complete: true },
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
    const seeded = render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);
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
      <TestProviders>
        <CopilotDrawer {...props} />
      </TestProviders>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("root continuity")).toHaveTextContent(expiredThread);
    });
    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    expect(await screen.findByText(
      "This investigation is no longer available. Start a new investigation to continue.",
    )).toBeInTheDocument();
    expect(screen.queryByText("Investigation thread not found")).not.toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory health/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).not.toHaveProperty("thread_id");
    expect(window.sessionStorage).toHaveLength(1);
    expect(JSON.parse(
      window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)!,
    )).toEqual({
      thread_id: replacementThread,
      thread_revision: 1,
    });
  });

  it("redacts the transcript and revalidates the retained thread when scope narrows", async () => {
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
    const view = render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    expect(await screen.findByText("server:wide")).toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(1);

    view.rerender(
      <TestProviders>
        <CopilotDrawer
          {...props}
          requestedScope={{ subscription: ["sub-a"] }}
        />
      </TestProviders>,
    );

    expect(screen.queryByText("server:wide")).not.toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(1);
    expect(screen.getByText(/Answers stay scoped/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).toMatchObject({
      requested_scope: { subscription: ["sub-a"] },
      thread_id: "thr-11111111111111111111111111111111",
    });
  });

  it("redacts the transcript but retains continuity when the page context changes", async () => {
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
    const view = render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    expect(await screen.findByText("server:os")).toBeInTheDocument();

    view.rerender(
      <TestProviders>
        <CopilotDrawer {...props} snapshot={canonicalSnapshot("software")} />
      </TestProviders>,
    );

    expect(screen.queryByText("server:os")).not.toBeInTheDocument();
    expect(window.sessionStorage).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).toMatchObject({
      thread_id: "thr-22222222222222222222222222222222",
      snapshot: canonicalSnapshot("software"),
    });
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
    const view = render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);

    fireEvent.click(screen.getByRole("button", { name: /Review inventory/ }));
    expect(screen.getByText(/Gathering the visible page evidence/)).toBeInTheDocument();
    view.rerender(
      <TestProviders>
        <CopilotDrawer {...props} snapshot={canonicalSnapshot("azure")} />
      </TestProviders>,
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
    render(<TestProviders><CopilotDrawer {...props} /></TestProviders>);

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
