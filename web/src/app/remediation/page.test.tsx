import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";

const {
  acceptRisk,
  approve,
  cancel,
  createExposureHandoff,
  execute,
  execution,
  exposureHandoffs,
  remediationPlans,
  retry,
  searchParams,
  supersede,
  workflow,
} = vi.hoisted(() => ({
  acceptRisk: vi.fn(),
  approve: vi.fn(),
  cancel: vi.fn(),
  createExposureHandoff: vi.fn(),
  execute: vi.fn(),
  execution: vi.fn(),
  exposureHandoffs: vi.fn(),
  remediationPlans: vi.fn(),
  retry: vi.fn(),
  searchParams: { current: new URLSearchParams() },
  supersede: vi.fn(),
  workflow: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams.current,
}));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return {
    ...actual,
    operationsApi: { remediationPlans },
    remediationApi: {
      approve,
      cancel,
      createExposureHandoff,
      execute,
      execution,
      exposureHandoffs,
      retry,
      supersede,
      workflow,
    },
    vulnerabilityApi: { acceptRisk },
  };
});

import RemediationPage from "./page";
import { usePollingBackoff } from "./polling";
import { ApiError } from "@/lib/types";

const TARGET = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll";
const OTHER_TARGET = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-other";
const PRIVATE_ENDPOINT_TARGET = "/subscriptions/sub-1/resourceGroups/rg-network/providers/Microsoft.Network/privateEndpoints/cosmos-pe";

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
      can_operate: overrides.canOperate ?? true,
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
        available_patches: overrides.availablePatches ?? [
          { patch_id: "KB600001", title: "Critical security update", severity: "Critical" },
        ],
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
      requirements: overrides.approvalRequirements ?? [
        {
          policy_id: "change-control",
          role: "Change Manager",
          stage: "Planning",
          satisfied: Boolean(overrides.approvalCurrent),
          unmet_reason: overrides.approvalCurrent ? undefined : "pending",
          approval_evidence_required: ["Plan evidence reviewed"],
        },
      ],
      decisions: overrides.approvalCurrent ? [{ decision: "approved", approver: "approver@example.com", decided_at: "2026-09-03T00:00:00Z", execution_snapshot: { snapshot_hash: "snapshot-hash-1" }, self_approved: false }] : [],
      latest: overrides.approvalCurrent ? { decision: "approved", approver: "approver@example.com", decided_at: "2026-09-03T00:00:00Z", execution_snapshot: { snapshot_hash: "snapshot-hash-1" }, self_approved: false } : null,
      current: Boolean(overrides.approvalCurrent),
      status: overrides.approvalStatus ?? (overrides.approvalCurrent ? "current" : "none"),
      stale_reasons: overrides.staleReasons ?? [],
      can_approve: overrides.canApprove ?? true,
      allow_self_approval: overrides.allowSelfApproval ?? false,
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
    blockers: overrides.blockers ?? [],
    degradation: overrides.degradation ?? [],
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
    execution.mockResolvedValue(envelope(executionRecord()));
    retry.mockResolvedValue(envelope(executionRecord({ status: "running" })));
    cancel.mockResolvedValue(envelope(executionRecord({ status: "cancelled" })));
    supersede.mockResolvedValue(envelope(executionRecord({ status: "queued" })));
    exposureHandoffs.mockResolvedValue(envelope({
      cases: [],
      read_only: true,
      execution_transition: false,
    }));
    createExposureHandoff.mockResolvedValue(envelope({
      handoff_id: "exposure-handoff:generation-17:exposure-image-1",
      exposure_id: "exposure-image-1",
      target_kind: "container_image",
      direct_execution_supported: false,
      created_by: "operator@example.com",
      created_at: "2026-09-06T08:00:00Z",
      execution_transition: false,
    }));
    acceptRisk.mockResolvedValue(envelope({
      exception_id: "risk-audit-1",
      cve_id: "CVE-2026-0001",
      server_id: TARGET,
      reason: "Compensating control verified",
      approved_by: "operator@example.com",
      created_at: "2026-09-06T08:00:00Z",
      expires_at: "",
    }));
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
      [],
    ));
  });

  it("renders a bounded compliance finding as manual review when no generated plan matches", async () => {
    searchParams.current = new URLSearchParams({
      resource_key: PRIVATE_ENDPOINT_TARGET,
      review_source: "compliance",
      finding_type: "missing_private_endpoint",
      finding_severity: "high",
      finding_title: "Private endpoint network policy gap",
      recommendation: "Review private endpoint subnet policy and DNS linkage.",
    });

    renderPage();

    const reviewHeading = await screen.findByRole("heading", {
      name: "Private endpoint network policy gap",
    });
    const reviewPanel = reviewHeading.closest("section");
    if (!reviewPanel) {
      throw new Error("Compliance finding review panel was not rendered.");
    }
    const review = within(reviewPanel);

    expect(reviewHeading).toBeInTheDocument();
    expect(review.getByText("Compliance finding review")).toBeInTheDocument();
    expect(review.getByText("High")).toBeInTheDocument();
    expect(review.getByTitle(PRIVATE_ENDPOINT_TARGET)).toHaveTextContent(
      "…/providers/Microsoft.Network/privateEndpoints/cosmos-pe",
    );
    expect(screen.queryByText(PRIVATE_ENDPOINT_TARGET)).not.toBeInTheDocument();
    expect(screen.getAllByTitle(PRIVATE_ENDPOINT_TARGET)).toHaveLength(2);
    expect(review.getByRole("heading", { name: "Recommendation" })).toBeInTheDocument();
    expect(
      review.getByText("Review private endpoint subnet policy and DNS linkage."),
    ).toBeInTheDocument();
    expect(
      review.getByRole("heading", { name: "Governed network-owner review" }),
    ).toBeInTheDocument();
    expect(review.getByText("Manual review only")).toBeInTheDocument();
    expect(
      review.getByText(/No executable network action has been generated/),
    ).toBeInTheDocument();
    expect(
      review.getByText("Review-only handoff. No changes are submitted from this page."),
    ).toBeInTheDocument();
    expect(
      review.queryByRole("link", { name: "Show all fixes in scope" }),
    ).not.toBeInTheDocument();
    expect(review.getByRole("link", { name: "Open network topology" })).toHaveAttribute(
      "href",
      "/network",
    );
    expect(remediationPlans).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Record decision" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review and run" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm run" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Remediation workflow" })).not.toBeInTheDocument();
    expect(screen.getByText("From Compliance")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to compliance" })).toHaveAttribute("href", "/compliance");
    expect(workflow).not.toHaveBeenCalled();
    expect(approve).not.toHaveBeenCalled();
    expect(execute).not.toHaveBeenCalled();
  });

  it("accepts compliance review text at the exact query bounds", async () => {
    const title = "T".repeat(200);
    const recommendation = "R".repeat(1_000);
    searchParams.current = new URLSearchParams({
      resource_key: PRIVATE_ENDPOINT_TARGET,
      review_source: "compliance",
      finding_type: "missing_private_endpoint",
      finding_severity: "high",
      finding_title: title,
      recommendation,
    });
    renderPage();

    expect(
      await screen.findByRole("heading", { name: title }),
    ).toBeInTheDocument();
    expect(screen.getByText(recommendation)).toBeInTheDocument();
    expect(workflow).not.toHaveBeenCalled();
  });

  it("does not request or expose unrelated executable plans for a compliance resource", async () => {
    searchParams.current = new URLSearchParams({
      resource_key: PRIVATE_ENDPOINT_TARGET,
      review_source: "compliance",
      finding_type: "missing_owner",
      finding_severity: "medium",
      finding_title: "Missing accountable owner",
      recommendation: "Assign a network owner.",
    });

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Missing accountable owner" }),
    ).toBeInTheDocument();
    expect(remediationPlans).not.toHaveBeenCalled();
    expect(screen.queryByRole("navigation", { name: "Remediation workflow" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve|Run/ })).not.toBeInTheDocument();
    expect(workflow).not.toHaveBeenCalled();
    expect(approve).not.toHaveBeenCalled();
    expect(execute).not.toHaveBeenCalled();
  });

  it.each([
    ["an over-limit title", "T".repeat(201), "Review the private endpoint."],
    ["an over-limit recommendation", "Private endpoint policy gap", "R".repeat(1_001)],
    ["an incomplete finding", "Private endpoint policy gap", ""],
  ])("rejects %s instead of presenting untrusted review context", async (_case, title, recommendation) => {
    remediationPlans.mockResolvedValueOnce(envelope({ plans: [] }));
    searchParams.current = new URLSearchParams({
      resource_key: PRIVATE_ENDPOINT_TARGET,
      review_source: "compliance",
      finding_type: "missing_private_endpoint",
      finding_severity: "high",
      finding_title: title,
      recommendation,
    });

    renderPage();

    expect(await screen.findByText("No fix for this resource")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: title || "Private endpoint policy gap" }),
    ).not.toBeInTheDocument();
    expect(workflow).not.toHaveBeenCalled();
  });

  it.each([
    [
      "a legacy resource alias",
      (params: URLSearchParams) => {
        params.delete("resource_key");
        params.set("resource", PRIVATE_ENDPOINT_TARGET);
      },
    ],
    [
      "an extra query field",
      (params: URLSearchParams) => params.set("evidence", "arbitrary"),
    ],
    [
      "a duplicate allowlisted field",
      (params: URLSearchParams) => params.append("recommendation", "Second value"),
    ],
  ])("rejects compliance review context with %s", async (_case, mutate) => {
    remediationPlans.mockResolvedValueOnce(envelope({ plans: [] }));
    const params = new URLSearchParams({
      resource_key: PRIVATE_ENDPOINT_TARGET,
      review_source: "compliance",
      finding_type: "missing_private_endpoint",
      finding_severity: "high",
      finding_title: "Private endpoint policy gap",
      recommendation: "Review the private endpoint.",
    });
    mutate(params);
    searchParams.current = params;

    renderPage();

    expect(await screen.findByText("No fix for this resource")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Private endpoint policy gap" }),
    ).not.toBeInTheDocument();
    expect(workflow).not.toHaveBeenCalled();
  });

  it("lets an operator narrow approval to a chosen subset of available patches", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      availablePatches: [
        { patch_id: "KB600001", title: "Critical security update", severity: "Critical" },
        { patch_id: "KB600002", title: "Optional feature update", severity: "Low" },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    // Both patches start selected (default is "install everything available").
    expect(checkboxes.every((box) => (box as HTMLInputElement).checked)).toBe(true);

    fireEvent.click(checkboxes[1]);
    await waitFor(() => expect(workflow).toHaveBeenLastCalledWith(
      "plan-1",
      {},
      ["KB600001"],
    ));
  });

  it("refuses to deselect the last remaining checked patch (CR-07)", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      availablePatches: [
        { patch_id: "KB600001", title: "Critical security update", severity: "Critical" },
        { patch_id: "KB600002", title: "Optional feature update", severity: "Low" },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    // Uncheck KB600002 first, leaving KB600001 as the sole checked patch.
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    await waitFor(() => expect(workflow).toHaveBeenLastCalledWith("plan-1", {}, ["KB600001"]));
    await screen.findAllByText(/KB600001/);

    // Attempt to uncheck the last remaining checked patch (KB600001) --
    // this click must have no effect on selection.
    fireEvent.click(screen.getAllByRole("checkbox")[0]);

    const refreshedCheckboxes = screen.getAllByRole("checkbox");
    expect((refreshedCheckboxes[0] as HTMLInputElement).checked).toBe(true);
    expect((refreshedCheckboxes[1] as HTMLInputElement).checked).toBe(false);
    expect(
      screen.getByText(
        "At least one patch must remain selected for this plan to be approved. Select a patch below, or use the mode line above to restore all eligible patches.",
      ),
    ).toBeInTheDocument();
  });

  it("narrows an explicit selection to the intersection when evidence refresh shrinks availability, and refuses (never falls back to all) when the intersection is empty", async () => {
    workflow.mockResolvedValueOnce(envelope(workflowFixture({
      availablePatches: [
        { patch_id: "KB600001", title: "Critical security update", severity: "Critical" },
        { patch_id: "KB600002", title: "Optional feature update", severity: "Low" },
      ],
    })));
    // Second fetch (triggered by narrowing the explicit selection below)
    // simulates an evidence refresh where KB600001 is no longer available
    // -- the operator's remaining explicit selection is now KB600002 only,
    // which IS still available, so this should narrow (removal-only), not
    // refuse, on this step.
    workflow.mockResolvedValueOnce(envelope(workflowFixture({
      availablePatches: [
        { patch_id: "KB600002", title: "Optional feature update", severity: "Low" },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    // Narrow the explicit selection to just KB600002 (uncheck KB600001).
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    await waitFor(() => expect(workflow).toHaveBeenLastCalledWith("plan-1", {}, ["KB600002"]));

    // The second response's available_patches (KB600002 only) still
    // contains the explicit selection -- no refusal expected here, mode
    // line still reflects the explicit selection.
    await screen.findByText("1 of 1 patches explicitly selected.");
  });

  it("refuses (never falls back to all) when an evidence refresh narrows the available set to exclude every explicitly selected patch", async () => {
    workflow.mockResolvedValueOnce(envelope(workflowFixture({
      availablePatches: [
        { patch_id: "KB600001", title: "Critical security update", severity: "Critical" },
        { patch_id: "KB600002", title: "Optional feature update", severity: "Low" },
      ],
    })));
    // Second fetch (triggered by narrowing the explicit selection below)
    // drops KB600001 entirely from availability -- the operator's
    // remaining explicit selection (["KB600001"]) has an empty
    // intersection with the new available set. Must refuse, never widen
    // back to "all".
    workflow.mockResolvedValueOnce(envelope(workflowFixture({
      availablePatches: [
        { patch_id: "KB600003", title: "Unrelated update", severity: "Low" },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    // Narrow the explicit selection to just KB600001 (uncheck KB600002).
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    await waitFor(() => expect(workflow).toHaveBeenLastCalledWith("plan-1", {}, ["KB600001"]));

    await waitFor(() => expect(
      screen.getByText(
        "Your previously selected patches are no longer available. Choose at least one currently available patch.",
      ),
    ).toBeInTheDocument());
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
    expect(screen.getByText("Provider verification")).toBeInTheDocument();
    expect(screen.getAllByText("RME-1")).not.toHaveLength(0);
  });

  it("revalidates can_operate immediately before execution and fails closed when it changed", async () => {
    const current = workflowFixture({ approvalCurrent: true });
    const revoked = workflowFixture({
      approvalCurrent: true,
      action: {
        ...current.action,
        can_operate: false,
        operate_ineligible_reason: "operator_role_required",
      },
    });
    workflow
      .mockResolvedValueOnce(envelope(current))
      .mockResolvedValueOnce(envelope(revoked));
    searchParams.current = new URLSearchParams(
      `resource_key=${encodeURIComponent(TARGET)}`,
    );
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Run/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review and run" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm run" }));

    expect(
      await screen.findByText("operator_role_required"),
    ).toBeInTheDocument();
    expect(execute).not.toHaveBeenCalled();
  });

  it("keeps unsupported configuration actions in manual review", async () => {
    renderPage();
    await screen.findByText("Patch payroll database");
    fireEvent.click(screen.getByRole("button", { name: /Review configuration baseline/ }));

    await screen.findByText("Impact summary");
    expect(screen.getByText("Exact operation")).toBeInTheDocument();
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
        provider_submitted: true,
        retryable: true,
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getAllByText((_, element) => Boolean(element?.textContent?.includes("Provider rejected the update"))).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Attempt 1").length).toBeGreaterThan(0);
    const attemptLabel = screen.getByText("Attempt 1", {
      selector: ".remediation-attempt-card summary strong",
    });
    const attempt = attemptLabel.closest("details");
    expect(attempt).not.toHaveAttribute("open");
    expect(screen.getByText("1 event")).toBeInTheDocument();
    fireEvent.click(attemptLabel.closest("summary") as HTMLElement);
    expect(attempt).toHaveAttribute("open");
    expect(screen.getAllByText(/Provider accepted the operation/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Retry approved snapshot" })).toBeEnabled();
  });

  it("preserves a validated Exposure return path and complete handoff context", async () => {
    const returnTo =
      "/exposure/patch-priorities?subscription=sub-1&q=kernel&sort_by=severity&sort_direction=asc&page_size=25&target=server-1&drawer=evidence&generation=generation-17";
    searchParams.current = new URLSearchParams(
      `resource_key=${encodeURIComponent(TARGET)}&subscription=sub-1&cve=CVE-2026-0001&kb=KB600001&generation=generation-17&return_focus=exposure-server-1&return_to=${encodeURIComponent(returnTo)}`,
    );

    renderPage();

    const back = await screen.findByRole("link", { name: "Back to exposure" });
    expect(back).toHaveAttribute("href", returnTo);
    expect(screen.getByText(/From Exposure/)).toBeInTheDocument();
    expect(screen.getByText(/generation-17/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing executes from Exposure/)).toBeInTheDocument();
  });

  it("rejects an external return target instead of creating an open redirect", async () => {
    searchParams.current = new URLSearchParams(
      `resource_key=${encodeURIComponent(TARGET)}&return_to=${encodeURIComponent("https://evil.example/steal")}`,
    );

    renderPage();

    expect(await screen.findByRole("link", { name: "Back to exposure" })).toHaveAttribute(
      "href",
      "/exposure/patch-priorities",
    );
  });

  it("creates an audited container review handoff without calling execution", async () => {
    exposureHandoffs.mockResolvedValue(envelope({
      cases: [
        {
          handoff_id: "exposure-handoff:generation-17:exposure-image-1",
          exposure_id: "exposure-image-1",
          resource_key: `sha256:${"a".repeat(64)}`,
          weakness_key: "CVE-2026-0002",
          target_kind: "container_image",
          read_model_generation_id: "generation-17",
          outcome: "review_handoff",
          outcome_reason: "Exact digest evidence is ready for governed review.",
          direct_execution_supported: false,
          review_handoff: {
            target_kind: "container_image",
            repository: "platform/api",
            image_digest: `sha256:${"a".repeat(64)}`,
            safe_blast_radius_known: true,
          },
        },
      ],
      read_only: true,
      execution_transition: false,
    }));
    searchParams.current = new URLSearchParams(
      `handoff=${encodeURIComponent("exposure-handoff:generation-17:exposure-image-1")}&return_to=${encodeURIComponent("/exposure/patch-priorities?subscription=sub-1&generation=generation-17")}`,
    );
    const user = userEvent.setup();

    renderPage();
    expect(
      await screen.findByRole("heading", { name: "Governed container review" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/No executable container action is available/)).toBeInTheDocument();
    await user.click(
      screen.getByRole("checkbox", {
        name: "I acknowledge this is a non-executable review handoff",
      }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Review handoff reason" }),
      "Platform team review requested",
    );
    await user.click(
      screen.getByRole("button", { name: "Create governed review handoff" }),
    );

    await waitFor(() =>
      expect(createExposureHandoff).toHaveBeenCalledWith(
        {
          exposure_id: "exposure-image-1",
          reason: "Platform team review requested",
          risk_acknowledged: true,
          risk_exception_id: "",
        },
        {},
      ),
    );
    expect(await screen.findByText(/Audit ID:/)).toHaveTextContent(
      "exposure-handoff:generation-17:exposure-image-1",
    );
    expect(execute).not.toHaveBeenCalled();
  });

  it("shows no-safe-action container evidence without a mutation control", async () => {
    exposureHandoffs.mockResolvedValue(envelope({
      cases: [
        {
          handoff_id: "exposure-handoff:generation-17:exposure-image-2",
          exposure_id: "exposure-image-2",
          resource_key: `sha256:${"b".repeat(64)}`,
          weakness_key: "CVE-2026-0003",
          target_kind: "container_image",
          read_model_generation_id: "generation-17",
          outcome: "no_safe_action",
          outcome_reason: "Exact digest deployment evidence is unavailable.",
          direct_execution_supported: false,
          review_handoff: {
            target_kind: "container_image",
            safe_blast_radius_known: false,
          },
        },
      ],
      read_only: true,
      execution_transition: false,
    }));
    searchParams.current = new URLSearchParams(
      `handoff=${encodeURIComponent("exposure-handoff:generation-17:exposure-image-2")}`,
    );

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "No safe container action" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Exact digest deployment evidence is unavailable."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create governed review handoff" }),
    ).not.toBeInTheDocument();
    expect(execute).not.toHaveBeenCalled();
  });

  it("records risk through the shared confirmation dialog with session-owned identity", async () => {
    searchParams.current = new URLSearchParams(
      `resource_key=${encodeURIComponent(TARGET)}&cve=CVE-2026-0001&generation=generation-17`,
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findAllByText(/KB600001/);

    const invoker = screen.getByRole("button", { name: "Record risk exception" });
    await user.click(invoker);
    expect(
      screen.getByRole("heading", { name: "Record risk exception" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Session approver")).toHaveValue(
      "Authenticated session",
    );
    await user.type(screen.getByLabelText("Reason"), "Compensating control verified");
    await user.click(screen.getByRole("button", { name: "Record exception" }));

    await waitFor(() =>
      expect(acceptRisk).toHaveBeenCalledWith({
        cve_id: "CVE-2026-0001",
        server_id: TARGET,
        reason: "Compensating control verified",
        expires_at: undefined,
      }),
    );
    expect(await screen.findByText(/Audit ID:/)).toHaveTextContent("risk-audit-1");
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(invoker).toHaveFocus());
  });

  describe("read-only Copilot handoff (Plan 11-15)", () => {
    const MUTATION_CONTROL_NAMES = [
      "Approve",
      "Run",
      "Review and run",
      "Confirm run",
      "Record decision",
      "Retry",
      "Cancel",
      "Supersede",
    ];

    it("offers an advisory Copilot entry point that exposes no mutation control", async () => {
      workflow.mockResolvedValue(envelope(workflowFixture({ approvalCurrent: true })));
      searchParams.current = new URLSearchParams(
        `resource_key=${encodeURIComponent(TARGET)}`,
      );
      renderPage();
      await screen.findAllByText(/KB600001/);

      fireEvent.click(
        screen.getByRole("button", { name: /Ask Copilot about remediation/i }),
      );
      const drawer = await screen.findByRole("dialog", { name: "Operations Copilot" });

      // Advisory explanation starter is available inside the drawer...
      expect(
        within(drawer).getByRole("button", { name: /Explain this remediation plan/i }),
      ).toBeInTheDocument();
      // ...but no approval/execution/recovery mutation control lives in it.
      for (const name of MUTATION_CONTROL_NAMES) {
        expect(within(drawer).queryByRole("button", { name })).toBeNull();
      }
      // Opening Copilot never invokes a governed mutation endpoint.
      expect(approve).not.toHaveBeenCalled();
      expect(execute).not.toHaveBeenCalled();
    });

    it("keeps execution bound to the existing governed server endpoint, not Copilot", async () => {
      workflow.mockResolvedValue(envelope(workflowFixture({ approvalCurrent: true })));
      searchParams.current = new URLSearchParams(
        `resource_key=${encodeURIComponent(TARGET)}`,
      );
      renderPage();
      await screen.findAllByText(/KB600001/);

      // Open the advisory drawer first; it must not intercept governed controls.
      fireEvent.click(
        screen.getByRole("button", { name: /Ask Copilot about remediation/i }),
      );
      await screen.findByRole("dialog", { name: "Operations Copilot" });

      fireEvent.click(screen.getByRole("button", { name: /Run/ }));
      fireEvent.click(screen.getByRole("button", { name: "Review and run" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm run" }));

      await waitFor(() => expect(execute).toHaveBeenCalledWith("plan-1", {}));
    });

    it("keeps deterministic cited evidence and the governed workflow available without Copilot narration", async () => {
      workflow.mockResolvedValue(envelope(workflowFixture({ approvalCurrent: true })));
      searchParams.current = new URLSearchParams(
        `resource_key=${encodeURIComponent(TARGET)}`,
      );
      renderPage();
      await screen.findAllByText(/KB600001/);

      // The deterministic governed surface renders with no narration provider.
      expect(
        screen.getByRole("button", { name: /Ask Copilot about remediation/i }),
      ).toBeInTheDocument();
      expect(screen.getAllByText(/Missing critical update/).length).toBeGreaterThan(0);
      expect(screen.getByRole("button", { name: /Run/ })).toBeInTheDocument();
    });
  });
});

describe("Phase 03.5: approval requirement satisfaction and authorization", () => {
  it("renders 0 of 0 requirements satisfied with no rows for a zero-requirement plan", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ approvalRequirements: [] })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.getByText("0 of 0 requirements satisfied")).toBeInTheDocument();
    expect(screen.queryByText("Satisfied")).not.toBeInTheDocument();
    expect(screen.queryByText("Unmet")).not.toBeInTheDocument();
  });

  it("renders exactly one satisfied and one unmet row for a two-role SoD fixture", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalRequirements: [
        {
          policy_id: "change-control",
          role: "Change Manager",
          stage: "Planning",
          satisfied: false,
          unmet_reason: "wrong_role_decision",
          approval_evidence_required: ["Plan evidence reviewed"],
        },
        {
          policy_id: "security-review",
          role: "Security Response Owner",
          stage: "Planning",
          satisfied: true,
          approval_evidence_required: ["Risk assessment accepted"],
        },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.getByText("1 of 2 requirements satisfied")).toBeInTheDocument();
    expect(screen.getAllByText("Satisfied")).toHaveLength(1);
    expect(screen.getAllByText("Unmet")).toHaveLength(1);
    expect(
      screen.getByText(/A decision exists, but not from the required Change Manager\. This requirement remains unmet\./),
    ).toBeInTheDocument();
  });

  it("joins a single stale reason without a trailing conjunction", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalCurrent: true,
      approvalStatus: "stale",
      staleReasons: ["stale_action_version"],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(
      screen.getByText(/but the plan's action version changed since\. A new decision is required before running\./),
    ).toBeInTheDocument();
  });

  it("joins two stale reasons with 'and'", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalCurrent: true,
      approvalStatus: "stale",
      staleReasons: ["stale_action_version", "stale_policy_version"],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(
      screen.getByText(/the plan's action version changed and the approval policy was updated/),
    ).toBeInTheDocument();
  });

  it("shows the self-approval policy banner only when the policy flag is true", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ allowSelfApproval: true })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.getByText(/Demo policy exception: self-approval is enabled/)).toBeInTheDocument();
  });

  it("renders no self-approval banner at all when the policy flag is false", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ allowSelfApproval: false })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.queryByText(/Demo policy exception/)).not.toBeInTheDocument();
  });

  it("shows the self-approved audit badge only for a decision recorded self_approved:true", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalCurrent: true,
      execution: executionRecord(),
      approval: {
        requirements: [],
        decisions: [
          { decision_id: "RMD-1", decision: "approved", approver: "self@example.com", decided_at: "2026-09-03T00:00:00Z", self_approved: true, self_approval_policy_id: "demo-self-approval" },
          { decision_id: "RMD-2", decision: "approved", approver: "other@example.com", decided_at: "2026-09-02T00:00:00Z", self_approved: false },
        ],
        latest: { decision: "approved", approver: "self@example.com", decided_at: "2026-09-03T00:00:00Z" },
        current: true,
        status: "current",
        stale_reasons: [],
        can_approve: true,
        allow_self_approval: true,
      },
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getAllByText("Self-approved (demo exception)")).toHaveLength(1);
  });

  it("disables Record decision with its exact reason when can_approve is false", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ canApprove: false })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();
    expect(
      screen.getByText("You can review this approval but cannot record a decision. Ask an approver to record it."),
    ).toBeInTheDocument();
  });

  it("disables Review and run/Confirm run with its exact reason when can_operate is false, independent of can_approve", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ approvalCurrent: true, canOperate: false })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Run/ }));

    expect(screen.getByRole("button", { name: "Review and run" })).toBeDisabled();
    expect(
      screen.getByText("You can approve work but cannot run it. Ask an operator to run this approved snapshot."),
    ).toBeInTheDocument();
    // can_approve is independently true in this fixture -- Record decision
    // (a different step) is unaffected by can_operate being false.
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(screen.getByRole("button", { name: "Record decision" })).toBeEnabled();
  });
});

describe("Phase 03.5 CR-05: stable per-role attestation in the approval UI", () => {
  it("requires an explicit role selection and disables Record decision until one is chosen when multiple unmet roles remain", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalRequirements: [
        {
          policy_id: "change-control",
          role: "Change Manager",
          role_id: "change-control:change-manager",
          stage: "Planning",
          satisfied: false,
          unmet_reason: "pending",
          approval_evidence_required: ["Plan evidence reviewed"],
        },
        {
          policy_id: "security-review",
          role: "Security Response Owner",
          role_id: "security-review:security-response-owner",
          stage: "Planning",
          satisfied: false,
          unmet_reason: "pending",
          approval_evidence_required: ["Risk assessment accepted"],
        },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    // Both unmet roles are offered, and the decision cannot be recorded
    // until one is explicitly selected (Phase 03.5 CR-05 fix: a decision
    // attests exactly one required role).
    expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Rationale"), { target: { value: "CAB approved" } });
    fireEvent.change(screen.getByLabelText("Expires"), { target: { value: "2026-12-31" } });
    expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^Role for this decision/), {
      target: { value: "security-review:security-response-owner" },
    });
    expect(screen.getByRole("button", { name: "Record decision" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    await waitFor(() => expect(approve).toHaveBeenCalledWith(
      "plan-1",
      expect.objectContaining({
        decision: "approved",
        role_id: "security-review:security-response-owner",
      }),
      {},
    ));
    expect(screen.getByRole("button", { name: "Record decision" })).toBeInTheDocument();
    expect(screen.queryByText("Approved operation")).not.toBeInTheDocument();
  });

  it("auto-selects the single unmet role without requiring an explicit choice", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture()));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    fireEvent.change(screen.getByLabelText("Rationale"), { target: { value: "CAB approved" } });
    fireEvent.change(screen.getByLabelText("Expires"), { target: { value: "2026-12-31" } });

    // Exactly one unmet role (the default single-row fixture) -- no
    // selection is required, and Record decision is immediately enabled.
    expect(screen.getByRole("button", { name: "Record decision" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));

    await waitFor(() => expect(approve).toHaveBeenCalledWith(
      "plan-1",
      expect.objectContaining({ decision: "approved", role_id: "Change Manager" }),
      {},
    ));
    expect(screen.getByText("Approved operation")).toBeInTheDocument();
  });

  it("discloses which decision and approver satisfied each requirement row", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      approvalRequirements: [
        {
          policy_id: "change-control",
          role: "Change Manager",
          role_id: "change-control:change-manager",
          stage: "Planning",
          satisfied: true,
          approver: "change-manager@example.com",
          decision_id: "RMD-AAAA1111",
          approval_evidence_required: ["Plan evidence reviewed"],
        },
        {
          policy_id: "security-review",
          role: "Security Response Owner",
          role_id: "security-review:security-response-owner",
          stage: "Planning",
          satisfied: true,
          approver: "security-owner@example.com",
          decision_id: "RMD-BBBB2222",
          approval_evidence_required: ["Risk assessment accepted"],
        },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    // Two distinct rows, satisfied by two distinct decisions/approvers --
    // an operator must never be able to mistake one person's sign-off for
    // two-stakeholder governance (Phase 03.5 CR-05 fix).
    expect(screen.getByText(/change-manager@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/RMD-AAAA1111/)).toBeInTheDocument();
    expect(screen.getByText(/security-owner@example.com/)).toBeInTheDocument();
    expect(screen.getByText(/RMD-BBBB2222/)).toBeInTheDocument();
  });
});

describe("Phase 03.6 Plan 04: Blocker Contract, Degradation Contract, and Verify-step honesty", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParams.current = new URLSearchParams();
    remediationPlans.mockResolvedValue(envelope({
      plans: [
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
    approve.mockResolvedValue(envelope({ decision_id: "RMD-1", decision: "approved" }));
    execute.mockResolvedValue(envelope(executionRecord()));
    execution.mockResolvedValue(envelope(executionRecord()));
    retry.mockResolvedValue(envelope(executionRecord({ status: "running" })));
    cancel.mockResolvedValue(envelope(executionRecord({ status: "cancelled" })));
    supersede.mockResolvedValue(envelope(executionRecord({ status: "queued" })));
  });

  it("renders a recognized blocker code in the cross-step summary panel using client fallback copy", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      blockers: [{ code: "not_approved", step: "approve" }],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    expect(screen.getByText("Workflow blockers")).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getAllByText("Approve").length).toBeGreaterThan(0);
    expect(screen.getByText("No decision has been recorded yet.")).toBeInTheDocument();
    expect(screen.getByText(/Record an approval decision for every required role\./)).toBeInTheDocument();
  });

  it("renders the unrecognized-code fallback and logs telemetry exactly once even across re-renders", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    workflow.mockResolvedValue(envelope(workflowFixture({
      blockers: [{ code: "totally_novel_code", step: "review" }],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    expect(screen.getByText("An unrecognized workflow condition (totally_novel_code) is blocking this step.")).toBeInTheDocument();
    expect(warnSpy).toHaveBeenCalledWith("remediation.blocker.unknown_code", { code: "totally_novel_code" });
    const callsAfterFirstRender = warnSpy.mock.calls.length;

    // Trigger a re-render (switching steps) -- must not log again for the
    // same unrecognized code.
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));
    fireEvent.click(screen.getByRole("button", { name: /Review impact/ }));

    expect(warnSpy).toHaveBeenCalledTimes(callsAfterFirstRender);
    warnSpy.mockRestore();
  });

  it("never renders already_succeeded as a blocker row and never triggers unrecognized-code telemetry for it", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    workflow.mockResolvedValue(envelope(workflowFixture({
      blockers: [{ code: "already_succeeded", step: "verify" }],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    expect(screen.queryByText("Workflow blockers")).not.toBeInTheDocument();
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("renders a degradation row above the Approve control with source, reason, counts, and freshness", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      degradation: [
        {
          source: "AUM patch inventory",
          availability: "degraded",
          reason: "AUM patch inventory evidence is degraded.",
          dropped_count: 3,
          unmatched_count: 2,
          freshness: "2026-09-01T00:00:00Z",
        },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.getByText("Degraded inputs")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("AUM patch inventory")).toBeInTheDocument();
    expect(screen.getByText("AUM patch inventory evidence is degraded.")).toBeInTheDocument();
    expect(screen.getByText("3 evidence row(s) dropped, 2 unmatched for this scope.")).toBeInTheDocument();
    expect(screen.getByText("Last known good: 2026-09-01T00:00:00Z")).toBeInTheDocument();
  });

  it("renders no degradation section at all when the array is empty", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({ degradation: [] })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);

    expect(screen.queryByText("Degraded inputs")).not.toBeInTheDocument();
  });

  it("omits the counts clause entirely when both dropped_count and unmatched_count are zero/absent", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      degradation: [
        {
          source: "Vulnerability evidence (AUM/Defender)",
          availability: "unavailable",
          reason: "Vulnerability evidence is unavailable.",
        },
      ],
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    expect(screen.getByText("Vulnerability evidence is unavailable.")).toBeInTheDocument();
    expect(screen.queryByText(/evidence row\(s\) dropped/)).not.toBeInTheDocument();
    expect(screen.getByText("Freshness: unknown")).toBeInTheDocument();
  });

  it("renders the pre-submission honesty sentence when provider_submitted is false and failure_details is populated", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "failed",
        outcome: "failed",
        failure_details: "No execution identity configured",
        provider_submitted: false,
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByText(
      "Blocked before submission: No execution identity configured. No change was sent to the provider.",
    )).toBeInTheDocument();
  });

  it("renders the post-submission honesty sentence when provider_submitted is true and failure_details is populated", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "failed",
        outcome: "failed",
        failure_details: "Provider rejected the update",
        provider_submitted: true,
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByText("Submitted; provider reported: Provider rejected the update.")).toBeInTheDocument();
  });

  it("renders the closed pre-submission fallback sentence when failure_details is empty, never dangling punctuation", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "failed",
        outcome: "failed",
        failure_details: "",
        provider_submitted: false,
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByText(
      "Blocked before submission: no failure detail was recorded for this attempt. No change was sent to the provider.",
    )).toBeInTheDocument();
  });

  it("renders the closed post-submission fallback sentence when failure_details is empty", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "failed",
        outcome: "failed",
        failure_details: "",
        provider_submitted: true,
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByText(
      "Submitted; the provider did not return failure detail for this attempt.",
    )).toBeInTheDocument();
  });
});

describe("Phase 03.6 Plan 05: Recovery Controls, Reconciliation Summary, and Lineage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParams.current = new URLSearchParams();
    remediationPlans.mockResolvedValue(envelope({
      plans: [
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
    approve.mockResolvedValue(envelope({ decision_id: "RMD-1", decision: "approved" }));
    execute.mockResolvedValue(envelope(executionRecord()));
    execution.mockResolvedValue(envelope(executionRecord()));
    retry.mockResolvedValue(envelope(executionRecord({ status: "running" })));
    cancel.mockResolvedValue(envelope(executionRecord({ status: "cancelled" })));
    supersede.mockResolvedValue(envelope(executionRecord({ status: "queued" })));
  });

  it("renders only Cancel when cancellable is true and retryable/supersedable are false, and completes the confirm flow", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({ status: "queued", cancellable: true, retryable: false, supersedable: false }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByRole("button", { name: "Cancel queued execution" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry approved snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supersede this execution" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel queued execution" }));
    expect(screen.getByRole("alertdialog", { name: "Confirm cancel" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));

    await waitFor(() => expect(cancel).toHaveBeenCalledWith("RME-1", {}));
  });

  it("renders only Supersede when supersedable is true, with a required reason before Confirm supersede is enabled", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({ status: "failed", cancellable: false, retryable: false, supersedable: true }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByRole("button", { name: "Supersede this execution" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel queued execution" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Supersede this execution" }));
    const confirmButton = screen.getByRole("button", { name: "Confirm supersede" });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Root cause fixed; superseding" } });
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    await waitFor(() => expect(supersede).toHaveBeenCalledWith("RME-1", "Root cause fixed; superseding", {}));
  });

  it("renders no recovery-control button when all three are false and the execution is non-terminal", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({ status: "running", cancellable: false, retryable: false, supersedable: false }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.queryByRole("button", { name: "Cancel queued execution" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry approved snapshot" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Supersede this execution" })).not.toBeInTheDocument();
  });

  it("renders the shared blocker vocabulary explanation when a supersede click is refused server-side by a race", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({ status: "failed", cancellable: false, retryable: false, supersedable: true }),
    })));
    const raceError = new ApiError(409, "conflict", "execution_active", { reason: "execution_active" });
    supersede.mockRejectedValueOnce(raceError);
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));
    fireEvent.click(screen.getByRole("button", { name: "Supersede this execution" }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Attempting supersede" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm supersede" }));

    await waitFor(() => expect(screen.getByText(
      "This execution is still active and cannot be superseded until it reaches a terminal failed or cancelled state.",
    )).toBeInTheDocument());
  });

  it("logs unknown-code telemetry (WR-02) when a supersede race refusal returns a reason RecoveryControls has never seen via workflow.blockers[]", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({ status: "failed", cancellable: false, retryable: false, supersedable: true }),
    })));
    // This reason is deliberately absent from workflow.blockers[] and from
    // BLOCKER_VOCABULARY -- RecoveryControls's ineligibility callout is the
    // *only* call site that ever sees it, so a telemetry event here proves
    // WR-02's centralization actually reaches this call site independently
    // of WorkflowBlockers/stepBlockerEcho.
    const raceError = new ApiError(409, "conflict", "supersede_race_novel_reason", { reason: "supersede_race_novel_reason" });
    supersede.mockRejectedValueOnce(raceError);
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));
    fireEvent.click(screen.getByRole("button", { name: "Supersede this execution" }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Attempting supersede" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm supersede" }));

    await waitFor(() => expect(screen.getByText(
      "An unrecognized workflow condition (supersede_race_novel_reason) is blocking this step.",
    )).toBeInTheDocument());
    expect(warnSpy).toHaveBeenCalledWith("remediation.blocker.unknown_code", { code: "supersede_race_novel_reason" });
    warnSpy.mockRestore();
  });

  it("renders remaining/submitted attempts, verification deadline, and next check regardless of which recovery controls are visible", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "running",
        cancellable: false,
        retryable: false,
        supersedable: false,
        remaining_attempts: 2,
        submitted_attempt_count: 1,
        verification_deadline_at: "2026-09-05T00:00:00Z",
        next_verification_at: "2026-09-04T00:05:00Z",
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(within(screen.getByText("Attempts remaining").closest("div") as HTMLElement).getByText("2")).toBeInTheDocument();
    expect(within(screen.getByText("Submitted attempts").closest("div") as HTMLElement).getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Verification deadline")).toBeInTheDocument();
    expect(screen.getByText(/Next automatic check:/)).toBeInTheDocument();
  });

  it("renders the reconciled_incomplete sentence with KB count and code-formatted list, plus a Confirmed cleared line when kbs_cleared is non-empty", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "succeeded",
        outcome: "succeeded",
        cancellable: false,
        retryable: false,
        supersedable: false,
        evidence_reconciliation: {
          status: "reconciled_incomplete",
          kbs_cleared: ["KB600001"],
          kbs_remaining: ["KB600002"],
          assessed_at: "2026-09-04T00:00:00Z",
        },
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByText("Provider reported success, but 1 patch(es) remain present: KB600002.")).toBeInTheDocument();
    expect(screen.getByText("Confirmed cleared: KB600001.")).toBeInTheDocument();
  });

  it("renders nothing from the Reconciliation section when evidence_reconciliation is absent or status is empty", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({ status: "succeeded", outcome: "succeeded" }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.queryByText(/Reconciliation/)).not.toBeInTheDocument();
  });

  it("renders lineage text for supersedes and superseded_by as plain monospace text, not a link", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        supersedes: "RME-0",
        superseded_by: "RME-2",
        superseded_reason: "Retry budget exhausted",
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    expect(screen.getByText(/Supersedes execution/)).toBeInTheDocument();
    expect(screen.getAllByText("RME-0").length).toBeGreaterThan(0);
    expect(screen.getByText(/Superseded by execution/)).toBeInTheDocument();
    expect(screen.getAllByText("RME-2").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /RME-0|RME-2/ })).not.toBeInTheDocument();
  });

  it("wires a Check reconciliation manual button beside the pending row that performs a one-off fetch without resuming automatic polling", async () => {
    workflow.mockResolvedValue(envelope(workflowFixture({
      execution: executionRecord({
        status: "succeeded",
        outcome: "succeeded",
        cancellable: false,
        retryable: false,
        supersedable: false,
        evidence_reconciliation: {
          status: "pending",
          kbs_cleared: [],
          kbs_remaining: [],
          assessed_at: "",
        },
      }),
    })));
    searchParams.current = new URLSearchParams(`resource_key=${encodeURIComponent(TARGET)}`);
    renderPage();
    await screen.findAllByText(/KB600001/);
    fireEvent.click(screen.getByRole("button", { name: /Verify/ }));

    const initialCalls = execution.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Check reconciliation" }));

    await waitFor(() => expect(execution.mock.calls.length).toBe(initialCalls + 1));
    expect(execution).toHaveBeenLastCalledWith("RME-1", {});
  });
});

describe("usePollingBackoff (Bounded Polling Contract)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops after exactly 40 requests when elapsed time under the stub never approaches the 600000ms ceiling", () => {
    let clock = 0;
    const now = () => {
      clock += 1;
      return clock;
    };
    const onPoll = vi.fn();
    const { result } = renderHook(() =>
      usePollingBackoff({ active: true, resetKey: "exec-request-ceiling", onPoll, now }));

    for (let i = 0; i < 40; i += 1) {
      act(() => {
        vi.runOnlyPendingTimers();
      });
    }

    expect(onPoll).toHaveBeenCalledTimes(40);
    expect(result.current.paused).toBe(true);
    expect(result.current.requestCount).toBe(40);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops immediately once 600000ms has elapsed under the stub, independent of request count", () => {
    const start = 1_000_000;
    let jumped = false;
    const now = vi.fn(() => (jumped ? start + 600_000 : start));
    const onPoll = vi.fn();
    const { result } = renderHook(() =>
      usePollingBackoff({ active: true, resetKey: "exec-elapsed-ceiling", onPoll, now }));

    // First scheduled poll (1500ms delay) fires normally.
    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(onPoll).toHaveBeenCalledTimes(1);

    // The clock stub now reports 600000ms elapsed since the first poll.
    // The already-scheduled 2nd poll still fires (timers are driven by
    // the fixed backoff sequence, not by `now()`), but the ceiling check
    // that runs immediately afterward must stop any further poll from
    // ever being scheduled -- proving the elapsed-time ceiling fires on
    // its own, independent of request count (well under the 40-request
    // ceiling).
    jumped = true;
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(result.current.paused).toBe(true);
    expect(onPoll).toHaveBeenCalledTimes(2);
    expect(onPoll.mock.calls.length).toBeLessThan(40);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops automatically on terminal status transition with no ceiling message", () => {
    const onPoll = vi.fn();
    const { result, rerender } = renderHook(
      ({ active }: { active: boolean }) =>
        usePollingBackoff({ active, resetKey: "exec-terminal", onPoll }),
      { initialProps: { active: true } },
    );

    act(() => {
      vi.advanceTimersByTime(1500);
    });
    expect(onPoll).toHaveBeenCalledTimes(1);

    act(() => {
      rerender({ active: false });
    });
    act(() => {
      vi.advanceTimersByTime(100_000);
    });

    expect(onPoll).toHaveBeenCalledTimes(1);
    expect(result.current.paused).toBe(false);
  });

  it("resets the poll counter and elapsed clock when resetKey changes (a fresh execution gets its own full budget)", () => {
    let clock = 0;
    const now = () => {
      clock += 1;
      return clock;
    };
    const onPoll = vi.fn();
    const { result, rerender } = renderHook(
      ({ resetKey }: { resetKey: string }) =>
        usePollingBackoff({ active: true, resetKey, onPoll, now }),
      { initialProps: { resetKey: "exec-reset-a" } },
    );

    for (let i = 0; i < 40; i += 1) {
      act(() => {
        vi.runOnlyPendingTimers();
      });
    }
    expect(result.current.paused).toBe(true);
    expect(result.current.requestCount).toBe(40);

    act(() => {
      rerender({ resetKey: "exec-reset-b" });
    });

    expect(result.current.paused).toBe(false);
    expect(result.current.requestCount).toBe(0);
  });
});
