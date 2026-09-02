"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/lib/types";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import {
  buildCopilotSnapshot,
  copilotEvidenceRows,
  networkApi,
  operationsApi,
  remediationApi,
  vulnerabilityApi,
} from "@/lib/services";
import type {
  RemediationApprovalContext,
  RemediationBusinessDecision,
  RemediationExecution,
  RemediationExecutionPreview,
  RemediationPlanDetail,
} from "@/lib/services";
import type { DefenderRemediationCase, NetworkGap, RemediationDecision, RemediationOpportunity, RemediationPlan, RuleFinding, VulnerabilityExposure } from "@/lib/types";

type BacklogKind = "plan" | "opportunity" | "network" | "vulnerability" | "patch" | "lifecycle" | "configuration" | "incident" | "identity" | "defender";

interface BacklogItem {
  uiId: string;
  id: string;
  kind: BacklogKind;
  sourceIds: Record<string, string>;
  title: string;
  status: string;
  priority: string;
  businessService: string;
  resource: string;
  impact: string;
  riskReduction: number;
  downtimeRisk: string;
  complianceImprovement: number;
  debtReduction: number;
  evidence: unknown;
  source: unknown;
  plan?: RemediationPlan;
  defenderCase?: DefenderRemediationCase;
}

function listValues(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => renderValue(item)).filter((item) => item !== "Not specified");
}

function searchableText(item: BacklogItem): string {
  return [
    item.title,
    item.status,
    item.priority,
    item.businessService,
    item.resource,
    item.impact,
    item.kind,
    ...Object.values(item.sourceIds),
  ].join(" ").toLowerCase();
}

function priorityRank(value: string): number {
  const normalized = value.toLowerCase();
  if (normalized.includes("critical") || normalized.includes("priority 1")) return 4;
  if (normalized.includes("high") || normalized.includes("priority 2")) return 3;
  if (normalized.includes("medium") || normalized.includes("priority 3")) return 2;
  if (normalized.includes("low") || normalized.includes("priority 4")) return 1;
  return 0;
}

function planToBacklog(plan: RemediationPlan): BacklogItem {
  const action = plan.recommended_action ?? {};
  return {
    uiId: `plan:${plan.plan_id}`,
    id: plan.plan_id,
    kind: "plan",
    sourceIds: { plan_id: plan.plan_id },
    title: plan.title || plan.plan_id,
    status: plan.status || "draft",
    priority: String(action.priority ?? plan.status ?? "review"),
    businessService: plan.business_service || "",
    resource: renderValue(plan.resource, plan.application || ""),
    impact: String(action.impact ?? action.summary ?? "Approval-ready remediation plan"),
    riskReduction: plan.simulation_result?.risk_reduction_percent ?? 0,
    downtimeRisk: String(plan.simulation_result?.downtime_risk ?? "requires maintenance window"),
    complianceImprovement: Number(plan.simulation_result?.compliance_improvement_percent ?? 0),
    debtReduction: plan.simulation_result?.operational_debt_reduction_percent ?? 0,
    evidence: plan,
    source: plan,
    plan,
  };
}

function opportunityToBacklog(opportunity: RemediationOpportunity): BacklogItem {
  const resourceName = opportunity.resource?.name || "Scope not identified";
  const id = `${opportunity.action_id || opportunity.opportunity_type || "opportunity"}-${resourceName}`;
  return {
    uiId: `opportunity:${id}`,
    id,
    kind: String(opportunity.opportunity_type || "opportunity").toLowerCase().includes("identity") ? "identity" : "opportunity",
    sourceIds: { action_id: String(opportunity.action_id || "") },
    title: titleize(opportunity.opportunity_type || "Remediation opportunity"),
    status: "candidate",
    priority: "review",
    businessService: String(opportunity.business_service ?? ""),
    resource: resourceName,
    impact: opportunity.evidence?.[0] || "Candidate requires plan generation before approval.",
    riskReduction: Number(opportunity.predictive_risk_score ?? opportunity.patch_risk_score ?? 0),
    downtimeRisk: "unknown until simulated",
    complianceImprovement: 0,
    debtReduction: Number(opportunity.operational_debt_score ?? 0),
    evidence: opportunity,
    source: opportunity,
  };
}

function defenderCaseToBacklog(defenderCase: DefenderRemediationCase): BacklogItem {
  const id = `${defenderCase.resource_key}:${defenderCase.weakness_key}`;
  return {
    uiId: `defender:${id}`,
    id,
    kind: "defender",
    sourceIds: { resource_key: defenderCase.resource_key, weakness_key: defenderCase.weakness_key },
    title: defenderCase.resource_name || defenderCase.resource_key,
    status: defenderCase.business_mapping_review_required ? "review required" : "candidate",
    priority: defenderCase.disposition || "review",
    businessService: String((defenderCase.business_context as Record<string, unknown> | undefined)?.affected_services ?? ""),
    resource: defenderCase.resource_name || defenderCase.resource_key,
    impact: defenderCase.urgency_rationale || "Defender-correlated remediation case.",
    riskReduction: 0,
    downtimeRisk: defenderCase.cost_of_action || "unknown",
    complianceImprovement: 0,
    debtReduction: 0,
    evidence: defenderCase.evidence_citations,
    source: defenderCase,
    defenderCase,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function renderValue(value: unknown, fallback = "Not specified"): string {
  if (Array.isArray(value)) return value.map((item) => renderValue(item)).join(", ");
  if (isRecord(value)) {
    return String(value.name ?? value.title ?? value.role ?? value.description ?? fallback);
  }
  const text = String(value ?? "").trim();
  return text || fallback;
}

function renderDetails(value: unknown, fallback = "Not specified"): string {
  if (Array.isArray(value)) {
    const rendered = value.map((item) => renderDetails(item, "")).filter(Boolean);
    return rendered.join(", ") || fallback;
  }
  if (isRecord(value)) {
    const rendered = Object.entries(value)
      .filter(([, item]) => item !== null && item !== undefined && item !== "")
      .map(([key, item]) => `${titleize(key)}: ${renderDetails(item, "")}`);
    return rendered.join(" · ") || fallback;
  }
  const text = String(value ?? "").trim();
  return text || fallback;
}

function eligibilityReason(reason: string): string {
  if (!reason) return "";
  return titleize(reason.replaceAll("_", " "));
}

function sourceWarning(label: string, error: Error | ApiError | null): string[] {
  if (!error) return [];
  const message = error instanceof ApiError && error.isNotImplemented
    ? `${label} is not implemented in this build.`
    : `${label} unavailable: ${error.message}`;
  return [message];
}

function networkGapToBacklog(gap: NetworkGap): BacklogItem {
  return {
    uiId: `network:${gap.gap_id}`,
    id: gap.gap_id,
    kind: "network",
    sourceIds: { gap_id: gap.gap_id },
    title: gap.title,
    status: "candidate",
    priority: gap.severity,
    businessService: "",
    resource: gap.resource_id || gap.resource_name,
    impact: gap.detail || gap.recommendation,
    riskReduction: gap.severity === "critical" ? 75 : gap.severity === "high" ? 60 : 35,
    downtimeRisk: "medium - network path validation required",
    complianceImprovement: gap.severity === "critical" ? 55 : 30,
    debtReduction: 25,
    evidence: gap.evidence,
    source: gap,
  };
}

function ruleToBacklog(rule: RuleFinding): BacklogItem {
  return {
    uiId: `configuration:${rule.finding_id}`,
    id: rule.finding_id,
    kind: "configuration",
    sourceIds: { finding_id: rule.finding_id },
    title: rule.title,
    status: "candidate",
    priority: rule.severity,
    businessService: "",
    resource: rule.rule_id,
    impact: rule.detail || rule.recommendation,
    riskReduction: rule.severity === "critical" ? 70 : rule.severity === "high" ? 50 : 25,
    downtimeRisk: "low - rule blast radius review required",
    complianceImprovement: 45,
    debtReduction: 20,
    evidence: rule.evidence,
    source: rule,
  };
}

function exposureToBacklog(exposure: VulnerabilityExposure): BacklogItem {
  return {
    uiId: `vulnerability:${exposure.cve_id}`,
    id: exposure.cve_id,
    kind: "vulnerability",
    sourceIds: { cve_id: exposure.cve_id },
    title: `${exposure.cve_id}: ${exposure.recommended_patch}`,
    status: "candidate",
    priority: exposure.severity,
    businessService: "",
    resource: `${exposure.affected_server_count} affected servers`,
    impact: `${exposure.affected_business_service_count} business services affected; ${exposure.reachable_server_count} reachable servers.`,
    riskReduction: exposure.expected_risk_reduction,
    downtimeRisk: "maintenance window required for patching",
    complianceImprovement: exposure.is_known_exploited ? 70 : 40,
    debtReduction: 30,
    evidence: exposure.finding_ids,
    source: exposure,
  };
}

/** Approval-oriented remediation workspace that separates recommendations from execution. */
export default function RemediationPage() {
  return (
    <Suspense fallback={<div className="page-container"><div className="state-panel state-loading">Preparing remediation workspace…</div></div>}>
      <RemediationContent />
    </Suspense>
  );
}

function RemediationContent() {
  const { scope } = useScope();
  const searchParams = useSearchParams();
  const fromCve = searchParams.get("cve") ?? "";
  const fromKb = searchParams.get("kb") ?? "";
  const fromBusinessService = searchParams.get("business_service") ?? "";
  const fromIncident = searchParams.get("incident") ?? "";
  const fromResourceKey = searchParams.get("resource_key") ?? "";
  const plans = useApi(() => operationsApi.remediationPlans(scope, 0, 100, fromResourceKey), [scope, fromResourceKey]);
  const opportunities = useApi(() => operationsApi.remediationOpportunities(scope), [scope]);
  const defenderCases = useApi(() => operationsApi.defenderCases(scope), [scope]);
  const networkGaps = useApi(() => networkApi.gaps(scope), [scope]);
  const ruleFindings = useApi(() => networkApi.ruleFindings(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope), [scope]);
  const [selectedId, setSelectedId] = useState("");
  const [category, setCategory] = useState<BacklogKind | "all">("all");
  const [query, setQuery] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [sortBy, setSortBy] = useState<"risk" | "priority" | "confidence" | "source">("risk");
  const [decisionChoice, setDecisionChoice] = useState<RemediationDecision["decision"]>("approved");
  const [decisionReason, setDecisionReason] = useState("");
  const [decisionExpiresAt, setDecisionExpiresAt] = useState("");
  const [decisionSubmitting, setDecisionSubmitting] = useState(false);
  const [decisionResult, setDecisionResult] = useState<RemediationDecision | null>(null);
  const [decisionError, setDecisionError] = useState("");
  const [planContext, setPlanContext] = useState<RemediationPlanDetail | null>(null);
  const [executionPreview, setExecutionPreview] = useState<RemediationExecutionPreview | null>(null);
  const [approvalContext, setApprovalContext] = useState<RemediationApprovalContext | null>(null);
  const [businessDecision, setBusinessDecision] = useState<RemediationBusinessDecision | null>(null);
  const [executionContextLoading, setExecutionContextLoading] = useState(false);
  const [executionContextError, setExecutionContextError] = useState("");
  const [executionContextRefresh, setExecutionContextRefresh] = useState(0);
  const [executionConfirmOpen, setExecutionConfirmOpen] = useState(false);
  const [activeExecution, setActiveExecution] = useState<RemediationExecution | null>(null);
  const [executionSubmitting, setExecutionSubmitting] = useState(false);
  const [executionActionError, setExecutionActionError] = useState("");
  const contextRequest = useRef(0);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const allPlanRows = plans.data?.data.plans ?? [];
  const allOpportunityRows = opportunities.data?.data.opportunities ?? [];
  // Remediation plans/opportunities are resource- and business-service-driven,
  // not CVE/KB-specific (Prompt 7's patch findings and this engine remain
  // decoupled by design), so a CVE/KB drilldown links here scoped to the
  // affected business service — the closest concrete cross-reference this
  // engine can answer today.
  const planRows = fromBusinessService
    ? allPlanRows.filter((plan) => plan.business_service === fromBusinessService)
    : allPlanRows;
  const opportunityRows = (
    fromBusinessService
      ? allOpportunityRows.filter((opportunity) => opportunity.business_service === fromBusinessService)
      : allOpportunityRows
  ).filter((opportunity) =>
    fromResourceKey
      ? String(opportunity.resource_key ?? opportunity.resource?.name ?? "") === fromResourceKey
      : true,
  );
  const backlog = useMemo(() => {
    const rows = [
      ...planRows.map(planToBacklog),
      ...opportunityRows.map(opportunityToBacklog),
      ...(defenderCases.data?.data.cases ?? []).map(defenderCaseToBacklog),
      ...(networkGaps.data?.data.gaps ?? []).map(networkGapToBacklog),
      ...(ruleFindings.data?.data.findings ?? []).map(ruleToBacklog),
      ...(exposures.data?.data ?? []).map(exposureToBacklog),
    ];
    const seeded: BacklogItem[] = [
      {
        uiId: "incident:readiness",
        id: fromIncident ? `incident-${fromIncident}` : "incident-readiness",
        kind: "incident",
        sourceIds: { incident_id: fromIncident || "incident-readiness" },
        title: fromIncident ? `Resolve incident ${fromIncident}` : "Incident remediation readiness",
        status: "candidate",
        priority: fromIncident ? "high" : "medium",
        businessService: fromBusinessService,
        resource: fromIncident || "incident queue",
        impact: "Convert incident commander findings into a governed remediation handoff.",
        riskReduction: fromIncident ? 65 : 20,
        downtimeRisk: "depends on selected change",
        complianceImprovement: 15,
        debtReduction: 20,
        evidence: { incident: fromIncident },
        source: { incident: fromIncident },
      },
      {
        uiId: "lifecycle:debt",
        id: "lifecycle-debt",
        kind: "lifecycle",
        sourceIds: { seed_id: "lifecycle-debt" },
        title: "Address lifecycle and supportability debt",
        status: "candidate",
        priority: "medium",
        businessService: fromBusinessService,
        resource: "lifecycle inventory",
        impact: "Upgrade or retire stale runtime and platform versions before they become incident drivers.",
        riskReduction: 30,
        downtimeRisk: "planned maintenance required",
        complianceImprovement: 25,
        debtReduction: 60,
        evidence: { source: "semantic lifecycle metadata" },
        source: { category: "lifecycle" },
      },
      {
        uiId: "identity:governance",
        id: "identity-governance",
        kind: "identity",
        sourceIds: { seed_id: "identity-governance" },
        title: "Review identity and access remediation",
        status: "candidate",
        priority: "medium",
        businessService: fromBusinessService,
        resource: "identity assignments",
        impact: "Validate least-privilege access and approval boundaries for remediation execution.",
        riskReduction: 25,
        downtimeRisk: "low",
        complianceImprovement: 35,
        debtReduction: 20,
        evidence: { source: "governance policy" },
        source: { category: "identity" },
      },
    ];
    const normalizedQuery = query.trim().toLowerCase();
    return [...rows, ...seeded]
      .filter((item) => category === "all" || item.kind === category)
      .filter((item) => priorityFilter === "all" || item.priority.toLowerCase().includes(priorityFilter))
      .filter((item) => statusFilter === "all" || item.status.toLowerCase().includes(statusFilter))
      .filter((item) => !normalizedQuery || searchableText(item).includes(normalizedQuery))
      .sort((left, right) => {
        if (sortBy === "priority") return priorityRank(right.priority) - priorityRank(left.priority) || right.riskReduction - left.riskReduction;
        if (sortBy === "confidence") return (right.plan?.confidence ?? 0) - (left.plan?.confidence ?? 0) || right.riskReduction - left.riskReduction;
        if (sortBy === "source") return left.kind.localeCompare(right.kind) || right.riskReduction - left.riskReduction;
        return right.riskReduction - left.riskReduction;
      });
  }, [planRows, opportunityRows, defenderCases.data, networkGaps.data, ruleFindings.data, exposures.data, category, fromBusinessService, fromIncident, priorityFilter, query, sortBy, statusFilter]);
  const selected = backlog.find((item) => item.uiId === selectedId) ?? backlog.find((item) => item.kind === "plan") ?? backlog[0] ?? null;
  const selectedPlan = selected?.plan ?? null;
  const scopeKey = JSON.stringify(scope);
  useEffect(() => {
    const planId = selectedPlan?.plan_id;
    const requestId = ++contextRequest.current;
    setExecutionConfirmOpen(false);
    if (!planId) {
      setPlanContext(null);
      setExecutionPreview(null);
      setApprovalContext(null);
      setBusinessDecision(null);
      setActiveExecution(null);
      setExecutionContextError("");
      setExecutionContextLoading(false);
      return;
    }
    setExecutionContextLoading(true);
    setExecutionContextError("");
    void Promise.all([
      remediationApi.plan(planId, scope),
      remediationApi.preview(planId, scope),
      remediationApi.approvals(planId, scope),
      remediationApi.businessDecision(planId, scope),
      remediationApi.executions(planId, scope),
    ])
      .then(([planResponse, previewResponse, approvalsResponse, businessResponse, executionsResponse]) => {
        if (contextRequest.current !== requestId) return;
        setPlanContext(planResponse.data);
        setExecutionPreview(previewResponse.data);
        setApprovalContext(approvalsResponse.data);
        setBusinessDecision(businessResponse.data);
        setActiveExecution(executionsResponse.data.executions.slice(-1)[0] ?? null);
      })
      .catch((error) => {
        if (contextRequest.current !== requestId) return;
        setPlanContext(null);
        setExecutionPreview(null);
        setApprovalContext(null);
        setBusinessDecision(null);
        setActiveExecution(null);
        setExecutionContextError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (contextRequest.current === requestId) setExecutionContextLoading(false);
      });
    return () => {
      if (contextRequest.current === requestId) contextRequest.current += 1;
    };
    // scopeKey intentionally invalidates in-flight detail reads when any scope dimension changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPlan?.plan_id, scopeKey, executionContextRefresh]);

  useEffect(() => {
    setDecisionResult(null);
    setDecisionError("");
    setExecutionActionError("");
  }, [selectedPlan?.plan_id]);

  useEffect(() => {
    const executionId = activeExecution?.execution_id;
    if (
      !executionId
      || !["queued", "running", "retrying"].includes(activeExecution.status)
      || !selectedPlan?.plan_id
    ) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let remainingPolls = 40;
    const selectedPlanId = selectedPlan.plan_id;

    const poll = async () => {
      if (cancelled || remainingPolls <= 0) {
        if (!cancelled && remainingPolls <= 0) {
          setExecutionActionError("Automatic polling paused after 40 checks. Refresh the plan to continue observing provider state.");
        }
        return;
      }
      remainingPolls -= 1;
      try {
        const response = await remediationApi.execution(executionId, scope);
        if (cancelled || contextRequest.current < 1 || selectedPlan?.plan_id !== selectedPlanId) return;
        setActiveExecution(response.data);
        if (["queued", "running", "retrying"].includes(response.data.status)) {
          timer = setTimeout(() => void poll(), 1500);
        }
      } catch (error) {
        if (cancelled) return;
        setExecutionActionError(error instanceof Error ? error.message : String(error));
        timer = setTimeout(() => void poll(), 3000);
      }
    };

    timer = setTimeout(() => void poll(), 1500);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // scopeKey and selected plan identity terminate stale polling across trust boundaries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeExecution?.execution_id, selectedPlan?.plan_id, scopeKey]);

  const latestApproval = approvalContext?.decisions.slice(-1)[0] ?? null;
  const previewSnapshot = executionPreview?.execution_snapshot ?? null;
  const approvalSnapshot = latestApproval?.execution_snapshot ?? null;
  const reviewRequirements = businessDecision?.review_requirements;
  const businessEvidenceReady = Boolean(
    businessDecision
      && ["act_now", "schedule"].includes(businessDecision.disposition ?? "")
      && isRecord(businessDecision.business_impact)
      && businessDecision.business_impact.status === "known"
      && (businessDecision.urgency_rationale?.evidence_citations?.length ?? 0) > 0
      && (Array.isArray(reviewRequirements) ? reviewRequirements.length === 0 : !reviewRequirements || Object.keys(reviewRequirements).length === 0)
      && (businessDecision.unknowns?.length ?? 0) === 0
  );
  const approvalIsCurrent = Boolean(
    latestApproval?.decision === "approved"
      && previewSnapshot
      && approvalSnapshot?.snapshot_hash === previewSnapshot.snapshot_hash
  );
  const controlledPatchPlan = (planContext?.action_id ?? planContext?.opportunity_type) === "controlled-patch-recovery";
  const canExecute = Boolean(
    controlledPatchPlan
      && planContext?.executable
      && executionPreview?.executable
      && previewSnapshot
      && approvalIsCurrent
      && businessEvidenceReady
  );
  const executionBlockReason = !controlledPatchPlan
    ? planContext?.ineligibility_reason || "action_not_executable"
    : planContext?.ineligibility_reason
      || executionPreview?.ineligibility_reason
      || (!approvalIsCurrent ? "current_approval_required" : "")
      || (!businessEvidenceReady ? "decision_grade_business_evidence_required" : "");

  const executePlan = async () => {
    if (!selectedPlan || !canExecute || executionSubmitting) return;
    setExecutionSubmitting(true);
    setExecutionActionError("");
    try {
      const response = await remediationApi.execute(selectedPlan.plan_id, scope);
      setActiveExecution(response.data);
      setExecutionConfirmOpen(false);
    } catch (error) {
      setExecutionActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setExecutionSubmitting(false);
    }
  };

  const retryExecution = async () => {
    if (!activeExecution?.retryable || executionSubmitting) return;
    setExecutionSubmitting(true);
    setExecutionActionError("");
    try {
      const response = await remediationApi.retry(activeExecution.execution_id, scope);
      setActiveExecution(response.data);
    } catch (error) {
      setExecutionActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setExecutionSubmitting(false);
    }
  };

  const cancelExecution = async () => {
    if (!activeExecution?.cancellable || executionSubmitting) return;
    setExecutionSubmitting(true);
    setExecutionActionError("");
    try {
      const response = await remediationApi.cancel(activeExecution.execution_id, scope);
      setActiveExecution(response.data);
    } catch (error) {
      setExecutionActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setExecutionSubmitting(false);
    }
  };
  const pending = backlog.length;
  const evidencePack = selected ? {
    plan: selected.source,
    evidence: selected.evidence,
    sourceEvidence: [
      ...(plans.data?.evidence ?? []),
      ...(opportunities.data?.evidence ?? []),
      ...(defenderCases.data?.evidence ?? []),
      ...(networkGaps.data?.evidence ?? []),
      ...(ruleFindings.data?.evidence ?? []),
      ...(exposures.data?.evidence ?? []),
    ],
    review_boundary: "Phase 2 records approval decisions only; Azure execution, rollback, and realized-outcome capture remain unavailable.",
  } : {};
  const loading = plans.loading || opportunities.loading || defenderCases.loading || networkGaps.loading || ruleFindings.loading || exposures.loading;
  const sourceWarnings = [
    ...sourceWarning("Remediation plans", plans.error),
    ...sourceWarning("Remediation opportunities", opportunities.error),
    ...sourceWarning("Defender remediation cases", defenderCases.error),
    ...sourceWarning("Network gaps", networkGaps.error),
    ...sourceWarning("Configuration findings", ruleFindings.error),
    ...sourceWarning("Vulnerability exposures", exposures.error),
  ];
  const pageError = !loading && backlog.length === 0 ? plans.error ?? opportunities.error ?? defenderCases.error ?? networkGaps.error ?? ruleFindings.error ?? exposures.error : null;

  const recordDecision = async () => {
    if (!selectedPlan?.action_version) return;
    
    // Validate: expires_at is only for approved decisions
    if (decisionChoice !== "approved" && decisionExpiresAt.trim()) {
        setDecisionError(`${decisionChoice} decisions must not include an expiry date.`);
        return;
    }
    if (decisionChoice === "approved" && !decisionExpiresAt.trim()) {
        setDecisionError("Approved decisions must include a future expiry date.");
        return;
    }
    
    setDecisionSubmitting(true);
    setDecisionError("");
    setDecisionResult(null);
    try {
      const result = await remediationApi.approve(selectedPlan.plan_id, {
        decision: decisionChoice,
        reason: decisionReason.trim(),
        action_version: selectedPlan.action_version,
        expires_at: decisionExpiresAt.trim(),
        preview_snapshot_hash: decisionChoice === "approved" ? previewSnapshot?.snapshot_hash : undefined,
      }, scope);
      setDecisionResult(result.data);
      setDecisionReason("");
      setExecutionContextRefresh((value) => value + 1);
    } catch (error) {
      if (
        error instanceof ApiError
        && error.details?.reason === "stale_execution_preview"
      ) {
        setDecisionError("The execution preview changed. Review the refreshed target and operation before approving again.");
        setExecutionContextRefresh((value) => value + 1);
        return;
      }
      setDecisionError(error instanceof Error ? error.message : String(error));
    } finally {
      setDecisionSubmitting(false);
    }
  };

  return (
    <div className="page-container remediation-center">
      <PageHeader
        eyebrow="Governed remediation center"
        title="Review, approve, and observe safe remediation"
        description="Review business impact and the exact server-owned operation before executing an approved controlled patch recovery."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about remediation" />}
        metadata={
          <>
            <span>Approval-bound execution</span>
            <span>Verified provider outcomes</span>
            <span>Evidence-backed recommendations</span>
          </>
        }
      />
      <EvidenceBar
        evidence={[...(plans.data?.evidence ?? []), ...(opportunities.data?.evidence ?? []), ...(defenderCases.data?.evidence ?? []), ...(networkGaps.data?.evidence ?? []), ...(ruleFindings.data?.evidence ?? []), ...(exposures.data?.evidence ?? [])]}
        knowledgeVersion={plans.data?.knowledge_version}
        warnings={[...sourceWarnings, ...(plans.data?.warnings ?? []), ...(opportunities.data?.warnings ?? []), ...(defenderCases.data?.warnings ?? []), ...(networkGaps.data?.warnings ?? []), ...(ruleFindings.data?.warnings ?? []), ...(exposures.data?.warnings ?? [])]}
      />

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={fromBusinessService || "Remediation"}
        snapshot={buildCopilotSnapshot({
          pageKind: "remediation",
          pageId: "remediation",
          scope,
          filters: {
            category: category === "all" ? [] : [category],
            priority: priorityFilter === "all" ? [] : [priorityFilter],
            status: statusFilter === "all" ? [] : [statusFilter],
            query: query ? [query] : [],
            business_service: fromBusinessService ? [fromBusinessService] : [],
            cve: fromCve ? [fromCve] : [],
          },
          selectedResources: selected ? [{ resource_id: selected.resource, resource_type: selected.kind, name: selected.title }] : [],
          evidence: copilotEvidenceRows("remediation", [
            ...(plans.data?.evidence ?? []),
            ...(opportunities.data?.evidence ?? []),
            ...(defenderCases.data?.evidence ?? []),
            ...(networkGaps.data?.evidence ?? []),
            ...(ruleFindings.data?.evidence ?? []),
            ...(exposures.data?.evidence ?? []),
          ], backlog),
        })}
        starterQuestions={[
          { label: "What should be fixed first?", tool: "remediation_opportunities", toolArguments: {} },
          { label: "Highest risk-reduction remediation plans", tool: "remediation_plans", toolArguments: {} },
          ...(fromBusinessService
            ? [
                {
                  label: `Tell me about the ${fromBusinessService} business service.`,
                  tool: "business_service_context",
                  toolArguments: { name: fromBusinessService },
                },
              ]
            : [{ label: "What changed before the outage?", tool: "incidents", toolArguments: {} }]),
        ]}
      />

      {(fromCve || fromKb || fromIncident || fromResourceKey) && (
        <div className="callout" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <span>
            Filtered from{" "}
            {fromCve && (
              <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(fromCve)}`}>
                {fromCve}
              </Link>
            )}
            {fromCve && fromKb && " / "}
            {fromKb && (
              <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(fromKb)}`}>
                {fromKb}
              </Link>
            )}
            {fromIncident && `Incident ${fromIncident}`}
            {fromIncident && (fromCve || fromKb || fromBusinessService || fromResourceKey) ? " · " : ""}
            {fromResourceKey && `Resource ${fromResourceKey}`}
            {fromResourceKey && fromBusinessService ? " · " : ""}
            {fromBusinessService
              ? `showing plans and opportunities for the "${fromBusinessService}" business service.`
              : "this environment has no business-service mapping for that handoff, so all plans are shown."}
          </span>
          <Link className="button" href="/remediation">Clear filter</Link>
        </div>
      )}

      <div className="remediation-form-grid" aria-label="Remediation filters">
        <label>
          Search
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Title, resource, service, source ID" />
        </label>
        <label>
          Priority
          <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
            <option value="all">All priorities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
            <option value="priority 1">Priority 1</option>
            <option value="priority 2">Priority 2</option>
          </select>
        </label>
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="all">All statuses</option>
            <option value="draft">Draft</option>
            <option value="candidate">Candidate</option>
            <option value="approval">Approval required</option>
          </select>
        </label>
        <label>
          Sort
          <select value={sortBy} onChange={(event) => setSortBy(event.target.value as typeof sortBy)}>
            <option value="risk">Risk reduction</option>
            <option value="priority">Priority</option>
            <option value="confidence">Confidence</option>
            <option value="source">Source/category</option>
          </select>
        </label>
      </div>

      <div className="metric-grid remediation-metrics">
        <MetricCard label="Unified backlog" value={backlog.length} detail={`${pending} scoped candidates`} />
        <MetricCard label="Network candidates" value={(networkGaps.data?.data.gaps.length ?? 0) + (ruleFindings.data?.data.findings.length ?? 0)} detail="Firewall, NSG, UDR, peering, private endpoint, and inspection-path fixes" />
        <MetricCard
          label="Highest simulated reduction"
          value={`${Math.round(Math.max(0, ...backlog.map((item) => item.riskReduction)))}%`}
          detail="Projected current-to-future risk delta"
          tone="success"
        />
        <MetricCard
          label="Execution boundary"
          value="Governed"
          detail="Only approved controlled patch recovery is executable"
          tone="success"
        />
      </div>

      <div className="segmented-control remediation-filter" aria-label="Remediation category filter">
        {(["all", "network", "vulnerability", "patch", "configuration", "incident", "identity", "lifecycle", "defender"] as const).map((value) => (
          <button type="button" key={value} className={category === value ? "segmented-active" : ""} onClick={() => setCategory(value)}>
            {value === "all" ? "All" : titleize(value)}
          </button>
        ))}
      </div>

      {pageError ? (
        <StatePanel
          title="Remediation intelligence is unavailable"
          message={pageError.message ?? "No remediation response was returned."}
          tone="error"
        />
      ) : loading ? (
        <StatePanel title="Reading remediation candidates" message="Joining source evidence with projected impact and governed execution eligibility." tone="loading" />
      ) : (
        <div className="remediation-layout">
          <section className="card">
            <div className="card-header">
              <div>
                <h2>Unified remediation backlog</h2>
                <p>Network, vulnerability, patch, lifecycle, configuration, incident, and identity candidates in one governed queue.</p>
              </div>
            </div>
            <div className="plan-list">
              {backlog.map((item) => {
                const decision = item.status;
                return (
                <article className={`plan-row ${selected?.uiId === item.uiId ? "plan-row-selected" : ""}`} key={item.uiId}>
                  <div className="plan-row-heading">
                    <div className="plan-row-summary">
                      <div className="plan-row-badges">
                        <StatusBadge label={decision || "draft"} tone={statusTone(decision)} />
                        <StatusBadge label={titleize(item.kind)} tone="info" compact />
                      </div>
                      <h3>{item.title}</h3>
                      <p>{item.businessService || item.resource || "Scope not mapped"}</p>
                      <p>{item.impact}</p>
                    </div>
                    <div className="plan-risk">
                      <strong>{Math.round(item.riskReduction)}%</strong>
                      <span>risk reduction</span>
                    </div>
                  </div>
                  <div className="plan-actions">
                    <button type="button" className="button button-secondary" onClick={() => setSelectedId(item.uiId)}>Review</button>
                  </div>
                </article>
              )})}
              {backlog.length === 0 && <StatePanel title="No remediation backlog" message="No governed remediation candidates exist in this scope." />}
            </div>
          </section>

          <aside className="card">
            <div className="card-header">
              <div>
                <h2>Evidence and projected impact</h2>
                <p>Affected entities, business evidence, and the exact provider operation are reviewed together.</p>
              </div>
            </div>
            <div className="card-body remediation-plan-detail">
              {selected ? (
                <>
                  <h3>{selected.title}</h3>
                  {selected.defenderCase ? (
                    <>
                      <div className="simulation-grid">
                        <MetricCard
                          label={selected.defenderCase.business_mapping_review_required ? "Review required" : "Confidence"}
                          value={selected.defenderCase.business_mapping_review_required ? "Business mapping unknown" : `${Math.round((selected.defenderCase.confidence ?? 0) * 100)}%`}
                          detail={selected.defenderCase.business_mapping_review_required ? "No priority can be assigned until business ownership is confirmed." : "Correlation confidence across evidence sources"}
                          tone={selected.defenderCase.business_mapping_review_required ? "warning" : "success"}
                          size={selected.defenderCase.business_mapping_review_required ? "text" : undefined}
                        />
                        <MetricCard label="Disposition" value={titleize(selected.defenderCase.disposition || "review")} detail={selected.defenderCase.urgency_rationale || "See urgency rationale"} tone="warning" size="text" />
                        <MetricCard label="Cost of acting" value={selected.defenderCase.cost_of_action || "Not assessed"} detail="Cost of action" size="text" />
                        <MetricCard label="Cost of inaction" value={selected.defenderCase.cost_of_inaction || "Not assessed"} detail="Cost of inaction" size="text" tone="warning" />
                      </div>
                      <section className="remediation-section">
                        <h4>Evidence citations</h4>
                        <ul>
                          {(selected.defenderCase.evidence_citations || []).map((citation, index) => (
                            <li key={index}>{citation.source_type}:{citation.source_id} - {citation.severity || "unspecified"} severity - {citation.summary}</li>
                          ))}
                        </ul>
                        {selected.defenderCase.contradictory_evidence && (
                          <p className="callout callout-warning">Evidence sources disagree on severity for this case; confidence has been reduced.</p>
                        )}
                      </section>
                      <section className="remediation-section">
                        <h4>Observed, inferred, and unknown</h4>
                        <p>Observed: {listValues(selected.defenderCase.observed_facts).join("; ") || "None recorded"}</p>
                        <p>Inferred: {listValues(selected.defenderCase.derived_inferences).join("; ") || "None recorded"}</p>
                        <p>Unknown: {listValues(selected.defenderCase.unknowns).join("; ") || "None recorded"}</p>
                      </section>
                      {selected.defenderCase.outcome === "no_safe_action" ? (
                        <section className="remediation-section">
                          <h4>Outcome</h4>
                          <p className="callout callout-warning">No safe automated action exists for this case: {selected.defenderCase.outcome_reason || "no catalog match was found"}. This case requires manual review; no approval control is offered.</p>
                        </section>
                      ) : (
                        <section className="remediation-section">
                          <h4>Execution boundary</h4>
                          <p>Phase 2 surfaces this Defender-correlated case for review. Azure execution, rollback actions, and realized-outcome validation remain unavailable here.</p>
                        </section>
                      )}
                    </>
                  ) : (
                    <>
                  <div className="simulation-grid">
                    <MetricCard label="Projected risk reduction" value={`${Math.round(selected.riskReduction)}%`} detail="Current vs projected risk" tone="success" />
                    <MetricCard label="Downtime risk" value={selected.downtimeRisk} detail="Requires maintenance-window review" tone="warning" size="text" />
                    <MetricCard label="Compliance improvement" value={`${Math.round(selected.complianceImprovement)}%`} detail="Policy/SLA uplift estimate" />
                    <MetricCard label="Debt reduction" value={`${Math.round(selected.debtReduction)}%`} detail="Operational-debt reduction estimate" />
                  </div>
                  <section className="remediation-section">
                    <h4>Objective and scope</h4>
                    <p>{selectedPlan?.objective || selected.impact}</p>
                    <p>Resource: {selected.resource || "Scope not mapped"} · Service: {selected.businessService || "Unmapped"} · Source IDs: {Object.entries(selected.sourceIds).map(([key, value]) => `${key}=${value}`).join(", ")}</p>
                  </section>
                  <section className="remediation-section">
                    <h4>Plan steps</h4>
                    <ol>
                      {(selectedPlan?.execution_steps?.length ? selectedPlan.execution_steps : [
                        { description: "Confirm affected entities and owner accountability." },
                        { description: "Review the source evidence and affected entities." },
                        { description: "Record an approval, rejection, or expiry decision." },
                        { description: "Validate live state only in a later execution phase." },
                      ]).map((step, index) => (
                        <li key={index}>
                          {renderValue(step, "Review remediation step")}
                          {isRecord(step) && step.stage ? <span> ({renderValue(step.stage)})</span> : null}
                        </li>
                      ))}
                    </ol>
                  </section>
                  <section className="remediation-section">
                    <h4>Prerequisites and risk</h4>
                    <p>Preconditions: {listValues(selectedPlan?.recommended_action?.preconditions ?? selectedPlan?.preconditions).join(", ") || "Review owner accountability, current evidence, and rollback readiness before recording approval."}</p>
                    <p>Risk assessment: {renderValue(selectedPlan?.risk_assessment?.overall_risk ?? selectedPlan?.risk_assessment)}</p>
                  </section>
                  <section className="remediation-section">
                    <h4>Required approvals</h4>
                    {selectedPlan?.approval_requirements?.length ? (
                      <ul>
                        {selectedPlan.approval_requirements.map((approval, index) => (
                          <li key={index}>{renderValue(approval.role)} - {renderValue(approval.stage)} - {renderValue(approval.status)}</li>
                        ))}
                      </ul>
                    ) : (
                      <p>Owner sign-off, CAB approval, affected-path validation, and rollback owner review are required before execution.</p>
                    )}
                  </section>
                  <section className="remediation-section">
                    <h4>Rollback, simulation, and confidence</h4>
                    <p>Rollback: {renderValue(selectedPlan?.rollback_plan?.summary ?? selectedPlan?.rollback_plan)}</p>
                    <p>Dependencies: {renderValue(selectedPlan?.dependencies)}</p>
                    <p>Simulation: {Math.round(selected.riskReduction)}% risk reduction, {Math.round(selected.complianceImprovement)}% compliance improvement, {Math.round(selected.debtReduction)}% debt reduction.</p>
                    <p>Confidence: {selectedPlan?.confidence ? `${Math.round(selectedPlan.confidence * 100)}%` : "Not scored"} {selectedPlan?.confidence_kind ? `(${selectedPlan.confidence_kind})` : ""}</p>
                  </section>
                  <section className="remediation-section">
                    <h4>Execution boundary</h4>
                    <p>{controlledPatchPlan ? "This generated plan can proceed only through its current server-approved execution snapshot." : "This plan is recommendation-only in the current execution phase."}</p>
                  </section>
                    </>
                  )}
                </>
              ) : <StatePanel title="No plan selected" message="Select a backlog item to generate a governed plan." />}
            </div>
          </aside>
        </div>
      )}

      {selected && (
        <section className="card evidence-pack-card">
          <details>
            <summary>CAB-ready evidence pack</summary>
            <div className="evidence-pack">
              <StructuredData value={evidencePack} />
            </div>
          </details>
        </section>
      )}

      {selected && (
        <div className="remediation-governance-grid">
          <section className="card">
            <div className="card-header">
              <div>
                <h2>Approval decision record</h2>
                <p>Record a bounded human decision against the current server-generated execution preview.</p>
              </div>
              <StatusBadge label={selectedPlan ? "Decision-ready" : "Plan required"} tone="info" />
            </div>
            <div className="card-body remediation-form-grid">
              {selectedPlan ? (
                <>
                  <p className="callout callout-warning">Approval records the current preview hash. It does not itself submit provider work.</p>
                  <label>
                    Decision
                    <select value={decisionChoice} onChange={(event) => setDecisionChoice(event.target.value as RemediationDecision["decision"])}>
                      <option value="approved">Approve recommendation</option>
                      <option value="rejected">Reject recommendation</option>
                      <option value="expired">Expire recommendation</option>
                    </select>
                  </label>
                  <label>
                    Reason
                    <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="Why is this decision appropriate?" />
                  </label>
                  <label>
                    Expires at
                    <input type="date" value={decisionExpiresAt} onChange={(event) => setDecisionExpiresAt(event.target.value)} />
                  </label>
                  <button type="button" className="button" disabled={decisionSubmitting || !decisionReason.trim() || (decisionChoice === "approved" && !decisionExpiresAt)} onClick={recordDecision}>
                    {decisionSubmitting ? "Recording decision..." : "Record decision"}
                  </button>
                  {decisionError && <p className="callout callout-warning">{decisionError}</p>}
                  {decisionResult && <p className="callout">Recorded {decisionResult.decision} decision {decisionResult.decision_id}; server eligibility is being refreshed.</p>}
                </>
              ) : (
                <p className="callout callout-warning">Only generated remediation plans can receive approval decisions. Select a plan row to continue.</p>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Execution preview</h2>
                <p>Business impact, approval evidence, target, and operation must agree before execution is offered.</p>
              </div>
              <StatusBadge
                label={canExecute ? "Eligible" : "Recommendation only"}
                tone={canExecute ? "success" : "warning"}
              />
            </div>
            <div className="card-body remediation-form-grid">
              {executionContextLoading ? (
                <StatePanel title="Loading execution preview" message="Reading current approval, business evidence, and provider target." tone="loading" />
              ) : executionContextError ? (
                <StatePanel title="Execution preview unavailable" message={executionContextError} tone="error" />
              ) : executionPreview && planContext ? (
                <>
                  <section className="remediation-section">
                    <h3>Business-impact evidence</h3>
                    <p>Disposition: {eligibilityReason(businessDecision?.disposition ?? "not_assessed")}</p>
                    <p>Urgency: {businessDecision?.urgency_rationale?.message || "No evidence-backed urgency rationale was returned."}</p>
                    <p>Cost of acting: {renderDetails(businessDecision?.cost_of_action)}</p>
                    <p>Cost of inaction: {renderDetails(businessDecision?.cost_of_inaction)}</p>
                    <p>Business impact: {renderDetails(businessDecision?.business_impact)}</p>
                    <p>Confidence: {renderDetails(businessDecision?.confidence)}</p>
                  </section>
                  <section className="remediation-section">
                    <h3>Exact approved operation</h3>
                    <p>Target: {previewSnapshot?.target_id || renderDetails(executionPreview.target)}</p>
                    <p>Target kind: {previewSnapshot?.target_kind || "Not executable"}</p>
                    <p>ARM operation: <code>{executionPreview.operation}</code></p>
                    <p>Patch selection: {previewSnapshot?.patch_ids.join(", ") || "No approved patch selection"}</p>
                    <p>Preconditions: {renderDetails(executionPreview.preconditions)}</p>
                    <p>Expected effect: {renderDetails(executionPreview.expected_effect)}</p>
                    <p>Collateral impact: {renderDetails(executionPreview.collateral_impact)}</p>
                  </section>
                  {canExecute ? (
                    <>
                      <button
                        type="button"
                        className="button button-primary"
                        disabled={executionSubmitting || Boolean(activeExecution && ["queued", "running", "retrying"].includes(activeExecution.status))}
                        onClick={() => setExecutionConfirmOpen(true)}
                      >
                        Review and execute
                      </button>
                      {executionConfirmOpen && (
                        <div className="callout" role="alertdialog" aria-label="Confirm governed execution">
                          <p>
                            Submit <strong>{previewSnapshot?.operation}</strong> to exactly <code>{previewSnapshot?.target_id}</code>
                            {" "}with patches {previewSnapshot?.patch_ids.join(", ")}. Submission is not success; Azure verification remains authoritative.
                          </p>
                          <button
                            type="button"
                            className="button button-primary"
                            disabled={executionSubmitting}
                            onClick={() => void executePlan()}
                          >
                            {executionSubmitting ? "Submitting…" : "Confirm execution"}
                          </button>
                          <button type="button" className="button button-quiet" disabled={executionSubmitting} onClick={() => setExecutionConfirmOpen(false)}>
                            Keep reviewing
                          </button>
                        </div>
                      )}
                    </>
                  ) : (
                    <p className="callout callout-warning">
                      Recommendation only: <strong>{eligibilityReason(executionBlockReason || "server_did_not_mark_plan_executable")}</strong>.
                    </p>
                  )}
                  {activeExecution && (
                    <section className="remediation-section" aria-label="Execution outcome">
                      <div className="card-header">
                        <div>
                          <h3>Execution {activeExecution.execution_id}</h3>
                          <p>Durable state from the remediation execution service.</p>
                        </div>
                        <StatusBadge
                          label={titleize(activeExecution.status)}
                          tone={activeExecution.status === "succeeded" ? "success" : activeExecution.status === "failed" || activeExecution.status === "cancelled" ? "critical" : "warning"}
                        />
                      </div>
                      <p>Verified actual state: <strong>{activeExecution.verified_state || "Verification pending"}</strong></p>
                      <p>Provider job: <code>{activeExecution.provider_job_id || "Not submitted"}</code></p>
                      <p>Outcome: {activeExecution.outcome || "Pending upstream verification"}</p>
                      <p>Failure details: {activeExecution.failure_details || "No failure reported"}</p>
                      <p>Attempts: {activeExecution.attempt_count} · Remaining retries: {activeExecution.remaining_attempts}</p>
                      <p>Requested by: {activeExecution.requested_by} · Approved by: {activeExecution.approved_by}</p>
                      <p>Created: {activeExecution.created_at} · Updated: {activeExecution.updated_at}</p>
                      {activeExecution.message && <p className="callout">{activeExecution.message}</p>}
                      {activeExecution.ineligibility_reason && (
                        <p className="callout callout-warning">{eligibilityReason(activeExecution.ineligibility_reason)}</p>
                      )}
                      <h4>Rollback guidance</h4>
                      {activeExecution.rollback_guidance.length > 0 ? (
                        <ul>{activeExecution.rollback_guidance.map((guidance) => <li key={guidance}>{guidance}</li>)}</ul>
                      ) : (
                        <p>No automated rollback is available; follow the owning service runbook.</p>
                      )}
                      <h4>Immutable attempts and transitions</h4>
                      {activeExecution.attempts.map((attempt) => (
                        <div key={attempt.attempt_number}>
                          <p><strong>Attempt {attempt.attempt_number}</strong> · {titleize(attempt.status)} · actor {attempt.actor || "Not recorded"}</p>
                          <ol>
                            {attempt.transitions.map((transition, index) => (
                              <li key={`${attempt.attempt_number}-${transition.sequence ?? index}`}>
                                {transition.timestamp || "Timestamp unavailable"} · {titleize(transition.status)} · {transition.actor || "Actor unavailable"}
                                {transition.verified_state ? ` · ${transition.verified_state}` : ""}
                                {transition.failure_details ? ` · ${transition.failure_details}` : ""}
                              </li>
                            ))}
                          </ol>
                        </div>
                      ))}
                      <div className="plan-actions">
                        {activeExecution.retryable && (
                          <button type="button" className="button button-primary" disabled={executionSubmitting} onClick={() => void retryExecution()}>
                            Retry execution
                          </button>
                        )}
                        {activeExecution.cancellable && (
                          <button type="button" className="button button-quiet" disabled={executionSubmitting} onClick={() => void cancelExecution()}>
                            Cancel queued execution
                          </button>
                        )}
                      </div>
                    </section>
                  )}
                  {executionActionError && <p className="callout callout-warning" role="alert">{executionActionError}</p>}
                </>
              ) : (
                <p className="callout callout-warning">Select a generated remediation plan to load its governed execution preview.</p>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
