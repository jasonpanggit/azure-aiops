import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  COPILOT_THREAD_STORAGE_KEY,
  ThreadContinuityProvider,
  useThreadContinuity,
} from "@/lib/copilot/thread-context";
import { normalizeCopilotSnapshotV2, type CanonicalCopilotResult } from "@/lib/copilot/page-adapters";
import { ScopeProvider } from "@/lib/scope-context";
import { ApiError, type EvidenceItem } from "@/lib/types";
import { CopilotDrawer } from "./CopilotDrawer";

const { investigateCanonical } = vi.hoisted(() => ({ investigateCanonical: vi.fn() }));
vi.mock("@/lib/copilot/page-adapters", async () => {
  const actual = await vi.importActual<typeof import("@/lib/copilot/page-adapters")>("@/lib/copilot/page-adapters");
  return { ...actual, investigateCanonical };
});
vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return {
    ...actual,
    investigateCanonical,
    copilotApi: {
      ...actual.copilotApi,
      investigate: (
        question: string,
        scope: Record<string, string[]>,
        options: {
          sessionId?: string;
          tool?: string;
          toolArguments?: Record<string, unknown>;
        },
      ) => investigateCanonical(
        {
          contract_version: "1",
          question,
          requested_scope: scope,
          ...(options.sessionId ? { thread_id: options.sessionId } : {}),
          ...(options.tool
            ? {
                hint: {
                  specialist_id: options.tool.startsWith("cve")
                    ? "vulnerability"
                    : "server-routed",
                  tool: options.tool,
                  arguments: options.toolArguments ?? {},
                },
              }
            : {}),
        },
        scope,
      ),
    },
  };
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

  function canonicalResult(
    threadId: string,
    citationId: string,
  ): {
    data: CanonicalCopilotResult;
    evidence: EvidenceItem[];
    warnings: string[];
  } {
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

  it.each(["governance", "identity", "finops"] as const)(
    "retains %s page context, reviewed hints and exact thread revisions",
    async (pageKind) => {
      const nativeSnapshot = normalizeCopilotSnapshotV2({
        ...canonicalSnapshot("azure"),
        page_kind: pageKind,
        page_id: pageKind,
        evidence: [],
      });
      const specialist = pageKind === "identity" ? "identity_access" : pageKind;
      const tool = `${pageKind}_summary`;
      const threadId = "thr-ffffffffffffffffffffffffffffffff";
      investigateCanonical.mockResolvedValue(canonicalResult(threadId, "native:source"));
      render(
        <TestProviders>
          <CopilotDrawer
            open onClose={vi.fn()} snapshot={nativeSnapshot}
            requestedScope={{ subscription: ["visible"] }}
            starterQuestions={[{
              label: "Summarize current evidence",
              specialistId: specialist, tool, toolArguments: {},
            }]}
          />
        </TestProviders>,
      );
      fireEvent.click(screen.getByRole("button", { name: /Summarize current evidence/ }));
      await waitFor(() => expect(investigateCanonical).toHaveBeenCalledWith(
        expect.objectContaining({
          snapshot: nativeSnapshot,
          requested_scope: { subscription: ["visible"] },
          hint: { specialist_id: specialist, tool, arguments: {} },
        }),
        { subscription: ["visible"] },
      ));
      await waitFor(() => expect(screen.getByLabelText("root continuity")).toHaveTextContent(threadId));
      fireEvent.change(screen.getByRole("textbox"), { target: { value: "What is uncertain?" } });
      fireEvent.click(screen.getByRole("button", { name: /^Send$/ }));
      await waitFor(() => expect(investigateCanonical).toHaveBeenLastCalledWith(
        expect.objectContaining({
          question: "What is uncertain?", snapshot: nativeSnapshot,
          thread_id: threadId, expected_thread_revision: 1,
        }),
        { subscription: ["visible"] },
      ));
      expect(investigateCanonical.mock.calls.at(-1)?.[0]).not.toHaveProperty("hint");
    },
  );

  it("keeps the page snapshot local and renders server-grounded citations", async () => {
    const result = canonicalResult(
      "thr-ffffffffffffffffffffffffffffffff",
      "server:network",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        policy_status: "fallback",
        fallback_reason: "planner_unavailable",
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
      }),
      {},
    ));
    expect(investigateCanonical).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Firewall bypass")).toBeInTheDocument();
    const citations = screen.getByRole("button", { name: "Citations (1)" });
    expect(citations).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(citations);
    expect(citations).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("server:network")).toBeVisible();
  });

  it("keeps legacy snapshots local and submits retained opaque continuity", async () => {
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
      }),
      { subscription: ["sub-a"] },
    ));
    const request = investigateCanonical.mock.calls.at(-1)?.[0];
    expect(request).not.toHaveProperty("snapshot");
    expect(request).not.toHaveProperty("expected_thread_revision");
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
    expect(request).not.toHaveProperty("snapshot");
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
    expect(screen.getByLabelText("Investigation coverage")).toHaveTextContent(
      "1 of 4 visible recordsPartial coverage",
    );
    expect(screen.getByText("visible subset is incomplete")).toBeInTheDocument();
    expect(screen.getByText("inventory:azure:stable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute/i })).not.toBeInTheDocument();
  });

  it("renders a degraded direct answer whose material facts cite retained evidence", async () => {
    const result = canonicalResult(
      "thr-33333333333333333333333333333333",
      "retained:selection:kb-current",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        status: "partial",
        policy_status: "fallback",
        fallback_reason: "planner_unavailable",
        uncertainty: [
          "visible subset is incomplete",
          "Foundry narration unavailable; retained current page evidence was used.",
        ],
        coverage: { visible_count: 1, total_count: 137, complete: false },
        synthesis: {
          status: "degraded",
          reason: "deterministic_page_evidence",
          domain_count: 1,
          claims: [{
            finding_id: "page:kb-current",
            summary:
              "KB5001 applies to Windows Server 2022, was published 2026-09-01, targets 2026-09-30, and affects 137 servers.",
            evidence_refs: ["retained:selection:kb-current"],
            confidence: "high",
            freshness: "fresh",
            uncertainty: ["visible subset is incomplete"],
          }],
          warning:
            "Foundry narration unavailable; retained current page evidence was used.",
        },
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="KB5001"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={snapshot}
          starterQuestions={[{ label: "Explain this KB" }]}
        />
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Explain this KB/ }));

    expect(await screen.findByText(/KB5001 applies to Windows Server 2022/)).toBeInTheDocument();
    expect(screen.getByText("retained:selection:kb-current")).toBeInTheDocument();
    expect(screen.getAllByText(/Foundry narration unavailable/)).toHaveLength(1);
    expect(screen.getByText("About this response")).toBeInTheDocument();
    expect(screen.getByLabelText("Investigation coverage")).toHaveTextContent(
      "1 of 137 visible recordsPartial coverage",
    );
  });

  it("renders deterministic highest-risk Compliance claims above raw tool evidence", async () => {
    const result = canonicalResult(
      "thr-44444444444444444444444444444444",
      "retained:compliance:critical",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        status: "partial",
        policy_status: "fallback",
        fallback_reason: "candidate_rejected:invalid_arguments",
        selected_specialists: ["vulnerability", "governance"],
        selected_tools: ["cve_exposure", "risk_context"],
        tool_results: [{
          call_id: "vulnerability:cve_exposure",
          specialist_id: "vulnerability",
          tool: "cve_exposure",
          status: "ok",
          data: { total_count: 7121 },
          evidence: [],
          warning: "",
        }],
        uncertainty: [
          "governance risk_context tool status is unavailable: The semantic provider is deferred",
        ],
        coverage: { visible_count: 153, total_count: 153, complete: false },
        synthesis: {
          status: "deterministic",
          reason: "deterministic_page_evidence",
          domain_count: 1,
          claims: [{
            finding_id: "page:critical",
            summary:
              "The current compliance page reports severity critical: Firewall rule accepts any source.",
            evidence_refs: ["retained:compliance:critical"],
            confidence: "medium",
            freshness: "unknown",
            uncertainty: ["visible subset is incomplete"],
          }],
          warning: "",
        },
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Compliance"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={snapshot}
          starterQuestions={[{
            label: "What are my highest-risk compliance findings?",
          }]}
        />
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", {
      name: /What are my highest-risk compliance findings/i,
    }));

    expect(await screen.findByText(
      /The current compliance page reports severity critical/,
    )).toBeInTheDocument();
    expect(screen.getByText("retained:compliance:critical")).toBeInTheDocument();
    expect(screen.getByText(
      /governance risk_context tool status is unavailable/,
    )).toBeInTheDocument();
    expect(screen.queryByText("7,121")).not.toBeInTheDocument();
  });

  it.each([
    { model: "gpt-5.4-mini", agent: "aiops-network-agent", version: "1", foundry: true },
    { model: "deterministic", agent: "operations-copilot", version: "", foundry: false },
  ])("renders the same retained compatibility answer in the Insights follow-up: $model", async ({
    model, agent, version, foundry,
  }) => {
    const result = canonicalResult("thr-12121212121212121212121212121212", "tool:network:one");
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        policy_status: "fallback",
        fallback_reason: "compatibility_rollout",
        uncertainty: ["Incidents evidence is unavailable."],
        synthesis: {
          status: "compatibility", reason: "retained_compatibility",
          domain_count: 0, claims: [], warning: "",
          compatibility_answer: {
            text: "Only the current topology evidence can be evaluated.",
            agent_name: agent, agent_version: version, model, grounded: true,
          },
        },
      },
    });
    render(
      <TestProviders>
        <CopilotDrawer open onClose={vi.fn()} snapshot={snapshot}
          starterQuestions={[{ label: "Summarize this view" }]} />
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Summarize this view/ }));

    expect(await screen.findByText("Only the current topology evidence can be evaluated.")).toBeInTheDocument();
    expect(screen.getByText(model)).toBeInTheDocument();
    expect(screen.getByText("Incidents evidence is unavailable.")).toBeInTheDocument();
    if (foundry) {
      expect(screen.getByText(`Narrated by ${agent}.`)).toBeInTheDocument();
      expect(screen.queryByText("Deterministic evidence is shown. Optional narration is unavailable.")).not.toBeInTheDocument();
    } else {
      expect(screen.queryByText(`Narrated by ${agent}.`)).not.toBeInTheDocument();
      expect(screen.getByText("Deterministic evidence is shown. Optional narration is unavailable.")).toBeInTheDocument();
    }
  });

  it("recognizes provider provenance on the deployed legacy follow-up response", async () => {
    investigateCanonical.mockResolvedValue({
      data: {
        question: "Summarize this view", fact_status: "ok",
        policy_status: "fallback", fallback_reason: "compatibility_rollout",
        tool_calls: [], warnings: [],
        answer: {
          text: "The provider confirms an isolated network.",
          agent_name: "aiops-network-agent", agent_version: "1",
          model: "gpt-5.4-mini", grounded: true,
        },
        synthesis: {
          status: "compatibility", reason: "retained_compatibility",
          domain_count: 0, claims: [], warning: "",
        },
      },
      evidence: [], warnings: [],
    });
    render(
      <TestProviders>
        <CopilotDrawer open onClose={vi.fn()} snapshot={snapshot}
          starterQuestions={[{ label: "Summarize this view" }]} />
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Summarize this view/ }));

    expect(await screen.findByText("The provider confirms an isolated network.")).toBeInTheDocument();
    expect(screen.getByText("Narrated by aiops-network-agent.")).toBeInTheDocument();
    expect(screen.queryByText("Deterministic evidence is shown. Optional narration is unavailable.")).not.toBeInTheDocument();
  });

  it("renders canonical synthesis claims without duplicating their tool result cards", async () => {
    const result = canonicalResult(
      "thr-12121212121212121212121212121212",
      "tool:evidence:one",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        policy_status: "fallback",
        fallback_reason: "planner_unavailable",
        tool_results: [{
          call_id: "network:0",
          specialist_id: "network",
          tool: "network_topology",
          status: "ok",
          data: { summary: "The payments service depends on hub-vnet." },
          evidence: [{ evidence_id: "tool:evidence:one" }],
          warning: "",
        }],
        synthesis: {
          status: "synthesized",
          reason: "cross_domain",
          domain_count: 2,
          coordinator: {
            name: "operations-copilot",
            version: "provider-version-1234567890-extra",
            planned: true,
          },
          claims: [{
            finding_id: "finding:payments-path",
            summary: "The payments service depends on hub-vnet.",
            evidence_refs: ["tool:evidence:one"],
            confidence: "high",
            freshness: "fresh",
            uncertainty: [],
          }],
          warning: "",
        },
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Network"
          snapshot={snapshot}
          starterQuestions={[{ label: "Summarize dependencies" }]}
        />
      </TestProviders>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Summarize dependencies/ }));

    expect(await screen.findByText("The payments service depends on hub-vnet.")).toBeInTheDocument();
    expect(screen.getByText("tool:evidence:one")).toBeInTheDocument();
    expect(screen.getByText("Narrated by operations-copilot.")).toBeInTheDocument();
    expect(screen.getByText("Foundry · vprovider-version-1234567890-extra")).toBeInTheDocument();
    expect(
      screen.getByTitle("Foundry · vprovider-version-1234567890-extra"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Optional narration is unavailable/)).not.toBeInTheDocument();
    expect(screen.getByText("Planning fallback")).toBeInTheDocument();
    expect(screen.getByText(/planner_unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("network_topology")).not.toBeInTheDocument();
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

  it("clears stale CAS continuity so the next explicit attempt starts a new thread", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    const staleThread = "thr-34343434343434343434343434343434";
    const replacementThread = "thr-56565656565656565656565656565656";
    window.sessionStorage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: staleThread,
      thread_revision: 3,
    }));
    investigateCanonical
      .mockRejectedValueOnce(new ApiError(
        409,
        "conflict",
        "Investigation thread revision conflict; current revision is 9",
        { field: "expected_thread_revision", current_revision: 9 },
      ))
      .mockResolvedValueOnce(
        canonicalResult(replacementThread, "server:new-thread"),
      );

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Inventory"
          requestedScope={{ subscription: ["sub-a"] }}
          snapshot={canonicalSnapshot("os")}
          starterQuestions={[{ label: "Review after conflict" }]}
        />
      </TestProviders>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("root continuity")).toHaveTextContent(staleThread);
    });
    fireEvent.click(screen.getByRole("button", { name: /Review after conflict/ }));

    expect(await screen.findByText(
      "This investigation changed in another request. Start a new investigation to continue.",
    )).toBeInTheDocument();
    expect(screen.queryByText(/current revision is 9/i)).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    expect(screen.getByLabelText("root continuity")).toHaveTextContent("none");

    fireEvent.click(screen.getByRole("button", { name: /Review after conflict/ }));
    await waitFor(() => expect(investigateCanonical).toHaveBeenCalledTimes(2));
    expect(investigateCanonical.mock.calls[1][0]).not.toHaveProperty("thread_id");
    expect(investigateCanonical.mock.calls[1][0]).not.toHaveProperty(
      "expected_thread_revision",
    );
    expect(await screen.findByText("server:new-thread")).toBeInTheDocument();
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

  it("ignores a stale CVE response after the visible route switches", async () => {
    investigateCanonical.mockClear();
    window.sessionStorage.clear();
    let resolveOldRequest:
      | ((value: ReturnType<typeof canonicalResult>) => void)
      | undefined;
    investigateCanonical
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveOldRequest = resolve;
      }))
      .mockResolvedValueOnce({
        ...canonicalResult(
          "thr-55555555555555555555555555555555",
          "tool:cve-new:0",
        ),
        data: {
          ...canonicalResult(
            "thr-55555555555555555555555555555555",
            "tool:cve-new:0",
          ).data,
          synthesis: {
            status: "degraded",
            reason: "deterministic_page_evidence",
            domain_count: 1,
            warning: "Foundry narration is not configured; deterministic cited CVE evidence was used.",
            claims: [{
              finding_id: "cve:new",
              summary: "CVE-2026-13221 current evidence",
              evidence_refs: ["tool:cve-new:0"],
              confidence: "high",
              freshness: "fresh",
              uncertainty: [],
            }],
          },
        },
      });
    const oldSnapshot = {
      ...canonicalSnapshot("os"),
      page_kind: "vulnerability" as const,
      page_id: "cve:CVE-2026-11111",
    };
    const newSnapshot = {
      ...canonicalSnapshot("software"),
      page_kind: "vulnerability" as const,
      page_id: "cve:CVE-2026-13221",
    };
    const view = render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="CVE-2026-11111"
          snapshot={oldSnapshot}
          starterQuestions={[{
            label: "Explain CVE-2026-11111",
            specialistId: "vulnerability",
            tool: "cve_detail",
            toolArguments: { cve_id: "CVE-2026-11111" },
          }]}
        />
      </TestProviders>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Explain CVE-2026-11111/ }));
    view.rerender(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="CVE-2026-13221"
          snapshot={newSnapshot}
          starterQuestions={[{
            label: "Explain CVE-2026-13221",
            specialistId: "vulnerability",
            tool: "cve_detail",
            toolArguments: { cve_id: "CVE-2026-13221" },
          }]}
        />
      </TestProviders>,
    );
    resolveOldRequest?.({
      ...canonicalResult(
        "thr-44444444444444444444444444444444",
        "tool:cve-old:0",
      ),
      data: {
        ...canonicalResult(
          "thr-44444444444444444444444444444444",
          "tool:cve-old:0",
        ).data,
        synthesis: {
          status: "degraded",
          reason: "deterministic_page_evidence",
          domain_count: 1,
          warning: "Foundry narration timed out; deterministic cited CVE evidence was used.",
          claims: [{
            finding_id: "cve:old",
            summary: "CVE-2026-11111 stale evidence",
            evidence_refs: ["tool:cve-old:0"],
            confidence: "high",
            freshness: "fresh",
            uncertainty: [],
          }],
        },
      },
    });

    await waitFor(() => {
      expect(screen.queryByText("CVE-2026-11111 stale evidence")).not.toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Explain CVE-2026-13221/ }));
    expect(await screen.findByText("CVE-2026-13221 current evidence")).toBeInTheDocument();
    expect(
      screen.getByText(/Deterministic evidence is shown/, {
        selector: ".copilot-live-status",
      }),
    ).toBeInTheDocument();
    expect(investigateCanonical.mock.calls[1][0]).toMatchObject({
      question: "Explain CVE-2026-13221",
      hint: {
        specialist_id: "vulnerability",
        tool: "cve_detail",
        arguments: { cve_id: "CVE-2026-13221" },
      },
    });
  });

  it("renders durable CVE evidence when optional semantic narration is unavailable", async () => {
    const cveId = "CVE-2026-8376";
    const cveSnapshot = {
      version: "2" as const,
      page_kind: "vulnerability" as const,
      page_id: `cve:${cveId}`,
      filters: { weakness_id: [cveId] },
      coverage: { visible_count: 1, total_count: 1, complete: true },
      freshness: [{
        source: "nvd",
        observed_at: "2026-09-14T00:00:00Z",
        status: "fresh" as const,
      }],
      selected_entities: [{
        type: "domain" as const,
        namespace: "vulnerability",
        kind: "cve",
        source_key: cveId,
      }],
      evidence: [],
      material_claims: [],
    };
    const result = canonicalResult(
      "thr-66666666666666666666666666666666",
      "tool:cve-deferred:0",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        selected_specialists: ["vulnerability"],
        selected_tools: ["cve_detail"],
        tool_results: [{
          call_id: "cve-deferred",
          specialist_id: "vulnerability",
          tool: "cve_detail",
          status: "ok",
          data: { cve_id: cveId },
          evidence: [],
          warning: "",
        }],
        synthesis: {
          status: "degraded",
          reason: "deterministic_page_evidence",
          domain_count: 1,
          warning: "Foundry narration is not configured; deterministic cited CVE evidence was used.",
          claims: [{
            finding_id: "cve:deferred",
            summary: `${cveId} durable CVE evidence`,
            evidence_refs: ["tool:cve-deferred:0"],
            confidence: "high",
            freshness: "fresh",
            uncertainty: [],
          }],
        },
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel={cveId}
          snapshot={cveSnapshot}
          starterQuestions={[{
            label: `Explain ${cveId}`,
            specialistId: "vulnerability",
            tool: "cve_detail",
            toolArguments: { cve_id: cveId },
          }]}
        />
      </TestProviders>,
    );

    fireEvent.click(screen.getByRole("button", { name: `Explain ${cveId} →` }));

    expect(await screen.findByText(`${cveId} durable CVE evidence`)).toBeInTheDocument();
    expect(screen.getByText(/Deterministic evidence is shown/, {
      selector: ".copilot-live-status",
    })).toBeInTheDocument();
    expect(screen.queryByText(/The request failed/)).not.toBeInTheDocument();
    expect(screen.queryByText(/semantic provider is deferred/i)).not.toBeInTheDocument();
    expect(investigateCanonical).toHaveBeenCalledWith(
      expect.objectContaining({
        question: `Explain ${cveId}`,
        hint: {
          specialist_id: "vulnerability",
          tool: "cve_detail",
          arguments: { cve_id: cveId },
        },
      }),
      {},
    );
  });

  it("renders retained-rollout deterministic CVE claims instead of raw-only fallback", async () => {
    const cveId = "CVE-2026-13221";
    const result = canonicalResult(
      "thr-77777777777777777777777777777777",
      "tool:cve-retained:0",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        policy_status: "fallback",
        fallback_reason: "compatibility_rollout",
        selected_specialists: [],
        selected_tools: ["cve_detail"],
        tool_results: [{
          call_id: "cve-retained",
          specialist_id: "",
          tool: "cve_detail",
          status: "ok",
          data: {
            cve_id: cveId,
            scoped_exposure: { total_count: 37, returned_count: 25 },
          },
          evidence: [],
          warning: "",
        }],
        synthesis: {
          status: "degraded",
          reason: "retained_compatibility",
          domain_count: 1,
          warning: "Foundry narration is not configured; deterministic cited CVE evidence was used.",
          claims: [{
            finding_id: "compatibility:cve-2026-13221",
            summary: [
              `**${cveId}: what is known**`,
              "",
              "- NVD reports **CVSS 9.1 Critical** with vector `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:H`.",
              "- EPSS estimates **0.432%** exploitation probability at the 36.545th percentile.",
              `- The current CISA KEV lookup has **no listing for ${cveId}**.`,
              "- No KB association is present in the current CVE metadata.",
              "- The current scope contains **37** matching findings; **25 records were inspected**. **37 are active**.",
              "",
              "**What is not known**",
              "",
              "- The running workload impact is unknown because the inspected findings contain no represented workload mapping.",
            ].join("\n"),
            evidence_refs: ["tool:cve-retained:0"],
            confidence: "medium",
            freshness: "fresh",
            uncertainty: ["visible subset is incomplete"],
          }],
        },
      },
    });
    const snapshot = {
      ...canonicalSnapshot("software"),
      page_kind: "vulnerability" as const,
      page_id: `cve:${cveId}`,
      filters: { weakness_id: [cveId] },
    };

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel={cveId}
          snapshot={snapshot}
          starterQuestions={[{
            label: `Explain ${cveId}`,
            specialistId: "vulnerability",
            tool: "cve_detail",
            toolArguments: { cve_id: cveId },
          }]}
        />
      </TestProviders>,
    );

    fireEvent.click(screen.getByRole("button", { name: new RegExp(`Explain ${cveId}`) }));

    expect(await screen.findByText(/CVSS 9.1 Critical/)).toBeInTheDocument();
    expect(screen.getByText(/0.432%/)).toBeInTheDocument();
    expect(screen.getByText(/no listing for CVE-2026-13221/)).toBeInTheDocument();
    expect(screen.getByText(/No KB association/)).toBeInTheDocument();
    expect(screen.getByText((_, element) =>
      element?.tagName === "LI"
      && element.textContent?.includes("37 matching findings") === true,
    )).toBeInTheDocument();
    expect(screen.getByText(/running workload impact is unknown/)).toBeInTheDocument();
    expect(screen.getByText("tool:cve-retained:0")).toBeInTheDocument();
    expect(screen.queryByText(/Showing governed results directly/)).not.toBeInTheDocument();
  });

  it("renders retained Network findings as a readable cited answer instead of a raw tool card", async () => {
    const result = canonicalResult(
      "thr-88888888888888888888888888888888",
      "tool:network-retained:0",
    );
    investigateCanonical.mockResolvedValue({
      ...result,
      data: {
        ...result.data,
        policy_status: "fallback",
        fallback_reason: "compatibility_rollout",
        selected_specialists: ["network"],
        selected_tools: ["firewall_nsg_gaps"],
        tool_results: [{
          call_id: "network-retained",
          specialist_id: "network",
          tool: "firewall_nsg_gaps",
          status: "ok",
          data: {
            gaps: [{ title: "Spoke bypasses hub firewall" }],
            rule_findings: [{ title: "NSG permits unrestricted inbound traffic" }],
          },
          evidence: [],
          warning: "",
        }],
        synthesis: {
          status: "degraded",
          reason: "retained_compatibility",
          domain_count: 1,
          coordinator: {
            name: "operations-copilot",
            version: "5",
            planned: false,
          },
          warning: "Foundry narration is not configured; deterministic cited network evidence was used.",
          claims: [{
            finding_id: "network:inspection",
            summary: "Network evidence reports 1 inspection gap and 1 firewall/NSG rule finding. Highest-priority findings: Spoke bypasses hub firewall (critical, payments-spoke); NSG permits unrestricted inbound traffic (high, payments-nsg).",
            evidence_refs: ["tool:network-retained:0"],
            confidence: "high",
            freshness: "fresh",
            uncertainty: [],
          }],
        },
      },
    });

    render(
      <TestProviders>
        <CopilotDrawer
          open
          onClose={vi.fn()}
          contextLabel="Network paths"
          snapshot={snapshot}
          starterQuestions={[{
            label: "Show inspection bypass paths.",
            specialistId: "network",
            tool: "firewall_nsg_gaps",
            toolArguments: {},
          }]}
        />
      </TestProviders>,
    );

    fireEvent.click(screen.getByRole("button", { name: /Show inspection bypass paths/ }));

    expect(await screen.findByText(/1 inspection gap/)).toBeInTheDocument();
    expect(screen.getByText(/Spoke bypasses hub firewall/)).toBeInTheDocument();
    expect(screen.getByText(/NSG permits unrestricted inbound traffic/)).toBeInTheDocument();
    expect(screen.getByText("tool:network-retained:0")).toBeInTheDocument();
    expect(screen.getByText("About this response")).toBeInTheDocument();
    expect(screen.getByText(/Coordinator: operations-copilot · v5/)).toBeInTheDocument();
    expect(screen.getByText(/Planning fallback: compatibility_rollout/)).toBeInTheDocument();
    expect(screen.queryByText(/Showing governed results directly/)).not.toBeInTheDocument();
    expect(screen.queryByText("firewall_nsg_gaps")).not.toBeInTheDocument();
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
