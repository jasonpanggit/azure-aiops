"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import {
  RiskExceptionDialog,
  type RiskExceptionRecordRequest,
  type RiskExceptionRecordResult,
} from "@/components/exposure/RiskExceptionDialog";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { buildRemediationCopilotContext } from "@/lib/copilot/page-adapters";
import { useApi } from "@/hooks/useApi";
import { relativeTime, titleize } from "@/lib/format";
import {
  encodeExposureQueryState,
  parseExposureQueryState,
} from "@/lib/exposure-query-state";
import type { ScopeSelection } from "@/lib/scope";
import { useScope } from "@/lib/scope-context";
import {
  isCanonicalAzureResourceId,
  operationsApi,
  remediationApi,
  vulnerabilityApi,
} from "@/lib/services";
import type {
  ExposureRemediationCase,
  RemediationApprovalDecision,
  RemediationApprovalRequirement,
  RemediationAvailablePatch,
  RemediationBlocker,
  RemediationDegradation,
  RemediationEvidenceReconciliation,
  RemediationExecution,
  RemediationWorkflow,
} from "@/lib/services";
import { ApiError } from "@/lib/types";
import type { RemediationDecision, RemediationPlan } from "@/lib/types";

import { usePollingBackoff } from "./polling";

import { BLOCKER_VOCABULARY, WORKFLOW_STEPS, blockerCopyWithTelemetry } from "./blockers";
import type { WorkflowStep } from "./blockers";

const COMPLIANCE_FINDING_TYPES = new Set([
  "firewall_bypass",
  "missing_udr",
  "unapproved_peering",
  "dev_uat_to_prod",
  "any_any_rule",
  "public_paas_exposure",
  "missing_private_endpoint",
  "dns_gap",
  "missing_owner",
  "logging_gap",
] as const);
const COMPLIANCE_FINDING_SEVERITIES = new Set(["critical", "high", "medium", "low"] as const);
const COMPLIANCE_REVIEW_RESOURCE_MAX = 2_048;
const COMPLIANCE_REVIEW_TITLE_MAX = 200;
const COMPLIANCE_REVIEW_RECOMMENDATION_MAX = 1_000;
const COMPLIANCE_REVIEW_QUERY_KEYS = [
  "resource_key",
  "review_source",
  "finding_type",
  "finding_severity",
  "finding_title",
  "recommendation",
] as const;

type ComplianceFindingType = typeof COMPLIANCE_FINDING_TYPES extends Set<infer Value> ? Value : never;
type ComplianceFindingSeverity = typeof COMPLIANCE_FINDING_SEVERITIES extends Set<infer Value> ? Value : never;

interface ComplianceFindingReview {
  resource: string;
  type: ComplianceFindingType;
  severity: ComplianceFindingSeverity;
  title: string;
  recommendation: string;
}

function ComplianceFindingReviewPanel({ review }: { review: ComplianceFindingReview }) {
  return (
    <section className="card remediation-workflow-selection">
      <div className="card-header">
        <div>
          <h2>Compliance finding review</h2>
          <p>{review.title}</p>
        </div>
        <StatusBadge label="Manual review only" tone="warning" compact />
      </div>
      <div className="card-body">
        <dl className="compliance-fact-list">
          <dt>Resource</dt>
          <dd>{review.resource}</dd>
          <dt>Finding type</dt>
          <dd>{titleize(review.type)}</dd>
          <dt>Severity</dt>
          <dd>{titleize(review.severity)}</dd>
          <dt>Recommendation</dt>
          <dd>{review.recommendation}</dd>
        </dl>
        <p>
          No executable network action has been generated for this compliance finding.
          Route the recommendation through the governed network-owner review process.
        </p>
        <div className="remediation-handoff-actions">
          <Link className="button" href="/network">Open network topology</Link>
        </div>
      </div>
    </section>
  );
}

function boundedQueryValue(
  searchParams: { get(name: string): string | null },
  name: string,
  maxLength: number,
): string | null {
  const value = searchParams.get(name)?.trim() ?? "";
  return value && value.length <= maxLength ? value : null;
}

function complianceFindingReview(
  searchParams: Pick<URLSearchParams, "get" | "getAll" | "keys">,
): ComplianceFindingReview | null {
  const keys = Array.from(searchParams.keys());
  if (
    keys.length !== COMPLIANCE_REVIEW_QUERY_KEYS.length
    || keys.some((key) => !COMPLIANCE_REVIEW_QUERY_KEYS.includes(
      key as typeof COMPLIANCE_REVIEW_QUERY_KEYS[number],
    ))
    || COMPLIANCE_REVIEW_QUERY_KEYS.some((key) => searchParams.getAll(key).length !== 1)
  ) return null;
  if (searchParams.get("review_source") !== "compliance") return null;
  const requestedResource = boundedQueryValue(
    searchParams,
    "resource_key",
    COMPLIANCE_REVIEW_RESOURCE_MAX,
  );
  if (
    !requestedResource
    || !isCanonicalAzureResourceId(requestedResource)
  ) return null;

  const type = boundedQueryValue(searchParams, "finding_type", 64);
  const severity = boundedQueryValue(searchParams, "finding_severity", 16);
  const title = boundedQueryValue(searchParams, "finding_title", COMPLIANCE_REVIEW_TITLE_MAX);
  const recommendation = boundedQueryValue(
    searchParams,
    "recommendation",
    COMPLIANCE_REVIEW_RECOMMENDATION_MAX,
  );
  if (
    !type
    || !COMPLIANCE_FINDING_TYPES.has(type as ComplianceFindingType)
    || !severity
    || !COMPLIANCE_FINDING_SEVERITIES.has(severity as ComplianceFindingSeverity)
    || !title
    || !recommendation
  ) return null;

  return {
    resource: requestedResource,
    type: type as ComplianceFindingType,
    severity: severity as ComplianceFindingSeverity,
    title,
    recommendation,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stepBlockerEcho(blockers: RemediationBlocker[] | undefined, step: WorkflowStep) {
  const rows = (blockers ?? []).filter((row) => row.step === step && row.code !== "already_succeeded");
  if (!rows.length) return null;
  return (
    <>
      {rows.map((row, index) => {
        const copy = blockerCopyWithTelemetry(row.code, row.step, row.message, row.next_action, row.severity);
        return (
          <p
            key={`${row.code}-${index}`}
            className={`callout ${copy.severity === "critical" ? "callout-critical" : "callout-warning"}`}
            role="status"
          >
            {copy.message} <strong>Next:</strong> {copy.nextAction}
          </p>
        );
      })}
    </>
  );
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

function shortenId(value: string, keep = 2): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  const segments = trimmed.split("/").filter(Boolean);
  if (segments.length <= keep) return trimmed;
  return `…/${segments.slice(-keep).join("/")}`;
}

function summaryDetails(value: unknown, fallback = "Not specified"): string {
  if (!isRecord(value)) return details(value, fallback);

  const preferredKeys = ["message", "service", "application", "level", "status", "name"];
  const preferred = preferredKeys
    .map((key) => value[key])
    .filter((item) => item !== null && item !== undefined && item !== "")
    .map((item) => details(item, ""));
  if (preferred.length) return preferred.map(titleize).join(" · ");

  if (isRecord(value.overall_risk)) {
    return details(value.overall_risk, fallback);
  }
  if (Array.isArray(value.affected_services)) {
    return details(value.affected_services, fallback);
  }
  return details(value, fallback);
}

function patchClassification(patch: RemediationAvailablePatch): string {
  const value = patch.severity || patch.classification || "";
  const normalized = String(value)
    .trim()
    .replace(/^\[['"]?/, "")
    .replace(/['"]?\]$/, "");
  return normalized ? titleize(normalized) : "";
}

function citationLabel(citation: unknown): { title: string; meta: string } {
  if (!isRecord(citation)) return { title: details(citation), meta: "" };
  const sourceId = String(citation.source_id ?? "");
  const cveMatch = sourceId.match(/CVE-\d{4}-\d+/i);
  const title =
    String(citation.summary ?? "") ||
    (cveMatch ? cveMatch[0] : "") ||
    shortenId(sourceId, 1) ||
    "Evidence item";
  const meta = [
    citation.source_type ? titleize(String(citation.source_type)) : "",
    cveMatch && citation.summary ? cveMatch[0] : "",
    citation.observed_at ? new Date(String(citation.observed_at)).toLocaleString() : "",
    citation.freshness ? titleize(String(citation.freshness)) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  return { title, meta };
}

function resourceId(plan: RemediationPlan | RemediationWorkflow["plan"]): string {
  if (isRecord(plan.resource)) {
    return String(plan.resource.id ?? plan.resource.resource_key ?? plan.resource.name ?? "");
  }
  return String(plan.resource ?? plan.resource_key ?? "");
}

function resourceName(plan: RemediationPlan | RemediationWorkflow["plan"]): string {
  if (isRecord(plan.resource)) {
    return String(plan.resource.name ?? plan.resource.id ?? "");
  }
  return String(plan.resource ?? "");
}

// Closed, machine-readable vocabulary -- exact locked copy from
// 03.5-UI-SPEC.md's "Approval Requirement Contract" table. Never
// paraphrased.
const UNMET_REASON_COPY: Record<string, string> = {
  pending: "No decision recorded yet for this role.",
  wrong_role_decision: "A decision exists, but not from the required {role}. This requirement remains unmet.",
  stale_action_version: "The plan's action version changed since the last decision for this role.",
  stale_evidence_snapshot: "The executable preview changed since the last decision for this role.",
  stale_policy_version: "The approval policy was updated since the last decision for this role.",
  expired: "The last decision for this role expired.",
};

// Exact locked copy fragments for joining `stale_reasons` in the
// plan-level Stale Approval State Contract -- same closed vocabulary as
// the per-row unmet_reason table above, just phrased as a fragment.
const STALE_REASON_FRAGMENT: Record<string, string> = {
  stale_action_version: "the plan's action version changed",
  stale_evidence_snapshot: "the executable preview changed",
  stale_policy_version: "the approval policy was updated",
};

function joinStaleReasons(reasons: string[]): string {
  const fragments = reasons.map((reason) => STALE_REASON_FRAGMENT[reason] ?? reason);
  if (fragments.length === 0) return "";
  if (fragments.length === 1) return fragments[0];
  return `${fragments.slice(0, -1).join(", ")} and ${fragments[fragments.length - 1]}`;
}

function ApprovalRequirementsList({ requirements }: { requirements: RemediationApprovalRequirement[] }) {
  const satisfiedCount = requirements.filter((row) => row.satisfied).length;
  return (
    <section className="remediation-approval-requirements">
      <div className="remediation-section-heading">
        <h3>Approval requirements</h3>
        <span>{satisfiedCount} of {requirements.length} requirements satisfied</span>
      </div>
      {requirements.map((row, index) => (
        <div key={`${row.policy_id}-${row.stage}-${index}`} className="remediation-approval-requirement-row">
          <div className="remediation-approval-requirement-heading">
            <StatusBadge
              label={row.satisfied ? "Satisfied" : "Unmet"}
              tone={row.satisfied ? "success" : "warning"}
            />
            <strong className="remediation-approval-requirement-role">{row.role}</strong>
          </div>
          <dl className="remediation-approval-requirement-meta">
            <div>
              <dt>Policy</dt>
              <dd><code title={row.policy_id}>{row.policy_id}</code></dd>
            </div>
            <div>
              <dt>Stage</dt>
              <dd>{row.stage}</dd>
            </div>
          </dl>
          {!row.satisfied && row.unmet_reason && (
            <p className="remediation-approval-requirement-message">
              {(UNMET_REASON_COPY[row.unmet_reason] ?? row.unmet_reason).replace("{role}", row.role)}
            </p>
          )}
          {row.satisfied && (
            // Phase 03.5 CR-05 fix: disclose exactly which decision/approver
            // satisfied this row -- an operator must never mistake one
            // person's single sign-off for genuine multi-stakeholder
            // approval across every row that happens to show "Satisfied".
            <p className="remediation-approval-requirement-satisfied-by">
              Satisfied by <strong>{row.approver ?? "unknown"}</strong>
              {row.decision_id && <> (decision <code>{row.decision_id}</code>)</>}
            </p>
          )}
          <details>
            <summary>Evidence required</summary>
            <ul>
              {(row.approval_evidence_required ?? []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </details>
        </div>
      ))}
    </section>
  );
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

function safeExposureReturnPath(
  value: string,
  authorizedScope: ScopeSelection,
): string {
  const fallback = "/exposure/patch-priorities";
  if (!value || value.startsWith("//")) return fallback;
  try {
    const parsed = new URL(value, "https://aiops.invalid");
    if (
      parsed.origin !== "https://aiops.invalid" ||
      !/^\/exposure(?:\/|$)/.test(parsed.pathname)
    ) {
      return fallback;
    }
    const canonicalState = parseExposureQueryState(parsed.searchParams, {
      authorizedScope,
    });
    const canonicalQuery = encodeExposureQueryState(canonicalState).toString();
    return canonicalQuery
      ? `${parsed.pathname}?${canonicalQuery}`
      : parsed.pathname;
  } catch {
    return fallback;
  }
}

function ContainerReviewHandoff({
  handoff,
  loading,
  error,
  submitting,
  result,
  onSubmit,
  returnTo,
}: {
  handoff: ExposureRemediationCase | null;
  loading: boolean;
  error: Error | null;
  submitting: boolean;
  result: string;
  onSubmit: (reason: string) => Promise<void>;
  returnTo: string;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [reason, setReason] = useState("");
  const [localError, setLocalError] = useState("");
  const errorRef = useRef<HTMLParagraphElement>(null);
  const successRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (localError) errorRef.current?.focus();
  }, [localError]);
  useEffect(() => {
    if (result) successRef.current?.focus();
  }, [result]);

  if (loading) {
    return (
      <StatePanel
        title="Loading governed container review"
        message="Revalidating the server-owned handoff against current evidence."
        tone="loading"
        busy
      />
    );
  }
  if (error) {
    return (
      <StatePanel
        title="Container review is unavailable"
        message={error.message}
        tone="error"
        action={<Link className="button" href={returnTo}>Back to exposure</Link>}
      />
    );
  }
  if (!handoff) {
    return (
      <StatePanel
        title="No safe container action"
        message="The requested handoff is not present in the current authorized Exposure generation."
        tone="error"
        action={<Link className="button" href={returnTo}>Back to exposure</Link>}
      />
    );
  }
  const canCreate =
    handoff.target_kind === "container_image" &&
    handoff.outcome === "review_handoff" &&
    handoff.direct_execution_supported === false;
  if (!canCreate) {
    return (
      <section className="card remediation-container-review">
        <div className="card-header">
          <h2>No safe container action</h2>
        </div>
        <div className="card-body">
          <p>{handoff.outcome_reason || "No safe governed handoff is available for this evidence."}</p>
          <p>Container rebuild, base-image change, workload mutation, and deployment remain unavailable from Exposure.</p>
          <Link className="button" href={returnTo}>Back to exposure</Link>
        </div>
      </section>
    );
  }

  return (
    <section className="card remediation-container-review">
      <div className="card-header">
        <div>
          <span className="eyebrow">From Exposure</span>
          <h2>Governed container review</h2>
          <p>No executable container action is available. This creates an audited review record only.</p>
        </div>
      </div>
      <div className="card-body">
        <dl className="remediation-review-facts">
          <div>
            <dt>Finding</dt>
            <dd>{handoff.weakness_key}</dd>
          </div>
          <div>
            <dt>Generation</dt>
            <dd><code>{handoff.read_model_generation_id}</code></dd>
          </div>
          <div className="remediation-review-fact-wide">
            <dt>Image digest</dt>
            <dd className="exposure-long-value">{handoff.review_handoff.image_digest || handoff.resource_key}</dd>
          </div>
        </dl>
        <p>{handoff.outcome_reason}</p>
        {result ? (
          <div ref={successRef} className="callout" role="status" tabIndex={-1}>
            <h3>Container review handoff recorded</h3>
            <p>Audit ID: <code>{result}</code></p>
          </div>
        ) : (
          <>
            <label className="form-field">
              <span>Review handoff reason</span>
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                required
              />
            </label>
            <label className="remediation-handoff-acknowledgement">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              <span>I acknowledge this is a non-executable review handoff</span>
            </label>
            {localError && (
              <p ref={errorRef} className="callout callout-warning" role="alert" tabIndex={-1}>
                {localError}
              </p>
            )}
            <button
              type="button"
              className="button button-primary"
              disabled={submitting || !acknowledged || !reason.trim()}
              onClick={() => {
                if (!acknowledged || !reason.trim()) {
                  setLocalError("A reason and explicit acknowledgement are required.");
                  return;
                }
                setLocalError("");
                void onSubmit(reason.trim());
              }}
            >
              {submitting ? "Creating review handoff…" : "Create governed review handoff"}
            </button>
          </>
        )}
        <Link className="button button-quiet" href={returnTo}>Back to exposure</Link>
      </div>
    </section>
  );
}

/** Five-step, approval-gated remediation workflow. */
export default function RemediationPage() {
  return (
    <Suspense fallback={<div className="page-container"><StatePanel title="Preparing remediation" message="Loading the governed workflow." tone="loading" /></div>}>
      <RemediationContent />
    </Suspense>
  );
}

function withExecution(
  workflow: RemediationWorkflow,
  execution: RemediationExecution,
): RemediationWorkflow {
  const replace = (rows: RemediationExecution[]) => {
    const next = rows.filter((row) => row.execution_id !== execution.execution_id);
    return [execution, ...next];
  };
  return {
    ...workflow,
    execution,
    executions: replace(workflow.executions),
    audit: {
      ...workflow.audit,
      executions: replace(workflow.audit.executions),
    },
  };
}

function RemediationContent() {
  const { scope } = useScope();
  const searchParams = useSearchParams();
  const requestedResource = searchParams.get("resource_key") ?? searchParams.get("resource") ?? "";
  const fromCve = searchParams.get("cve") ?? "";
  const fromKb = searchParams.get("kb") ?? "";
  const fromIncident = searchParams.get("incident") ?? "";
  const fromGeneration = searchParams.get("generation") ?? "";
  const requestedHandoff = searchParams.get("handoff") ?? "";
  const requestedReturnFocus = searchParams.get("return_focus") ?? "";
  const complianceReview = complianceFindingReview(searchParams);
  const effectiveScope = useMemo<ScopeSelection>(() => {
    const scoped: ScopeSelection = { ...scope };
    const subscriptions = searchParams.getAll("subscription").filter(Boolean);
    const connections = searchParams.getAll("subscription_connection").filter(Boolean);
    if (subscriptions.length) scoped.subscription = subscriptions;
    if (connections.length) scoped.subscription_connection = connections;
    return scoped;
  }, [scope, searchParams]);
  const scopeKey = JSON.stringify(effectiveScope);
  const returnTo = useMemo(
    () =>
      safeExposureReturnPath(
        searchParams.get("return_to") ?? "",
        effectiveScope,
      ),
    [effectiveScope, searchParams],
  );
  const plans = useApi(
    () => operationsApi.remediationPlans(effectiveScope, 0, 100, requestedResource),
    [scopeKey, requestedResource],
  );
  const handoffs = useApi(
    () =>
      requestedHandoff
        ? remediationApi.exposureHandoffs(effectiveScope)
        : Promise.resolve({
            data: {
              cases: [],
              read_only: true as const,
              execution_transition: false as const,
            },
            evidence: [],
            warnings: [],
            scope: effectiveScope,
            knowledge_version: "",
          }),
    [requestedHandoff, scopeKey],
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
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState("");
  const [confirmRun, setConfirmRun] = useState(false);
  const [selectedPatchIds, setSelectedPatchIds] = useState<string[] | null>(null);
  const [patchSelectionRefusal, setPatchSelectionRefusal] = useState("");
  const [riskDialogOpen, setRiskDialogOpen] = useState(false);
  const [handoffSubmitting, setHandoffSubmitting] = useState(false);
  const [handoffResult, setHandoffResult] = useState("");
  const [handoffError, setHandoffError] = useState("");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const riskInvokerRef = useRef<HTMLButtonElement>(null);
  const requestId = useRef(0);

  // Phase 03.5 CR-05 fix: a decision attests exactly one required role
  // (approval_role_id), so the operator must pick which unmet requirement
  // row a new approval decision is for whenever more than one distinct
  // role is still unmet. Deduped by role_id (falling back to role text
  // for a legacy requirement row with no role_id at all).
  const unmetRoleOptions = useMemo(() => {
    const rows = workflow?.approval.requirements ?? [];
    const seen = new Map<string, string>();
    for (const row of rows) {
      if (row.satisfied) continue;
      const roleId = String(row.role_id || row.role || "");
      if (!roleId || seen.has(roleId)) continue;
      seen.set(roleId, row.role);
    }
    return Array.from(seen, ([roleId, role]) => ({ roleId, role }));
  }, [workflow?.approval.requirements]);
  const roleSelectionRequired = decision === "approved" && unmetRoleOptions.length > 1;

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
  const selectedPlan = complianceReview
    ? null
    : planRows.find((plan) => plan.plan_id === selectedPlanId) ?? null;

  useEffect(() => {
    if (complianceReview) {
      setSelectedPlanId("");
      return;
    }
    if (!planRows.length) {
      setSelectedPlanId("");
      return;
    }
    if (selectedPlanId && planRows.some((plan) => plan.plan_id === selectedPlanId)) return;
    const contextual = planRows.find((plan) => resourceMatches(plan, requestedResource));
    setSelectedPlanId((contextual ?? planRows[0]).plan_id);
  }, [complianceReview, planRows, requestedResource, selectedPlanId]);

  useEffect(() => {
    if (!selectedPlanId) {
      setWorkflow(null);
      setWorkflowError("");
      return;
    }
    const currentRequest = ++requestId.current;
    setWorkflowLoading(true);
    setWorkflowError("");
    void remediationApi.workflow(selectedPlanId, effectiveScope, selectedPatchIds ?? [])
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
  }, [scopeKey, selectedPlanId, workflowRefresh, selectedPatchIds]);

  useEffect(() => {
    setActiveStep(selectedPlanId ? "review" : "select");
    setActionError("");
    setConfirmRun(false);
    setSelectedPatchIds(null);
    setPatchSelectionRefusal("");
    setSelectedRoleId("");
  }, [selectedPlanId]);

  // Patch Selection Safety Contract: "Evidence-refresh reconciliation"
  // (locked). A refreshed available-patches set that shrinks below a
  // current explicit selection narrows (removal-only) or refuses -- it
  // never falls back to "all".
  useEffect(() => {
    const availablePatches = workflow?.preview?.execution_snapshot?.available_patches;
    if (!availablePatches || selectedPatchIds === null) return;
    const availableIds = new Set(availablePatches.map((patch) => patch.patch_id));
    const stillAvailable = selectedPatchIds.filter((id) => availableIds.has(id));
    if (stillAvailable.length === selectedPatchIds.length) return;
    if (stillAvailable.length > 0) {
      setSelectedPatchIds(stillAvailable);
      setPatchSelectionRefusal("");
    } else {
      setPatchSelectionRefusal(
        "Your previously selected patches are no longer available. Choose at least one currently available patch.",
      );
    }
    // selectedPatchIds intentionally excluded: this effect only reacts to
    // the *available* set narrowing, not to the operator's own selection
    // changes (which are handled inline by the checkbox handler).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow?.preview?.execution_snapshot?.available_patches]);

  const executionStatus = workflow?.execution?.status ?? "";
  const pollingActive = ["queued", "running", "retrying"].includes(executionStatus);
  const pollingResetKey = `${selectedPlanId}:${workflow?.execution?.execution_id ?? ""}`;
  const handlePoll = useRef(() => setWorkflowRefresh((value) => value + 1));
  handlePoll.current = () => {
    const executionId = workflow?.execution?.execution_id;
    if (!executionId) {
      setWorkflowRefresh((value) => value + 1);
      return;
    }
    void remediationApi.execution(executionId, effectiveScope)
      .then((response) => {
        setWorkflow((current) => (
          current ? withExecution(current, response.data) : current
        ));
      })
      .catch((error) => {
        setActionError(error instanceof Error ? error.message : String(error));
      });
  };
  const polling = usePollingBackoff({
    active: pollingActive,
    resetKey: pollingResetKey,
    onPoll: () => handlePoll.current(),
  });

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
    if (roleSelectionRequired && !selectedRoleId) {
      setActionError("Select which required role this decision is for.");
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
          selected_patch_ids: decision === "approved" ? (selectedPatchIds ?? []) : [],
          role_id: decision === "approved"
            ? (selectedRoleId || unmetRoleOptions[0]?.roleId || "")
            : "",
        },
        effectiveScope,
      );
      setDecisionReason("");
      setSelectedRoleId("");
      setWorkflowRefresh((value) => value + 1);
      setActiveStep(
        decision === "approved" && unmetRoleOptions.length <= 1
          ? "run"
          : "approve",
      );
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
      const revalidated = await remediationApi.workflow(
        planId,
        effectiveScope,
        selectedPatchIds ?? [],
      );
      const latest = revalidated.data;
      setWorkflow(latest);
      if (
        !latest.action.executable ||
        !latest.action.can_operate ||
        !latest.approval.current ||
        !latest.preview?.execution_snapshot ||
        !latest.plan.executable ||
        !businessEvidenceReady(latest)
      ) {
        setConfirmRun(false);
        setActionError(
          latest.action.operate_ineligible_reason ||
            latest.plan.ineligibility_reason ||
            "The server no longer considers this exact snapshot eligible to run.",
        );
        return;
      }
      const response = await remediationApi.execute(planId, effectiveScope);
      setWorkflow((current) => (
        current ? withExecution(current, response.data) : current
      ));
      setConfirmRun(false);
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
      const response = await remediationApi.retry(execution.execution_id, effectiveScope);
      setWorkflow((current) => (
        current ? withExecution(current, response.data) : current
      ));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const [supersedeIneligibilityReason, setSupersedeIneligibilityReason] = useState("");

  const cancelExecution = async (execution: RemediationExecution) => {
    if (!execution.cancellable || submitting) return;
    setSubmitting(true);
    setActionError("");
    try {
      const response = await remediationApi.cancel(execution.execution_id, effectiveScope);
      setWorkflow((current) => (
        current ? withExecution(current, response.data) : current
      ));
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  };

  const supersedeExecution = async (execution: RemediationExecution, reason: string) => {
    if (!execution.supersedable || submitting) return;
    setSubmitting(true);
    setActionError("");
    setSupersedeIneligibilityReason("");
    try {
      const response = await remediationApi.supersede(execution.execution_id, reason, effectiveScope);
      setWorkflow((current) => (
        current ? withExecution(current, response.data) : current
      ));
    } catch (error) {
      if (error instanceof ApiError && typeof error.details?.reason === "string") {
        setSupersedeIneligibilityReason(error.details.reason);
        setWorkflowRefresh((value) => value + 1);
      } else {
        setActionError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const selectedEvidence = workflow?.evidence ?? [];
  const audit = workflow?.audit ?? { decisions: [], executions: [] };
  const handoffCase =
    handoffs.data?.data.cases.find(
      (row) =>
        row.handoff_id === requestedHandoff ||
        row.exposure_id === requestedHandoff,
    ) ?? null;
  const canRun = Boolean(
    workflow?.action.executable
    && workflow.approval.current
    && workflow.preview?.execution_snapshot
    && workflow.plan.executable
    && businessEvidenceReady(workflow),
  );
  const pageError = plans.error && planRows.length === 0 ? plans.error : null;

  // Read-only Copilot context over the current governed workflow projection.
  // Approval and execution stay bound to the existing server endpoints; this
  // only powers explanation and a governed handoff (D-10).
  const remediationCopilot = useMemo(
    () =>
      buildRemediationCopilotContext({
        scope: effectiveScope,
        selectedPlan: workflow
          ? {
              plan_id: workflow.plan.plan_id,
              action_id: workflow.action.action_id,
              action_version: workflow.plan.action_version,
              title: workflow.plan.title,
              status: workflow.plan.status,
              family: workflow.action.family,
              resource_id: resourceId(workflow.plan),
              resource_name: resourceName(workflow.plan),
              snapshot_hash: workflow.preview?.execution_snapshot?.snapshot_hash,
            }
          : null,
        eligibility: workflow
          ? {
              plan_executable: workflow.plan.executable,
              plan_ineligibility_reason: workflow.plan.ineligibility_reason,
              can_operate: workflow.action.can_operate,
              operate_ineligible_reason: workflow.action.operate_ineligible_reason,
              can_approve: workflow.approval.can_approve,
              approve_ineligible_reason: workflow.approval.approve_ineligible_reason,
              approval_current: workflow.approval.current,
              approval_status: workflow.approval.status,
              has_executable_preview: Boolean(workflow.preview?.execution_snapshot),
              recommended_step: workflow.recommended_step,
            }
          : null,
        requirements: (workflow?.approval.requirements ?? []).map((requirement) => ({
          policy_id: requirement.policy_id,
          role: requirement.role,
          stage: requirement.stage,
          satisfied: requirement.satisfied,
          unmet_reason: requirement.unmet_reason,
        })),
        execution: workflow?.execution
          ? {
              execution_id: workflow.execution.execution_id,
              status: workflow.execution.status,
              retryable: workflow.execution.retryable,
              cancellable: workflow.execution.cancellable,
              supersedable: Boolean(workflow.execution.supersedable),
              remaining_attempts: workflow.execution.remaining_attempts,
            }
          : null,
        evidence: plans.data?.evidence ?? [],
        historicalEvidence: [],
        coverage: {
          visiblePlanCount: planRows.length,
          totalPlanCount: plans.data?.pagination?.total ?? planRows.length,
        },
        sourceStatuses: [
          {
            source: "plans",
            availability: "available",
            freshness: "fresh",
            observedAt: plans.data?.data.generated_at,
          },
          ...(workflow?.degradation ?? []).map((entry) => ({
            source: entry.source,
            availability: entry.availability,
            freshness: entry.freshness,
          })),
        ],
      }),
    [effectiveScope, workflow, plans.data, planRows],
  );

  const createContainerReview = async (reason: string) => {
    if (!handoffCase || handoffSubmitting) return;
    setHandoffSubmitting(true);
    setHandoffError("");
    try {
      const response = await remediationApi.createExposureHandoff(
        {
          exposure_id: handoffCase.exposure_id,
          reason,
          risk_acknowledged: true,
          risk_exception_id: "",
        },
        effectiveScope,
      );
      if (
        response.data.execution_transition !== false ||
        response.data.direct_execution_supported !== false ||
        response.data.target_kind !== "container_image"
      ) {
        setHandoffError(
          "The server response did not confirm a non-executable container review handoff.",
        );
        return;
      }
      setHandoffResult(
        response.data.handoff_id ||
          response.data.exposure_id,
      );
    } catch (error) {
      setHandoffError(error instanceof Error ? error.message : String(error));
    } finally {
      setHandoffSubmitting(false);
    }
  };

  const recordRiskException = async (
    request: RiskExceptionRecordRequest,
  ): Promise<RiskExceptionRecordResult> => {
    try {
      const response = await vulnerabilityApi.acceptRisk({
        cve_id: request.cveId,
        server_id: requestedResource || undefined,
        reason: request.reason,
        expires_at: request.expiresAt || undefined,
      });
      return {
        status: "success",
        auditId: response.data.exception_id,
        effectiveScope: request.targetScope,
        expiresAt: response.data.expires_at || null,
        canRevoke: true,
        governance: request.governance,
      };
    } catch (error) {
      return {
        status: "failure",
        message: error instanceof Error ? error.message : String(error),
      };
    }
  };

  if (requestedHandoff) {
    return (
      <div className="page-container remediation-center">
        <PageHeader
          eyebrow="Governed remediation"
          title="Container review handoff"
          description="Review exact Exposure evidence and create an audited, non-executable platform-team handoff."
          metadata={
            <>
              <span>Review-only container path</span>
              <span>Execution transition disabled</span>
            </>
          }
        />
        {handoffError && (
          <p className="callout callout-warning" role="alert">{handoffError}</p>
        )}
        <ContainerReviewHandoff
          handoff={handoffCase}
          loading={handoffs.loading}
          error={handoffs.error}
          submitting={handoffSubmitting}
          result={handoffResult}
          onSubmit={createContainerReview}
          returnTo={returnTo}
        />
      </div>
    );
  }

  return (
    <div className="page-container remediation-center">
      <PageHeader
        eyebrow="Governed remediation"
        title="Fix safely, one step at a time"
        description="Select a governed fix, review its impact, approve the exact snapshot, run it once, and verify the provider outcome."
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about remediation"
          />
        }
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
        <div className="callout remediation-handoff remediation-handoff-context">
          <div>
            <strong>{complianceReview ? "From Compliance" : "From Exposure"}</strong>
            <span>
              Scoped handoff:
              {requestedResource ? ` ${requestedResource}` : ""}
            </span>
            <span>
              {fromIncident ? ` Incident ${fromIncident}.` : ""}
              {fromCve ? ` ${fromCve}.` : ""}
              {fromKb ? ` ${fromKb}.` : ""}
              {requestedResource ? ` Target ${requestedResource}.` : ""}
              {fromGeneration ? ` Evidence generation ${fromGeneration}.` : ""}
            </span>
            {requestedReturnFocus && (
              <span> Return focus: {requestedReturnFocus}.</span>
            )}
            <p>
              {complianceReview
                ? "Nothing executes from this compliance handoff."
                : "Nothing executes from Exposure."}
              {" "}The server revalidates targets,
              evidence, approval, and operator eligibility immediately before
              the governed transition.
            </p>
          </div>
          <div className="remediation-handoff-actions">
            {fromCve && (
              <button
                ref={riskInvokerRef}
                type="button"
                className="button"
                onClick={() => setRiskDialogOpen(true)}
              >
                Record risk exception
              </button>
            )}
            <Link className="button button-quiet" href={complianceReview ? "/compliance" : returnTo}>
              {complianceReview ? "Back to compliance" : "Back to exposure"}
            </Link>
          </div>
        </div>
      )}

      {!complianceReview && (
        <nav className="remediation-workflow-steps" aria-label="Remediation workflow">
          {WORKFLOW_STEPS.map((step) => {
            const projected = workflow?.steps.find((item) => item.id === step.id)?.status;
            const status = step.id === "select" ? "complete" : projected ?? "pending";
            const stepBlockers = (workflow?.blockers ?? []).filter((row) => row.step === step.id);
            const blockedSeverityStyle = status === "blocked"
              ? {
                  color: stepBlockers.some((row) => (row.severity ?? BLOCKER_VOCABULARY[row.code]?.severity) === "critical")
                    ? "var(--color-critical)"
                    : "var(--color-warning)",
                }
              : undefined;
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
                <small style={blockedSeverityStyle}>{titleize(status)}</small>
              </button>
            );
          })}
        </nav>
      )}

      {workflow && workflow.blockers.length > 0 && (
        <WorkflowBlockers blockers={workflow.blockers} activeStep={activeStep} />
      )}

      {pageError ? (
        <StatePanel title="Remediation plans unavailable" message={pageError.message} tone="error" />
      ) : plans.loading ? (
        <StatePanel title="Loading governed fixes" message="Reading scoped, evidence-backed plans." tone="loading" />
      ) : complianceReview ? (
        <ComplianceFindingReviewPanel review={complianceReview} />
      ) : (
        <div className="remediation-workflow-layout">
          <aside className="card remediation-workflow-selection">
            <div className="card-header">
              <div>
                <h2>Select fix</h2>
                <p>Only generated plans can enter approval and execution.</p>
              </div>
              <StatusBadge label={`${planRows.length} ${planRows.length === 1 ? "fix" : "fixes"}`} tone="info" />
            </div>
            <div className="card-body">
              <label className="remediation-search-field">
                <span>Search fixes</span>
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
                    <small title={resourceId(plan)}>
                      {shortenId(resourceId(plan), 4) || plan.business_service || "Scope not mapped"}
                    </small>
                  </button>
                ))}
                {!filteredPlans.length && (
                  planRows.length > 0 ? (
                    <StatePanel title="No fix matches your search" message="Plans exist for this scope but none match the current search text. Clear the search to see them." />
                  ) : requestedResource ? (
                    <StatePanel
                      title="No fix for this resource"
                      message="No remediation plan has been generated for the resource you came from. Plans are generated only when a resource's evidence signals match a catalogued remediation action."
                      action={<Link className="button" href="/remediation">Show all fixes in scope</Link>}
                    />
                  ) : (
                    <StatePanel
                      title="No fixes generated"
                      message="No remediation plan exists for this scope. Plans are generated by matching resource evidence signals (patch, lifecycle, incident, change drift, Defender posture, and critical vulnerabilities) against the governed remediation action catalog, so an unseeded catalog or resources with no matching signals both produce an empty list."
                    />
                  )
                )}
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
                      <p>Resource: <code title={resourceId(workflow.plan)}>{shortenId(resourceId(workflow.plan), 4) || "Not mapped"}</code></p>
                      <button type="button" className="button button-primary" onClick={() => setActiveStep("review")}>Review impact</button>
                    </section>
                  )}

                  {activeStep === "review" && (
                    <>
                      {stepBlockerEcho(workflow.blockers, "review")}
                      <WorkflowDegradation degradation={workflow.degradation} />
                      <section className="remediation-review-grid">
                        <div className="remediation-review-panel">
                          <div className="remediation-review-panel-heading">
                            <span className="eyebrow">Decision context</span>
                            <h3>Impact summary</h3>
                          </div>
                          <dl className="remediation-review-facts">
                            <div>
                              <dt>Disposition</dt>
                              <dd>
                                <StatusBadge
                                  label={titleize(workflow.business_decision.disposition ?? "not assessed")}
                                  tone="info"
                                  compact
                                />
                              </dd>
                            </div>
                            <div>
                              <dt>Business impact</dt>
                              <dd>{summaryDetails(workflow.business_decision.business_impact)}</dd>
                            </div>
                            <div>
                              <dt>Cost of acting</dt>
                              <dd>{summaryDetails(workflow.business_decision.cost_of_action)}</dd>
                            </div>
                            <div>
                              <dt>Cost of inaction</dt>
                              <dd>{summaryDetails(workflow.business_decision.cost_of_inaction)}</dd>
                            </div>
                            <div>
                              <dt>Risk</dt>
                              <dd>{summaryDetails(workflow.plan.risk_assessment)}</dd>
                            </div>
                            <div>
                              <dt>Dependencies</dt>
                              <dd>{summaryDetails(workflow.plan.dependencies)}</dd>
                            </div>
                          </dl>
                        </div>
                        <div className="remediation-review-panel">
                          <div className="remediation-review-panel-heading">
                            <span className="eyebrow">Execution scope</span>
                            <h3>Exact operation</h3>
                          </div>
                          <dl className="remediation-review-facts">
                            <div>
                              <dt>Action</dt>
                              <dd>{titleize(workflow.action.action_id)}</dd>
                            </div>
                            <div>
                              <dt>Operation</dt>
                              <dd>{titleize(workflow.preview?.operation ?? "Manual review only")}</dd>
                            </div>
                            <div className="remediation-review-fact-wide">
                              <dt>Target</dt>
                              <dd>
                                <strong>{resourceName(workflow.plan) || workflow.plan.title}</strong>
                                <code title={workflow.preview?.execution_snapshot?.target_id ?? resourceId(workflow.plan)}>
                                  {shortenId(workflow.preview?.execution_snapshot?.target_id ?? resourceId(workflow.plan), 4)}
                                </code>
                              </dd>
                            </div>
                          </dl>
                          {workflow.preview?.execution_snapshot?.snapshot_kind === "defender_configuration" ? (
                            <dl className="remediation-review-facts remediation-state-change">
                              <div>
                                <dt>Current state</dt>
                                <dd>{details(workflow.preview.execution_snapshot.prior_properties)}</dd>
                              </div>
                              <div>
                                <dt>Approved state</dt>
                                <dd>{details(workflow.preview.execution_snapshot.desired_properties)}</dd>
                              </div>
                            </dl>
                          ) : null}
                          <div className="remediation-rollback">
                            <span className="eyebrow">Rollback plan</span>
                            <p>{summaryDetails(workflow.plan.rollback_plan)}</p>
                          </div>
                        </div>
                      </section>
                      {workflow.preview?.execution_snapshot?.snapshot_kind !== "defender_configuration" && (
                        <section className="remediation-review-section">
                          <div className="remediation-section-heading">
                            <div>
                              <span className="eyebrow">Change contents</span>
                              <h3>Patch selection</h3>
                            </div>
                            {workflow.preview?.execution_snapshot?.available_patches?.length ? (
                              <StatusBadge
                                label={`${selectedPatchIds?.length ?? workflow.preview.execution_snapshot.available_patches.length} selected`}
                                tone="info"
                                compact
                              />
                            ) : null}
                          </div>
                          {workflow.preview?.execution_snapshot?.available_patches?.length ? (
                            <>
                              <p className="remediation-patch-mode-line">
                                {selectedPatchIds === null
                                  ? `All ${workflow.preview.execution_snapshot.available_patches.length} eligible patches are selected.`
                                  : `${selectedPatchIds.length} of ${workflow.preview.execution_snapshot.available_patches.length} patches explicitly selected.`}
                              </p>
                              <ul className="remediation-patch-list">
                                {workflow.preview.execution_snapshot.available_patches.map((patch) => {
                                  const allPatchIds = workflow.preview!.execution_snapshot!.available_patches!.map((p) => p.patch_id);
                                  const checked = selectedPatchIds === null || selectedPatchIds.includes(patch.patch_id);
                                  const classification = patchClassification(patch);
                                  return (
                                    <li key={patch.patch_id} className="remediation-patch-item">
                                      <label>
                                        <input
                                          type="checkbox"
                                          checked={checked}
                                          onChange={(event) => {
                                            const current = selectedPatchIds === null ? allPatchIds : selectedPatchIds;
                                            const next = event.target.checked
                                              ? [...current, patch.patch_id]
                                              : current.filter((id) => id !== patch.patch_id);
                                            if (next.length === allPatchIds.length) {
                                              setSelectedPatchIds(null);
                                              setPatchSelectionRefusal("");
                                            } else if (next.length === 0) {
                                              setPatchSelectionRefusal(
                                                "At least one patch must remain selected for this plan to be approved. Select a patch below, or use the mode line above to restore all eligible patches.",
                                              );
                                            } else {
                                              setSelectedPatchIds(next);
                                              setPatchSelectionRefusal("");
                                            }
                                          }}
                                        />
                                        <span className="remediation-patch-content">
                                          <strong>{patch.title || `Update ${patch.patch_id}`}</strong>
                                          <span className="remediation-patch-meta">
                                            <code>{patch.patch_id}</code>
                                            {classification && <StatusBadge label={classification} tone={classification.toLowerCase() === "critical" ? "critical" : "warning"} compact />}
                                            {patch.reboot_required && <StatusBadge label="Reboot required" tone="warning" compact />}
                                          </span>
                                        </span>
                                      </label>
                                    </li>
                                  );
                                })}
                              </ul>
                              {patchSelectionRefusal && (
                                <p className="callout callout-warning" role="alert">{patchSelectionRefusal}</p>
                              )}
                            </>
                          ) : (
                            <p className="remediation-empty-detail">
                              {workflow.preview?.execution_snapshot?.patch_ids.length
                                ? workflow.preview.execution_snapshot.patch_ids.join(", ")
                                : "No patch inventory is attached to this snapshot."}
                            </p>
                          )}
                        </section>
                      )}
                      <section className="remediation-review-section">
                        <div className="remediation-review-panel-heading">
                          <span className="eyebrow">Source material</span>
                          <h3>Evidence citations</h3>
                        </div>
                        {selectedEvidence.length ? (
                          <ul className="remediation-evidence-list">
                            {selectedEvidence.slice(0, 8).map((citation, index) => {
                              const { title, meta } = citationLabel(citation);
                              return (
                                <li key={index} className="remediation-evidence-item">
                                  <span className="remediation-evidence-title">{title}</span>
                                  {meta && <span className="remediation-evidence-meta">{meta}</span>}
                                </li>
                              );
                            })}
                          </ul>
                        ) : <p className="callout callout-warning">No cited evidence is available.</p>}
                        {selectedEvidence.length > 8 && (
                          <p className="remediation-evidence-more">
                            +{selectedEvidence.length - 8} more evidence item{selectedEvidence.length - 8 === 1 ? "" : "s"} in the audit trail below.
                          </p>
                        )}
                      </section>
                      {workflow.action.executable && workflow.preview?.execution_snapshot ? (
                        <div className="remediation-review-actions">
                          <button type="button" className="button button-primary" onClick={() => setActiveStep("approve")}>Continue to approval</button>
                        </div>
                      ) : !workflow.action.executable ? (
                        <p>This recommendation cannot enter automated approval or execution. Route it to the owning platform team with the evidence above.</p>
                      ) : (
                        <p>Approval is unavailable until the provider can produce a current executable preview.</p>
                      )}
                    </>
                  )}

                  {activeStep === "approve" && (
                    <>
                      {stepBlockerEcho(workflow.blockers, "approve")}
                      <WorkflowDegradation degradation={workflow.degradation} />
                      {!workflow.action.executable ? (
                        <StatePanel title="Manual review only" message={workflow.action.manual_review_reason} />
                      ) : !workflow.preview?.execution_snapshot ? (
                        <StatePanel title="Preview required" message="Return to Review impact and resolve the provider preview before approval." />
                      ) : (
                        <>
                          <p className="callout callout-warning remediation-snapshot-callout">
                            <span>Approval binds to this exact snapshot. It does not run the change.</span>
                            <code title={workflow.preview?.execution_snapshot?.snapshot_hash ?? "unavailable"}>
                              {workflow.preview?.execution_snapshot?.snapshot_hash
                                ? `${workflow.preview.execution_snapshot.snapshot_hash.slice(0, 12)}…`
                                : "unavailable"}
                            </code>
                          </p>
                          {workflow.approval.allow_self_approval && (
                            <p className="callout">
                              Demo policy exception: self-approval is enabled for this environment.
                              Approvers may approve their own requests. Production policy defaults this off.
                            </p>
                          )}
                          <ApprovalRequirementsList requirements={workflow.approval.requirements} />
                          <div className="remediation-approval-form">
                            <ApprovalStatusLine approval={workflow.approval} />
                            <label>
                              <span>Decision</span>
                              <select value={decision} onChange={(event) => setDecision(event.target.value as RemediationDecision["decision"])}>
                                <option value="approved">Approve</option>
                                <option value="rejected">Reject</option>
                                <option value="expired">Expire</option>
                              </select>
                            </label>
                            {decision === "approved" && unmetRoleOptions.length > 0 && (
                              <label>
                                <span>Required role this decision is for</span>
                                <select
                                  value={selectedRoleId}
                                  onChange={(event) => setSelectedRoleId(event.target.value)}
                                >
                                  {unmetRoleOptions.length > 1 && (
                                    <option value="">Select a role…</option>
                                  )}
                                  {unmetRoleOptions.map((option) => (
                                    <option key={option.roleId} value={option.roleId}>{option.role}</option>
                                  ))}
                                </select>
                                {unmetRoleOptions.length > 1 && (
                                  <p className="remediation-approval-role-hint">
                                    This decision attests exactly one required role. Multiple unmet roles remain -- a separate decision is needed for each.
                                  </p>
                                )}
                              </label>
                            )}
                            <label>
                              <span>Rationale</span>
                              <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} />
                            </label>
                            {decision === "approved" && (
                              <label>
                                <span>Expires</span>
                                <input type="date" value={decisionExpiresAt} onChange={(event) => setDecisionExpiresAt(event.target.value)} />
                              </label>
                            )}
                            <button
                              type="button"
                              className="button button-primary"
                              disabled={submitting || !workflow.approval.can_approve || (roleSelectionRequired && !selectedRoleId)}
                              onClick={() => void recordDecision()}
                            >
                              {submitting ? "Recording…" : "Record decision"}
                            </button>
                            {!workflow.approval.can_approve && (
                              <p>You can review this approval but cannot record a decision. Ask an approver to record it.</p>
                            )}
                          </div>
                        </>
                      )}
                    </>
                  )}

                  {activeStep === "run" && (
                    <>
                      {stepBlockerEcho(workflow.blockers, "run")}
                      <WorkflowDegradation degradation={workflow.degradation} />
                      <h3>Approved operation</h3>
                      <p>{actionSummary(workflow)}</p>
                      <p>Target: <code>{workflow.preview?.execution_snapshot?.target_id ?? resourceId(workflow.plan)}</code></p>
                      {!workflow.approval.current && <p className="callout callout-warning">A current approval for this exact preview is required.</p>}
                      {workflow.approval.current && !businessEvidenceReady(workflow) && (
                        <p className="callout callout-warning">Decision-grade business evidence is incomplete.</p>
                      )}
                      {canRun && !confirmRun && (
                        <button
                          type="button"
                          className="button button-primary"
                          disabled={!workflow.action.can_operate}
                          onClick={() => setConfirmRun(true)}
                        >
                          Review and run
                        </button>
                      )}
                      {canRun && confirmRun && (
                        <div className="callout" role="alertdialog" aria-label="Confirm governed execution">
                          <p>Run this exact approved snapshot once? Provider verification, not submission, determines success.</p>
                          <button
                            type="button"
                            className="button button-primary"
                            disabled={submitting || !workflow.action.can_operate}
                            onClick={() => void runPlan()}
                          >
                            {submitting ? "Submitting…" : "Confirm run"}
                          </button>
                          <button type="button" className="button button-quiet" onClick={() => setConfirmRun(false)}>Back</button>
                        </div>
                      )}
                      {canRun && !workflow.action.can_operate && (
                        <p>You can approve work but cannot run it. Ask an operator to run this approved snapshot.</p>
                      )}
                    </>
                  )}

                  {activeStep === "verify" && (
                    <>
                      {stepBlockerEcho(workflow.blockers, "verify")}
                      {!workflow.execution ? (
                        <StatePanel title="Not run yet" message="Complete approval and run before verification." />
                      ) : (
                        <ExecutionAudit
                          execution={workflow.execution}
                          decisions={workflow.approval.decisions}
                          onCheckReconciliation={() => polling.checkNow()}
                        />
                      )}
                      {polling.paused && (
                        <p className="callout callout-warning" role="status">
                          {`Live updates paused after ${polling.requestCount} checks. This execution may still be progressing server-side.`}
                          {" "}
                          <button type="button" className="button button-quiet" onClick={() => polling.checkNow()}>
                            Check now
                          </button>
                        </p>
                      )}
                      {workflow.execution && (
                        <RecoveryControls
                          execution={workflow.execution}
                          onCancel={() => cancelExecution(workflow.execution!)}
                          onRetry={() => retryExecution(workflow.execution!)}
                          onSupersede={(reason) => supersedeExecution(workflow.execution!, reason)}
                          submitting={submitting}
                          supersedeIneligibilityReason={supersedeIneligibilityReason}
                        />
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

      {fromCve && (
        <RiskExceptionDialog
          mode="record"
          open={riskDialogOpen}
          onOpenChange={setRiskDialogOpen}
          returnFocusRef={riskInvokerRef}
          governance={{
            decision: workflow?.approval.latest ?? null,
            workflow,
            execution: workflow?.execution ?? null,
          }}
          record={{
            cveId: fromCve,
            targetScope: requestedResource || "Current authorized Exposure scope",
            affectedMetrics: ["Open exposure", "Patch priority"],
            evidenceFreshness: fromGeneration
              ? `Generation ${fromGeneration}`
              : "Current server-projected evidence",
            sessionApprover: "Authenticated session",
          }}
          onRecord={recordRiskException}
          onRefresh={async () => {
            plans.refetch();
            setWorkflowRefresh((value) => value + 1);
          }}
        />
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={workflow?.plan.title ?? "Remediation"}
        requestedScope={remediationCopilot.requestedScope}
        snapshot={remediationCopilot.snapshot}
        starterQuestions={remediationCopilot.starterQuestions}
      />
    </div>
  );
}

function ApprovalStatusLine({ approval }: { approval: RemediationWorkflow["approval"] }) {
  const { status, stale_reasons: staleReasons, latest } = approval;
  const approver = latest?.approver ?? "";
  const decidedAt = latest?.decided_at ? new Date(latest.decided_at).toLocaleString() : "";
  if (status === "current") {
    return (
      <p>
        <StatusBadge label="Approved" tone="success" />{" "}
        {`Approved by ${approver} on ${decidedAt}. This approval matches the current version, evidence, and policy.`}
      </p>
    );
  }
  if (status === "stale") {
    return (
      <p>
        <StatusBadge label="Stale" tone="warning" />{" "}
        {`Approved by ${approver} on ${decidedAt}, but ${joinStaleReasons(staleReasons)} since. A new decision is required before running.`}
      </p>
    );
  }
  if (status === "rejected") {
    return (
      <p>
        <StatusBadge label="Rejected" tone="critical" />{" "}
        {`Rejected by ${approver} on ${decidedAt}: ${latest?.reason ?? ""}`}
      </p>
    );
  }
  if (status === "expired") {
    return (
      <p>
        <StatusBadge label="Expired" tone="warning" />{" "}
        {`Expired on ${latest?.expires_at ?? ""}. A new decision is required.`}
      </p>
    );
  }
  return (
    <p>
      <StatusBadge label="No decision" tone="neutral" /> No decision recorded yet.
    </p>
  );
}

function WorkflowBlockers({
  blockers,
  activeStep,
}: {
  blockers: RemediationBlocker[];
  activeStep: WorkflowStep;
}) {
  const rows = blockers.filter((row) => row.code !== "already_succeeded");
  if (!rows.length) return null;
  return (
    <section className="remediation-blockers">
      <h3>Workflow blockers</h3>
      {rows.map((row, index) => {
        const copy = blockerCopyWithTelemetry(row.code, row.step, row.message, row.next_action, row.severity);
        const stepLabel = WORKFLOW_STEPS.find((item) => item.id === copy.step)?.label ?? titleize(copy.step);
        return (
          <div
            key={`${row.code}-${row.step}-${index}`}
            className={`remediation-blocker-row${copy.step === activeStep ? " remediation-blocker-row-active" : ""}`}
          >
            <StatusBadge label="Blocked" tone={copy.severity === "critical" ? "critical" : "warning"} compact />
            <span className="remediation-blocker-step-chip">{stepLabel}</span>
            <span>{copy.message}</span>
            <span><strong>Next:</strong> {copy.nextAction}</span>
          </div>
        );
      })}
    </section>
  );
}

function WorkflowDegradation({ degradation }: { degradation: RemediationDegradation[] }) {
  if (!degradation.length) return null;
  return (
    <section className="remediation-degradation">
      <h3>Degraded inputs</h3>
      {degradation.map((row, index) => {
        const droppedCount = row.dropped_count ?? 0;
        const unmatchedCount = row.unmatched_count ?? 0;
        const hasCounts = Boolean(row.dropped_count) || Boolean(row.unmatched_count);
        return (
          <div key={`${row.source}-${index}`} className="remediation-degradation-row">
            <StatusBadge label={titleize(row.availability)} tone="warning" compact />
            <span className="remediation-degradation-source">{row.source}</span>
            <span>{row.reason}</span>
            {hasCounts && (
              <span>{`${droppedCount} evidence row(s) dropped, ${unmatchedCount} unmatched for this scope.`}</span>
            )}
            <span>{row.freshness ? `Last known good: ${row.freshness}` : "Freshness: unknown"}</span>
          </div>
        );
      })}
    </section>
  );
}

function ReconciliationSummary({
  reconciliation,
  nextVerificationAt,
  onCheckReconciliation,
}: {
  reconciliation?: RemediationEvidenceReconciliation;
  nextVerificationAt?: string;
  onCheckReconciliation?: () => void;
}) {
  if (!reconciliation || !reconciliation.status) return null;
  const tone = reconciliation.status === "reconciled_clean" ? "success" : "warning";
  let message: string;
  switch (reconciliation.status) {
    case "pending":
      message = `Reconciliation in progress — next check ${relativeTime(nextVerificationAt)}.`;
      break;
    case "reconciled_clean":
      message = `All selected patches confirmed cleared as of ${reconciliation.assessed_at}.`;
      break;
    case "reconciled_incomplete":
      message = `Provider reported success, but ${reconciliation.kbs_remaining.length} patch(es) remain present: ${reconciliation.kbs_remaining.join(", ")}.`;
      break;
    case "unreconciled":
      message = "Reconciliation could not confirm the outcome within the deadline; provider success is preserved, but the selected patches' actual state is unconfirmed.";
      break;
    case "unreconciled_timed_out":
      message = "The submission's outcome could not be confirmed within the deadline; this is now an ordinary retryable/supersedable failure.";
      break;
    default:
      message = "";
  }
  return (
    <div className="remediation-reconciliation">
      <StatusBadge label={titleize(reconciliation.status)} tone={tone} compact />
      <span>{message}</span>
      {reconciliation.kbs_cleared.length > 0 && (
        <span>{`Confirmed cleared: ${reconciliation.kbs_cleared.join(", ")}.`}</span>
      )}
      {reconciliation.status === "pending" && onCheckReconciliation && (
        <button type="button" className="button button-quiet" onClick={() => onCheckReconciliation()}>
          Check reconciliation
        </button>
      )}
    </div>
  );
}

function RecoveryControls({
  execution,
  onCancel,
  onRetry,
  onSupersede,
  submitting,
  supersedeIneligibilityReason,
}: {
  execution: RemediationExecution;
  onCancel: () => void | Promise<void>;
  onRetry: () => void | Promise<void>;
  onSupersede: (reason: string) => void | Promise<void>;
  submitting: boolean;
  supersedeIneligibilityReason: string;
}) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [showSupersedeForm, setShowSupersedeForm] = useState(false);
  const [supersedeReason, setSupersedeReason] = useState("");

  if (!execution.cancellable && !execution.retryable && !execution.supersedable) return null;

  return (
    <div className="remediation-recovery">
      {execution.cancellable && !confirmCancel && (
        <button type="button" className="button" onClick={() => setConfirmCancel(true)}>
          Cancel queued execution
        </button>
      )}
      {execution.cancellable && confirmCancel && (
        <div className="callout" role="alertdialog" aria-label="Confirm cancel">
          <p>Cancel this queued execution before it reaches the provider?</p>
          <button
            type="button"
            className="button button-primary"
            disabled={submitting}
            onClick={() => {
              void onCancel();
              setConfirmCancel(false);
            }}
          >
            Confirm cancel
          </button>
          <button type="button" className="button button-quiet" onClick={() => setConfirmCancel(false)}>Back</button>
        </div>
      )}
      {execution.retryable && (
        <button type="button" className="button" disabled={submitting} onClick={() => void onRetry()}>
          Retry approved snapshot
        </button>
      )}
      {execution.supersedable && !showSupersedeForm && (
        <button type="button" className="button" onClick={() => setShowSupersedeForm(true)}>
          Supersede this execution
        </button>
      )}
      {execution.supersedable && showSupersedeForm && (
        <div className="remediation-supersede-form">
          <label>
            <span>Reason</span>
            <textarea
              value={supersedeReason}
              onChange={(event) => setSupersedeReason(event.target.value)}
              aria-describedby="supersede-reason-hint"
              required
            />
          </label>
          <p id="supersede-reason-hint">Explain why this execution should be replaced. The reason is written to the audit trail.</p>
          <button
            type="button"
            className="button button-primary"
            disabled={submitting || !supersedeReason.trim()}
            onClick={() => {
              void onSupersede(supersedeReason.trim());
              setShowSupersedeForm(false);
              setSupersedeReason("");
            }}
          >
            Confirm supersede
          </button>
          <button type="button" className="button button-quiet" onClick={() => setShowSupersedeForm(false)}>Back</button>
        </div>
      )}
      {supersedeIneligibilityReason && (
        <p className="callout callout-warning">
          {blockerCopyWithTelemetry(supersedeIneligibilityReason, "verify").message}
        </p>
      )}
    </div>
  );
}

function ExecutionAudit({
  execution,
  decisions,
  onCheckReconciliation,
}: {
  execution: RemediationExecution;
  decisions?: RemediationApprovalDecision[];
  onCheckReconciliation?: () => void;
}) {
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
      {execution.status === "failed" && (
        execution.provider_submitted === false ? (
          <p className="callout callout-warning">
            {execution.failure_details
              ? `Blocked before submission: ${execution.failure_details}. No change was sent to the provider.`
              : "Blocked before submission: no failure detail was recorded for this attempt. No change was sent to the provider."}
          </p>
        ) : (
          <p className="callout callout-warning">
            {execution.failure_details
              ? `Submitted; provider reported: ${execution.failure_details}.`
              : "Submitted; the provider did not return failure detail for this attempt."}
          </p>
        )
      )}
      {execution.remaining_attempts !== undefined && (
        <p>{`Remaining attempts: ${execution.remaining_attempts}`}</p>
      )}
      {(execution.submitted_attempt_count !== undefined || execution.attempt_count !== undefined) && (
        <p>{`Submitted attempts: ${execution.submitted_attempt_count ?? execution.attempt_count}`}</p>
      )}
      {execution.verification_deadline_at && (
        <p>
          {execution.verified_state === "verification_deadline_exceeded"
            ? "Verification deadline passed"
            : `Verification deadline: ${new Date(execution.verification_deadline_at).toLocaleString()}`}
        </p>
      )}
      {execution.next_verification_at && !["succeeded", "failed", "cancelled"].includes(execution.status) && (
        <p>{`Next automatic check: ${relativeTime(execution.next_verification_at)}`}</p>
      )}
      <ReconciliationSummary
        reconciliation={execution.evidence_reconciliation}
        nextVerificationAt={execution.next_verification_at}
        onCheckReconciliation={onCheckReconciliation}
      />
      {(execution.supersedes || execution.superseded_by) && (
        <div className="remediation-lineage">
          {execution.supersedes && (
            <p>Supersedes execution <code>{execution.supersedes}</code>.</p>
          )}
          {execution.superseded_by && (
            <p>Superseded by execution <code>{execution.superseded_by}</code>: {execution.superseded_reason}.</p>
          )}
        </div>
      )}
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
      {decisions && decisions.length > 0 && (
        <>
          <h3>Decisions</h3>
          <ul>
            {decisions.map((entry, index) => (
              <li key={entry.decision_id || index}>
                {titleize(entry.decision)} by {entry.approver} on {entry.decided_at ? new Date(entry.decided_at).toLocaleString() : "unknown time"}
                {entry.self_approved && (
                  <>
                    {" "}
                    <StatusBadge label="Self-approved (demo exception)" tone="info" />
                    {entry.self_approval_policy_id && <code>{entry.self_approval_policy_id}</code>}
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
