import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { decideRemediationPlan, exposures, gaps, remediationOpportunities, remediationPlans, ruleFindings } = vi.hoisted(() => ({
  decideRemediationPlan: vi.fn(),
  exposures: vi.fn(),
  gaps: vi.fn(),
  remediationOpportunities: vi.fn(),
  remediationPlans: vi.fn(),
  ruleFindings: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("incident=INC-1001&business_service=Payroll"),
}));

vi.mock("@/lib/services", () => ({
  buildCopilotSnapshot: (input: Record<string, unknown>) => input,
  copilotEvidenceRows: () => [],
  networkApi: { gaps, ruleFindings },
  operationsApi: { decideRemediationPlan, remediationPlans, remediationOpportunities },
  vulnerabilityApi: { exposures },
}));

import RemediationPage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [{ source_engine: "ARG", source_table: "securityresources", timestamp: "2026-01-01T10:00:00Z", confidence: "high", freshness: "fresh" }],
  scope: {},
  knowledge_version: "graph-1",
});

function renderPage() {
  return render(
    <ScopeProvider>
      <RemediationPage />
    </ScopeProvider>
  );
}

describe("Governed Remediation Center", () => {
  beforeEach(() => {
    window.localStorage.clear();
    remediationPlans.mockResolvedValue(envelope({
      plans: [{
        plan_id: "plan-1",
        action_version: "version-1",
        title: "Patch payroll database",
        status: "draft",
        business_service: "Payroll",
        resource: "vm-payroll-db",
        simulation_result: {
          risk_reduction_percent: 64,
          operational_debt_reduction_percent: 30,
          compliance_improvement_percent: 42,
          downtime_risk: "medium",
        },
        rollback_plan: { summary: "Restore previous VM image" },
        approval_requirements: [{ role: "Change Manager", stage: "Production", status: "Required - Not Approved" }],
        execution_steps: [{ step_number: 1, description: "Validate the update baseline", stage: "Development" }],
        dependencies: { owners: ["Payroll Owner"], affected_services: ["Payroll"] },
        confidence: 0.82,
        confidence_kind: "Evidence completeness",
        recommended_action: { impact: "Close reachable CVE exposure", priority: "high" },
      }],
      generated_at: "2026-01-01T10:00:00Z",
    }));
    remediationOpportunities.mockResolvedValue(envelope({
      opportunities: [{ opportunity_id: "opp-1", category: "patch", priority: "high", business_service: "Payroll", resource: "vm-payroll-db", rationale: ["Patch overdue server"], expected_risk_reduction: 45 }],
    }));
    gaps.mockResolvedValue(envelope({
      gaps: [{ gap_id: "gap-1", category: "inspection", severity: "high", title: "Restore hub inspection path", detail: "Spoke bypasses firewall", resource_id: "route-1", resource_name: "route", resource_type: "routeTable", evidence: {}, recommendation: "Fix UDR", basis: "topology", connection_id: "prod", subscription_id: "sub-1", environment: "prod" }],
      intended_design_declared: true,
      summary: {},
    }));
    ruleFindings.mockResolvedValue(envelope({
      findings: [{ finding_id: "rule-1", category: "nsg", severity: "medium", rule_id: "rule-1", rule_name: "AllowSQL", control: "nsg", control_id: "nsg-1", title: "Narrow NSG SQL rule", detail: "Broad source prefix", evidence: {}, recommendation: "Narrow source", connection_id: "prod", subscription_id: "sub-1", environment: "prod" }],
      summary: {},
    }));
    exposures.mockResolvedValue(envelope([{
      cve_id: "CVE-2026-0001",
      severity: "critical",
      missing_kb: "KB500",
      affected_server_count: 1,
      affected_application_count: 1,
      affected_business_service_count: 1,
      reachable_server_count: 1,
      exploit_signal: "known exploited",
      internet_exposed: false,
      critical_business_count: 1,
      priority_score: 95,
      expected_risk_reduction: 58,
      recommended_patch: "Install KB500",
      epss_score: 0.9,
      is_known_exploited: true,
      finding_ids: ["vf-1"],
    }]));

    decideRemediationPlan.mockResolvedValue(envelope({
      decision_id: "RMD-1",
      plan_id: "plan-1",
      decision: "approved",
      approver: "operator@example.com",
      decided_at: "2026-01-01T10:00:00Z",
      reason: "CAB approved",
      scope: {},
      action_version: "version-1",
      expires_at: "2026-12-31",
      revalidation: { status: "passed", checks: ["action_version_current"] },
      execution_authorized: false,
      execution_performed: false,
      read_only: true,
    }));
  });

  it("records approval decisions without enabling execution", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Unified remediation backlog" })).toBeInTheDocument();
    expect(screen.getAllByText("Patch payroll database").length).toBeGreaterThan(0);
    expect(screen.getByText("Restore hub inspection path")).toBeInTheDocument();
    expect(screen.getAllByText("CVE-2026-0001: Install KB500").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Approval decision record" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Execution handoff boundary" })).toBeInTheDocument();
    expect(screen.getByText(/No Azure execution, rollback, or realized-outcome controls/)).toBeInTheDocument();
    expect(screen.getAllByText(/Validate the update baseline/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Change Manager - Production - Required - Not Approved/)).toBeInTheDocument();
    expect(screen.getByLabelText("Search")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "CVE-2026-0001" } });
    expect(screen.getAllByText("CVE-2026-0001: Install KB500").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "" } });

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "CAB approved" } });
    fireEvent.change(screen.getByLabelText("Expires at"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    await waitFor(() => expect(decideRemediationPlan).toHaveBeenCalledWith("plan-1", {
      decision: "approved",
      reason: "CAB approved",
      action_version: "version-1",
      expires_at: "2026-12-31",
    }, {}));
    expect(await screen.findByText(/execution_performed=false/)).toBeInTheDocument();
  });

  it("renders available sources when one provider fails", async () => {
    gaps.mockRejectedValue(new Error("Network provider offline"));

    renderPage();

    expect(await screen.findByRole("heading", { name: "Unified remediation backlog" })).toBeInTheDocument();
    expect(screen.getAllByText("Patch payroll database").length).toBeGreaterThan(0);
    expect(screen.queryByText("Remediation intelligence is unavailable")).not.toBeInTheDocument();
  });
});
