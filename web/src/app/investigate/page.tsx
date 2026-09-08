"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { TopologyWorkspace } from "@/components/network/TopologyWorkspace";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import {
  contextApi,
  askCanonicalInvestigation,
  toCanonicalInvestigationView,
  ROOT_COPILOT_SESSION,
  networkApi,
  operationsApi,
  vulnerabilityApi,
} from "@/lib/services";
import type { CanonicalInvestigationView, CopilotInvestigation } from "@/lib/services";
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
  copilot?: Envelope<CopilotInvestigation>;
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

/** Prerender-safe query-context boundary around the investigation workspace. */
export default function InvestigationWorkspacePage() {
  return (
    <Suspense fallback={<div className="page-container"><div className="state-panel state-loading">Preparing investigation workspace…</div></div>}>
      <InvestigationWorkspaceContent />
    </Suspense>
  );
}

function InvestigationWorkspaceContent() {
  const params = useSearchParams();
  const { scope } = useScope();
  const threadContinuity = useOptionalThreadContinuity();
  const [entryType, setEntryType] = useState<EntryType>((params.get("type") as EntryType) || "BusinessService");
  const [entryValue, setEntryValue] = useState(params.get("value") || "");
  const [mode, setMode] = useState<Mode>((params.get("mode") as Mode) || "executive");
  const [selected, setSelected] = useState<FocusEntity | null>(null);
  const [state, setState] = useState<WorkspaceState>({ errors: [] });
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState<SavedInvestigation[]>([]);
  const [audit, setAudit] = useState<Array<{ at: string; action: string }>>([]);

  const subject = entryValue.trim();

  useEffect(() => {
    setSaved(loadSaved());
  }, []);

  const pushAudit = (action: string) =>
    setAudit((items) => [{ at: new Date().toISOString(), action }, ...items].slice(0, 12));

  useEffect(() => {
    let active = true;
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
    };
  }, [entryType, subject, scope]);

  const score = riskScore(state.risk, state.vulnerabilities);
  const owner = ownerFrom(state.context, state.incidentDetail);
  const decision = decisionFrom(state);
  const topExposure = state.exposures?.data?.[0];
  const activeIncidents = state.incidents?.data.incidents ?? [];
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
    ...(state.remediation?.evidence ?? []),
    ...(state.cveDetail?.evidence ?? []),
    ...(state.attackPath?.evidence ?? []),
  ];
  const timeline = [
    ...(state.incidentDetail?.data.finding.timeline ?? []),
    ...activeIncidents.flatMap((item) => item.timeline ?? []),
  ]
    .slice()
    .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))
    .slice(0, 8);

  const setFocus = (entity: FocusEntity) => {
    setSelected(entity);
    pushAudit(`Focused ${entity.kind}: ${entity.label}`);
  };

  const runCopilot = async () => {
    const focusPrompt = selected ? ` Current focus is ${selected.kind} ${selected.label}: ${selected.reason ?? selected.id}.` : "";
    const question = `Summarize the investigation for ${entryType} ${subject || "current scope"}; explain business risk, affected dependencies, evidence, and recommended decision.${focusPrompt}`;
    setLoading(true);
    try {
      const result = await askCanonicalInvestigation(question, scope, { sessionId: ROOT_COPILOT_SESSION });
      const view = toCanonicalInvestigationView(result.data);
      // Mirror the server-issued thread into the shared root continuity so every
      // dedicated surface reflects one authorized handle (best-effort; the
      // provider is absent in isolated renders).
      if (view.threadId && view.threadRevision) {
        threadContinuity?.acceptServerState({ threadId: view.threadId, threadRevision: view.threadRevision });
      }
      setState((current) => ({ ...current, copilot: result, copilotView: view }));
      pushAudit("Generated Copilot conclusion");
    } catch {
      setState((current) => ({ ...current, errors: [...current.errors, "copilot unavailable"] }));
    } finally {
      setLoading(false);
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
    const query = new URLSearchParams({ type: entryType, value: subject, mode });
    const url = `${window.location.origin}/investigate?${query.toString()}`;
    window.history.replaceState(null, "", `/investigate?${query.toString()}`);
    await navigator.clipboard?.writeText(url).catch(() => undefined);
    pushAudit("Created share link");
  };

  const exportInvestigation = () => {
    const blob = new Blob([JSON.stringify({ entryType, entryValue: subject, mode, selected, audit, state }, null, 2)], {
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
        eyebrow="Executive investigation workspace"
        title={subject ? `${entryType}: ${subject}` : "Investigate business risk end to end"}
        description="One surface for business risk, dependencies, network paths, vulnerabilities, changes, incidents, evidence, Copilot reasoning, owners, and recommended actions."
        actions={
          <>
            <button className="button button-secondary" type="button" onClick={saveInvestigation}>Save view locally</button>
            <button className="button button-secondary" type="button" onClick={share}>Share</button>
            <button className="button button-secondary" type="button" onClick={exportInvestigation}>Export</button>
            <button className="button button-primary" type="button" onClick={runCopilot}>Generate conclusion</button>
          </>
        }
        metadata={
          <>
            <StatusBadge label={mode === "executive" ? "Executive mode" : "Engineer mode"} tone="info" />
            <span>{modeDescription(mode)}</span>
          </>
        }
      />

      <section className="investigation-entry card" aria-label="Investigation entry">
        <label>
          Entry point
          <select value={entryType} onChange={(event) => setEntryType(event.target.value as EntryType)}>
            {ENTRY_TYPES.map((type) => <option key={type}>{type}</option>)}
          </select>
        </label>
        <label>
          Subject
          <input value={entryValue} onChange={(event) => setEntryValue(event.target.value)} placeholder="Service, app, incident, CVE, gap, or plan id" />
        </label>
        <div className="segmented-control" role="group" aria-label="Workspace mode">
          <button type="button" className={mode === "executive" ? "active" : ""} onClick={() => setMode("executive")}>Executive</button>
          <button type="button" className={mode === "engineer" ? "active" : ""} onClick={() => setMode("engineer")}>Engineer</button>
        </div>
      </section>

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
          <MetricCard label="Trend" value={timeline.length ? "Active" : "Quiet"} detail={`${activeIncidents.length} active situations, ${state.exposures?.data?.length ?? 0} vulnerability exposures`} tone={activeIncidents.length ? "warning" : "success"} />
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
            {timeline.length === 0 ? <span className="muted">No timeline events in scope.</span> : timeline.map((event) => (
              <button key={event.event_id} type="button" className="timeline-row" onClick={() => setFocus({ kind: "Evidence", id: event.event_id, label: event.event_type, reason: event.summary })}>
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
            {state.copilotView?.citations.length ? (
              <div className="copilot-citations" aria-label="Investigation citations">
                <StatusBadge label="Citations" tone="info" compact />
                <ul>
                  {state.copilotView.citations.map((citation) => (
                    <li key={citation.citation_id}>
                      {citation.source}
                      {citation.status ? <span className="muted"> — {citation.status}</span> : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
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
