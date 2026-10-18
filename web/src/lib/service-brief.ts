import type { Envelope, SemanticContext } from "./types";
import { overviewHref } from "./overview";
import { scopeToSearchParams, type ScopeSelection } from "./scope";
import { isCanonicalAzureResourceId } from "./services";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

const UNAVAILABLE = new Set(["deferred", "empty", "unavailable", "failed", "error"]);

/** A successful HTTP response alone proves neither complete data nor freshness. */
export function serviceSourceState(envelope?: Envelope<SemanticContext> | null, error?: Error | null) {
  if (error || !envelope) return { available: false, state: "unavailable" as const, fresh: false };
  const statuses = Object.values(envelope.data.source_status ?? {}).map(value => value.toLowerCase().trim());
  if (statuses.length && statuses.every(value => UNAVAILABLE.has(value))) {
    return { available: false, state: "unavailable" as const, fresh: false };
  }
  const evidence = envelope.evidence ?? [];
  const graphFreshness = envelope.data.graph_freshness?.trim().toLowerCase();
  const fresh = evidence.length > 0 && evidence.every(row => row.freshness === "fresh") && (!graphFreshness || graphFreshness === "fresh");
  const partial = statuses.some(value => value !== "ok") || !fresh || Boolean(envelope.warnings?.length);
  const state = graphFreshness === "stale" || evidence.some(row => row.freshness === "stale") ? "stale" : partial ? "partial" : "fresh";
  return { available: true, state, fresh: state === "fresh" };
}

const RELATIONS = [
  "applications", "infrastructure", "dependencies", "upstream_dependencies", "downstream_dependents",
  "impacted_resources", "impacted_applications", "impacted_services", "impacted_business_services",
] as const;

export interface ServiceDependency {
  id: string;
  name: string;
  entityType: string;
  relation: string;
  resourceId: string;
  identity: "explicit" | "name-only";
}

/** Read actual object-based semantic projections and legacy strings without guessing an entity identity. */
export function serviceDependencies(...contexts: Array<SemanticContext | undefined>): ServiceDependency[] {
  const seen = new Set<string>();
  const rows: ServiceDependency[] = [];
  for (const context of contexts) {
    if (!context) continue;
    for (const relation of RELATIONS) {
      const sections = record(context.sections)[relation];
      const root = record(context)[relation];
      const values = [...(Array.isArray(sections) ? sections : []), ...(Array.isArray(root) ? root : [])];
      for (const value of values) {
        const item = record(value);
        const name = typeof value === "string" ? value.trim() : text(item.name) || text(item.resource_id);
        if (!name) continue;
        const resourceId = text(item.resource_id) || (typeof value === "string" && isCanonicalAzureResourceId(value.trim()) ? value.trim() : "");
        const entityType = text(item.entity_type) || (resourceId ? "Resource" : "");
        const id = resourceId || text(item.id) || name;
        const key = `${relation}:${entityType}:${id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        rows.push({ id, name, entityType, relation, resourceId, identity: resourceId || text(item.id) ? "explicit" : "name-only" });
      }
    }
  }
  return rows;
}

/** Navigate explicit resource IDs or named domain lookups, never pretend names are resolved ARM IDs. */
export function serviceDependencyHref(row: ServiceDependency, scope: ScopeSelection): string | null {
  const value = row.resourceId || row.name;
  if (value.length > 2048 || /[\u0000-\u001f\u007f]/.test(value)) return null;
  if (isCanonicalAzureResourceId(row.resourceId)) {
    const params = scopeToSearchParams(scope);
    params.set("resource_id", row.resourceId);
    return `/inventory/assets?${params}`;
  }
  if (row.entityType === "BusinessService") return overviewHref(`/services/${encodeURIComponent(row.name)}`, scope);
  if (["Application", "Environment"].includes(row.entityType)) {
    const params = scopeToSearchParams(scope);
    params.set("type", row.entityType); params.set("value", row.name);
    return `/investigate?${params}`;
  }
  return null;
}

/** Project only known identity fields and bounded numeric risk facts; no arbitrary sections become KPIs. */
export function serviceBrief(context?: SemanticContext, riskContext?: unknown) {
  const subject = record(context?.subject);
  const risk = record(record(riskContext).risk);
  const score = risk.score;
  return {
    name: text(subject.name),
    owner: text(subject.owner),
    supportTeam: text(subject.support_team),
    environment: text(subject.environment),
    criticality: text(subject.criticality),
    lifecycle: text(subject.lifecycle_status),
    riskScore: typeof score === "number" && Number.isInteger(score) && score >= 0 && score <= 100 ? score : null,
    riskLevel: text(risk.level),
    factors: Object.entries(record(risk.factors)).filter((entry): entry is [string, number] =>
      typeof entry[1] === "number" && Number.isSafeInteger(entry[1]) && entry[1] >= 0),
  };
}
