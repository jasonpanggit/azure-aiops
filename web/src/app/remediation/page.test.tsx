import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { decideRemediationPlan, defenderCases, exposures, gaps, remediationOpportunities, remediationPlans, ruleFindings } = vi.hoisted(() => ({
  decideRemediationPlan: vi.fn(),
  defenderCases: vi.fn(),
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
  operationsApi: { decideRemediationPlan, remediationPlans, remediationOpportunities, defenderCases },
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
      opportunities: [{
        resource: { name: "vm-payroll-db", entity_type: "VirtualMachine" },
        application: "Payroll App",
        business_service: "Payroll",
        environment: "prod",
        owner: "payroll-team",
        subscription_id: "sub-1",
        subscription_connection: "conn-1",
        opportunity_type: "Patch overdue server",
        action_id: "patch-vm",
        evidence: ["Missing KB500 for 45 days"],
        patch_risk_score: 62,
        lifecycle_risk_score: 10,
        predictive_risk_score: 45,
        operational_debt_score: 20,
        read_only: true,
      }],
    }));
    defenderCases.mockResolvedValue(envelope({
      cases: [
        {
          resource_key: "res-mapped",
          weakness_key: "cve:cve-2026-1000",
          resource_name: "vm-checkout-db",
          evidence_citations: [
            { source_type: "assessment", source_id: "assess-1", severity: "high", summary: "Enable disk encryption", observed_at: "2026-08-18T05:00:00Z", freshness: "fresh" },
          ],
          business_context: { affected_services: ["Checkout"] },
          business_mapping_review_required: false,
          cost_of_action: "Low - scheduled maintenance window",
          cost_of_inaction: "High - continued exposure to a known weakness",
          disposition: "act_now",
          urgency_rationale: "Critical weakness with known business mapping",
          confidence: 0.9,
          max_severity: "high",
          catalog_match: true,
          outcome: "action_available",
          outcome_reason: "",
          observed_facts: ["Assessment reports high severity"],
          derived_inferences: [],
          unknowns: [],
          source_family_status: { assessment: { availability: "available", freshness: "fresh" } },
          contradictory_evidence: false,
          read_only: true,
        },
        {
          resource_key: "res-unmapped",
          weakness_key: "text:enable-disk-encryption",
          resource_name: "vm-unmapped",
          evidence_citations: [
            { source_type: "assessment", source_id: "assess-2", severity: "medium", summary: "Enable disk encryption", observed_at: "2026-08-18T05:00:00Z", freshness: "fresh" },
          ],
          business_context: {},
          business_mapping_review_required: true,
          cost_of_action: "Unknown - business ownership not established",
          cost_of_inaction: "Unknown - business ownership not established",
          disposition: "escalate",
          urgency_rationale: "Business mapping is unknown; escalate for ownership review",
          confidence: 0.3,
          max_severity: "medium",
          catalog_match: true,
          outcome: "action_available",
          outcome_reason: "",
          observed_facts: [],
          derived_inferences: [],
          unknowns: ["Business ownership unknown"],
          source_family_status: { assessment: { availability: "available", freshness: "fresh" } },
          contradictory_evidence: false,
          read_only: true,
        },
        {
          resource_key: "res-no-safe-action",
          weakness_key: "text:unmatched-weakness",
          resource_name: "vm-no-safe-action",
          evidence_citations: [
            { source_type: "alert", source_id: "alert-1", severity: "low", summary: "Unmatched weakness", observed_at: "2026-08-18T05:00:00Z", freshness: "fresh" },
          ],
          business_context: { affected_services: ["Checkout"] },
          business_mapping_review_required: false,
          cost_of_action: "Not applicable - no safe action exists",
          cost_of_inaction: "Low",
          disposition: "defer",
          urgency_rationale: "No catalog action matches this weakness",
          confidence: 0.4,
          max_severity: "low",
          catalog_match: false,
          outcome: "no_safe_action",
          outcome_reason: "no catalog match was found",
          observed_facts: [],
          derived_inferences: [],
          unknowns: [],
          source_family_status: { alert: { availability: "available", freshness: "fresh" } },
          contradictory_evidence: false,
          read_only: true,
        },
      ],
      read_only: true,
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

  it("renders a Defender case as a backlog row with disposition and urgency rationale", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Unified remediation backlog" })).toBeInTheDocument();
    expect(screen.getAllByText("vm-checkout-db").length).toBeGreaterThan(0);
    expect(screen.getByText(/Critical weakness with known business mapping/)).toBeInTheDocument();
  });

  it("shows citations, cost of action/inaction, and observed/inferred/unknown groupings for a selected Defender case", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Unified remediation backlog" });
    const rows = screen.getAllByRole("button", { name: "Review" });
    const row = screen.getAllByText("vm-checkout-db")[0].closest("article");
    expect(row).not.toBeNull();
    fireEvent.click(row!.querySelector("button")!);

    expect(await screen.findByText(/assessment:assess-1 - high severity - Enable disk encryption/)).toBeInTheDocument();
    expect(screen.getAllByText(/Low - scheduled maintenance window/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/High - continued exposure to a known weakness/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Observed: Assessment reports high severity/)).toBeInTheDocument();
    expect(rows.length).toBeGreaterThan(0);
  });

  it("renders review requirement and reduced confidence for a case with unknown business mapping", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Unified remediation backlog" });
    const row = screen.getAllByText("vm-unmapped")[0].closest("article");
    fireEvent.click(row!.querySelector("button")!);

    expect(await screen.findByText("Business mapping unknown")).toBeInTheDocument();
    expect(screen.getByText(/No priority can be assigned until business ownership is confirmed/)).toBeInTheDocument();
  });

  it("renders a no-safe-action case as an explicit outcome row with no approval control", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Unified remediation backlog" });
    const row = screen.getByText("vm-no-safe-action").closest("article");
    fireEvent.click(row!.querySelector("button")!);

    expect(await screen.findByText(/No safe automated action exists for this case/)).toBeInTheDocument();
    expect(screen.getByText("Plan required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
  });

  it("filters the backlog to Defender-sourced rows via the category filter", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Unified remediation backlog" });
    fireEvent.click(screen.getByRole("button", { name: "Defender" }));

    expect(screen.getAllByText("vm-checkout-db").length).toBeGreaterThan(0);
    expect(screen.queryByText("Patch payroll database")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getAllByText("Patch payroll database").length).toBeGreaterThan(0);
  });

  it("renders real backend values for an opportunity row with no blank placeholders", async () => {
    renderPage();

    await screen.findByRole("heading", { name: "Unified remediation backlog" });
    expect(screen.getByText("Patch Overdue Server")).toBeInTheDocument();
    expect(screen.getAllByText(/vm-payroll-db/).length).toBeGreaterThan(0);
    expect(screen.getByText("Missing KB500 for 45 days")).toBeInTheDocument();
  });
});
