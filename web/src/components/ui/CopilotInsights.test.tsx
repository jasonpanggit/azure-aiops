import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildCopilotSnapshot } from "@/lib/services";
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
    const state = interpretInsightResult(result({
      synthesis: {
        status: "compatibility", reason: "retained_compatibility",
        domain_count: 0, claims: [], warning: "",
        compatibility_answer: {
          text: "A retained answer.", agent_name: "aiops-network-agent",
          agent_version: "1", model: "gpt-5.4-mini", grounded: true, ...override,
        },
      },
    }));
    expect(state.kind).not.toBe("llm");
    expect(state.provider).toBeUndefined();
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
