import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CopilotContextResult, CopilotPageSnapshot } from "@/lib/types";
import { TopologyInsights } from "./TopologyInsights";

const mocks = vi.hoisted(() => ({
  investigateContext: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  copilotApi: { investigateContext: mocks.investigateContext },
}));

const snapshot: CopilotPageSnapshot = {
  version: "1",
  page_kind: "network",
  page_id: "network-topology",
  selected_resources: [],
  filters: {},
  freshness: [],
  scope: { declared: {}, authorized: true },
  evidence: [],
  question: "placeholder",
  rechecks: [],
};

function result(overrides: Partial<CopilotContextResult> = {}): CopilotContextResult {
  return {
    page_kind: "network",
    page_id: "network-topology",
    snapshot_hash: "snapshot-1",
    stages: [],
    findings: [],
    tool_calls: [],
    synthesis_mode: "foundry",
    synthesis_agent: "network",
    synthesis: { mode: "foundry", narration: "Hub connectivity is grounded." },
    warnings: [],
    ...overrides,
  };
}

function envelope(data: CopilotContextResult) {
  return {
    data,
    evidence: [],
    scope: {},
    knowledge_version: "network-test",
    warnings: [],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("TopologyInsights", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders grounded Foundry narration and selected subject context", async () => {
    mocks.investigateContext.mockResolvedValue(envelope(result()));
    render(
      <TopologyInsights
        snapshot={snapshot}
        selection={{
          node: { id: "vnet-1", label: "Hub VNet", kind: "hub", entityType: "VNet" },
          edge: null,
        }}
        onAskFollowUp={vi.fn()}
      />,
    );

    expect(await screen.findByText("Grounded LLM insight")).toBeInTheDocument();
    expect(screen.getByText("Hub connectivity is grounded.")).toBeInTheDocument();
    expect(mocks.investigateContext).toHaveBeenCalledWith(
      expect.objectContaining({
        question: expect.stringMatching(
          /Selected label: Hub VNet.*Selected kind: hub.*Selected selector: vnet-1/,
        ),
      }),
    );
  });

  it("labels deterministic findings as an evidence-only fallback", async () => {
    mocks.investigateContext.mockResolvedValue(
      envelope(result({
        synthesis_mode: "deterministic",
        synthesis_agent: "",
        synthesis: null,
        findings: [{
          finding_id: "finding-1",
          resource_ids: [],
          check_id: "topology",
          policy_id: "",
          source_status: "ok",
          status: "verified",
          summary: "One unhealthy peering is present.",
          evidence_refs: [],
          confidence: "high",
          uncertainty: [],
          stale: false,
          next_check: "",
          actionable: false,
        }],
      })),
    );

    render(<TopologyInsights snapshot={snapshot} onAskFollowUp={vi.fn()} />);

    expect(await screen.findByText("Evidence-only fallback")).toBeInTheDocument();
    expect(screen.getByText("One unhealthy peering is present.")).toBeInTheDocument();
  });

  it("renders the deterministic Network narration when Foundry narration times out (planner_unavailable fallback)", async () => {
    // Live production regression: HTTP 200, status=partial, synthesis.mode=deterministic,
    // policy_status=fallback, fallback_reason=planner_unavailable, uncertainty noting
    // Foundry narration timed out -- while a successful `network_topology` tool
    // finding (hub, isolated VNet, shared services, resources) was present. The
    // backend now folds that citation-backed evidence into synthesis.narration
    // instead of leaving it empty, so the fallback must render it here.
    mocks.investigateContext.mockResolvedValue(
      envelope(result({
        synthesis_mode: "deterministic",
        synthesis_agent: "",
        synthesis: {
          mode: "deterministic",
          narration:
            "Topology counts: hub_count=1, isolated_vnet_count=1, shared_service_count=2.",
        },
        findings: [{
          finding_id: "topology:0",
          tool: "network_topology",
          specialist_id: "network",
          status: "ok",
          data: { summary: { hub_count: 1, isolated_vnet_count: 1 } },
          citation_ids: ["tool:topology:0:0", "tool:topology:0:1"],
        } as unknown as CopilotContextResult["findings"][number]],
        warnings: ["Foundry narration timed out; deterministic cited network evidence was used."],
      })),
    );

    render(<TopologyInsights snapshot={snapshot} onAskFollowUp={vi.fn()} />);

    expect(await screen.findByText("Evidence-only fallback")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Topology counts: hub_count=1, isolated_vnet_count=1, shared_service_count=2.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Insights unavailable")).not.toBeInTheDocument();
  });

  it("keeps the page rendered when a partial deployed finding omits summary", async () => {
    mocks.investigateContext.mockResolvedValue(
      envelope(result({
        synthesis_mode: "deterministic",
        synthesis_agent: "",
        synthesis: null,
        findings: [{
          finding_id: "finding-partial",
          resource_ids: [],
          check_id: "topology",
          policy_id: "",
          source_status: "partial",
          status: "partial",
          evidence_refs: [],
          confidence: "medium",
          uncertainty: ["Copilot response was partial"],
          stale: false,
          next_check: "",
          actionable: false,
        } as unknown as CopilotContextResult["findings"][number]],
      })),
    );

    render(<TopologyInsights snapshot={snapshot} onAskFollowUp={vi.fn()} />);

    expect(await screen.findByText("Insights unavailable")).toBeInTheDocument();
    expect(screen.getByText("The bounded snapshot returned no supported findings or narration.")).toBeInTheDocument();
  });

  it("refreshes on demand and opens the shared follow-up experience", async () => {
    const onAskFollowUp = vi.fn();
    mocks.investigateContext.mockResolvedValue(envelope(result()));
    render(
      <TopologyInsights snapshot={snapshot} onAskFollowUp={onAskFollowUp} />,
    );
    await screen.findByText("Grounded LLM insight");

    fireEvent.click(screen.getByRole("button", { name: "Refresh insights" }));
    await waitFor(() => expect(mocks.investigateContext).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Ask a follow-up" }));
    expect(onAskFollowUp).toHaveBeenCalledTimes(1);
  });

  it("waits for a usable page snapshot before asking Copilot", async () => {
    const { rerender } = render(
      <TopologyInsights
        snapshot={snapshot}
        ready={false}
        onAskFollowUp={vi.fn()}
      />,
    );

    expect(screen.getByText("Reviewing the bounded topology evidence…")).toBeInTheDocument();
    expect(mocks.investigateContext).not.toHaveBeenCalled();

    mocks.investigateContext.mockResolvedValue(envelope(result()));
    rerender(
      <TopologyInsights
        snapshot={{
          ...snapshot,
          evidence: [{
            evidence_id: "gap-1",
            section: "network/gaps",
            resource_id:
              "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/privateEndpoints/pe1",
            status: "ok",
            data: {
              source_key: "gap-1",
              claim_type: "inspection_gap",
              issue: "Private endpoint has no private DNS zone group.",
              recommendation: "Attach a private DNS zone group.",
            },
          }],
        }}
        ready
        onAskFollowUp={vi.fn()}
      />,
    );

    await waitFor(() => expect(mocks.investigateContext).toHaveBeenCalledTimes(1));
    expect(mocks.investigateContext).toHaveBeenCalledWith(
      expect.objectContaining({
        evidence: expect.arrayContaining([
          expect.objectContaining({ section: "network/gaps" }),
        ]),
      }),
    );
  });

  it("ignores a stale overlapping response", async () => {
    const first = deferred<ReturnType<typeof envelope>>();
    const second = deferred<ReturnType<typeof envelope>>();
    mocks.investigateContext
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<TopologyInsights snapshot={snapshot} onAskFollowUp={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh insights" }));
    await act(async () => second.resolve(envelope(result({
      synthesis: { mode: "foundry", narration: "Fresh insight." },
    }))));
    expect(await screen.findByText("Fresh insight.")).toBeInTheDocument();

    await act(async () => first.resolve(envelope(result({
      synthesis: { mode: "foundry", narration: "Stale insight." },
    }))));
    expect(screen.getByText("Fresh insight.")).toBeInTheDocument();
    expect(screen.queryByText("Stale insight.")).not.toBeInTheDocument();
  });
});
