import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const { services, currentScope, buildContext } = vi.hoisted(() => ({
  services: {
    identitySummary: vi.fn(), identityPrincipals: vi.fn(), subscriptionOwners: vi.fn(),
    staleAccess: vi.fn(), nonHumanIdentities: vi.fn(), spnCredentials: vi.fn(),
    identityLeastPrivilege: vi.fn(),
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
const leastPrivilegeCandidate = {
  assignment_id: "grant-1",
  principal_id: "unresolved-principal",
  principal_type: "User",
  role_definition_id: "/roles/owner",
  role: "Owner",
  scope: "/subscriptions/sub-a",
  scope_breadth: "subscription",
  age_state: "unknown" as const,
  last_changed: "",
  condition_state: "not_collected" as const,
  permission_profile: {
    actions: { count: 1, patterns: ["*"], truncated: false },
    not_actions: { count: 0, patterns: [], truncated: false },
    data_actions: { count: 1, patterns: ["Microsoft.Storage/*"], truncated: false },
    not_data_actions: { count: 0, patterns: [], truncated: false },
    wildcard_pattern_count: 2,
  },
  review_reasons: ["broad_subscription_scope", "elevated_role_or_action_heuristic"],
  recommendation: "Confirm required operations with the owner before narrowing.",
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
  services.identityLeastPrivilege.mockResolvedValue(envelope({
    effective_access: "not_evaluated",
    assignment_count: 1,
    candidate_count: 1,
    offset: 0,
    limit: 20,
    candidates: [leastPrivilegeCandidate],
    coverage: {
      role_definitions_resolved: 1,
      assignment_age_unknown: 1,
      assignment_scope_unknown: 0,
      conditional_assignments_observed: 0,
      group_membership: "not_collected",
      deny_assignments: "not_collected",
      pim_eligibility: "not_collected",
      role_conditions: "presence_only_not_evaluated",
      effective_access: "not_evaluated",
    },
  }));
});
describe("Identity evidence boundaries", () => {
  it("allocates six principal columns without changing evidence or the accessible scroller", async () => {
    render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    const region = screen.getByRole("region", { name: "Observed principal assignments" });
    const table = region.querySelector("table");
    expect(region).toHaveAttribute("tabindex", "0");
    expect(table).toHaveClass("identity-principals-grid");
    expect(table?.querySelectorAll(":scope > colgroup > col")).toHaveLength(6);
    expect(table?.querySelectorAll("thead th")).toHaveLength(6);
    expect(table?.querySelector("tbody tr")?.children).toHaveLength(6);
    expect(region).toHaveTextContent("Unresolved");
    expect(region).toHaveTextContent("2 subscription");
    expect(region.querySelector("a")).toHaveAttribute("href", "/search?q=unresolved-principal");
  });
  it("qualifies unresolved risk, observed breadth and unknown age without standard-access assurance", async () => {
    render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    expect(screen.getByText("1 unresolved role/action records; 1 unknown change ages")).toBeTruthy();
    expect(screen.queryByText("standard")).toBeNull();
    expect(screen.getByText(/data-plane permissions are not evaluated as effective access/)).toBeTruthy();
    expect(screen.getByText(/Change recency does not prove use/)).toBeTruthy();
  });
  it("shows scoped least-privilege candidates and the actual permission patterns", async () => {
    render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    expect(screen.getByText(/Effective access remains not evaluated/)).toBeTruthy();
    expect(screen.getByText("Subscription-wide scope")).toBeTruthy();
    expect(screen.getByText("Elevated role/action signal")).toBeTruthy();
    fireEvent.click(screen.getByText("Inspect 2 allow patterns"));
    expect(screen.getByText("*")).toBeTruthy();
    expect(screen.getByText("Microsoft.Storage/*")).toBeTruthy();
    expect(screen.getByText("Confirm required operations with the owner before narrowing.")).toBeTruthy();
    expect(services.identityLeastPrivilege).toHaveBeenCalledWith(currentScope.value, 0, 20);
  });
  it("requests the next server page without losing the candidate total", async () => {
    services.identityLeastPrivilege.mockResolvedValue(envelope({
      effective_access: "not_evaluated",
      assignment_count: 21,
      candidate_count: 21,
      offset: 0,
      limit: 20,
      candidates: [leastPrivilegeCandidate],
      coverage: {
        role_definitions_resolved: 1,
        assignment_age_unknown: 0,
        assignment_scope_unknown: 0,
        conditional_assignments_observed: 0,
        group_membership: "not_collected",
        deny_assignments: "not_collected",
        pim_eligibility: "not_collected",
        role_conditions: "presence_only_not_evaluated",
        effective_access: "not_evaluated",
      },
    }));
    render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(services.identityLeastPrivilege).toHaveBeenLastCalledWith(currentScope.value, 20, 20));
  });
  it("surfaces and retries an unavailable least-privilege read independently", async () => {
    services.identityLeastPrivilege
      .mockRejectedValueOnce(new Error("Review endpoint unavailable"))
      .mockResolvedValueOnce(envelope({
        effective_access: "not_evaluated",
        assignment_count: 0,
        candidate_count: 0,
        offset: 0,
        limit: 20,
        candidates: [],
        coverage: {
          role_definitions_resolved: 0,
          assignment_age_unknown: 0,
          assignment_scope_unknown: 0,
          conditional_assignments_observed: 0,
          group_membership: "not_collected",
          deny_assignments: "not_collected",
          pim_eligibility: "not_collected",
          role_conditions: "presence_only_not_evaluated",
          effective_access: "not_evaluated",
        },
      }));
    render(<IdentityPage />);
    expect(await screen.findByText("Review endpoint unavailable")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry review candidates" }));
    expect(await screen.findByText("No observed review candidates")).toBeTruthy();
    expect(services.identityLeastPrivilege).toHaveBeenCalledTimes(2);
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
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    expect(services[name]).toHaveBeenCalledTimes(2);
    expect(services.identitySummary).toHaveBeenCalledTimes(1);
  });
  it("keeps stale source evidence and all-source warnings in the Copilot projection", async () => {
    services.nonHumanIdentities.mockResolvedValue(envelope({ identities: [], count: 0 }, "stale", ["Managed identity coverage incomplete"]));
    render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    expect(screen.getByText("Managed identity coverage incomplete")).toBeTruthy();
    expect(buildContext).toHaveBeenLastCalledWith(expect.objectContaining({
      freshness: "stale", available: true,
      principals: [expect.objectContaining({ risk_classification: "incomplete", unknown_age_assignments: 1 })],
    }));
  });
  it("treats successful reads without source clocks as partial, not fresh", async () => {
    services.subscriptionOwners.mockResolvedValue({ data: { owners: [], count: 0 }, evidence: [], warnings: [] });
    render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
    expect(buildContext).toHaveBeenLastCalledWith(expect.objectContaining({ freshness: "partial" }));
  });
  it("unmounts old-scope rows, filters and drawer before accepting a delayed result", async () => {
    const view = render(<IdentityPage />);
    await screen.findByText("1 unresolved role/action records; 1 unknown change ages");
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
    services.identityLeastPrivilege.mockResolvedValueOnce(envelope({
      effective_access: "not_evaluated",
      assignment_count: 0,
      candidate_count: 0,
      offset: 0,
      limit: 20,
      candidates: [],
      coverage: {
        role_definitions_resolved: 0,
        assignment_age_unknown: 0,
        assignment_scope_unknown: 0,
        conditional_assignments_observed: 0,
        group_membership: "not_collected",
        deny_assignments: "not_collected",
        pim_eligibility: "not_collected",
        role_conditions: "presence_only_not_evaluated",
        effective_access: "not_evaluated",
      },
    }));
    view.rerender(<IdentityPage />);
    await screen.findByText("No principals observed");
    await act(async () => resolve(envelope({ principals: [principal], count: 1 })));
    await waitFor(() => expect(screen.queryByText("unresolved-principal")).toBeNull());
    Object.entries(services)
      .filter(([name]) => name !== "identityLeastPrivilege")
      .forEach(([, service]) => expect(service).toHaveBeenLastCalledWith(currentScope.value));
    expect(services.identityLeastPrivilege).toHaveBeenLastCalledWith(currentScope.value, 0, 20);
  });
});
