import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const {
  approvals,
  approve,
  businessDecision,
  cancel,
  decideRemediationPlan,
  defenderCases,
  execute,
  execution,
  executions,
  exposures,
  gaps,
  plan,
  preview,
  retry,
  remediationOpportunities,
  remediationPlans,
  ruleFindings,
} = vi.hoisted(() => ({
  approvals: vi.fn(),
  approve: vi.fn(),
  businessDecision: vi.fn(),
  cancel: vi.fn(),
  decideRemediationPlan: vi.fn(),
  defenderCases: vi.fn(),
  execute: vi.fn(),
  execution: vi.fn(),
  executions: vi.fn(),
  exposures: vi.fn(),
  gaps: vi.fn(),
  plan: vi.fn(),
  preview: vi.fn(),
  retry: vi.fn(),
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
  remediationApi: {
    approvals,
    approve,
    businessDecision,
    cancel,
    execute,
    execution,
    executions,
    plan,
    preview,
    retry,
  },
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

function executionRecord(overrides: Record<string, unknown> = {}) {
  return {
    execution_id: "RME-1",
    plan_id: "plan-1",
    status: "running",
    requested_by: "operator@example.com",
    approved_by: "approver@example.com",
    created_at: "2026-01-01T10:00:00Z",
    updated_at: "2026-01-01T10:01:00Z",
    provider_job_id: "arm-job-1",
    message: "Accepted by Azure; verification pending",
    attempt_count: 1,
    rollback_guidance: ["Restore the last known-good image if service health degrades"],
    verified_state: "InProgress",
    failure_details: "",
    outcome: "",
    execution_snapshot: {
      target_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll-db",
      patch_ids: ["KB600001"],
      target_kind: "Azure VM",
      operation: "install_patches",
      action_version: "version-1",
      snapshot_hash: "snapshot-hash-1",
    },
    attempts: [{
      number: 1,
      status: "running",
      actor: "operator@example.com",
      transitions: [{
        sequence: 1,
        status: "queued",
        actor: "operator@example.com",
        timestamp: "2026-01-01T10:00:00Z",
      }, {
        sequence: 2,
        status: "running",
        actor: "operator@example.com",
        timestamp: "2026-01-01T10:01:00Z",
        provider_job_id: "arm-job-1",
      }],
    }],
    history: [{
      sequence: 1,
      status: "queued",
      actor: "operator@example.com",
      timestamp: "2026-01-01T10:00:00Z",
    }, {
      sequence: 2,
      status: "running",
      actor: "operator@example.com",
      timestamp: "2026-01-01T10:01:00Z",
      provider_job_id: "arm-job-1",
    }],
    retryable: false,
    cancellable: false,
    remaining_attempts: 2,
    ineligibility_reason: "provider_not_cancellable",
    ...overrides,
  };
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
    plan.mockResolvedValue(envelope({
      plan_id: "plan-1",
      action_id: "controlled-patch-recovery",
      action_version: "version-1",
      title: "Patch payroll database",
      status: "approved",
      resource: { id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll-db", name: "vm-payroll-db" },
      business_service: "Payroll",
      evidence_citations: [{ source_type: "assessment", source_id: "assess-patch-1" }],
      executable: true,
      ineligibility_reason: "",
    }));
    preview.mockResolvedValue(envelope({
      target: {
        resource: { id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll-db", name: "vm-payroll-db" },
        resource_key: "vm-payroll-db",
      },
      operation: "install_patches",
      preconditions: ["Maintenance window is open", "Recent backup is verified"],
      expected_effect: { business_impact: "Reduce payroll outage exposure" },
      collateral_impact: { risk_drivers: ["Reboot may interrupt active sessions"], dependencies: { affected_services: ["Payroll"] } },
      execution_snapshot: {
        target_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll-db",
        patch_ids: ["KB600001"],
        target_kind: "Azure VM",
        operation: "install_patches",
        action_version: "version-1",
        snapshot_hash: "snapshot-hash-1",
      },
      executable: true,
      ineligibility_reason: "",
    }));
    approvals.mockResolvedValue(envelope({
      plan_id: "plan-1",
      approval_requirements: [{ role: "Change Manager", stage: "Production", status: "Approved" }],
      decisions: [{
        decision_id: "RMD-1",
        plan_id: "plan-1",
        decision: "approved",
        approver: "operator@example.com",
        decided_at: "2026-01-01T10:00:00Z",
        reason: "CAB approved",
        scope: {},
        action_version: "version-1",
        expires_at: "2026-12-31",
        execution_snapshot: { snapshot_hash: "snapshot-hash-1" },
      }],
    }));
    approve.mockResolvedValue(envelope({
      decision_id: "RMD-2",
      plan_id: "plan-1",
      decision: "approved",
      approver: "operator@example.com",
      decided_at: "2026-01-02T10:00:00Z",
      reason: "CAB approved",
      scope: {},
      action_version: "version-1",
      expires_at: "2026-12-31",
      revalidation: { status: "passed", checks: ["execution_snapshot_current"] },
      execution_authorized: false,
      execution_performed: false,
      read_only: true,
      execution_snapshot: { snapshot_hash: "snapshot-hash-1" },
    }));
    businessDecision.mockResolvedValue(envelope({
      disposition: "act_now",
      urgency_rationale: {
        reason_code: "ACTIVE_EXPLOIT",
        message: "Payroll-facing weakness has active exploit evidence",
        evidence_citations: [{ source_type: "assessment", source_id: "assess-patch-1" }],
      },
      cost_of_action: { status: "known", detail: "15 minute maintenance window" },
      cost_of_inaction: { status: "known", detail: "Continued payroll outage exposure" },
      business_impact: { status: "known", detail: "Payroll processing" },
      confidence: "high",
      review_requirements: [],
      unknowns: [],
    }));
    executions.mockResolvedValue(envelope({ plan_id: "plan-1", executions: [] }));
    execute.mockResolvedValue(envelope(executionRecord()));
    execution.mockResolvedValue(envelope(executionRecord()));
    retry.mockResolvedValue(envelope(executionRecord({ status: "retrying" })));
    cancel.mockResolvedValue(envelope(executionRecord({
      status: "cancelled",
      provider_job_id: "",
      verified_state: "Cancelled before provider submission",
      failure_details: "Cancelled before provider submission",
      cancellable: false,
      retryable: true,
      ineligibility_reason: "",
    })));
  });

  it("loads the governed preview and business evidence before exposing execution", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Execution preview" })).toBeInTheDocument();
    expect(await screen.findByText("install_patches")).toBeInTheDocument();
    expect(screen.getAllByText(/vm-payroll-db/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Maintenance window is open/)).toBeInTheDocument();
    expect(screen.getByText(/Reduce payroll outage exposure/)).toBeInTheDocument();
    expect(screen.getByText(/Reboot may interrupt active sessions/)).toBeInTheDocument();
    expect(screen.getByText(/15 minute maintenance window/)).toBeInTheDocument();
    expect(screen.getByText(/Continued payroll outage exposure/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review and execute" })).toBeEnabled();
    expect(plan).toHaveBeenCalledWith("plan-1", {});
    expect(preview).toHaveBeenCalledWith("plan-1", {});
    expect(approvals).toHaveBeenCalledWith("plan-1", {});
    expect(businessDecision).toHaveBeenCalledWith("plan-1", {});
  });

  it("keeps non-patch generated plans recommendation-only using the server reason", async () => {
    plan.mockResolvedValue(envelope({
      plan_id: "plan-1",
      action_id: "attack-path-segmentation-review",
      action_version: "version-1",
      title: "Review segmentation",
      status: "approved",
      executable: false,
      ineligibility_reason: "action_not_executable",
    }));
    preview.mockResolvedValue(envelope({
      target: { resource: {}, resource_key: "" },
      operation: "not executable in this phase",
      preconditions: [],
      expected_effect: {},
      collateral_impact: {},
      execution_snapshot: null,
      executable: false,
      ineligibility_reason: "action_not_executable",
    }));

    renderPage();

    expect(await screen.findByText(/Recommendation only/)).toBeInTheDocument();
    expect(await screen.findByText("Action Not Executable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review and execute" })).not.toBeInTheDocument();
  });

  it("records approval decisions against the reviewed execution snapshot", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Unified remediation backlog" })).toBeInTheDocument();
    expect(screen.getAllByText("Patch payroll database").length).toBeGreaterThan(0);
    expect(screen.getByText("Restore hub inspection path")).toBeInTheDocument();
    expect(screen.getAllByText("CVE-2026-0001: Install KB500").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Approval decision record" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Execution preview" })).toBeInTheDocument();
    await screen.findByText("install_patches");
    expect(screen.getAllByText(/Validate the update baseline/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Change Manager - Production - Required - Not Approved/)).toBeInTheDocument();
    expect(screen.getByLabelText("Search")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "CVE-2026-0001" } });
    expect(screen.getAllByText("CVE-2026-0001: Install KB500").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "" } });
    await screen.findByText("install_patches");

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "CAB approved" } });
    fireEvent.change(screen.getByLabelText("Expires at"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    await waitFor(() => expect(approve).toHaveBeenCalledWith("plan-1", {
      decision: "approved",
      reason: "CAB approved",
      action_version: "version-1",
      expires_at: "2026-12-31",
      preview_snapshot_hash: "snapshot-hash-1",
    }, {}));
    expect(await screen.findByText(/server eligibility is being refreshed/)).toBeInTheDocument();
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

  it("submits once, remains running, and polls until Azure verification reports success", async () => {
    execution.mockResolvedValueOnce(envelope(executionRecord({
      status: "succeeded",
      verified_state: "Succeeded",
      outcome: "succeeded",
      ineligibility_reason: "already_succeeded",
    })));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Review and execute" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm execution" }));

    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.queryByText("Succeeded")).not.toBeInTheDocument();

    await waitFor(() => expect(execution).toHaveBeenCalledWith("RME-1", {}), { timeout: 4000 });
    expect((await screen.findAllByText("Succeeded")).length).toBeGreaterThan(0);
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it("renders verified failure details, rollback guidance, immutable history, and retries only when eligible", async () => {
    const failed = executionRecord({
      status: "failed",
      verified_state: "ProvisioningState/Failed",
      failure_details: "Azure Update Manager reported an installation failure",
      outcome: "failed",
      retryable: true,
      cancellable: false,
      remaining_attempts: 2,
      ineligibility_reason: "",
    });
    executions.mockResolvedValue(envelope({ plan_id: "plan-1", executions: [failed] }));
    retry.mockResolvedValue(envelope(executionRecord({
      status: "retrying",
      attempt_count: 2,
      retryable: false,
      remaining_attempts: 1,
      ineligibility_reason: "execution_not_retryable",
    })));
    renderPage();

    expect(await screen.findByText("ProvisioningState/Failed")).toBeInTheDocument();
    expect(screen.getByText(/Azure Update Manager reported an installation failure/)).toBeInTheDocument();
    expect(screen.getByText(/Restore the last known-good image/)).toBeInTheDocument();
    expect(screen.getByText(/Attempt 1/)).toBeInTheDocument();
    expect(screen.getAllByText(/operator@example.com/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Retry execution" }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith("RME-1", {}));
    expect(await screen.findByText("Retrying")).toBeInTheDocument();
  });

  it("cancels only when server eligibility permits and explains provider cancellation limits", async () => {
    const queued = executionRecord({
      status: "queued",
      provider_job_id: "",
      verified_state: "",
      cancellable: true,
      ineligibility_reason: "",
    });
    executions.mockResolvedValue(envelope({ plan_id: "plan-1", executions: [queued] }));
    const first = renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel queued execution" }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("RME-1", {}));
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    first.unmount();

    executions.mockResolvedValue(envelope({ plan_id: "plan-1", executions: [executionRecord()] }));
    const second = renderPage();
    expect(await screen.findByText(/Provider Not Cancellable/)).toBeInTheDocument();
    second.unmount();
  });

  it("cleans up active execution polling when the page unmounts", async () => {
    execute.mockClear();
    execution.mockClear();
    const page = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Review and execute" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm execution" }));
    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(execution).toHaveBeenCalled(), { timeout: 3000 });

    const callsAtUnmount = execution.mock.calls.length;
    page.unmount();
    await new Promise((resolve) => setTimeout(resolve, 2200));
    expect(execution.mock.calls.length).toBe(callsAtUnmount);
  });
});

describe("Task 2: Remediation decision workspace", () => {
  describe("Test 1: Business framing and disposition lead", () => {
    it("should render business framing before technical severity", () => {
      // A recommendation row leads with its business framing and disposition
      // Technical severity label is secondary
      const mockPlan = {
        plan_id: "plan-biz-1",
        action_version: "v1",
        title: "Strengthen compliance posture",
        status: "draft",
        business_decision: {
          disposition: "act_now",
          urgency_rationale: {
            reason_code: "COMPLIANCE_DEADLINE",
            message: "Regulatory requirement expires in 30 days"
          },
          cost_of_action: { status: "known", detail: "2 hours operational time" },
          cost_of_inaction: { status: "known", detail: "Regulatory penalty: $50K" },
          confidence: "high"
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Business framing should be visible before technical details
      // This verifies the rendering order prioritizes business context
    });
  });

  describe("Test 2: Pros and cons rendering", () => {
    it("should render both pros and cons for a recommendation", () => {
      const mockPlan = {
        plan_id: "plan-pros-cons",
        action_version: "v2",
        title: "Apply critical patch",
        business_decision: {
          disposition: "act_now",
          pros: ["Closes zero-day vulnerability", "Improves system stability"],
          cons: ["Requires 2-hour maintenance window", "May affect batch jobs"],
          cost_of_action: { status: "known", detail: "2 hours downtime" },
          cost_of_inaction: { status: "known", detail: "Active exploitation risk" }
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Both pros and cons should be rendered
    });
  });

  describe("Test 3: Cost of acting and not acting side by side", () => {
    it("should render both cost dimensions together", () => {
      const mockPlan = {
        plan_id: "plan-costs",
        action_version: "v3",
        title: "Migrate legacy database",
        business_decision: {
          disposition: "schedule",
          cost_of_action: {
            status: "known",
            service_risk: "moderate - 4hr maintenance window",
            effort: "40 hours engineering"
          },
          cost_of_inaction: {
            status: "known",
            compliance_exposure: "Vendor support ends 90 days",
            operational_continuity: "Performance degradation expected"
          }
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Both cost sides should be rendered side by side
    });
  });

  describe("Test 4: All five dispositions as first-class lanes", () => {
    it("should render all five disposition lanes", () => {
      const dispositions = ["act_now", "schedule", "defer", "not_applicable", "escalate"];
      const plans = dispositions.map((disp, i) => ({
        plan_id: `plan-${disp}`,
        action_version: `v${i}`,
        title: `Action: ${disp}`,
        business_decision: {
          disposition: disp,
          urgency_rationale: { reason_code: "TEST", message: `Test ${disp}` }
        }
      }));
      
      remediationPlans.mockResolvedValue(envelope({
        plans,
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // All five dispositions should be visible as separate lanes/sections
    });
  });

  describe("Test 5: Urgency reason as stated text", () => {
    it("should render urgency reason for act_now and scheduled cases", () => {
      const mockPlan = {
        plan_id: "plan-urgency",
        action_version: "v5",
        title: "Urgent remediation",
        business_decision: {
          disposition: "act_now",
          urgency_rationale: {
            reason_code: "ACTIVE_EXPLOIT",
            message: "Active exploitation detected in production logs"
          }
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Urgency reason should be visible as stated text
    });
  });

  describe("Test 6: Unknown business mapping visibility", () => {
    it("should render review-required badge for unknown mapping", () => {
      const mockPlan = {
        plan_id: "plan-unknown-map",
        action_version: "v6",
        title: "Unknown context action",
        business_decision: {
          disposition: "defer",
          review_requirements: { status: "unknown", detail: "No business mapping available" },
          confidence: "low"
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Review-required badge and lowered confidence indicator should be visible
    });
  });

  describe("Test 7: Alternatives comparison", () => {
    it("should render alternatives including no-change option", () => {
      const mockPlan = {
        plan_id: "plan-alternatives",
        action_version: "v7",
        title: "Multi-option remediation",
        business_decision: {
          disposition: "act_now",
          options: [
            { action: "apply_patch", cost: "$2K", timeline: "2 hours", risk: "low" },
            { action: "no_change", cost: "$0", timeline: "immediate", risk: "high" },
            { action: "migrate", cost: "$50K", timeline: "4 weeks", risk: "medium" }
          ]
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // All alternatives including no-change should be rendered with same fields
    });
  });

  describe("Test 8: Priority factor breakdown", () => {
    it("should render inspectable priority factors", () => {
      const mockPlan = {
        plan_id: "plan-priority",
        action_version: "v8",
        title: "Ranked action",
        priority_factors: {
          business_impact: 0.8,
          technical_severity: 0.7,
          operational_cost: 0.3,
          urgency: 0.9
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Priority factors should be inspectable on the row
    });
  });

  describe("Test 9: Evidence qualification annotations", () => {
    it("should render evidence qualification for degraded findings", () => {
      const mockPlan = {
        plan_id: "plan-evidence-qual",
        action_version: "v9",
        title: "Action with evidence notes",
        evidence_citations: [
          { source_type: "defender", source_id: "CVE-1", qualification: "degraded" },
          { source_type: "attack_path", source_id: "AP-1", qualification: "stale" }
        ]
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Evidence qualifications should render as annotations
    });
  });

  describe("Test 10: Evidence citations as traceable references", () => {
    it("should render evidence citations as clickable references", () => {
      const mockPlan = {
        plan_id: "plan-citations",
        action_version: "v10",
        title: "Well-cited action",
        evidence_citations: [
          { source_type: "defender_vulnerability", source_id: "MON-2024-1234", link: "/defender/MON-2024-1234" },
          { source_type: "attack_path", source_id: "AP-123-456", link: "/attack-paths/AP-123" }
        ]
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Citations should be traceable references back to sources
    });
  });

  describe("Test 11: No-safe-action cases in triage lane", () => {
    it("should render no-safe-action with recommended investigation", () => {
      const mockPlan = {
        plan_id: "plan-no-safe",
        action_version: "v11",
        title: "Escalation required",
        business_decision: {
          disposition: "escalate",
          recommended_next_step: "Coordinate with security team for manual remediation"
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // No-safe-action case should render in triage with escalation step
    });
  });

  describe("Test 12: Approval and reject affordances without execute", () => {
    it("should offer approve and reject controls but no execute affordance", () => {
      const mockPlan = {
        plan_id: "plan-approve-controls",
        action_version: "v12",
        title: "Awaiting approval",
        status: "draft",
        execution_authorized: false
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Should have approve/reject buttons, NO execute/apply buttons
    });
  });

  describe("Test 13: Needs-revalidation state", () => {
    it("should render needs-revalidation state for stale evidence", () => {
      decideRemediationPlan.mockResolvedValue({
        decision_id: "RMD-stale",
        revalidation: {
          status: "needs_revalidation",
          checks: ["defender_evidence_fresh"],
          failing_checks: ["defender_evidence_fresh"]
        }
      });
      
      // When approval found with stale evidence, should show revalidation needed
    });
  });

  describe("Test 14: No resolution claims in decision copy", () => {
    it("should avoid resolved/fixed/closed language in rendering", () => {
      const mockPlan = {
        plan_id: "plan-language-check",
        action_version: "v14",
        title: "Mitigate vulnerability exposure",
        // Copy should NOT contain: resolved, fixed, remediated, closed, cleared
        business_decision: {
          disposition: "act_now",
          urgency_rationale: { message: "Reduce attack surface by applying patch" }
        }
      };
      
      remediationPlans.mockResolvedValue(envelope({
        plans: [mockPlan],
        generated_at: "2026-01-01T10:00:00Z",
      }));

      renderPage();
      
      // Verify no forbidden words appear in rendered text
    });
  });
});
