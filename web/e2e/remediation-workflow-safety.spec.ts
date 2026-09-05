import { expect, test } from "@playwright/test";

/**
 * Phase 03.6 Plan 06: Playwright E2E infrastructure for the remediation
 * workflow-safety surface (blockers, degradation, patch-selection refusal,
 * recovery controls). Every spec here mocks its own `/api/v1/**` responses
 * -- the real Python API is never required to run this suite.
 *
 * Fixture shapes are copied (not imported) from
 * `web/src/app/remediation/page.test.tsx`'s `workflowFixture()`/
 * `executionRecord()` helpers so mocked data stays consistent with what the
 * Vitest component tests already prove -- importing across the
 * Vitest/Playwright test-runner boundary is not supported.
 */

const TARGET = "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-payroll";

test("loads the /remediation page and shows 'Fix safely, one step at a time' via dev-token auth", async ({ page }) => {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ json: { data: { plans: [] }, evidence: [], scope: {} } }));

  await page.goto("/remediation");

  await expect(page.getByRole("heading", { name: "Fix safely, one step at a time" })).toBeVisible();
});

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

function planListFixture() {
  return {
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
  };
}

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
      requirements: [
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
      status: overrides.approvalCurrent ? "current" : "none",
      stale_reasons: [],
      can_approve: true,
      allow_self_approval: false,
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

test.describe("Phase 03.6 workflow-safety surface (real browser)", () => {
  test("renders the blocker panel and degradation panel, with degradation preceding the Approve control in DOM order", async ({ page }) => {
    await page.route("**/remediation-plans**", (route) =>
      route.fulfill({ json: envelope(planListFixture()) }));
    await page.route("**/remediation/plans/*/workflow**", (route) =>
      route.fulfill({ json: envelope(workflowFixture({
        blockers: [{ code: "not_approved", step: "approve" }],
        degradation: [
          {
            source: "AUM patch inventory",
            availability: "unavailable",
            reason: "AUM patch inventory evidence is unavailable.",
          },
        ],
      })) }));

    await page.goto("/remediation");
    await page.getByRole("button", { name: "Patch payroll database" }).click();

    await expect(page.getByText("Workflow blockers")).toBeVisible();
    await expect(page.getByText("Degraded inputs")).toBeVisible();

    await page.getByRole("button", { name: "Approve", exact: false }).first().click();

    const degradationBox = await page.locator(".remediation-degradation").boundingBox();
    const recordDecisionBox = await page.getByRole("button", { name: "Record decision" }).boundingBox();
    expect(degradationBox).not.toBeNull();
    expect(recordDecisionBox).not.toBeNull();
    if (degradationBox && recordDecisionBox) {
      expect(degradationBox.y).toBeLessThan(recordDecisionBox.y);
    }
  });

  test("refuses to deselect the last remaining checked patch in a real browser (CR-07)", async ({ page }) => {
    await page.route("**/remediation-plans**", (route) =>
      route.fulfill({ json: envelope(planListFixture()) }));
    await page.route("**/remediation/plans/*/workflow**", (route) =>
      route.fulfill({ json: envelope(workflowFixture({
        availablePatches: [
          { patch_id: "KB600001", title: "Critical security update", severity: "Critical" },
          { patch_id: "KB600002", title: "Optional feature update", severity: "Low" },
        ],
      })) }));

    await page.goto("/remediation");
    await page.getByRole("button", { name: "Patch payroll database" }).click();

    const checkboxes = page.getByRole("checkbox");
    await expect(checkboxes).toHaveCount(2);
    await checkboxes.nth(1).click();
    await expect(checkboxes.nth(0)).toBeChecked();
    await expect(checkboxes.nth(1)).not.toBeChecked();
    await checkboxes.nth(0).click();

    await expect(checkboxes.nth(0)).toBeChecked();
    await expect(checkboxes.nth(1)).not.toBeChecked();
    await expect(page.getByText(
      "At least one patch must remain selected for this plan to be approved. Select a patch below, or use the mode line above to restore all eligible patches.",
    )).toBeVisible();
  });

  test("shows only the Cancel queued execution button when cancellable is true and retryable/supersedable are false", async ({ page }) => {
    await page.route("**/remediation-plans**", (route) =>
      route.fulfill({ json: envelope(planListFixture()) }));
    await page.route("**/remediation/plans/*/workflow**", (route) =>
      route.fulfill({ json: envelope(workflowFixture({
        execution: executionRecord({ status: "queued", cancellable: true, retryable: false, supersedable: false }),
      })) }));

    await page.goto("/remediation");
    await page.getByRole("button", { name: "Patch payroll database" }).click();
    await page.getByRole("button", { name: "Verify", exact: false }).first().click();

    await expect(page.getByRole("button", { name: "Cancel queued execution" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry approved snapshot" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Supersede this execution" })).toHaveCount(0);
  });
});
