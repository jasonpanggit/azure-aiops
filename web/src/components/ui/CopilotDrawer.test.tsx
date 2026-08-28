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
    fireEvent.click(screen.getByRole("button", { name: "Ask", exact: true }));
    await waitFor(() => expect(investigateContext).toHaveBeenCalledWith({ ...snapshot, question: "What is wrong?" }));
    expect(await screen.findByText("Verified finding")).toBeInTheDocument();
    expect(screen.getByText(/Foundry narration was not produced/)).toBeInTheDocument();
  });
});
