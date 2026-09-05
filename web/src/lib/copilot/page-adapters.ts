import { apiRequest } from "@/lib/api-client";
import type { ScopeSelection } from "@/lib/scope";
import { scopeToSearchParams } from "@/lib/scope";
import type { Envelope } from "@/lib/types";

export type CopilotPageDisposition = "integrated" | "deferred" | "excluded";
export type CopilotSnapshotStatus = "ok" | "empty" | "partial" | "unavailable" | "denied";
export type CopilotFreshnessStatus = "fresh" | "stale" | "partial" | "unavailable";

export interface CopilotSnapshotCoverage {
  visible_count: number;
  total_count: number;
  complete: boolean;
}

export interface CopilotSnapshotFreshness {
  source: string;
  observed_at: string;
  status: CopilotFreshnessStatus;
}

export interface CopilotSnapshotEvidence {
  evidence_id: string;
  source: string;
  status: CopilotSnapshotStatus;
  observed_at: string;
  resource_id: string;
  data: Record<string, unknown>;
}

export interface CopilotEvidenceSnapshotV2 {
  version: "2";
  page_kind: "inventory";
  page_id: "inventory";
  coverage: CopilotSnapshotCoverage;
  freshness: CopilotSnapshotFreshness[];
  evidence: CopilotSnapshotEvidence[];
}

export interface CopilotPlanHint {
  specialist_id: string;
  tool: string;
  arguments: Record<string, unknown>;
}

export interface CanonicalCopilotRequest {
  contract_version: "1";
  question: string;
  requested_scope: ScopeSelection;
  snapshot: CopilotEvidenceSnapshotV2;
  thread_id?: string;
  hint?: CopilotPlanHint;
}

export interface CanonicalCopilotCitation {
  citation_id: string;
  source: string;
  status: string;
  observed_at: string;
  resource_id: string;
}

export interface CanonicalCopilotToolResult {
  call_id: string;
  specialist_id: string;
  tool: string;
  status: CopilotSnapshotStatus;
  data: unknown;
  evidence: unknown[];
  warning: string;
}

export interface CanonicalCopilotResult {
  contract_version: "1";
  status: CopilotSnapshotStatus;
  policy_status: "accepted" | "fallback";
  fallback_reason: string;
  selected_specialists: string[];
  selected_tools: string[];
  tool_results: CanonicalCopilotToolResult[];
  uncertainty: string[];
  coverage: CopilotSnapshotCoverage;
  citations: CanonicalCopilotCitation[];
  thread_id: string;
  thread_revision: number;
  mutation_authorized: false;
}

export interface InventoryCopilotRecord {
  identity: string;
  kind: "os_group" | "software_group" | "azure_group";
  source: string;
  observedAt?: string;
  resourceId?: string;
  status?: CopilotSnapshotStatus;
  data: Record<string, unknown>;
}

export interface InventorySourceObservation {
  source: string;
  observedAt?: string;
  status: string;
}

export interface InventoryCopilotAdapterInput {
  scope: ScopeSelection;
  tab: "os" | "software" | "azure";
  filters: Record<string, string>;
  records: InventoryCopilotRecord[];
  selectedIdentity?: string | null;
  totalCount: number;
  observedAt?: string;
  sourceStatuses: InventorySourceObservation[];
}

export interface InventoryCopilotContext {
  disposition: "integrated";
  requestedScope: ScopeSelection;
  snapshot: CopilotEvidenceSnapshotV2;
  starterQuestions: Array<{
    label: string;
    specialistId: string;
    tool: string;
    toolArguments: Record<string, unknown>;
  }>;
}

const PAGE_DISPOSITIONS = {
  "/inventory": "integrated",
} as const satisfies Record<string, CopilotPageDisposition>;

/** Returns the reviewed Copilot integration disposition for a route. */
export function copilotPageDisposition(pathname: string): CopilotPageDisposition {
  return PAGE_DISPOSITIONS[pathname as keyof typeof PAGE_DISPOSITIONS] ?? "deferred";
}

function stableToken(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function freshnessStatus(status: string): CopilotFreshnessStatus {
  if (status === "ready" || status === "fresh") return "fresh";
  if (status === "stale") return "stale";
  if (status === "partial") return "partial";
  return "unavailable";
}

function fallbackIdentity(record: InventoryCopilotRecord): string {
  return `inventory://${record.kind}/${encodeURIComponent(record.identity)}`;
}

/**
 * Builds the immutable Inventory v2 observation sent to the governed
 * orchestration route. It carries observations and hints, never authority.
 */
export function buildInventoryCopilotContext(input: InventoryCopilotAdapterInput): InventoryCopilotContext {
  const filterContext = Object.fromEntries(
    Object.entries(input.filters)
      .map(([key, value]) => [key, value.trim()])
      .filter(([, value]) => Boolean(value)),
  );
  const evidence = input.records
    .map((record): CopilotSnapshotEvidence => ({
      evidence_id: `inventory:${record.kind}:${stableToken(`${record.kind}:${record.identity}`)}`,
      source: record.source,
      status: record.status ?? "ok",
      observed_at: record.observedAt ?? input.observedAt ?? "",
      resource_id: record.resourceId || fallbackIdentity(record),
      data: {
        ...record.data,
        inventory_context: {
          tab: input.tab,
          filters: filterContext,
        },
        selected: record.identity === input.selectedIdentity,
      },
    }))
    .sort((left, right) => left.evidence_id.localeCompare(right.evidence_id));
  const freshness = input.sourceStatuses
    .map((source): CopilotSnapshotFreshness | null => {
      const observedAt = source.observedAt || input.observedAt;
      return observedAt
        ? {
            source: source.source,
            observed_at: observedAt,
            status: freshnessStatus(source.status),
          }
        : null;
    })
    .filter((item): item is CopilotSnapshotFreshness => item !== null)
    .sort((left, right) => left.source.localeCompare(right.source));
  const totalCount = Math.max(input.totalCount, evidence.length);
  const complete = evidence.length === totalCount && freshness.every((item) => item.status === "fresh");

  return {
    disposition: "integrated",
    requestedScope: input.scope,
    snapshot: {
      version: "2",
      page_kind: "inventory",
      page_id: "inventory",
      coverage: {
        visible_count: evidence.length,
        total_count: totalCount,
        complete,
      },
      freshness,
      evidence,
    },
    starterQuestions: [
      {
        label: "Review visible inventory health",
        specialistId: "inventory_data_health",
        tool: "inventory_resources",
        toolArguments: {},
      },
      {
        label: "Where is inventory coverage incomplete?",
        specialistId: "inventory_data_health",
        tool: "inventory_resources",
        toolArguments: {},
      },
    ],
  };
}

/** Submits a versioned request through the authenticated canonical API. */
export function investigateCanonical(
  request: CanonicalCopilotRequest,
  scope: ScopeSelection,
): Promise<Envelope<CanonicalCopilotResult>> {
  return apiRequest<CanonicalCopilotResult>("/copilot/investigations", {
    method: "POST",
    query: scopeToSearchParams(scope),
    body: request,
  });
}
