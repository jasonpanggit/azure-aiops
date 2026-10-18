"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { TopologyWorkspace } from "@/components/network/TopologyWorkspace";
import { InvestigationTeamWorkspacePanel } from "@/components/InvestigationTeamWorkspace";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { CopilotCitations } from "@/components/ui/CopilotCitations";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { PageScopeProvider, useScope } from "@/lib/scope-context";
import { SCOPE_DIMENSIONS, ScopeBookmarkError, scopedBookmark, scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import {
  contextApi,
  toCanonicalInvestigationView,
  networkApi,
  operationsApi,
  vulnerabilityApi,
} from "@/lib/services";
import type { CanonicalInvestigationView } from "@/lib/services";
import {
  buildInvestigationCopilotContext,
  investigateCanonical,
  normalizeCopilotSnapshotV2,
  type CanonicalCopilotResult,
  type CoreCopilotRecord,
  type CoreCopilotSourceStatus,
} from "@/lib/copilot/page-adapters";
import { useOptionalThreadContinuity } from "@/lib/copilot/thread-context";
import type {
  Envelope,
  IncidentDetail,
  IncidentReport,
  NetworkGap,
  NetworkTopology,
  RemediationPlanReport,
  RuleFinding,
  SemanticContext,
  AttackPathGraph,
  CveDetail,
  VulnerabilityExposure,
  VulnerabilitySummary,
  EvidenceItem,
} from "@/lib/types";

type EntryType =
  | "BusinessService"
  | "Application"
  | "Environment"
  | "SubscriptionConnection"
  | "Incident"
  | "CVE"
  | "NetworkGap"
  | "RemediationPlan";
type Mode = "executive" | "engineer";

interface FocusEntity {
  kind: EntryType | "Resource" | "Owner" | "Evidence";
  id: string;
  label: string;
  reason?: string;
}

interface WorkspaceState {
  context?: Envelope<SemanticContext>;
  risk?: Envelope<SemanticContext>;
  impact?: Envelope<SemanticContext>;
  incidents?: Envelope<IncidentReport>;
  incidentDetail?: Envelope<IncidentDetail>;
  topology?: Envelope<{ topology: NetworkTopology; summary: unknown }>;
  gaps?: Envelope<{ gaps: NetworkGap[]; intended_design_declared?: boolean; summary?: unknown }>;
  ruleFindings?: Envelope<{ findings: RuleFinding[]; summary?: unknown }>;
  vulnerabilities?: Envelope<VulnerabilitySummary>;
  exposures?: Envelope<VulnerabilityExposure[]>;
  remediation?: Envelope<RemediationPlanReport>;
  copilot?: Envelope<CanonicalCopilotResult>;
  copilotView?: CanonicalInvestigationView;
  cveDetail?: Envelope<CveDetail>;
  attackPath?: Envelope<AttackPathGraph>;
  errors: string[];
}

interface SavedInvestigation {
  id: string;
  title: string;
  entryType: EntryType;
  entryValue: string;
  mode: Mode;
  selected?: FocusEntity | null;
  savedAt: string;
  audit: Array<{ at: string; action: string }>;
}

const ENTRY_TYPES: EntryType[] = [
  "BusinessService",
  "Application",
  "Environment",
  "SubscriptionConnection",
  "Incident",
  "CVE",
  "NetworkGap",
  "RemediationPlan",
];

const STORAGE_KEY = "aiops.investigations.v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function labelOf(value: unknown, fallback = "Unmapped"): string {
  if (typeof value === "string" && value) return value;
  if (isRecord(value)) {
    return String(value.name ?? value.title ?? value.id ?? value.resource_id ?? fallback);
  }
  return fallback;
}

function riskScore(risk?: Envelope<SemanticContext>, vulnerabilities?: Envelope<VulnerabilitySummary>): number | null {
  const value = (risk?.data as unknown as Record<string, unknown> | undefined)?.risk;
  if (isRecord(value) && typeof value.score === "number") return value.score;
  const critical = vulnerabilities?.data.critical_count ?? 0;
  const exposed = vulnerabilities?.data.internet_exposed_count ?? 0;
  if (critical || exposed) return Math.min(100, critical * 20 + exposed * 15);
  return null;
}

function ownerFrom(context?: Envelope<SemanticContext>, incident?: Envelope<IncidentDetail>): string {
  const subject = context?.data.subject;
  if (subject?.owner) return subject.owner;
  const owners = asList(context?.data.sections?.ownership);
  if (owners[0]) return labelOf(owners[0]);
  const incidentOwners = incident?.data.finding.business_impact?.owners ?? [];
  return incidentOwners[0] ?? "Accountable owner not mapped";
}

function decisionFrom(state: WorkspaceState): string {
  const plan = state.remediation?.data.plans?.[0];
  if (plan) return `Approve or defer: ${String(plan.title ?? plan.plan_id ?? "recommended action")}`;
  const exposure = state.exposures?.data?.[0];
  if (exposure) return `Prioritize patch ${exposure.recommended_patch || exposure.missing_kb}`;
  const incident = state.incidentDetail?.data.finding.recommended_action;
  if (incident?.suggested_action) return incident.suggested_action;
  return "Decide whether to mitigate now, assign owner, or accept risk with evidence.";
}

function loadSaved(): SavedInvestigation[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistSaved(items: SavedInvestigation[]) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, 20)));
}

function modeDescription(mode: Mode): string {
  return mode === "executive"
    ? "Business impact, accountable owner, trend, risk drivers, and required decision."
    : "Resource IDs, paths, rules, CVEs, timestamps, raw evidence references, and diagnostic detail.";
}

function sourceFreshness(
  freshness: EvidenceItem["freshness"],
): CoreCopilotSourceStatus["status"] {
  if (freshness === "fresh") return "fresh";
  if (freshness === "stale") return "stale";
  if (freshness === "aging") return "partial";
  return "unavailable";
}

function investigationSourceStatus(
  source: string,
  envelope?: {
    evidence?: EvidenceItem[];
    live_observed_at?: string;
    source_status?: Record<string, string>;
  },
): CoreCopilotSourceStatus {
  if (!envelope) {
    return { source, observedAt: "unknown", status: "unavailable" };
  }
  const evidence = envelope.evidence ?? [];
  const statuses = evidence.map((item) => sourceFreshness(item.freshness));
  const status = statuses.includes("stale")
    ? "stale"
    : statuses.includes("partial")
      ? "partial"
      : statuses.length > 0 && statuses.every((item) => item === "fresh")
        ? "fresh"
        : Object.values(envelope.source_status ?? {}).some(
            (item) => item === "unavailable" || item === "deferred",
          )
          ? "unavailable"
          : "partial";
  const observedAt = evidence.reduce(
    (latest, item) => item.timestamp > latest ? item.timestamp : latest,
    envelope.live_observed_at ?? "",
  );
  return { source, observedAt: observedAt || "unknown", status };
}

/** Prerender-safe query-context boundary around the investigation workspace. */
export default function InvestigationWorkspacePage() {
  return (
    <Suspense fallback={<div className="page-container"><div className="state-panel state-loading">Preparing investigation workspace…</div></div>}>
      <InvestigationWorkspaceContent />
    </Suspense>
  );
}

function InvestigationWorkspaceContent() {
  const query = useSearchParams().toString();
  const { scope } = useScope();
  const threadContinuity = useOptionalThreadContinuity();
  const bookmark = useMemo<{ error: string } | {
    scope: ScopeSelection; entryType: EntryType; entryValue: string; mode: Mode;
    workspaceId: string; workspaceRevision: number | undefined;
  }>(() => {
    try {
      const params = new URLSearchParams(query);
      const restoredScope = scopedBookmark(params, scope);
      if (["type", "value", "mode", "workspace_id", "workspace_revision"].some(key => params.getAll(key).length > 1)) {
        throw new ScopeBookmarkError("Investigation entry parameters must not be repeated.");
      }
      const type = params.get("type") ?? "BusinessService";
      const entryType = ENTRY_TYPES.find(candidate => candidate === type);
      const mode = params.get("mode") ?? "executive";
      const entryValue = params.get("value") ?? "";
      if (!entryType || (mode !== "executive" && mode !== "engineer")) {
        throw new ScopeBookmarkError("The investigation entry type or mode is unsupported.");
      }
      if (entryValue.length > 512 || /[\0\r\n]/.test(entryValue)) {
        throw new ScopeBookmarkError("The investigation subject must be at most 512 characters without line breaks.");
      }
      const workspaceId = params.get("workspace_id") ?? "";
      const rawRevision = params.get("workspace_revision");
      if ((params.has("workspace_id") && !/^wrk-[0-9a-f]{32}$/.test(workspaceId))
        || (rawRevision !== null && (!workspaceId || !/^(?:[1-9]|[1-3][0-9]|40)$/.test(rawRevision)))) {
        throw new ScopeBookmarkError("The workspace identity or revision is invalid. Reopen a complete workspace revision link.");
      }
      return {
        scope: restoredScope, entryType, entryValue, mode, workspaceId,
        workspaceRevision: rawRevision === null ? undefined : Number(rawRevision),
      };
    } catch (error) {
      if (!(error instanceof ScopeBookmarkError)) throw error;
      return { error: error.message };
    }
  }, [query, scope]);
  if ("error" in bookmark) {
    return <div className="page-container"><StatePanel title="Investigation bookmark unavailable" message={bookmark.error} tone="error" action={<Link href="/investigate" className="button button-secondary">Start a new investigation</Link>} /></div>;
  }
  const shareRootContinuity = SCOPE_DIMENSIONS.every(dimension => {
    const original = new Set((scope[dimension] ?? []).map(value => value.trim().toLowerCase()));
    const effective = new Set((bookmark.scope[dimension] ?? []).map(value => value.trim().toLowerCase()));
    return original.size === effective.size && Array.from(effective).every(value => original.has(value));
  });
  return (
    <PageScopeProvider scope={bookmark.scope}>
      <InvestigationWorkspace
        key={JSON.stringify([bookmark, threadContinuity?.generation])}
        scope={bookmark.scope}
        initialEntryType={bookmark.entryType}
        initialEntryValue={bookmark.entryValue}
        initialMode={bookmark.mode}
        initialWorkspaceId={bookmark.workspaceId}
        initialWorkspaceRevision={bookmark.workspaceRevision}
        shareRootContinuity={shareRootContinuity}
      />
    </PageScopeProvider>
  );
}

function InvestigationWorkspace({ scope, initialEntryType, initialEntryValue, initialMode, shareRootContinuity, initialWorkspaceId, initialWorkspaceRevision }: {
  scope: ScopeSelection;
  initialEntryType: EntryType;
  initialEntryValue: string;
  initialMode: Mode;
  shareRootContinuity: boolean;
  initialWorkspaceId: string;
  initialWorkspaceRevision?: number;
}) {
  const rootContinuity = useOptionalThreadContinuity();
  const threadContinuity = shareRootContinuity ? rootContinuity : null;
  const [entryType, setEntryType] = useState<EntryType>(initialEntryType);
  const [entryValue, setEntryValue] = useState(initialEntryValue);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [selected, setSelected] = useState<FocusEntity | null>(null);
  const [state, setState] = useState<WorkspaceState>({ errors: [] });
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState<SavedInvestigation[]>([]);
  const [audit, setAudit] = useState<Array<{ at: string; action: string }>>([]);
  const [entryLink, setEntryLink] = useState<{ href: string; message: string } | null>(null);
  const [refreshSequence, setRefreshSequence] = useState(0);
  const generation = useRef(0);

  const subject = entryValue.trim();

  useEffect(() => {
    setSaved(loadSaved());
  }, []);

  const pushAudit = (action: string) =>
    setAudit((items) => [{ at: new Date().toISOString(), action }, ...items].slice(0, 12));

  useEffect(() => {
    let active = true;
    generation.current += 1;
    setState({ errors: [] });
    setSelected(null);
    setEntryLink(null);
    setLoading(true);
    const loaders: Array<Promise<unknown>> = [
      operationsApi.incidents(scope, 0, 25),
      networkApi.topology(scope),
      networkApi.gaps(scope),
      networkApi.ruleFindings(scope),
      vulnerabilityApi.summary(scope),
      vulnerabilityApi.exposures(scope),
      operationsApi.remediationPlans(scope, 0, 25),
    ];

    const labels = ["incidents", "topology", "gaps", "ruleFindings", "vulnerabilities", "exposures", "remediation"];
    if (subject) {
      if (entryType === "BusinessService") {
        loaders.push(contextApi.businessService(subject, scope), contextApi.risk(subject, scope), contextApi.impact(subject, scope));
        labels.push("context", "risk", "impact");
      } else if (entryType === "Application") {
        loaders.push(contextApi.application(subject, scope), contextApi.risk(subject, scope), contextApi.impact(subject, scope));
        labels.push("context", "risk", "impact");
      } else if (entryType === "Environment") {
        loaders.push(contextApi.environment(subject, scope), contextApi.risk(subject, scope), contextApi.impact(subject, scope));
        labels.push("context", "risk", "impact");
      } else if (entryType === "SubscriptionConnection") {
        loaders.push(contextApi.subscriptionConnectionContext(subject, scope), contextApi.risk(subject, scope), contextApi.impact(subject, scope));
        labels.push("context", "risk", "impact");
      } else if (entryType === "Incident") {
        loaders.push(operationsApi.incident(subject, scope));
        labels.push("incidentDetail");
      } else if (entryType === "CVE") {
        loaders.push(vulnerabilityApi.cve(subject, scope), vulnerabilityApi.attackPath(subject, scope));
        labels.push("cveDetail", "attackPath");
      }
    }

    Promise.allSettled(loaders).then((results) => {
      if (!active) return;
      const next: WorkspaceState = { errors: [] };
      results.forEach((result, index) => {
        const label = labels[index];
        if (result.status === "rejected") {
          next.errors.push(`${label} unavailable`);
          return;
        }
        if (label === "incidents") next.incidents = result.value as Envelope<IncidentReport>;
        if (label === "topology") next.topology = result.value as Envelope<{ topology: NetworkTopology; summary: unknown }>;
        if (label === "gaps") next.gaps = result.value as Envelope<{ gaps: NetworkGap[]; intended_design_declared?: boolean; summary?: unknown }>;
        if (label === "ruleFindings") next.ruleFindings = result.value as Envelope<{ findings: RuleFinding[]; summary?: unknown }>;
        if (label === "vulnerabilities") next.vulnerabilities = result.value as Envelope<VulnerabilitySummary>;
        if (label === "exposures") next.exposures = result.value as Envelope<VulnerabilityExposure[]>;
        if (label === "remediation") next.remediation = result.value as Envelope<RemediationPlanReport>;
        if (label === "context") next.context = result.value as Envelope<SemanticContext>;
        if (label === "risk") next.risk = result.value as Envelope<SemanticContext>;
        if (label === "impact") next.impact = result.value as Envelope<SemanticContext>;
        if (label === "incidentDetail") next.incidentDetail = result.value as Envelope<IncidentDetail>;
        if (label === "cveDetail") next.cveDetail = result.value as Envelope<CveDetail>;
        if (label === "attackPath") next.attackPath = result.value as Envelope<AttackPathGraph>;
      });
      setState(next);
      setLoading(false);
      pushAudit(subject ? `Loaded ${entryType}: ${subject}` : "Loaded workspace overview");
    });
    return () => {
      active = false;
      generation.current += 1;
    };
  }, [entryType, subject, scope, refreshSequence]);

  const score = riskScore(state.risk, state.vulnerabilities);
  const owner = ownerFrom(state.context, state.incidentDetail);
  const decision = decisionFrom(state);
  const topExposure = state.exposures?.data?.[0];
  const activeIncidents = state.incidents?.data.incidents ?? [];
  const signalsAvailable = Boolean(state.incidents && state.exposures);
  const hasSignals = activeIncidents.length > 0 || (state.exposures?.data.length ?? 0) > 0;
  const cveDetail = state.cveDetail;
  const owners = Array.from(
    new Set([
      owner,
      ...(state.incidentDetail?.data.finding.business_impact?.owners ?? []),
      ...activeIncidents.flatMap((item) => item.business_impact.owners ?? []),
    ].filter(Boolean))
  );
  const evidence = [
    ...(state.context?.evidence ?? []),
    ...(state.risk?.evidence ?? []),
    ...(state.impact?.evidence ?? []),
    ...(state.incidents?.evidence ?? []),
    ...(state.vulnerabilities?.evidence ?? []),
    ...(state.topology?.evidence ?? []),
    ...(state.gaps?.evidence ?? []),
    ...(state.ruleFindings?.evidence ?? []),
    ...(state.exposures?.evidence ?? []),
    ...(state.remediation?.evidence ?? []),
    ...(state.cveDetail?.evidence ?? []),
    ...(state.attackPath?.evidence ?? []),
  ];
  const fullTimeline = [
    ...(state.incidentDetail?.data.finding.timeline ?? []),
    ...activeIncidents.flatMap((item) => item.timeline ?? []),
  ]
    .slice()
    .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp));
  const timeline = fullTimeline.slice(0, 8);

  const setFocus = (entity: FocusEntity) => {
    setSelected(entity);
    pushAudit(`Focused ${entity.kind}: ${entity.label}`);
  };

  const runCopilot = async () => {
    if (loading) return;
    const requestGeneration = generation.current;
    const continuityGeneration = threadContinuity?.generation;
    const focusPrompt = selected ? ` Current focus is ${selected.kind} ${selected.label}: ${selected.reason ?? selected.id}.` : "";
    const question = `Summarize the investigation for ${entryType} ${subject || "current scope"}; explain business risk, affected dependencies, evidence, and recommended decision.${focusPrompt}`;
    const visibleIncidents = activeIncidents.slice(0, 25);
    const visibleGaps = (state.gaps?.data.gaps ?? []).slice(0, 50);
    const visibleRuleFindings = (state.ruleFindings?.data.findings ?? []).slice(0, 50);
    const visibleExposures = (state.exposures?.data ?? []).slice(0, 8);
    const visiblePlans = (state.remediation?.data.plans ?? []).slice(0, 6);
    const incidentTotal = Math.max(
      activeIncidents.length,
      state.incidents?.pagination?.total ?? 0,
    );
    const gapTotal = Math.max(
      state.gaps?.data.gaps.length ?? 0,
      state.gaps?.pagination?.total ?? 0,
    );
    const ruleFindingTotal = Math.max(
      state.ruleFindings?.data.findings.length ?? 0,
      state.ruleFindings?.pagination?.total ?? 0,
    );
    const exposureTotal = Math.max(
      state.exposures?.data?.length ?? 0,
      state.exposures?.pagination?.total ?? 0,
    );
    const remediationTotal = Math.max(
      state.remediation?.data.plans?.length ?? 0,
      state.remediation?.pagination?.total ?? 0,
    );
    const sourceStatuses: CoreCopilotSourceStatus[] = [
      investigationSourceStatus("investigate/incidents", state.incidents),
      investigationSourceStatus("investigate/timeline", state.incidentDetail ?? state.incidents),
      investigationSourceStatus("investigate/network", state.gaps),
      investigationSourceStatus("investigate/network-rules", state.ruleFindings),
      investigationSourceStatus("investigate/vulnerabilities", state.exposures),
      investigationSourceStatus("investigate/remediation", state.remediation),
      investigationSourceStatus("investigate/topology", state.topology),
    ];
    const summaryStatus = sourceStatuses.some((item) => item.status === "stale")
      ? "stale"
      : sourceStatuses.some((item) => item.status !== "fresh")
        ? "partial"
        : "fresh";
    sourceStatuses.unshift({
      source: "investigate/summary",
      observedAt: sourceStatuses.reduce(
        (latest, item) => (item.observedAt ?? "") > latest
          ? item.observedAt ?? ""
          : latest,
        "",
      ) || "unknown",
      status: summaryStatus,
    });
    const records: CoreCopilotRecord[] = [
      {
        identity: `summary:${entryType}:${subject || "current-scope"}`,
        namespace: "operations",
        kind: "investigation_summary",
        source: "investigate/summary",
        evidenceIdentity: "observation",
        selected: true,
        priority: 0,
        data: {
          entry_type: entryType,
          subject: subject || "current scope",
          mode,
          risk_score: score,
          owner,
          recommended_decision: decision,
          incident_count: activeIncidents.length,
          vulnerability_count: state.exposures?.data?.length ?? 0,
          network_gap_count: state.gaps?.data.gaps.length ?? 0,
          remediation_plan_count: state.remediation?.data.plans?.length ?? 0,
          mutation_authorized: false,
        },
      },
      ...visibleIncidents.map((item, index) => ({
        identity: item.incident.incident_id,
        namespace: "operations",
        kind: "incident",
        source: "investigate/incidents",
        evidenceIdentity: "observation" as const,
        observedAt: item.incident.started_at,
        priority: 10 + index,
        data: {
          title: item.incident.title,
          severity: item.incident.severity,
          status: item.incident.status,
          owner: item.business_impact.owners?.[0],
          business_services: item.business_impact.business_services,
        },
      })),
      ...timeline.map((event, index) => ({
        identity: `${event.event_id}:${event.timestamp}:${event.source}`,
        namespace: "operations",
        kind: "timeline_event",
        source: "investigate/timeline",
        evidenceIdentity: "observation" as const,
        observedAt: event.timestamp,
        priority: 40 + index,
        data: {
          event_type: event.event_type,
          summary: event.summary,
          source: event.source,
        },
      })),
      ...visibleGaps.map((gap, index) => ({
        identity: gap.gap_id,
        namespace: "operations",
        kind: "network_gap",
        source: "investigate/network",
        evidenceIdentity: "observation" as const,
        priority: 60 + index,
        data: {
          title: gap.title,
          severity: gap.severity,
          category: gap.category,
        },
      })),
      ...visibleRuleFindings.map((finding, index) => ({
        identity: String(finding.rule_id ?? finding.finding_id ?? index),
        namespace: "operations",
        kind: "network_rule_finding",
        source: "investigate/network-rules",
        evidenceIdentity: "observation" as const,
        priority: 100 + index,
        data: {
          title: finding.title,
          severity: finding.severity,
          rule_name: finding.rule_name,
          control: finding.control,
          affected_resource_count: finding.affected_resource_ids?.length ?? 0,
        },
      })),
      ...visibleExposures.map((exposure, index) => ({
        identity: exposure.cve_id,
        namespace: "operations",
        kind: "vulnerability_exposure",
        source: "investigate/vulnerabilities",
        evidenceIdentity: "observation" as const,
        priority: 120 + index,
        data: {
          cve_id: exposure.cve_id,
          severity: exposure.severity,
          affected_server_count: exposure.affected_server_count,
          affected_business_service_count: exposure.affected_business_service_count,
          reachable_server_count: exposure.reachable_server_count,
          recommended_patch: exposure.recommended_patch,
        },
      })),
      ...visiblePlans.map((plan, index) => ({
        identity: plan.plan_id,
        namespace: "operations",
        kind: "remediation_plan",
        source: "investigate/remediation",
        evidenceIdentity: "observation" as const,
        priority: 150 + index,
        data: {
          title: plan.title,
          status: plan.status,
          risk_reduction_percent: plan.simulation_result?.risk_reduction_percent,
        },
      })),
      {
        identity: "topology-summary",
        namespace: "operations",
        kind: "network_summary",
        source: "investigate/topology",
        evidenceIdentity: "observation",
        priority: 180,
        data: {
          hub_count: state.topology?.data.topology.hubs.length ?? 0,
          spoke_count: state.topology?.data.topology.spokes.length ?? 0,
          link_count: state.topology?.data.topology.links.length ?? 0,
        },
      },
    ];
    const pageContext = buildInvestigationCopilotContext({
      scope,
      filters: {
        entry_type: [entryType],
        mode: [mode],
        subject: subject ? [subject] : [],
      },
      records,
      evidence,
      coverage: [
        {
          key: "incidents",
          visibleCount: visibleIncidents.length,
          totalCount: Math.max(
            visibleIncidents.length,
            incidentTotal,
          ),
          truncated: visibleIncidents.length < incidentTotal,
          available: Boolean(state.incidents),
        },
        {
          key: "timeline",
          visibleCount: timeline.length,
          totalCount: fullTimeline.length,
          truncated: timeline.length < fullTimeline.length,
          available: Boolean(state.incidents || state.incidentDetail),
        },
        {
          key: "network_gaps",
          visibleCount: visibleGaps.length,
          totalCount: gapTotal,
          truncated: visibleGaps.length < gapTotal,
          available: Boolean(state.gaps),
        },
        {
          key: "network_rules",
          visibleCount: visibleRuleFindings.length,
          totalCount: ruleFindingTotal,
          truncated: visibleRuleFindings.length < ruleFindingTotal,
          available: Boolean(state.ruleFindings),
        },
        {
          key: "vulnerabilities",
          visibleCount: visibleExposures.length,
          totalCount: exposureTotal,
          truncated: visibleExposures.length < exposureTotal,
          available: Boolean(state.exposures),
        },
        {
          key: "remediation",
          visibleCount: visiblePlans.length,
          totalCount: remediationTotal,
          truncated: visiblePlans.length < remediationTotal,
          available: Boolean(state.remediation),
        },
        {
          key: "topology",
          visibleCount: state.topology ? 1 : 0,
          totalCount: state.topology ? 1 : 0,
          available: Boolean(state.topology),
        },
        {
          key: "citations",
          visibleCount: evidence.length,
          totalCount: evidence.length,
          available: true,
        },
      ],
      sourceStatuses,
    });
    const snapshot = normalizeCopilotSnapshotV2(pageContext.snapshot);
    setLoading(true);
    try {
      const result = await investigateCanonical(
        {
          contract_version: "1",
          question,
          requested_scope: scope,
          snapshot,
          ...(threadContinuity?.thread
            ? {
                thread_id: threadContinuity.thread.threadId,
                expected_thread_revision: threadContinuity.thread.threadRevision,
              }
            : {}),
        },
        scope,
      );
      if (requestGeneration !== generation.current) return;
      const view = toCanonicalInvestigationView(result.data);
      if (threadContinuity?.thread && (
        view.threadId !== threadContinuity.thread.threadId
        || view.threadRevision !== threadContinuity.thread.threadRevision + 1
      )) {
        throw new Error("The investigation response did not match the requested conversation revision.");
      }
      // Mirror the server-issued thread into the shared root continuity so every
      // dedicated surface reflects one authorized handle (best-effort; the
      // provider is absent in isolated renders).
      if (view.threadId && view.threadRevision) {
        threadContinuity?.acceptServerState({ threadId: view.threadId, threadRevision: view.threadRevision }, continuityGeneration);
      }
      setState((current) => ({ ...current, copilot: result, copilotView: view }));
      pushAudit("Generated Copilot conclusion");
    } catch {
      if (requestGeneration !== generation.current) return;
      setState((current) => ({ ...current, errors: [...current.errors, "copilot unavailable"] }));
    } finally {
      if (requestGeneration === generation.current) setLoading(false);
    }
  };

  const saveInvestigation = () => {
    const item: SavedInvestigation = {
      id: `inv-${Date.now()}`,
      title: `${entryType}: ${subject || "Current scope"}`,
      entryType,
      entryValue: subject,
      mode,
      selected,
      savedAt: new Date().toISOString(),
      audit,
    };
    const next = [item, ...saved.filter((existing) => existing.title !== item.title)];
    persistSaved(next);
    setSaved(next);
    pushAudit("Saved investigation state");
  };

  const reopen = (item: SavedInvestigation) => {
    setEntryType(item.entryType);
    setEntryValue(item.entryValue);
    setMode(item.mode);
    setSelected(item.selected ?? null);
    setAudit(item.audit);
  };

  const share = async () => {
    const requestGeneration = generation.current;
    const query = scopeToSearchParams(scope);
    query.set("type", entryType);
    query.set("value", subject);
    query.set("mode", mode);
    const href = `/investigate?${query.toString()}`;
    setEntryLink({ href, message: "Entry link ready. This does not share a team workspace or change membership." });
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(`${window.location.origin}${href}`);
      if (requestGeneration === generation.current) pushAudit("Copied current entry link");
    } catch {
      if (requestGeneration === generation.current) {
        setEntryLink({ href, message: "Clipboard copy unavailable. Open or copy the entry link below; team workspace membership is unchanged." });
      }
    }
  };

  const exportInvestigation = () => {
    const blob = new Blob([JSON.stringify({ scope, entryType, entryValue: subject, mode, selected, audit, state }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `investigation-${entryType}-${subject || "scope"}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    pushAudit("Exported investigation JSON");
  };

  return (
    <div className={`page-container investigation-workspace investigation-mode-${mode}`}>
      <PageHeader
        title={subject ? `${entryType}: ${subject}` : "Investigate business risk end to end"}
        description="One surface for business risk, dependencies, network paths, vulnerabilities, changes, incidents, evidence, Copilot reasoning, owners, and recommended actions."
        actions={
          <>
            <button className="button button-secondary" type="button" onClick={saveInvestigation}>Save view locally</button>
            <button className="button button-secondary" type="button" onClick={share}>Copy current entry link</button>
            <button className="button button-secondary" type="button" onClick={exportInvestigation}>Export</button>
            <button className="button button-primary" type="button" onClick={runCopilot} disabled={loading}>Generate conclusion</button>
          </>
        }
        metadata={
          <>
            <StatusBadge label={mode === "executive" ? "Executive mode" : "Engineer mode"} tone="info" />
            <span>{modeDescription(mode)}</span>
          </>
        }
      />

      {entryLink && <p role="status">{entryLink.message} <Link href={entryLink.href}>Open current entry link</Link></p>}

      <section className="investigation-entry card" aria-label="Investigation entry">
        <label>
          Entry point
          <select value={entryType} onChange={(event) => setEntryType(event.target.value as EntryType)}>
            {ENTRY_TYPES.map((type) => <option key={type}>{type}</option>)}
          </select>
        </label>
        <label>
          Subject
          <input value={entryValue} maxLength={512} onChange={(event) => setEntryValue(event.target.value)} placeholder="Service, app, incident, CVE, gap, or plan id" />
        </label>
        <div className="segmented-control" role="group" aria-label="Workspace mode">
          <button type="button" className={mode === "executive" ? "active" : ""} onClick={() => setMode("executive")}>Executive</button>
          <button type="button" className={mode === "engineer" ? "active" : ""} onClick={() => setMode("engineer")}>Engineer</button>
        </div>
      </section>

      <InvestigationTeamWorkspacePanel
        scope={scope}
        initialId={initialWorkspaceId}
        initialRevision={initialWorkspaceRevision}
        view={{ title: `${entryType}: ${subject || "Current scope"}`, entry_type: entryType, subject, mode }}
        onRestore={view => {
          setEntryType(view.entry_type);
          setEntryValue(view.subject);
          setMode(view.mode);
          setSelected(null);
          setRefreshSequence(sequence => sequence + 1);
          pushAudit("Applied team workspace navigation; reacquiring current evidence");
        }}
      />

      <EvidenceBar
        evidence={evidence}
        knowledgeVersion={state.context?.knowledge_version ?? state.incidents?.knowledge_version}
        graphFreshness={state.context?.graph_freshness ?? state.context?.data.graph_freshness}
        liveObservedAt={state.context?.live_observed_at ?? state.context?.data.live_observed_at}
        sourceStatus={state.context?.source_status ?? state.context?.data.source_status}
        warnings={[...state.errors, ...(state.context?.warnings ?? []), ...(state.risk?.warnings ?? [])]}
      />

      {loading && <StatePanel title="Synchronizing investigation context" message="Updating summary, topology, evidence, Copilot context, and actions." tone="loading" />}

      <div className="predeploy-summary">
        <section className="card">
          <div className="card-header">
            <h2>Business risk</h2>
          </div>
          <div className="card-body risk-gauge-body">
            {score === null ? (
              <p className="muted">Unknown — insufficient signal to compute a score.</p>
            ) : (
              <RiskGauge
                score={score}
                detail={topExposure ? `${topExposure.cve_id} is the top risk driver` : "Aggregated from live risk drivers"}
              />
            )}
          </div>
        </section>
        <section className="metric-grid investigation-summary-grid">
          <MetricCard label="Accountable owner" value={owner} detail={selected ? `Focused on ${selected.label}` : "Mapped from semantic ownership and incident impact"} size="text" />
          <MetricCard
            label="Current signals"
            value={signalsAvailable ? (hasSignals ? "Present" : "None reported") : null}
            detail={signalsAvailable
              ? `${activeIncidents.length} situations, ${state.exposures?.data.length ?? 0} CVE summaries in the loaded subset; not a historical trend`
              : "Incident or exposure evidence unavailable; no activity conclusion is available"}
            tone={signalsAvailable && hasSignals ? "warning" : "default"}
          />
          <MetricCard label="Required decision" value={decision} detail="Advisory only; operator approval remains required" tone="warning" size="text" />
        </section>
      </div>

      <div className="investigation-layout">
        <section className="card investigation-panel investigation-panel-wide">
          <div className="card-header">
            <h2>Business impact and dependency context</h2>
            <span>{selected ? `Focused: ${selected.label}` : "Synchronized overview"}</span>
          </div>
          <div className="card-body">
            {mode === "executive" ? (
              <div className="executive-brief">
                <p><strong>Why it matters:</strong> {decision}</p>
                <p><strong>Who owns it:</strong> {owner}</p>
                <p><strong>Risk drivers:</strong> {topExposure ? `${topExposure.cve_id}, ${topExposure.severity}, ${topExposure.affected_business_service_count} affected services` : "No dominant vulnerability driver reported."}</p>
                <p><strong>What is affected:</strong> {state.impact ? "Dependency impact is available in the graph context." : `${activeIncidents.length} active situations in scope.`}</p>
              </div>
            ) : (
              <StructuredData value={{ context: state.context?.data, risk: state.risk?.data, impact: state.impact?.data }} />
            )}
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Timeline</h2><span>{timeline.length} events</span></div>
          <div className="card-body investigation-timeline">
            {timeline.length === 0 ? <span className="muted">No timeline events in scope.</span> : timeline.map((event, index) => (
              <button key={`${event.event_id}:${event.timestamp}:${event.source}:${index}`} type="button" className="timeline-row" onClick={() => setFocus({ kind: "Evidence", id: event.event_id, label: event.event_type, reason: event.summary })}>
                <strong>{event.event_type}</strong>
                <span>{event.timestamp}</span>
                <p>{event.summary || event.event_id}</p>
              </button>
            ))}
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Vulnerabilities</h2><span>{state.exposures?.data?.length ?? 0} exposures</span></div>
          <div className="card-body investigation-list">
            {cveDetail ? (
              <button type="button" onClick={() => setFocus({ kind: "CVE", id: cveDetail.data.cve.cve_id, label: cveDetail.data.cve.title, reason: cveDetail.data.recommended_patch })}>
                <strong>{cveDetail.data.cve.title}</strong>
                <span>{cveDetail.data.cve.severity} - {cveDetail.data.affected_servers.length} affected servers</span>
              </button>
            ) : null}
            {(state.exposures?.data ?? []).slice(0, 8).map((exposure) => (
              <button key={exposure.cve_id} type="button" onClick={() => setFocus({ kind: "CVE", id: exposure.cve_id, label: exposure.cve_id, reason: exposure.recommended_patch })}>
                <strong>{exposure.cve_id}</strong>
                <span>{exposure.severity} · score {Math.round(exposure.priority_score)}</span>
              </button>
            ))}
            {(state.exposures?.data?.length ?? 0) === 0 && <span className="muted">No vulnerability exposure in scope.</span>}
          </div>
        </section>

        <section className="card investigation-panel investigation-panel-wide">
          <div className="card-header"><h2>Network topology and paths</h2><span>{state.gaps?.data.gaps.length ?? 0} gaps · {state.attackPath?.data.reachable_server_count ?? 0} reachable CVE paths</span></div>
          <div className="card-body">
            <TopologyWorkspace
              topology={state.topology?.data.topology ?? null}
              loading={false}
              error={state.topology ? null : state.errors.includes("topology unavailable") ? new Error("Topology unavailable") : null}
              gaps={state.gaps?.data.gaps ?? []}
              ruleFindings={state.ruleFindings?.data.findings ?? []}
            />
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Evidence</h2><span>{evidence.length} citations</span></div>
          <div className="card-body investigation-list">
            {evidence.map((item, index) => (
              <button key={`${item.source_engine}-${index}`} type="button" onClick={() => setFocus({ kind: "Evidence", id: item.source_table, label: item.source_engine, reason: item.timestamp })}>
                <strong>{item.source_table}</strong>
                <span>{item.source_engine}</span>
              </button>
            ))}
            {mode === "engineer" && <StructuredData value={evidence} />}
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Owners</h2><span>{owners.length} accountable parties</span></div>
          <div className="card-body investigation-list">
            {owners.map((item) => (
              <button key={item} type="button" onClick={() => setFocus({ kind: "Owner", id: item, label: item, reason: "Accountable owner or support team" })}>
                <strong>{item}</strong>
                <span>{item === owner ? "Primary accountable owner" : "Related incident owner"}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Recommended actions</h2><span>{state.remediation?.data.plans?.length ?? 0} candidates</span></div>
          <div className="card-body investigation-list">
            {(state.remediation?.data.plans ?? []).slice(0, 6).map((plan) => (
              <button key={plan.plan_id} type="button" onClick={() => setFocus({ kind: "RemediationPlan", id: plan.plan_id, label: String(plan.title ?? plan.plan_id), reason: String(plan.status ?? "") })}>
                <strong>{String(plan.title ?? plan.plan_id)}</strong>
                <span>{String(plan.status ?? plan.simulation_result?.risk_reduction_percent ?? "advisory")}</span>
              </button>
            ))}
            {(state.remediation?.data.plans?.length ?? 0) === 0 && <span className="muted">No remediation candidate in scope.</span>}
          </div>
        </section>

        <section className="card investigation-panel investigation-panel-wide">
          <div className="card-header">
            <h2>Copilot conclusion</h2>
            <button className="button button-secondary" type="button" onClick={runCopilot}>Refresh conclusion</button>
          </div>
          <div className="card-body">
            {state.copilotView?.narration?.text ? (
              <p className="copilot-conclusion">{state.copilotView.narration.text}</p>
            ) : (
              <StatePanel
                title="No Copilot conclusion yet"
                message={
                  state.copilotView
                    ? "The canonical service returned no synthesized narration; review the cited specialist evidence below."
                    : "Generate a conclusion after the investigation context loads."
                }
              />
            )}
            {state.copilotView?.degraded && state.copilotView.degradationNote ? (
              <p className="copilot-fallback-note" role="alert" aria-label="Investigation degradation">
                {state.copilotView.degradationNote}
              </p>
            ) : null}
            {state.copilotView?.uncertainty.length ? (
              <div className="copilot-uncertainty" aria-label="Investigation uncertainty">
                <StatusBadge label="Uncertainty" tone="warning" compact />
                <ul>
                  {state.copilotView.uncertainty.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>
            ) : null}
            <CopilotCitations
              key={`${state.copilotView?.threadId ?? "no-thread"}:${state.copilotView?.threadRevision ?? 0}`}
              citations={state.copilotView?.citations ?? []}
              ariaLabel="Investigation citations"
            />
            {mode === "engineer" && state.copilotView?.toolCalls.length ? <StructuredData value={state.copilotView.toolCalls} /> : null}
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Saved investigations</h2><span>{saved.length} saved</span></div>
          <div className="card-body investigation-list">
            {saved.map((item) => (
              <button key={item.id} type="button" onClick={() => reopen(item)}>
                <strong>{item.title}</strong>
                <span>{item.savedAt}</span>
              </button>
            ))}
            {saved.length === 0 && <span className="muted">No saved investigations yet.</span>}
          </div>
        </section>

        <section className="card investigation-panel">
          <div className="card-header"><h2>Audit trail</h2><span>{audit.length} events</span></div>
          <div className="card-body investigation-list">
            {audit.map((item) => (
              <div key={`${item.at}-${item.action}`} className="audit-row">
                <strong>{item.action}</strong>
                <span>{item.at}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="workspace-shortcuts" aria-label="Investigation entry shortcuts">
        <Link href="/services">Start from service</Link>
        <Link href="/situations">Start from incident</Link>
        <Link href="/exposure">Start from CVE</Link>
        <Link href="/network">Start from network gap</Link>
        <Link href="/remediation">Start from remediation</Link>
      </div>
    </div>
  );
}
