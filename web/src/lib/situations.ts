import type {
  IncidentBlastRadius,
  IncidentCause,
  IncidentFinding,
  IncidentIdentity,
  IncidentReportEntry,
  IncidentTimelineEvent,
  DurableSituationLink,
} from "./types";
import { scopeToSearchParams, type ScopeSelection } from "./scope";

/** Navigate only resolved, supported entity identities; destination reads reauthorize. */
export function situationEntityHref(link: DurableSituationLink, scope: ScopeSelection): string | null {
  const id = link.entity_id;
  if (link.quality !== "resolved" || !id.trim() || id.length > 2048 || /[\u0000-\u001f\u007f]/.test(id)) return null;
  const params = scopeToSearchParams(scope);
  let path: string;
  if (link.entity_type === "Situation") path = `/situations/${encodeURIComponent(id)}`;
  else if (link.entity_type === "BusinessService") path = `/services/${encodeURIComponent(id)}`;
  else if (link.entity_type === "CVE" && /^CVE-\d{4}-\d{4,}$/i.test(id)) path = `/exposure/cves/${encodeURIComponent(id)}`;
  else if (link.entity_type === "KB" && /^KB\d+$/i.test(id)) path = `/exposure/kbs/${encodeURIComponent(id)}`;
  else if (link.entity_type === "SubscriptionConnection") { path = "/connections"; params.set("connection", id); }
  else if (link.entity_type === "Resource") { path = "/inventory/assets"; params.set("resource_id", id); }
  else if (["Application", "Environment", "Incident", "NetworkGap", "RemediationPlan"].includes(link.entity_type)) {
    path = "/investigate"; params.set("type", link.entity_type); params.set("value", id);
  } else return null;
  const query = params.toString();
  return `${path}${query ? `?${query}` : ""}`;
}

export type SituationPriority = "P1" | "P2" | "P3";

export interface SituationSummary {
  id: string;
  title: string;
  priority: SituationPriority;
  severity: string;
  status: string;
  startedAt: string;
  owner: string;
  supportTeam: string;
  businessServices: string[];
  applications: string[];
  cause: string;
  confidence: number;
  latestChange: IncidentTimelineEvent | null;
  impactScore: number;
  responseDeadline?: import("./types").SituationResponseDeadline;
}

function priorityFor(incident: IncidentIdentity, blastRadius: IncidentBlastRadius): SituationPriority {
  const severity = incident.severity.toLowerCase();
  if (severity === "critical" || severity === "sev0" || severity === "sev1") return "P1";
  if (
    severity === "high" ||
    severity === "sev2" ||
    blastRadius.business_service_count > 1 ||
    blastRadius.application_count > 3
  ) {
    return "P2";
  }
  return "P3";
}

function causeLabel(cause: IncidentCause | undefined, conclusion?: string): string {
  const value = cause?.summary ?? cause?.classification ?? conclusion;
  if (!value) return "Cause not yet determined";
  return value.replace(/_/g, " ");
}

function latestChange(timeline: IncidentTimelineEvent[]): IncidentTimelineEvent | null {
  return (
    timeline
      .filter((event) => event.event_type.toLowerCase().includes("change"))
      .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))[0] ?? null
  );
}

/** Converts an incident report entry into the canonical Situation summary used throughout the workbench. */
export function toSituationSummary(entry: IncidentReportEntry | IncidentFinding): SituationSummary {
  const rootCause = entry.root_cause_analysis;
  const blastRadius = entry.blast_radius;
  const timeline = entry.timeline ?? rootCause.timeline ?? [];
  const riskScore = entry.business_impact?.risk_score ?? 0;
  const confidence = rootCause.confidence ?? rootCause.probable_causes?.[0]?.confidence ?? 0;

  return {
    id: entry.incident.incident_id,
    title: entry.incident.title,
    priority: priorityFor(entry.incident, blastRadius),
    severity: entry.incident.severity,
    status: entry.incident.status,
    startedAt: entry.incident.started_at,
    owner: blastRadius.owners?.[0] ?? entry.business_impact?.owners?.[0] ?? "Owner unassigned",
    supportTeam:
      blastRadius.support_teams?.[0] ?? entry.business_impact?.support_teams?.[0] ?? "Support team unassigned",
    businessServices: blastRadius.business_services ?? [],
    applications: blastRadius.applications ?? [],
    cause: causeLabel(rootCause.probable_causes?.[0], rootCause.conclusion),
    confidence,
    latestChange: latestChange(timeline),
    impactScore: typeof riskScore === "number" ? riskScore : 0,
  };
}

const PRIORITY_ORDER: Record<SituationPriority, number> = { P1: 0, P2: 1, P3: 2 };

/** Ranks active Situations by priority, blast-radius risk, and recency. */
export function rankSituations(entries: Array<IncidentReportEntry | IncidentFinding>): SituationSummary[] {
  return entries
    .map(toSituationSummary)
    .sort((left, right) => {
      const priority = PRIORITY_ORDER[left.priority] - PRIORITY_ORDER[right.priority];
      if (priority !== 0) return priority;
      const impact = right.impactScore - left.impactScore;
      if (impact !== 0) return impact;
      return Date.parse(right.startedAt) - Date.parse(left.startedAt);
    });
}

/** Adapt a durable server record to the existing comparison table shape. */
export function durableSituationSummary(situation: import("./types").DurableSituation): SituationSummary {
  return {
    id: situation.situation_id,
    title: situation.title,
    priority: situation.priority as SituationPriority,
    severity: situation.severity,
    status: situation.lifecycle_state,
    startedAt: situation.started_at,
    owner: situation.owner || "Owner unassigned",
    supportTeam: situation.support_team || "Support team unassigned",
    businessServices: situation.scope.business_service ?? [],
    applications: situation.scope.application ?? [],
    cause: situation.evidence_state === "contradictory" ? "Evidence conflicts" : "Cause not yet determined",
    confidence: situation.evidence_state === "complete" ? 1 : 0,
    latestChange: null,
    impactScore: situation.priority === "P1" ? 100 : situation.priority === "P2" ? 50 : 10,
    responseDeadline: situation.response_deadline,
  };
}

export function rankDurableSituations(situations: import("./types").DurableSituation[]): SituationSummary[] {
  return situations
    .map(durableSituationSummary)
    .sort((left, right) => {
      const priority = PRIORITY_ORDER[left.priority] - PRIORITY_ORDER[right.priority];
      if (priority !== 0) return priority;
      return Date.parse(right.startedAt) - Date.parse(left.startedAt);
    });
}
