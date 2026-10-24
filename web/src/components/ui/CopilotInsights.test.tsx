import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildCopilotSnapshot, toCanonicalInvestigationView } from "@/lib/services";
import { buildResourceHealthCopilotContext, RESOURCE_HEALTH_INSIGHT_QUESTION } from "@/lib/copilot/page-adapters";
import type { CanonicalCopilotResult } from "@/lib/types";
import { CopilotInsights, interpretInsightResult } from "./CopilotInsights";

const { investigateCanonical } = vi.hoisted(() => ({ investigateCanonical: vi.fn() }));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return { ...actual, investigateCanonical };
});

const snapshot = buildCopilotSnapshot({
  pageKind: "remediation",
  pageId: "remediation",
  scope: {},
  evidence: [{
    evidence_id: "remediation:visible:0",
    section: "remediation",
    status: "ok",
    data: { plan_count: 2 },
  }],
});

function result(overrides: Partial<CanonicalCopilotResult> & { synthesis?: unknown }): CanonicalCopilotResult {
  return {
    contract_version: "1",
    status: "ok",
    policy_status: "accepted",
    fallback_reason: "",
    selected_specialists: ["remediation"],
    selected_tools: ["remediation_plans"],
    tool_results: [],
    uncertainty: [],
    coverage: { visible_count: 1, total_count: 1, complete: true },
    citations: [],
    thread_id: "t",
    thread_revision: 1,
    mutation_authorized: false,
    ...overrides,
  } as CanonicalCopilotResult;
}

describe("CopilotInsights", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses shared neutral refresh and AI follow-up actions without changing their behavior", async () => {
    const onOpenCopilot = vi.fn();
    render(
      <CopilotInsights
        snapshot={{ ...snapshot, evidence: [] }}
        onOpenCopilot={onOpenCopilot}
      />,
    );

    expect(screen.getByRole("button", { name: "Refresh insights" }))
      .toHaveClass("button", "button-secondary");
    const followUp = screen.getByRole("button", { name: "Ask a follow-up" });
    expect(followUp).toHaveClass("button", "button-ai");
    fireEvent.click(followUp);
    expect(onOpenCopilot).toHaveBeenCalledOnce();
    await screen.findByText("No page evidence is available for a grounded insight yet.");
  });

  it("submits a canonical v2 snapshot and renders Foundry narration", async () => {
    investigateCanonical.mockResolvedValue({
      data: result({
        synthesis: {
          status: "synthesized", reason: "operations_copilot_coordinator", mode: "foundry",
          narration: "Two remediation plans await approval.", domain_count: 1, claims: [], warning: "",
        } as never,
      }),
    });
    render(<CopilotInsights snapshot={snapshot} contextLabel="Remediation" />);
    expect(await screen.findByText("Two remediation plans await approval.")).toBeInTheDocument();
    expect(screen.getByText("LLM insight · Foundry")).toBeInTheDocument();
    const [request] = investigateCanonical.mock.calls[0];
    expect(request.contract_version).toBe("1");
    expect(request.snapshot.version).toBe("2");
    expect(request.snapshot.page_kind).toBe("remediation");
  });

  it("keeps unavailability visible and retains the exact reason in an accessible disclosure", async () => {
    investigateCanonical.mockResolvedValue({
      data: result({
        synthesis: {
          status: "unavailable", reason: "no_cited_findings", domain_count: 0,
          claims: [], warning: "Provider coverage is incomplete.",
        } as never,
      }),
    });
    render(<CopilotInsights snapshot={snapshot} />);
    expect(await screen.findByText("No grounded insight was produced for this scope.")).toBeVisible();
    expect(screen.getByText("Insight unavailable")).toBeVisible();
    const disclosure = screen.getByText("Evidence limitations and diagnostics");
    expect(disclosure.closest("details")).not.toHaveAttribute("open");
    expect(disclosure.closest("details")).toHaveTextContent(
      "No cited findings were returned for this scope. Provider coverage is incomplete.",
    );
    fireEvent.click(disclosure);
    expect(disclosure.closest("details")).toHaveAttribute("open");
  });

  it("submits the exact Health observations, including null metrics, for a page-only insight", async () => {
    const health = buildResourceHealthCopilotContext({
      scope: { subscription: ["sub-a"] },
      resources: [95, null].map((cpu, index) => ({
        resource_id: `/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-${index}`,
        resource_name: `vm-${index}`,
        resource_type: "microsoft.compute/virtualmachines",
        status: cpu === null ? "unknown" : "critical",
        cpu_percent: cpu,
        memory_percent: null,
        disk_free_percent: null,
        unavailable_metrics: ["memory_percent", "disk_free_percent", ...(cpu === null ? ["cpu_percent"] : [])],
        series_point_count: cpu === null ? 0 : 12,
        observed_at: "2026-10-23T00:00:00Z",
      })),
      loadedCount: 2,
      totalCount: 2,
      available: true,
      freshness: "fresh",
      observedAt: "2026-10-23T00:00:00Z",
      evidence: [],
    });
    investigateCanonical.mockResolvedValue({
      data: result({
        synthesis: {
          status: "deterministic",
          reason: "deterministic_resource_health_page_evidence",
          domain_count: 1,
          warning: "",
          claims: [{
            finding_id: "resource-health:utilization-anomalies",
            summary: "vm-0 is critical at 95% CPU; vm-1 is unknown.",
            evidence_refs: ["retained:health"],
            confidence: "medium",
            freshness: "fresh",
            uncertainty: [],
          }],
        },
      }),
    });
    render(<CopilotInsights snapshot={health.snapshot} requestedScope={health.requestedScope}
      question={RESOURCE_HEALTH_INSIGHT_QUESTION} contextLabel="Resource health" />);
    await screen.findByText("vm-0 is critical at 95% CPU; vm-1 is unknown.");
    const [request, scope] = investigateCanonical.mock.calls[0];
    expect(request.question).toBe(RESOURCE_HEALTH_INSIGHT_QUESTION);
    expect(request.snapshot.page_kind).toBe("resource_health");
    expect(request.snapshot.page_id).toBe("resource-health");
    expect(scope).toEqual({ subscription: ["sub-a"] });
    const observations = request.snapshot.evidence.filter(
      (row: { claim_type: string }) => row.claim_type === "resource_utilization",
    );
    expect(observations.map((row: { data: { cpu_percent: number | null } }) => row.data.cpu_percent))
      .toEqual([95, null]);
    expect(observations[1].data).toMatchObject({
      status: "unknown", series_point_count: 0, actionable: false, mutation_authorized: false,
    });
  });

  it("renders the live retained compatibility LLM answer with its agent and model provenance", async () => {
    investigateCanonical.mockResolvedValue({
      data: result({
        policy_status: "fallback", fallback_reason: "compatibility_rollout",
        synthesis: {
          status: "compatibility", reason: "retained_compatibility",
          domain_count: 0, claims: [], warning: "",
          compatibility_answer: {
            text: "The isolated VNet has unresolved DNS dependencies.",
            agent_name: "aiops-network-agent", agent_version: "1",
            model: "gpt-5.4-mini", grounded: true,
          },
        },
      }),
    });
    render(<CopilotInsights snapshot={snapshot} />);
    expect(await screen.findByText("The isolated VNet has unresolved DNS dependencies.")).toBeInTheDocument();
    expect(screen.getByText("LLM insight · Foundry")).toBeInTheDocument();
    expect(screen.getByText(/Foundry agent: aiops-network-agent:1 · Model: gpt-5.4-mini/)).toBeInTheDocument();
    expect(screen.queryByText("Insight unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText(/Operations Copilot fallback/)).not.toBeInTheDocument();
  });

  it("keeps a retained deterministic status answer distinct from LLM narration", async () => {
    investigateCanonical.mockResolvedValue({
      data: result({
        synthesis: {
          status: "compatibility", reason: "retained_compatibility",
          domain_count: 0, claims: [], warning: "",
          compatibility_answer: {
            text: "No provider-backed records were returned.",
            agent_name: "operations-copilot", agent_version: "",
            model: "deterministic", grounded: true,
          },
        },
      }),
    });
    render(<CopilotInsights snapshot={snapshot} />);
    expect(await screen.findByText("No provider-backed records were returned.")).toBeInTheDocument();
    expect(screen.getByText("Grounded findings · deterministic")).toBeInTheDocument();
    expect(screen.queryByText("LLM insight · Foundry")).not.toBeInTheDocument();
  });

  it("preserves missing-source and scope uncertainty beside a valid LLM answer", async () => {
    investigateCanonical.mockResolvedValue({
      data: result({
        policy_status: "fallback", fallback_reason: "compatibility_rollout",
        uncertainty: ["Semantic identity resolution is unavailable."],
        tool_results: [{ tool: "incidents", status: "unavailable" } as never],
        synthesis: {
          status: "compatibility", reason: "retained_compatibility",
          domain_count: 0, claims: [], warning: "",
          compatibility_answer: {
            text: "The observed topology has one isolated VNet.",
            agent_name: "aiops-network-agent", agent_version: "1",
            model: "gpt-5.4-mini", grounded: true,
          },
        },
      }),
    });
    render(<CopilotInsights snapshot={snapshot} />);

    expect(await screen.findByText("LLM insight · Foundry")).toBeInTheDocument();
    expect(screen.getByText(/Semantic identity resolution is unavailable/)).toHaveTextContent(
      "Unavailable evidence: incidents (unavailable).",
    );
    expect(screen.queryByText(/Operations Copilot fallback/)).not.toBeInTheDocument();
  });

  it.each([
    { grounded: false }, { model: "" }, { agent_name: "" }, { agent_version: "" },
    { text: " " }, { model: " Deterministic " },
  ])("does not label incomplete or deterministic compatibility provenance as LLM: %j", (override) => {
    const reply = result({
      synthesis: {
        status: "compatibility", reason: "retained_compatibility",
        domain_count: 0, claims: [], warning: "",
        compatibility_answer: {
          text: "A retained answer.", agent_name: "aiops-network-agent",
          agent_version: "1", model: "gpt-5.4-mini", grounded: true, ...override,
        },
      },
    });
    const state = interpretInsightResult(reply);
    expect(state.kind).not.toBe("llm");
    expect(state.provider).toBeUndefined();
    if (!("model" in override) || override.model?.trim().toLowerCase() !== "deterministic") {
      expect(toCanonicalInvestigationView(reply).narration).toBeNull();
    }
  });

  it("does not label canonical narration as LLM without the Foundry mode", () => {
    const state = interpretInsightResult(result({
      synthesis: {
        status: "synthesized", reason: "", domain_count: 0, claims: [], warning: "",
        narration: "Unverified narration.",
      },
    }));
    expect(state.kind).toBe("unavailable");
  });

  it("explains skipped synthesis honestly with unavailable tools", async () => {
    investigateCanonical.mockResolvedValue({
      data: result({
        tool_results: [{ tool: "business_service_context", status: "unavailable" } as never],
        synthesis: { status: "skipped", reason: "no_cited_findings", domain_count: 0, claims: [], warning: "" },
      }),
    });
    render(<CopilotInsights snapshot={snapshot} />);
    expect(await screen.findByText(/No cited findings were returned/)).toBeInTheDocument();
    expect(screen.getByText(/business_service_context \(unavailable\)/)).toBeInTheDocument();
    expect(screen.getByText("Insight unavailable")).toBeInTheDocument();
  });

  it("shows request errors and refreshes on demand", async () => {
    investigateCanonical.mockRejectedValueOnce(new Error("boom"));
    render(<CopilotInsights snapshot={snapshot} />);
    expect(await screen.findByText("boom")).toBeInTheDocument();
    investigateCanonical.mockResolvedValueOnce({
      data: result({
        synthesis: {
          status: "deterministic", reason: "single_domain", domain_count: 1, warning: "",
          claims: [{ finding_id: "f", summary: "KB5001 ranks first.", evidence_refs: [], confidence: "high", freshness: "", uncertainty: [] }],
        },
      }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh insights" }));
    await waitFor(() => expect(screen.getByText("KB5001 ranks first.")).toBeInTheDocument());
    expect(screen.getByText("Grounded findings · deterministic")).toBeInTheDocument();
  });

  it("does not call the API without page evidence", async () => {
    const empty = buildCopilotSnapshot({ pageKind: "remediation", pageId: "remediation", scope: {} });
    render(<CopilotInsights snapshot={empty} />);
    expect(await screen.findByText(/No page evidence is available/)).toBeInTheDocument();
    expect(investigateCanonical).not.toHaveBeenCalled();
  });

  it("surfaces fallback reason when no narration was produced", () => {
    const state = interpretInsightResult(result({
      policy_status: "fallback",
      fallback_reason: "planner_unavailable",
      synthesis: { status: "skipped", reason: "", domain_count: 0, claims: [], warning: "" },
    }));
    expect(state.kind).toBe("unavailable");
  });

  describe("readiness, debounce and provenance", () => {
    afterEach(() => vi.useRealTimers());

    it("waits for page readiness before requesting an insight", async () => {
      investigateCanonical.mockResolvedValue({
        data: result({ synthesis: { status: "synthesized", mode: "foundry", reason: "", narration: "Ready insight.", domain_count: 1, claims: [], warning: "" } }),
      });
      const { rerender } = render(<CopilotInsights snapshot={snapshot} ready={false} />);
      expect(screen.getByText(/Waiting for page evidence to load/)).toBeInTheDocument();
      await new Promise((resolve) => setTimeout(resolve, 500));
      expect(investigateCanonical).not.toHaveBeenCalled();
      rerender(<CopilotInsights snapshot={snapshot} ready />);
      expect(await screen.findByText("Ready insight.")).toBeInTheDocument();
      expect(investigateCanonical).toHaveBeenCalledTimes(1);
    });

    it("coalesces snapshot churn into one request and aborts superseded ones", async () => {
      vi.useFakeTimers();
      investigateCanonical.mockResolvedValue({
        data: result({ synthesis: { status: "synthesized", mode: "foundry", reason: "", narration: "Final.", domain_count: 1, claims: [], warning: "" } }),
      });
      const next = (count: number) => buildCopilotSnapshot({
        pageKind: "remediation", pageId: "remediation", scope: {},
        evidence: [{ evidence_id: "remediation:visible:0", section: "remediation", status: "ok", data: { plan_count: count } }],
      });
      const { rerender } = render(<CopilotInsights snapshot={next(1)} />);
      await act(async () => { vi.advanceTimersByTime(100); });
      rerender(<CopilotInsights snapshot={next(2)} />);
      await act(async () => { vi.advanceTimersByTime(100); });
      rerender(<CopilotInsights snapshot={next(3)} />);
      await act(async () => { vi.advanceTimersByTime(500); });
      expect(investigateCanonical).toHaveBeenCalledTimes(1);
      const [request, , signal] = investigateCanonical.mock.calls[0];
      expect(request.snapshot.evidence[0].data.plan_count).toBe(3);
      expect(signal).toBeInstanceOf(AbortSignal);
    });

    it("reports the lowest synthesis claim confidence and selected specialists", () => {
      const state = interpretInsightResult(result({
        selected_specialists: ["vulnerability", "patch"],
        synthesis: {
          status: "synthesized", reason: "", domain_count: 2, warning: "",
          claims: [
            { finding_id: "a", summary: "A", evidence_refs: [], confidence: "high", freshness: "", uncertainty: [] },
            { finding_id: "b", summary: "B", evidence_refs: [], confidence: "medium", freshness: "", uncertainty: [] },
          ],
        },
      }));
      expect(state.confidence).toBe("medium");
      expect(state.specialists).toEqual(["vulnerability", "patch"]);
    });
  });
});
