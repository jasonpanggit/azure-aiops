import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const { approve, execute, remediationPlans, retry, searchParams, workflow } = vi.hoisted(() => ({
  approve: vi.fn(),
  execute: vi.fn(),
  remediationPlans: vi.fn(),
  retry: vi.fn(),
  searchParams: { current: new URLSearchParams() },
  workflow: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams.current,
}));

vi.mock("@/lib/services", () => ({
  operationsApi: { remediationPlans },
  remediationApi: { approve, execute, retry, workflow },
}));

import RemediationPage from "./page";

const TARGET = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll";
const OTHER_TARGET = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-other";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [{
    source_engine: "ARG",
    source_table: "securityresources",
    timestamp: "2026-09-03T00:00:00Z",
    confidence: "high",
    freshness: "fresh",
  }],
  scope: {},
  knowledge_version: "graph-1",
});

function executionRecord(overrides: Record<string, unknown> = {}) {
  return {
    execution_id: "RME-1",
    plan_id: "plan-1",
    status: "running",
    requested_by: "operator@example.com",
    approved_by: "approver@example.com",
    created_at: "2026-09-03T00:00:00Z",
    updated_at: "2026-09-03T00:01:00Z",
    provider_job_id: "arm-job-1",
    message: "Accepted; verification pending",
    attempt_count: 1,
    rollback_guidance: ["Restore the last known-good image"],
    verified_state: "InProgress",
    failure_details: "",
    outcome: "",
    execution_snapshot: {
      target_id: TARGET,
      patch_ids: ["KB600001"],
      target_kind: "Azure VM",
      operation: "install_patches",
      action_version: "version-1",
      snapshot_hash: "snapshot-hash-1",
    },
    attempts: [{
      attempt_number: 1,
      status: "running",
      actor: "operator@example.com",
      transitions: [{
        sequence: 1,
        status: "running",
        actor: "operator@example.com",
        timestamp: "2026-09-03T00:01:00Z",
        message: "Provider accepted the operation",
      }],
    }],
    history: [],
    retryable: false,
    cancellable: false,
    remaining_attempts: 2,
    ineligibility_reason: "provider_not_cancellable",
    ...overrides,
  };
}

function workflowFixture(overrides: Record<string, unknown> = {}) {
  const execution = overrides.execution ?? null;
  return {
    plan: {
      plan_id: "plan-1",
      action_id: "controlled-patch-recovery",
      action_version: "version-1",
      title: "Patch payroll database",
      status: "Draft - Approval Required",
      resource: { id: TARGET, name: "vm-payroll" },
      business_service: "Payroll",
      risk_assessment: { overall_risk: { level: "high" } },
      dependencies: { affected_services: ["Payroll"] },
      rollback_plan: { rollback_actions: ["Restore the last known-good image"] },
      executable: Boolean(overrides.approvalCurrent),
      ineligibility_reason: overrides.approvalCurrent ? "" : "not_approved",
    },
    action: {
      action_id: "controlled-patch-recovery",
      family: "patch",
      executable: true,
      manual_review_reason: "",
    },
    preview: {
      target: { resource: { id: TARGET }, resource_key: TARGET },
      operation: "install_patches",
      preconditions: ["Backup verified"],
      expected_effect: { risk: "reduced" },
      collateral_impact: { reboot: "possible" },
      execution_snapshot: {
        target_id: TARGET,
        patch_ids: ["KB600001"],
        target_kind: "Azure VM",
        operation: "install_patches",
        action_version: "version-1",
        snapshot_hash: "snapshot-hash-1",
      },
      executable: Boolean(overrides.approvalCurrent),
      ineligibility_reason: overrides.approvalCurrent ? "" : "not_approved",
    },
    preview_error: "",
    business_decision: {
      disposition: "schedule",
      business_impact: { status: "known", service: "Payroll" },
      cost_of_action: "15 minute maintenance window",
      cost_of_inaction: "Continued critical exposure",
      review_requirements: [],
      unknowns: [],
      urgency_rationale: { evidence_citations: ["assessment:assessment-1"] },
    },
    approval: {
      requirements: [{ role: "Change Manager" }],
      decisions: overrides.approvalCurrent ? [{ decision: "approved", approver: "approver@example.com", execution_snapshot: { snapshot_hash: "snapshot-hash-1" } }] : [],
      latest: overrides.approvalCurrent ? { decision: "approved", approver: "approver@example.com", execution_snapshot: { snapshot_hash: "snapshot-hash-1" } } : null,
      current: Boolean(overrides.approvalCurrent),
    },
    execution,
    executions: execution ? [execution] : [],
    steps: [
      { id: "select", label: "Select fix", status: "complete" },
      { id: "review", label: "Review impact", status: "complete" },
      { id: "approve", label: "Approve", status: overrides.approvalCurrent ? "complete" : "current" },
      { id: "run", label: "Run", status: execution ? "complete" : overrides.approvalCurrent ? "current" : "pending" },
      { id: "verify", label: "Verify", status: execution ? "current" : "pending" },
    ],
    recommended_step: execution ? "verify" : overrides.approvalCurrent ? "run" : "approve",
    evidence: [{ source_type: "assessment", source_id: "assessment-1", summary: "Missing critical update" }],
    audit: {
      decisions: overrides.approvalCurrent ? [{ decision: "approved", approver: "approver@example.com" }] : [],
      executions: execution ? [execution] : [],
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <ScopeProvider>
      <RemediationPage />
    </ScopeProvider>,
  );
}

describe("Governed remediation workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParams.current = new URLSearchParams();
    remediationPlans.mockResolvedValue(envelope({
      plans: [
        {
          plan_id: "plan-other",
          action_version: "version-1",
          action_id: "configuration-baseline-recovery",
          title: "Review configuration baseline",
          status: "Draft",
          resource: { id: OTHER_TARGET, name: "vm-other" },
        },
        {
          plan_id: "plan-1",
          action_version: "version-1",
          action_id: "controlled-patch-recovery",
          title: "Patch payroll database",
          status: "Draft",
          resource: { id: TARGET, name: "vm-payroll" },
          business_service: "Payroll",
        },
      ],
    }));
    workflow.mockImplementation((planId: string) => Promise.resolve(envelope(
      planId === "plan-1"
        ? workflowFixture()
        : workflowFixture({
            plan: {
              ...workflowFixture().plan,
              plan_id: "plan-other",
              action_id: "configuration-baseline-recovery",
              title: "Review configuration baseline",
              resource: { id: OTHER_TARGET },
            },
            action: {
              action_id: "configuration-baseline-recovery",
              family: "configuration",
              executable: false,
              manual_review_reason: "No bounded provider handler is allowlisted for this action.",
            },
            preview: { ...workflowFixture().preview, execution_snapshot: null, executable: false, ineligibility_reason: "action_not_executable" },
            steps: workflowFixture().steps.map((step) => (
              ["approve", "run", "verify"].includes(step.id)
                ? { ...step, status: "blocked" }
                : step
            )),
            recommended_step: "manual_review",
          }),
    )));
    approve.mockResolvedValue(envelope({ decision_id: "RMD-1", decision: "approved" }));
    execute.mockResolvedValue(envelope(executionRecord()));
    retry.mockResolvedValue(envelope(executionRecord({ status: "running" })));
  });

  it("shows the simplified five-step workflow and generated fixes only", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Fix safely, one step at a time" })).toBeInTheDocument();
    for (const label of ["Select fix", "Review impact", "Approve", "Run", "Verify"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Patch payroll database")).toBeInTheDocument();
    expect(screen.queryByText("Unified remediation backlog")).not.toBeInTheDocument();
    expect(await screen.findByText("Evidence and audit history")).toBeInTheDocument();
  });

  it("uses resource and subscription handoff to select the matching fix", async () => {
    searchParams.current = new URLSearchParams(
      `resource_key=${encodeURIComponent(TARGET)}&subscription=sub-1`,
    );
    renderPage();

    await screen.findByText(`Scoped handoff: ${TARGET}`);
    await waitFor(() => expect(remediationPlans).toHaveBeenCalledWith(
      { subscription: ["sub-1"] },
      0,
      100,
      TARGET,
    ));
    await waitFor(() => expect(workflow).toHaveBeenCalledWith(
      "plan-1",
      { subscription: ["sub-1"] },
    ));
  });

  it("reviews exact operation, impact, rollback, and evidence together", async () => {
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();

    expect((await screen.findAllByText(/Continued critical exposure/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/KB600001/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Restore the last known-good image/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Missing critical update/).length).toBeGreaterThan(0);
  });

  it("records approval against the exact preview hash", async () => {
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    fireEvent.change(screen.getByLabelText("Rationale"), { target: { value: "CAB approved exact snapshot" } });
    fireEvent.change(screen.getByLabelText("Expires"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    await waitFor(() => expect(approve).toHaveBeenCalledWith(
      "plan-1",
      expect.objectContaining({
        decision: "approved",
        preview_snapshot_hash: "snapshot-hash-1",
      }),
      {},
    ));
  });

  it("runs only a currently approved, business-ready snapshot", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ approvalCurrent: true })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Run/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review and run" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("exact approved snapshot once");
    fireEvent.click(screen.getByRole("button", { name: "Confirm run" }));

    await waitFor(() => expect(execute).toHaveBeenCalledWith("plan-1", {}));
  });

  it("keeps unsupported configuration actions in manual review", async () => {
    renderPage();
    await screen.findByText("Patch payroll database");
    fireEvent.click(screen.getByRole("button", { name: /Review configuration baseline/ }));

    expect(await screen.findByText(/Manual review required:/)).toHaveTextContent(
      "No bounded provider handler is allowlisted",
    );
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(screen.getByText("Manual review only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
  });

  it("shows provider verification and immutable attempt history", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalCurrent: true,
      execution: executionRecord({
        status: "failed",
        outcome: "failed",
        verified_state: "Failed",
        failure_details: "Provider rejected the update",
        retryable: true,
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getAllByText("Provider rejected the update").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Attempt 1").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Provider accepted the operation/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Retry approved snapshot" })).toBeEnabled();
  });
});
