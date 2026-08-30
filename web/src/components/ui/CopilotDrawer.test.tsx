import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import { CopilotDrawer } from "./CopilotDrawer";

const { investigateContext } = vi.hoisted(() => ({ investigateContext: vi.fn() }));
vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return { ...actual, copilotApi: { ...actual.copilotApi, investigateContext } };
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
});
