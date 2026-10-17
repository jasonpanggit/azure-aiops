import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const { services, currentScope, buildContext } = vi.hoisted(() => ({
  services: {
    identitySummary: vi.fn(), identityPrincipals: vi.fn(), subscriptionOwners: vi.fn(),
    staleAccess: vi.fn(), nonHumanIdentities: vi.fn(), spnCredentials: vi.fn(),
  },
  currentScope: { value: {} as ScopeSelection },
  buildContext: vi.fn(() => ({ snapshot: {}, requestedScope: {}, starterQuestions: [] })),
}));
vi.mock("@/lib/services", () => ({ governanceApi: services }));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: currentScope.value }) }));
vi.mock("@/lib/copilot/page-adapters", () => ({ buildIdentityCopilotContext: buildContext }));
vi.mock("@/components/ui/CopilotInsights", () => ({ CopilotInsights: () => null }));
vi.mock("@/components/ui/CopilotDrawer", () => ({ CopilotDrawer: ({ open }: { open: boolean }) => open ? <div>Identity drawer open</div> : null }));
import IdentityPage from "./page";

function envelope(data: object, freshness = "fresh", warnings: string[] = []) {
  return { data, evidence: [{ source_engine: "identity-fixture", source_table: "generation", timestamp: "2026-01-01T00:00:00Z", freshness, confidence: "high" }], warnings };
}
const principal = {
  principal_id: "unresolved-principal", principal_type: "User", assignment_count: 2,
  privileged: false, stale: false, widest_scope: "/subscriptions/sub-a",
  widest_scope_breadth: "subscription", roles: [], blast_radius: { subscription: 2 },
  risk_evidence: { classification: "incomplete", unresolved_role_assignments: 1, unknown_age_assignments: 1, stale_assignments: 0, effective_access: "not_evaluated", age_evaluated_at: "2026-01-01T00:00:00Z" },
};
beforeEach(() => {
  vi.clearAllMocks();
  currentScope.value = { subscription: ["sub-a"] };
  services.identitySummary.mockResolvedValue(envelope({ principal_count: 1, assignment_count: 2, privileged_principal_count: 0, stale_assignment_count: 0, non_human_principal_count: 0 }));
  services.identityPrincipals.mockResolvedValue(envelope({ principals: [principal], count: 1 }));
  services.subscriptionOwners.mockResolvedValue(envelope({ owners: [], count: 0 }));
  services.staleAccess.mockResolvedValue(envelope({ assignments: [], count: 0 }));
  services.nonHumanIdentities.mockResolvedValue(envelope({ identities: [], count: 0 }));
  services.spnCredentials.mockResolvedValue(envelope({ credentials: [], count: 0, summary: {} }));
});
describe("Identity evidence boundaries", () => {
  it("qualifies unresolved risk, observed breadth and unknown age without standard-access assurance", async () => {
    render(<IdentityPage />);
    await screen.findByRole("link", { name: "unresolved-principal" });
    expect(screen.getByText("1 unresolved role/action records; 1 unknown change ages")).toBeTruthy();
    expect(screen.queryByText("standard")).toBeNull();
    expect(screen.getByText(/data-plane permissions are not evaluated as effective access/)).toBeTruthy();
    expect(screen.getByText(/Change recency does not prove use/)).toBeTruthy();
  });
  it("does not render an empty owner assurance while that source is pending", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    services.subscriptionOwners.mockImplementation(() => new Promise(done => { resolve = done; }));
    render(<IdentityPage />);
    expect(await screen.findByText("Reading access assignments")).toBeTruthy();
    expect(screen.queryByText("No subscription owners observed")).toBeNull();
    await act(async () => resolve(envelope({ owners: [], count: 0 })));
    expect(await screen.findByText("No subscription owners observed")).toBeTruthy();
  });
  it.each(["subscriptionOwners", "staleAccess", "nonHumanIdentities"] as const)("surfaces and retries a failed %s read rather than claiming an empty set", async name => {
    services[name].mockRejectedValueOnce(new Error(`Unavailable ${name}`));
    render(<IdentityPage />);
    expect(await screen.findByText(`Unavailable ${name}`)).toBeTruthy();
    expect(screen.queryByText("No stale access")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry failed identity reads" }));
    await screen.findByRole("link", { name: "unresolved-principal" });
    expect(services[name]).toHaveBeenCalledTimes(2);
    expect(services.identitySummary).toHaveBeenCalledTimes(1);
  });
  it("keeps stale source evidence and all-source warnings in the Copilot projection", async () => {
    services.nonHumanIdentities.mockResolvedValue(envelope({ identities: [], count: 0 }, "stale", ["Managed identity coverage incomplete"]));
    render(<IdentityPage />);
    await screen.findByRole("link", { name: "unresolved-principal" });
    expect(screen.getByText("Managed identity coverage incomplete")).toBeTruthy();
    expect(buildContext).toHaveBeenLastCalledWith(expect.objectContaining({
      freshness: "stale", available: true,
      principals: [expect.objectContaining({ risk_classification: "incomplete", unknown_age_assignments: 1 })],
    }));
  });
  it("treats successful reads without source clocks as partial, not fresh", async () => {
    services.subscriptionOwners.mockResolvedValue({ data: { owners: [], count: 0 }, evidence: [], warnings: [] });
    render(<IdentityPage />);
    await screen.findByRole("link", { name: "unresolved-principal" });
    expect(buildContext).toHaveBeenLastCalledWith(expect.objectContaining({ freshness: "partial" }));
  });
  it("unmounts old-scope rows, filters and drawer before accepting a delayed result", async () => {
    const view = render(<IdentityPage />);
    await screen.findByRole("link", { name: "unresolved-principal" });
    fireEvent.click(screen.getByRole("button", { name: "Ask Copilot about identity access" }));
    expect(screen.getByText("Identity drawer open")).toBeTruthy();
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    services.identityPrincipals.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    currentScope.value = { subscription: ["sub-b"] };
    view.rerender(<IdentityPage />);
    expect(screen.queryByText("unresolved-principal")).toBeNull();
    expect(screen.queryByText("Identity drawer open")).toBeNull();
    currentScope.value = { subscription: ["sub-c"] };
    services.identityPrincipals.mockResolvedValueOnce(envelope({ principals: [], count: 0 }));
    view.rerender(<IdentityPage />);
    await screen.findByText("No principals observed");
    await act(async () => resolve(envelope({ principals: [principal], count: 1 })));
    await waitFor(() => expect(screen.queryByText("unresolved-principal")).toBeNull());
    Object.values(services).forEach(service => expect(service).toHaveBeenLastCalledWith(currentScope.value));
  });
});
