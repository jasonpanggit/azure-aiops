import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";
import PreDeploymentPage from "./page";

const api = vi.hoisted(() => ({
  sources: vi.fn(), assessments: vi.fn(), assess: vi.fn(), review: vi.fn(), query: "",
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(api.query) }));
vi.mock("@/lib/services", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/services")>(),
  predeployApi: api, networkApi: api,
}));
vi.mock("@/components/ui/CopilotInsights", () => ({ CopilotInsights: () => null }));
vi.mock("@/components/ui/CopilotDrawer", () => ({ CopilotDrawer: () => null }));
vi.mock("@/components/predeploy/BlastRadiusGraph", () => ({ default: () => null }));
const reference = { kind: "gap" as const, finding_id: "gap-a", reviewed_digest: "a".repeat(64) };
const scope = { subscription: ["sub-a", "sub-b"], region: ["eastus"] };
const linked = `network_kind=gap&network_finding=gap-a&network_digest=${reference.reviewed_digest}`;
const review = {
  ...reference, title: "Current Network gap", severity: "high", category: "inspection",
  detail: "Current source detail", recommendation: "Review the configuration.", resource_ids: [],
  basis: "configuration", flow_log_state: "not_ingested", source_observed_at: "", scope,
  policy_digest: "b".repeat(64), source_finding_digest: "c".repeat(64),
};

describe("Predeployment exact Network attachment", () => {
  beforeEach(() => {
    vi.clearAllMocks(); api.query = linked;
    api.sources.mockResolvedValue({ data: { sources: ["terraform_plan"] } });
    api.assessments.mockResolvedValue({ data: [] });
    api.review.mockResolvedValue({ data: review });
    api.assess.mockRejectedValue(new Error("Fixture assessment unavailable"));
  });

  it("requires an explicit attachment and keeps a separately entered artifact", async () => {
    render(<ScopeProvider initialScope={scope}><PreDeploymentPage /></ScopeProvider>);
    await screen.findByText(review.title);
    const artifact = screen.getByRole("textbox", { name: "Change artifact (JSON)" });
    expect(artifact).toHaveValue("");
    fireEvent.change(artifact, { target: { value: '{"resource_changes":[]}' } });
    expect(screen.getByRole("button", { name: "Assess impact" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Attach this exact Network finding context/ }));
    fireEvent.click(screen.getByRole("button", { name: "Assess impact" }));
    await screen.findByText("Assessment failed");
    expect(api.assess).toHaveBeenCalledWith("terraform_plan", { resource_changes: [] }, "", {
      scope, networkReview: reference, signal: expect.any(AbortSignal),
    });
    expect(screen.getByRole("button", { name: "Assess impact" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload exact Network evidence before retrying" }));
    await waitFor(() => expect(api.review).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("checkbox", { name: /Attach this exact Network finding context/ })).not.toBeChecked();
    expect(api.assess).toHaveBeenCalledTimes(1);
  });

  it("blocks incomplete references without acquiring Network or silently dropping them", async () => {
    api.query = "network_kind=gap";
    render(<ScopeProvider initialScope={scope}><PreDeploymentPage /></ScopeProvider>);
    await screen.findByRole("alert");
    fireEvent.change(screen.getByRole("textbox", { name: "Change artifact (JSON)" }), { target: { value: "{}" } });
    expect(screen.getByRole("button", { name: "Assess impact" })).toBeDisabled();
    expect(api.review).not.toHaveBeenCalled();
    expect(api.assess).not.toHaveBeenCalled();
  });

  it("preserves unlinked review while sending its actual selected scope", async () => {
    api.query = "";
    render(<ScopeProvider initialScope={scope}><PreDeploymentPage /></ScopeProvider>);
    await waitFor(() => expect(api.assessments).toHaveBeenCalled());
    fireEvent.change(screen.getByRole("textbox", { name: "Change artifact (JSON)" }), { target: { value: "{}" } });
    fireEvent.click(screen.getByRole("button", { name: "Assess impact" }));
    await screen.findByText("Assessment failed");
    expect(api.assess).toHaveBeenCalledWith("terraform_plan", {}, "", { scope, signal: expect.any(AbortSignal) });
    expect(api.review).not.toHaveBeenCalled();
  });

  it("aborts late submissions and clears artifact/context on bookmark change", async () => {
    let reject: (reason: Error) => void = () => {};
    api.assess.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
    const view = render(<ScopeProvider initialScope={scope}><PreDeploymentPage /></ScopeProvider>);
    await screen.findByText(review.title);
    fireEvent.change(screen.getByRole("textbox", { name: "Change artifact (JSON)" }), { target: { value: "{}" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Attach this exact Network finding context/ }));
    fireEvent.click(screen.getByRole("button", { name: "Assess impact" }));
    const signal: AbortSignal = api.assess.mock.calls[0][3].signal;
    api.query = "";
    view.rerender(<ScopeProvider initialScope={scope}><PreDeploymentPage /></ScopeProvider>);
    expect(signal.aborted).toBe(true);
    expect(screen.getByRole("textbox", { name: "Change artifact (JSON)" })).toHaveValue("");
    await act(async () => reject(new Error("Old request failed")));
    expect(screen.queryByText("Assessment failed")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
