"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import type { ScopeSelection } from "@/lib/scope";
import { useScope } from "@/lib/scope-context";
import {
  operationsApi,
  remediationApi,
} from "@/lib/services";
import type {
  RemediationExecution,
  RemediationWorkflow,
} from "@/lib/services";
import { ApiError } from "@/lib/types";
import type { RemediationDecision, RemediationPlan } from "@/lib/types";

type WorkflowStep = "select" | "review" | "approve" | "run" | "verify";

const WORKFLOW_STEPS: Array<{ id: WorkflowStep; label: string }> = [
  { id: "select", label: "Select fix" },
  { id: "review", label: "Review impact" },
  { id: "approve", label: "Approve" },
  { id: "run", label: "Run" },
  { id: "verify", label: "Verify" },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function details(value: unknown, fallback = "Not specified"): string {
  if (Array.isArray(value)) {
    return value.map((item) => details(item, "")).filter(Boolean).join(", ") || fallback;
  }
  if (isRecord(value)) {
    return Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined && item !== "")
      .map(([key, item]) => `${titleize(key)}: ${details(item, "")}`)
      .join(" · ") || fallback;
  }
  return String(value ?? "").trim() || fallback;
}

function resourceId(plan: RemediationPlan | RemediationWorkflow["plan"]): string {
  if (isRecord(plan.resource)) {
    return String(plan.resource.id ?? plan.resource.resource_key ?? plan.resource.name ?? "");
  }
  return String(plan.resource ?? plan.resource_key ?? "");
}

function resourceMatches(plan: RemediationPlan, requested: string): boolean {
  if (!requested) return true;
  const expected = requested.trim().toLowerCase();
  const actual = resourceId(plan).trim().toLowerCase();
  return actual === expected || actual.endsWith(`/${expected}`);
}

function businessEvidenceReady(workflow: RemediationWorkflow): boolean {
  const decision = workflow.business_decision;
  const reviewRequirements = decision.review_requirements;
  return Boolean(
    ["act_now", "schedule"].includes(decision.disposition ?? "")
    && isRecord(decision.business_impact)
    && decision.business_impact.status === "known"
    && (decision.urgency_rationale?.evidence_citations?.length ?? 0) > 0
    && (
      Array.isArray(reviewRequirements)
        ? reviewRequirements.length === 0
        : !reviewRequirements || Object.keys(reviewRequirements).length === 0
    )
    && (decision.unknowns?.length ?? 0) === 0
  );
}

function actionSummary(workflow: RemediationWorkflow): string {
  const snapshot = workflow.preview?.execution_snapshot;
  if (!snapshot) return "No executable snapshot";
  if (snapshot.snapshot_kind === "defender_configuration") {
    return `${snapshot.operation}: ${details(snapshot.desired_properties)}`;
  }
  return `${snapshot.operation}: ${snapshot.patch_ids.join(", ")}`;
}

/** Five-step, approval-gated remediation workflow. */
export default function RemediationPage() {
  return (
    <Suspense fallback={<div className="page-container"><StatePanel title="Preparing remediation" message="Loading the governed workflow." tone="loading" /></div>}>
      <RemediationContent />
    </Suspense>
  );
}

function RemediationContent() {
  const { scope } = useScope();
  const searchParams = useSearchParams();
  const requestedResource = searchParams.get("resource_key") ?? searchParams.get("resource") ?? "";
  const fromCve = searchParams.get("cve") ?? "";
  const fromKb = searchParams.get("kb") ?? "";
  const fromIncident = searchParams.get("incident") ?? "";
  const effectiveScope = useMemo<ScopeSelection>(() => {
    const scoped: ScopeSelection = { ...scope };
    const subscriptions = searchParams.getAll("subscription").filter(Boolean);
    const connections = searchParams.getAll("subscription_connection").filter(Boolean);
    if (subscriptions.length) scoped.subscription = subscriptions;
    if (connections.length) scoped.subscription_connection = connections;
    return scoped;
  }, [scope, searchParams]);
  const scopeKey = JSON.stringify(effectiveScope);
  const plans = useApi(
    () => operationsApi.remediationPlans(effectiveScope, 0, 100, requestedResource),
    [scopeKey, requestedResource],
  );
  const [selectedPlanId, setSelectedPlanId] = useState("");
  const [activeStep, setActiveStep] = useState<WorkflowStep>("select");
  const [query, setQuery] = useState("");
  const [workflow, setWorkflow] = useState<RemediationWorkflow | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState("");
  const [workflowRefresh, setWorkflowRefresh] = useState(0);
  const [decision, setDecision] = useState<RemediationDecision["decision"]>("approved");
  const [decisionReason, setDecisionReason] = useState("");
  const [decisionExpiresAt, setDecisionExpiresAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState("");
  const [confirmRun, setConfirmRun] = useState(false);
  const requestId = useRef(0);

  const planRows = useMemo(
    () => plans.data?.data.plans ?? [],
    [plans.data],
  );
  const filteredPlans = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return planRows.filter((plan) => {
      if (!normalized) return true;
      return [
        plan.title,
        plan.status,
        plan.action_id,
        plan.business_service,
        resourceId(plan),
      ].some((value) => String(value ?? "").toLowerCase().includes(normalized));
    });
  }, [planRows, query]);
  const selectedPlan = planRows.find((plan) => plan.plan_id === selectedPlanId) ?? null;

  useEffect(() => {
    if (!planRows.length) {
      setSelectedPlanId("");
      return;
    }
    if (selectedPlanId && planRows.some((plan) => plan.plan_id === selectedPlanId)) return;
    const contextual = planRows.find((plan) => resourceMatches(plan, requestedResource));
    setSelectedPlanId((contextual ?? planRows[0]).plan_id);
  }, [planRows, requestedResource, selectedPlanId]);

  useEffect(() => {
    if (!selectedPlanId) {
      setWorkflow(null);
      setWorkflowError("");
      return;
    }
    const currentRequest = ++requestId.current;
    setWorkflowLoading(true);
    setWorkflowError("");
    void remediationApi.workflow(selectedPlanId, effectiveScope)
      .then((response) => {
        if (requestId.current !== currentRequest) return;
        setWorkflow(response.data);
      })
      .catch((error) => {
        if (requestId.current !== currentRequest) return;
        setWorkflow(null);
        setWorkflowError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (requestId.current === currentRequest) setWorkflowLoading(false);
      });
    return () => {
      if (requestId.current === currentRequest) requestId.current += 1;
    };
    // scopeKey intentionally invalidates the request when any scope dimension changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey, selectedPlanId, workflowRefresh]);

  useEffect(() => {
    setActiveStep(selectedPlanId ? "review" : "select");
    setActionError("");
    setConfirmRun(false);
  }, [selectedPlanId]);

  useEffect(() => {
    const execution = workflow?.execution;
    if (!execution || !["queued", "running", "retrying"].includes(execution.status)) return;
    const timer = setTimeout(() => setWorkflowRefresh((value) => value + 1), 1500);
    return () => clearTimeout(timer);
  }, [workflow?.execution]);

  const recordDecision = async () => {
    const planId = String(workflow?.plan.plan_id ?? "");
    const actionVersion = String(workflow?.plan.action_version ?? "");
    if (!planId || !actionVersion || !workflow?.action.executable || submitting) return;
    if (decision === "approved" && !workflow.preview?.execution_snapshot) {
      setActionError("A current executable preview is required before approval.");
      return;
    }
    if (!decisionReason.trim()) {
      setActionError("Enter the approval rationale.");
      return;
    }
    if (decision === "approved" && !decisionExpiresAt) {
      setActionError("Approved decisions require a future expiry.");
      return;
    }
    setSubmitting(true);
    setActionError("");
    try {
      await remediationApi.approve(
        planId,
        {
          decision,
          reason: decisionReason.trim(),
          action_version: actionVersion,
          expires_at: decision === "approved" ? decisionExpiresAt : "",
          preview_snapshot_hash: decision === "approved"
            ? workflow.preview?.execution_snapshot?.snapshot_hash
            : undefined,
        },
        effectiveScope,
      );
      setDecisionReason("");
      setWorkflowRefresh((value) => value + 1);
      setActiveStep(decision === "approved" ? "run" : "approve");
    } catch (error) {
      if (error instanceof ApiError && error.details?.reason === "stale_execution_preview") {
        setActionError("The preview changed. Review the refreshed impact before approving.");
        setWorkflowRefresh((value) => value + 1);
        setActiveStep("review");
      } else {
        setActionError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const runPlan = async () => {
    const planId = String(workflow?.plan.plan_id ?? "");
    if (!planId || !workflow?.approval.current || submitting) return;
    setSubmitting(true);
    setActionError("");
    try {
      await remediationApi.execute(planId, effectiveScope);
      setConfirmRun(false);
      setWorkflowRefresh((value) => value + 1);
      setActiveStep("verify");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const retryExecution = async (execution: RemediationExecution) => {
    if (!execution.retryable || submitting) return;
    setSubmitting(true);
    setActionError("");
    try {
      await remediationApi.retry(execution.execution_id, effectiveScope);
      setWorkflowRefresh((value) => value + 1);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const selectedEvidence = workflow?.evidence ?? [];
  const audit = workflow?.audit ?? { decisions: [], executions: [] };
  const canRun = Boolean(
    workflow?.action.executable
    && workflow.approval.current
    && workflow.preview?.execution_snapshot
    && workflow.plan.executable
    && businessEvidenceReady(workflow),
  );
  const pageError = plans.error && planRows.length === 0 ? plans.error : null;

  return (
    <div className="page-container remediation-center">
      <PageHeader
        eyebrow="Governed remediation"
        title="Fix safely, one step at a time"
        description="Select a governed fix, review its impact, approve the exact snapshot, run it once, and verify the provider outcome."
        metadata={
          <>
            <span>Allowlisted actions only</span>
            <span>Approval-bound snapshots</span>
            <span>Provider-verified outcomes</span>
          </>
        }
      />
      <EvidenceBar
        evidence={plans.data?.evidence ?? []}
        knowledgeVersion={plans.data?.knowledge_version}
        warnings={plans.data?.warnings ?? []}
      />

      {(requestedResource || fromCve || fromKb || fromIncident) && (
        <div className="callout remediation-handoff">
          <span>
            Scoped handoff:
            {fromIncident ? ` incident ${fromIncident}` : ""}
            {fromCve ? ` ${fromCve}` : ""}
            {fromKb ? ` ${fromKb}` : ""}
            {requestedResource ? ` ${requestedResource}` : ""}
          </span>
          <Link className="button button-quiet" href="/remediation">Clear</Link>
        </div>
      )}

      <nav className="remediation-workflow-steps" aria-label="Remediation workflow">
        {WORKFLOW_STEPS.map((step) => {
          const projected = workflow?.steps.find((item) => item.id === step.id)?.status;
          const status = step.id === "select" ? "complete" : projected ?? "pending";
          return (
            <button
              type="button"
              key={step.id}
              className={activeStep === step.id ? "remediation-workflow-step-active" : ""}
              onClick={() => setActiveStep(step.id)}
              disabled={step.id !== "select" && !selectedPlan}
            >
              <span>{WORKFLOW_STEPS.findIndex((item) => item.id === step.id) + 1}</span>
              <strong>{step.label}</strong>
              <small>{titleize(status)}</small>
            </button>
          );
        })}
      </nav>

      {pageError ? (
        <StatePanel title="Remediation plans unavailable" message={pageError.message} tone="error" />
      ) : plans.loading ? (
        <StatePanel title="Loading governed fixes" message="Reading scoped, evidence-backed plans." tone="loading" />
      ) : (
        <div className="remediation-workflow-layout">
          <aside className="card remediation-workflow-selection">
            <div className="card-header">
              <div>
                <h2>Select fix</h2>
                <p>Only generated plans can enter approval and execution.</p>
              </div>
              <StatusBadge label={`${planRows.length} fixes`} tone="info" />
            </div>
            <div className="card-body">
              <label>
                Search fixes
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Action, resource, or service" />
              </label>
              <div className="plan-list">
                {filteredPlans.map((plan) => (
                  <button
                    type="button"
                    key={plan.plan_id}
                    className={`plan-row remediation-fix-option ${selectedPlanId === plan.plan_id ? "plan-row-selected" : ""}`}
                    onClick={() => setSelectedPlanId(plan.plan_id)}
                  >
                    <span>
                      <StatusBadge label={plan.status || "Draft"} tone={statusTone(plan.status)} compact />
                      <StatusBadge label={titleize(String(plan.action_id ?? "manual review"))} tone="info" compact />
                    </span>
                    <strong>{plan.title}</strong>
                    <small>{resourceId(plan) || plan.business_service || "Scope not mapped"}</small>
                  </button>
                ))}
                {!filteredPlans.length && <StatePanel title="No governed fixes" message="No generated remediation plan matches this scope and search." />}
              </div>
            </div>
          </aside>

          <main className="card remediation-workflow-main">
            {workflowLoading ? (
              <StatePanel title="Loading workflow" message="Resolving impact, approval, execution, and audit state." tone="loading" />
            ) : workflowError ? (
              <StatePanel title="Workflow unavailable" message={workflowError} tone="error" />
            ) : !workflow ? (
              <StatePanel title="Select a fix" message="Choose a generated plan to begin." />
            ) : (
              <>
                <div className="card-header">
                  <div>
                    <span className="eyebrow">Step {WORKFLOW_STEPS.findIndex((item) => item.id === activeStep) + 1} of 5</span>
                    <h2>{WORKFLOW_STEPS.find((item) => item.id === activeStep)?.label}</h2>
                    <p>{workflow.plan.title}</p>
                  </div>
                  <StatusBadge
                    label={workflow.action.executable ? titleize(workflow.action.family) : "Manual review"}
                    tone={workflow.action.executable ? "success" : "warning"}
                  />
                </div>
                <div className="card-body remediation-workflow-content">
                  {activeStep === "select" && (
                    <section>
                      <h3>Selected fix</h3>
                      <p>{workflow.plan.title}</p>
                      <p>Resource: <code>{resourceId(workflow.plan) || "Not mapped"}</code></p>
                      <button type="button" className="button button-primary" onClick={() => setActiveStep("review")}>Review impact</button>
                    </section>
                  )}

                  {activeStep === "review" && (
                    <>
                      {!workflow.action.executable && (
                        <p className="callout callout-warning" role="status">
                          Manual review required: {workflow.action.manual_review_reason}
                        </p>
                      )}
                      {workflow.preview_error && (
                        <p className="callout callout-warning">Preview blocked: {titleize(workflow.preview_error)}</p>
                      )}
                      <section className="remediation-review-grid">
                        <div>
                          <h3>Impact and evidence</h3>
                          <p>Disposition: {titleize(workflow.business_decision.disposition ?? "not assessed")}</p>
                          <p>Business impact: {details(workflow.business_decision.business_impact)}</p>
                          <p>Cost of acting: {details(workflow.business_decision.cost_of_action)}</p>
                          <p>Cost of inaction: {details(workflow.business_decision.cost_of_inaction)}</p>
                          <p>Risk: {details(workflow.plan.risk_assessment)}</p>
                          <p>Dependencies: {details(workflow.plan.dependencies)}</p>
                        </div>
                        <div>
                          <h3>Exact operation</h3>
                          <p>Family: {titleize(workflow.action.family)}</p>
                          <p>Action: <code>{workflow.action.action_id}</code></p>
                          <p>Target: <code>{workflow.preview?.execution_snapshot?.target_id ?? resourceId(workflow.plan)}</code></p>
                          <p>Operation: <code>{workflow.preview?.operation ?? "Manual review only"}</code></p>
                          {workflow.preview?.execution_snapshot?.snapshot_kind === "defender_configuration" ? (
                            <>
                              <p>Prior state: {details(workflow.preview.execution_snapshot.prior_properties)}</p>
                              <p>Approved state: {details(workflow.preview.execution_snapshot.desired_properties)}</p>
                            </>
                          ) : (
                            <p>Patch selection: {workflow.preview?.execution_snapshot?.patch_ids.join(", ") || "None"}</p>
                          )}
                          <p>Rollback: {details(workflow.plan.rollback_plan)}</p>
                        </div>
                      </section>
                      <section>
                        <h3>Evidence citations</h3>
                        {selectedEvidence.length ? (
                          <ul>
                            {selectedEvidence.map((citation, index) => (
                              <li key={index}>{details(citation)}</li>
                            ))}
                          </ul>
                        ) : <p className="callout callout-warning">No cited evidence is available.</p>}
                      </section>
                      {workflow.action.executable && workflow.preview?.execution_snapshot ? (
                        <button type="button" className="button button-primary" onClick={() => setActiveStep("approve")}>Continue to approval</button>
                      ) : !workflow.action.executable ? (
                        <p>This recommendation cannot enter automated approval or execution. Route it to the owning platform team with the evidence above.</p>
                      ) : (
                        <p>Approval is unavailable until the provider can produce a current executable preview.</p>
                      )}
                    </>
                  )}

                  {activeStep === "approve" && (
                    <>
                      {!workflow.action.executable ? (
                        <StatePanel title="Manual review only" message={workflow.action.manual_review_reason} />
                      ) : !workflow.preview?.execution_snapshot ? (
                        <StatePanel title="Preview required" message="Return to Review impact and resolve the provider preview before approval." />
                      ) : (
                        <>
                          <p className="callout callout-warning">
                            Approval binds to snapshot <code>{workflow.preview?.execution_snapshot?.snapshot_hash ?? "unavailable"}</code>. It does not run the change.
                          </p>
                          <p>Required: {details(workflow.approval.requirements)}</p>
                          <p>Latest decision: {workflow.approval.latest ? `${workflow.approval.latest.decision} by ${workflow.approval.latest.approver}` : "None"}</p>
                          <div className="remediation-approval-form">
                            <label>
                              Decision
                              <select value={decision} onChange={(event) => setDecision(event.target.value as RemediationDecision["decision"])}>
                                <option value="approved">Approve</option>
                                <option value="rejected">Reject</option>
                                <option value="expired">Expire</option>
                              </select>
                            </label>
                            <label>
                              Rationale
                              <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} />
                            </label>
                            {decision === "approved" && (
                              <label>
                                Expires
                                <input type="date" value={decisionExpiresAt} onChange={(event) => setDecisionExpiresAt(event.target.value)} />
                              </label>
                            )}
                            <button type="button" className="button button-primary" disabled={submitting} onClick={() => void recordDecision()}>
                              {submitting ? "Recording…" : "Record decision"}
                            </button>
                          </div>
                        </>
                      )}
                    </>
                  )}

                  {activeStep === "run" && (
                    <>
                      <h3>Approved operation</h3>
                      <p>{actionSummary(workflow)}</p>
                      <p>Target: <code>{workflow.preview?.execution_snapshot?.target_id ?? resourceId(workflow.plan)}</code></p>
                      {!workflow.approval.current && <p className="callout callout-warning">A current approval for this exact preview is required.</p>}
                      {workflow.approval.current && !businessEvidenceReady(workflow) && (
                        <p className="callout callout-warning">Decision-grade business evidence is incomplete.</p>
                      )}
                      {canRun && !confirmRun && (
                        <button type="button" className="button button-primary" onClick={() => setConfirmRun(true)}>Review and run</button>
                      )}
                      {canRun && confirmRun && (
                        <div className="callout" role="alertdialog" aria-label="Confirm governed execution">
                          <p>Run this exact approved snapshot once? Provider verification, not submission, determines success.</p>
                          <button type="button" className="button button-primary" disabled={submitting} onClick={() => void runPlan()}>
                            {submitting ? "Submitting…" : "Confirm run"}
                          </button>
                          <button type="button" className="button button-quiet" onClick={() => setConfirmRun(false)}>Back</button>
                        </div>
                      )}
                    </>
                  )}

                  {activeStep === "verify" && (
                    <>
                      {!workflow.execution ? (
                        <StatePanel title="Not run yet" message="Complete approval and run before verification." />
                      ) : (
                        <ExecutionAudit execution={workflow.execution} />
                      )}
                      {workflow.execution?.retryable && (
                        <button type="button" className="button button-primary" disabled={submitting} onClick={() => void retryExecution(workflow.execution!)}>
                          Retry approved snapshot
                        </button>
                      )}
                    </>
                  )}

                  {actionError && <p className="callout callout-warning" role="alert">{actionError}</p>}
                </div>
              </>
            )}
          </main>
        </div>
      )}

      {workflow && (
        <section className="card remediation-audit">
          <details>
            <summary>Evidence and audit history</summary>
            <div className="card-body remediation-review-grid">
              <div>
                <h3>Evidence</h3>
                <StructuredData value={selectedEvidence} />
              </div>
              <div>
                <h3>Immutable decisions and executions</h3>
                <StructuredData value={audit} />
              </div>
            </div>
          </details>
        </section>
      )}
    </div>
  );
}

function ExecutionAudit({ execution }: { execution: RemediationExecution }) {
  return (
    <section>
      <div className="plan-row-badges">
        <StatusBadge label={titleize(execution.status)} tone={statusTone(execution.status)} />
        <StatusBadge label={`Attempt ${execution.attempt_count}`} tone="info" />
      </div>
      <h3>Provider verification</h3>
      <p>Execution: <code>{execution.execution_id}</code></p>
      <p>Provider state: {execution.verified_state || "Awaiting verification"}</p>
      <p>Outcome: {execution.outcome || "Pending"}</p>
      {execution.failure_details && <p className="callout callout-warning">{execution.failure_details}</p>}
      <p>Rollback guidance: {execution.rollback_guidance.join("; ") || "No automated rollback is available."}</p>
      <ol>
        {execution.attempts.map((attempt) => (
          <li key={attempt.attempt_number}>
            <strong>Attempt {attempt.attempt_number}</strong> — {titleize(attempt.status)}
            <ul>
              {attempt.transitions.map((transition, index) => (
                <li key={index}>{transition.timestamp || "Unknown time"} · {titleize(transition.status)} · {transition.message || transition.verified_state || transition.actor || "Recorded"}</li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </section>
  );
}
