import { apiRequest, resolveApiBaseUrl } from "./api-client";
import type { ScopeSelection } from "./scope";
import { scopeToSearchParams } from "./scope";
import type {
  BusinessMetadata,
  ChangeAssessment,
  ChangeAssessmentSources,
  ChangeAssessmentSummary,
  ComplianceDeviation,
  ComplianceResourcePosture,
  ComplianceSummary,
  ConnectionCreateRequest,
  ConnectionCreateResult,
  ConnectionHealthReport,
  ConnectionSyncResult,
  ConnectionUpdateRequest,
  ConnectionValidationReport,
  DefenderRemediationCaseReport,
  DependencyGraph,
  Envelope,
  IncidentDetail,
  IncidentReport,
  RemediationOpportunityReport,
  RemediationDecision,
  RemediationPlan,
  RemediationPlanReport,
  FlowResult,
  HubDependents,
  NetworkGap,
  NetworkDesignPolicy,
  NetworkSeverity,
  NetworkSummary,
  NetworkTopology,
  NetworkTopologyResourceDetails,
  RuleFinding,
  SearchResult,
  AssetExposure,
  DefenderPostureFinding,
  ContainerImageExposure,
  DefenderAlert,
  DefenderAttackPath,
  DefenderOverview,
  DefenderSecureScore,
  DefenderSecureScoreControl,
  CanonicalCopilotRequest,
  CanonicalCopilotResult,
  CanonicalCopilotCitation,
  CanonicalInvestigationSemantics,
  CanonicalInvestigationSynthesis,
  CopilotSnapshotCoverageV2,
  SemanticContext,
  SubscriptionConnection,
  CveDetail,
  KbDetail,
  PatchPriority,
  PatchRun,
  PatchTarget,
  RiskException,
  SlaComplianceReport,
  AttackPathGraph,
  ExposureCollection,
  ExposureEnvelope,
  ExposureExternalCatalog,
  ExposureFacets,
  ExposureOverview,
  ExposurePage,
  ExposureQueryCatalog,
  VulnerabilityExposure,
  VulnerabilitySummary,
  EvidenceItem,
  FabricCapabilities,
  FabricDataset,
  FabricGovernanceSummary,
  FabricIngestionRun,
  FabricLayerCounts,
  FabricManifestEntry,
  TwinComparison,
  TwinExport,
  TwinQueryResult,
  TwinScenarioResult,
  TwinSnapshot,
  TwinTraversal,
  AutonomousAgent,
  MultiAgentLedger,
  FinOpsSummary,
  SavingsOpportunity,
  WasteItem,
  FinOpsAttributionGroup,
  IdentitySummary,
  PrincipalRisk,
  SubscriptionOwnerRecord,
  StaleAccessRecord,
  NonHumanIdentity,
  SpnSummary,
  ServicePrincipalGovernance,
  AccessReviewPack,
  AuditExportPack,
  EnterpriseSettings,
  OsInventoryCollection,
  OsInventoryDetail,
  InventoryNarrative,
  OntologyAutomationStatus,
  OntologyEvaluation,
  OntologyEvaluationSnapshot,
  OntologyGeneration,
  OntologyProposal,
  OntologyProposalReview,
  OntologyProposalReviewRequest,
  OntologyRollbackRequest,
  OntologyRun,
  OntologyRunMutationRequest,
  OntologyRunNowRequest,
  SoftwareInventoryCollection,
  SoftwareInventoryDetail,
  SoftwareMapping,
  SoftwareMappingCollection,
  ResourceHealthSnapshot,
  CopilotPageKind, CopilotPageSnapshot, CopilotSelectedResource, CopilotEvidenceRow, CopilotContextResult,
} from "./types";
import {
  toExposureApiSearchParams,
  type ExposureQueryState,
} from "./exposure-query-state";

async function listAllConnections(scope: ScopeSelection): Promise<Envelope<SubscriptionConnection[]>> {
  const connections: SubscriptionConnection[] = [];
  let offset = 0;
  let lastEnvelope: Envelope<SubscriptionConnection[]> | null = null;

  do {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", "500");
    lastEnvelope = await apiRequest<SubscriptionConnection[]>("/subscription-connections", { query });
    connections.push(...lastEnvelope.data);
    offset = lastEnvelope.pagination?.next_offset ?? -1;
  } while (offset >= 0);

  if (!lastEnvelope) {
    throw new Error("Subscription connection list returned no response");
  }
  return { ...lastEnvelope, data: connections };
}

// ---------------------------------------------------------------------------
// Subscription connections
// ---------------------------------------------------------------------------

export const connectionsApi = {
  list: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<SubscriptionConnection[]>("/subscription-connections", { query });
  },

  /** Loads every accessible connection so global scope menus are complete across paginated estates. */
  listAll: (scope: ScopeSelection = {}) => listAllConnections(scope),

  get: (id: string) => apiRequest<SubscriptionConnection>(`/subscription-connections/${encodeURIComponent(id)}`),

  create: (payload: ConnectionCreateRequest) =>
    apiRequest<ConnectionCreateResult>("/subscription-connections", { method: "POST", body: payload }),

  update: (id: string, payload: ConnectionUpdateRequest) =>
    apiRequest<SubscriptionConnection>(`/subscription-connections/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: payload,
    }),

  mapMetadata: (id: string, metadata: BusinessMetadata) =>
    apiRequest<SubscriptionConnection>(`/subscription-connections/${encodeURIComponent(id)}/metadata`, {
      method: "PUT",
      body: { metadata },
    }),

  disable: (id: string) =>
    apiRequest<SubscriptionConnection>(`/subscription-connections/${encodeURIComponent(id)}/disable`, {
      method: "POST",
    }),

  enable: (id: string) =>
    apiRequest<SubscriptionConnection>(`/subscription-connections/${encodeURIComponent(id)}/enable`, {
      method: "POST",
    }),

  delete: (id: string) =>
    apiRequest<void>(`/subscription-connections/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  validate: (id: string) =>
    apiRequest<ConnectionValidationReport>(`/subscription-connections/${encodeURIComponent(id)}/validate`, {
      method: "POST",
    }),

  sync: (id: string, mode: "initial" | "scheduled" | "manual" = "initial") =>
    apiRequest<ConnectionSyncResult>(`/subscription-connections/${encodeURIComponent(id)}/sync`, {
      method: "POST",
      body: { mode },
    }),

  health: (id: string) =>
    apiRequest<ConnectionHealthReport>(`/subscription-connections/${encodeURIComponent(id)}/health`),
};


export const fabricMedallionApi = {
  layers: (scope: ScopeSelection = {}) =>
    apiRequest<{
      layers: Record<"bronze" | "silver" | "gold", FabricLayerCounts>;
      tables?: Record<"bronze" | "silver" | "gold", string[]>;
    }>("/fabric-medallion/layers", {
      query: scopeToSearchParams(scope),
    }),

  dataset: (tableName: string, scope: ScopeSelection = {}) =>
    apiRequest<FabricDataset>(`/fabric-medallion/datasets/${encodeURIComponent(tableName)}`, {
      query: scopeToSearchParams(scope),
    }),

  manifest: (scope: ScopeSelection = {}) =>
    apiRequest<{ entries: FabricManifestEntry[] }>("/fabric-medallion/manifest", {
      query: scopeToSearchParams(scope),
    }),

  governance: (scope: ScopeSelection = {}) =>
    apiRequest<FabricGovernanceSummary>("/fabric-medallion/governance", {
      query: scopeToSearchParams(scope),
    }),

  ingestionHistory: (scope: ScopeSelection = {}) =>
    apiRequest<{ runs: FabricIngestionRun[] }>("/fabric-medallion/ingestion-history", {
      query: scopeToSearchParams(scope),
    }),

  capabilities: (scope: ScopeSelection = {}) =>
    apiRequest<FabricCapabilities>("/fabric-medallion/capabilities", {
      query: scopeToSearchParams(scope),
    }),
};

function ontologyQuery(
  connectionId: string,
  scope: ScopeSelection,
  offset?: number,
  limit?: number,
): URLSearchParams {
  const query = scopeToSearchParams(scope);
  query.set("connection_id", connectionId);
  if (offset !== undefined) query.set("offset", String(offset));
  if (limit !== undefined) query.set("limit", String(limit));
  return query;
}

/**
 * Connection-scoped client for durable ontology state. Callers must pass the
 * effective UI scope and the selected connection on every request; mutations
 * additionally carry the server revision or pointer ETag they observed.
 */
export const ontologyAutomationApi = {
  status: (connectionId: string, scope: ScopeSelection) =>
    apiRequest<OntologyAutomationStatus>("/ontology-discovery/status", {
      query: ontologyQuery(connectionId, scope),
    }),

  runs: (connectionId: string, scope: ScopeSelection, offset = 0, limit = 100) =>
    apiRequest<OntologyRun[]>("/ontology-discovery/runs", {
      query: ontologyQuery(connectionId, scope, offset, limit),
    }),

  run: (connectionId: string, runId: string, scope: ScopeSelection) =>
    apiRequest<OntologyRun>(`/ontology-discovery/runs/${encodeURIComponent(runId)}`, {
      query: ontologyQuery(connectionId, scope),
    }),

  runNow: (connectionId: string, scope: ScopeSelection, payload: OntologyRunNowRequest) =>
    apiRequest<OntologyRun>("/ontology-discovery/runs", {
      method: "POST",
      query: ontologyQuery(connectionId, scope),
      body: payload,
    }),

  cancelRun: (
    connectionId: string,
    runId: string,
    scope: ScopeSelection,
    payload: OntologyRunMutationRequest,
  ) =>
    apiRequest<OntologyRun>(`/ontology-discovery/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      query: ontologyQuery(connectionId, scope),
      body: payload,
    }),

  retryRun: (
    connectionId: string,
    runId: string,
    scope: ScopeSelection,
    payload: OntologyRunMutationRequest,
  ) =>
    apiRequest<OntologyRun>(`/ontology-discovery/runs/${encodeURIComponent(runId)}/retry`, {
      method: "POST",
      query: ontologyQuery(connectionId, scope),
      body: payload,
    }),

  proposals: (connectionId: string, scope: ScopeSelection, offset = 0, limit = 100) =>
    apiRequest<OntologyProposal[]>("/ontology-discovery/proposals", {
      query: ontologyQuery(connectionId, scope, offset, limit),
    }),

  proposal: (connectionId: string, proposalId: string, scope: ScopeSelection) =>
    apiRequest<OntologyProposal>(
      `/ontology-discovery/proposals/${encodeURIComponent(proposalId)}`,
      { query: ontologyQuery(connectionId, scope) },
    ),

  reviewProposal: (
    connectionId: string,
    proposalId: string,
    scope: ScopeSelection,
    payload: OntologyProposalReviewRequest,
  ) =>
    apiRequest<OntologyProposalReview>(
      `/ontology-discovery/proposals/${encodeURIComponent(proposalId)}/review`,
      {
        method: "POST",
        query: ontologyQuery(connectionId, scope),
        body: payload,
      },
    ),

  generation: (connectionId: string, scope: ScopeSelection) =>
    apiRequest<OntologyGeneration>("/ontology-discovery/generations", {
      query: ontologyQuery(connectionId, scope),
    }),

  publications: (connectionId: string, scope: ScopeSelection, offset = 0, limit = 100) =>
    apiRequest<OntologyRun[]>("/ontology-discovery/publications", {
      query: ontologyQuery(connectionId, scope, offset, limit),
    }),

  rollbackGeneration: (
    connectionId: string,
    generationId: string,
    scope: ScopeSelection,
    payload: OntologyRollbackRequest,
  ) =>
    apiRequest<OntologyGeneration>(
      `/ontology-discovery/generations/${encodeURIComponent(generationId)}/rollback`,
      {
        method: "POST",
        query: ontologyQuery(connectionId, scope),
        body: payload,
      },
    ),

  evaluation: (connectionId: string, scope: ScopeSelection) =>
    apiRequest<OntologyEvaluation>("/ontology-discovery/evaluation", {
      query: ontologyQuery(connectionId, scope),
    }),

  evaluations: (connectionId: string, scope: ScopeSelection, offset = 0, limit = 100) =>
    apiRequest<OntologyEvaluationSnapshot[]>("/ontology-discovery/evaluations", {
      query: ontologyQuery(connectionId, scope, offset, limit),
    }),
};

export const inventoryApi = {
  os: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<OsInventoryCollection>("/inventory/os", { query });
  },
  osGroup: (key: string, scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<OsInventoryDetail>(`/inventory/os/${encodeURIComponent(key)}`, { query });
  },
  lifecycleReview: (key: string, scope: ScopeSelection = {}) =>
    apiRequest<import("./types").LifecycleReview>(
      `/inventory/os/${encodeURIComponent(key)}/lifecycle`,
      { query: scopeToSearchParams(scope) },
    ),
  confirmLifecycle: (
    key: string,
    payload: {
      normalized_os_key: string;
      expected_revision: number;
      candidate_id?: string;
      manual_date?: string;
      support_channel?: "mainstream" | "extended";
    },
    scope: ScopeSelection = {},
  ) =>
    apiRequest<import("./types").LifecycleReview>(
      `/inventory/os/${encodeURIComponent(key)}/lifecycle/confirm`,
      {
        method: "POST",
        query: scopeToSearchParams(scope),
        body: payload,
      },
    ),
  software: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<SoftwareInventoryCollection>("/inventory/software", { query });
  },
  softwareGroup: (key: string, scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<SoftwareInventoryDetail>(`/inventory/software/${encodeURIComponent(key)}`, { query });
  },
  paas: (scope: ScopeSelection = {}, offset = 0, limit = 200) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<import("./types").PaasInventoryCollection>("/inventory/paas", { query });
  },
  paasGroup: (key: string, scope: ScopeSelection = {}, offset = 0, limit = 200) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<import("./types").PaasInventoryDetail>(
      `/inventory/paas/${encodeURIComponent(key)}`,
      { query },
    );
  },
  resources: (scope: ScopeSelection = {}, offset = 0, limit = 500) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<import("./types").FlatResourceCollection>("/inventory/resources", { query });
  },
  narrative: (scope: ScopeSelection = {}) =>
    apiRequest<InventoryNarrative>("/inventory/narrative", {
      query: scopeToSearchParams(scope),
    }),
  mappings: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<SoftwareMappingCollection>("/inventory/software/mappings", { query });
  },
  approveMapping: (
    mapping_id: string,
    expected_revision: number,
    scope: ScopeSelection = {},
    reason = "",
  ) =>
    apiRequest<SoftwareMapping>("/inventory/software/mappings/approve", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { mapping_id, expected_revision, reason },
    }),
  rejectMapping: (
    mapping_id: string,
    expected_revision: number,
    scope: ScopeSelection = {},
    reason = "",
  ) =>
    apiRequest<SoftwareMapping>("/inventory/software/mappings/reject", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { mapping_id, expected_revision, reason },
    }),
};

// ---------------------------------------------------------------------------
// Context (Semantic Knowledge Layer)
// ---------------------------------------------------------------------------

/** Supported /search intent phrases (see docs/OPERATIONS_API.md — search is intent-driven, not free text). */
export const SUPPORTED_SEARCH_PHRASES = [
  "show list of VMs",
  "production applications",
  "applications owned by <owner>",
  "servers with failed patches",
  "resources missing ownership",
  "applications missing ownership",
  "resources related to business service <name>",
  "critical infrastructure",
] as const;

export const contextApi = {
  search: (q: string, scope: ScopeSelection = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("q", q);
    return apiRequest<SearchResult>("/search", { query });
  },

  businessService: (name: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/business-services/${encodeURIComponent(name)}`, { query: scopeToSearchParams(scope) }),
  application: (name: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/applications/${encodeURIComponent(name)}`, { query: scopeToSearchParams(scope) }),
  environment: (name: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/environments/${encodeURIComponent(name)}`, { query: scopeToSearchParams(scope) }),
  subscription: (name: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/subscriptions/${encodeURIComponent(name)}`, { query: scopeToSearchParams(scope) }),
  subscriptionConnectionContext: (name: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/subscription-connections/${encodeURIComponent(name)}/context`, {
      query: scopeToSearchParams(scope),
    }),
  resource: (resourceId: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/resources/${encodeURIComponent(resourceId)}`, {
      query: scopeToSearchParams(scope),
    }),
  risk: (subject: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/risk/${encodeURIComponent(subject)}`, { query: scopeToSearchParams(scope) }),
  impact: (subject: string, scope: ScopeSelection = {}) =>
    apiRequest<SemanticContext>(`/impact/${encodeURIComponent(subject)}`, { query: scopeToSearchParams(scope) }),
  dependencyGraph: (
    application: string,
    direction: "upstream" | "downstream" | "both" = "both",
    scope: ScopeSelection = {},
  ) =>
    apiRequest<DependencyGraph>(`/graph/dependencies/${encodeURIComponent(application)}`, {
      query: { ...Object.fromEntries(scopeToSearchParams(scope)), direction },
    }),
};

export interface CopilotAnswer {
  text: string;
  agent_name: string;
  model: string;
  grounded: boolean;
}

/** A Copilot turn: retrieved rows plus the Foundry agent's narration of them. */
export interface CopilotReply {
  question: string;
  intent: string;
  results: Array<Record<string, unknown>>;
  answer: CopilotAnswer | null;
}

/** One governed tool call executed during a multi-step investigation. */
export interface CopilotToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  status: "ok" | "empty" | "unavailable" | "denied";
  data: unknown;
  evidence: EvidenceItem[];
  warning: string;
}

/** The outcome of a `/copilot/investigate` turn: every tool call plus the narration. */
export interface CopilotInvestigation extends CanonicalInvestigationSemantics {
  question: string;
  tool_calls: CopilotToolCall[];
  answer: CopilotAnswer | null;
  fact_status: "ok" | "partial" | "empty" | "unavailable" | "denied";
  warnings: string[];
}

export interface CopilotPageSnapshotInput {
  pageKind: CopilotPageKind; pageId: string; scope: ScopeSelection;
  filters?: Record<string, string[]>; selectedResources?: CopilotSelectedResource[];
  evidence?: CopilotEvidenceRow[]; freshness?: CopilotPageSnapshot["freshness"];
  question?: string; rechecks?: string[];
}

export function isCanonicalAzureResourceId(value: string | null | undefined): value is string {
  const parts = String(value ?? "").split("/").filter(Boolean);
  const providerIndex = parts.findIndex((part) => part.toLowerCase() === "providers");
  return (
    String(value ?? "").startsWith("/") &&
    parts.length > providerIndex + 2 &&
    parts[0]?.toLowerCase() === "subscriptions" &&
    Boolean(parts[1]) &&
    providerIndex >= 0
  );
}

function validatedCopilotResource(resource: CopilotSelectedResource): CopilotSelectedResource | null {
  return isCanonicalAzureResourceId(resource.resource_id) ? resource : null;
}

function validatedCopilotEvidence(row: CopilotEvidenceRow): CopilotEvidenceRow {
  if (!row.resource_id || isCanonicalAzureResourceId(row.resource_id)) return row;
  const { resource_id: resourceId, data, ...rest } = row;
  return {
    ...rest,
    data: { ...data, resource_id: resourceId },
  };
}

export function buildCopilotSnapshot(input: CopilotPageSnapshotInput): CopilotPageSnapshot {
  return {
    version: "1", page_kind: input.pageKind, page_id: input.pageId,
    selected_resources: (input.selectedResources ?? []).map(validatedCopilotResource).filter((resource): resource is CopilotSelectedResource => Boolean(resource)).slice(0, 50),
    filters: input.filters ?? {}, freshness: (input.freshness ?? []).slice(0, 32),
    scope: { declared: input.scope, authorized: true }, evidence: (input.evidence ?? []).map(validatedCopilotEvidence).slice(0, 200),
    question: input.question?.trim() || "Summarize the visible page evidence.", rechecks: input.rechecks ?? [],
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

export function copilotEvidenceRows(
  section: string, evidence: EvidenceItem[], records: unknown[] = [],
  status: "ok" | "empty" | "unavailable" | "denied" = "ok",
): CopilotEvidenceRow[] {
  const rows: CopilotEvidenceRow[] = evidence.map((item, index) => ({
    evidence_id: `${section}:${item.source_table || "source"}:${index}`,
    resource_id: isCanonicalAzureResourceId(item.resource_id) ? item.resource_id : undefined, section,
    data: { source_engine: item.source_engine, source_table: item.source_table },
    status, observed_at: item.timestamp,
  }));
  return rows.concat(records.slice(0, 200).map((record, index): CopilotEvidenceRow => ({
    evidence_id: `${section}:visible:${index}`, section,
    data: (record && typeof record === "object" ? record : { value: record }) as Record<string, unknown>, status,
  })));
}

export interface CopilotToolSpec {
  name: string;
  description: string;
  parameters: Record<string, string>;
}

export const copilotApi = {
  /**
   * Asks the Operations Copilot. The API grounds an Azure AI Foundry prompt
   * agent on governed context, so `answer` is a narration of `results` — never
   * an independent claim. `answer` is null when no agent is configured or it
   * could not be reached; `warnings` on the envelope explains which.
   */
  ask: (question: string, scope: ScopeSelection = {}) =>
    apiRequest<CopilotReply>("/copilot/ask", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { question },
    }),

  /**
   * Multi-step investigation: plans and runs up to a handful of governed tool
   * calls (topology, traffic-flow, CVE exposure, incidents, remediation,
   * ontology context) and narrates the aggregate. Pass `sessionId` to keep a
   * bounded, principal-scoped conversation thread; pass `tool`/`toolArguments`
   * to bypass the planner for a known starter question.
   */
  investigate: (
    question: string,
    scope: ScopeSelection = {},
    options: { sessionId?: string; tool?: string; toolArguments?: Record<string, unknown> } = {}
  ) =>
    apiRequest<CopilotInvestigation>("/copilot/investigate", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: {
        question,
        session_id: options.sessionId ?? "",
        tool: options.tool ?? "",
        tool_arguments: options.toolArguments ?? {},
      },
    }),

  tools: () => apiRequest<{ tools: CopilotToolSpec[] }>("/copilot/tools"),

  history: (sessionId: string) =>
    apiRequest<{ session_id: string; turns: CopilotInvestigation[] }>(
      `/copilot/history/${encodeURIComponent(sessionId)}`
    ),

    investigateContext: (snapshot: CopilotPageSnapshot) =>
      apiRequest<CopilotContextResult>("/copilot/investigate-context", { method: "POST", body: { snapshot } }),
};

/**
 * The one same-tab root session every dedicated Copilot surface shares.
 *
 * The server binds a `(principal, session_id)` pair to a single opaque
 * canonical thread, so passing this shared identifier from the standalone
 * Copilot, the investigation workspace, and any other dedicated surface keeps
 * them on one authorized, principal-scoped thread rather than fragmenting
 * continuity per page. It is not authority: the server still validates scope
 * and issues the real `thr-…` handle it returns.
 */
export const ROOT_COPILOT_SESSION = "aiops-root-copilot";

/**
 * The one canonical API client helper the dedicated Copilot surfaces submit
 * through. It posts the canonical-backed `/copilot/investigate` contract and
 * defaults continuity to {@link ROOT_COPILOT_SESSION} so equivalent questions
 * resolve to the same governed policy/evidence semantics regardless of which
 * surface asked. Standalone requests may omit page context; workspace requests
 * pass the same helper with their own generated question.
 */
export function askCanonicalInvestigation(
  question: string,
  scope: ScopeSelection = {},
  options: { sessionId?: string; tool?: string; toolArguments?: Record<string, unknown> } = {},
): Promise<Envelope<CopilotInvestigation>> {
  return apiRequest<CopilotInvestigation>("/copilot/investigate", {
    method: "POST",
    query: scopeToSearchParams(scope),
    body: {
      question,
      session_id: options.sessionId ?? ROOT_COPILOT_SESSION,
      tool: options.tool ?? "",
      tool_arguments: options.toolArguments ?? {},
    },
  });
}

/** Display-ready projection of a canonical turn, shared across surfaces. */
export interface CanonicalInvestigationView {
  toolCalls: CopilotToolCall[];
  narration: CopilotAnswer | null;
  policyStatus: "accepted" | "fallback";
  fallbackReason: string;
  degraded: boolean;
  degradationNote: string;
  citations: CanonicalCopilotCitation[];
  uncertainty: string[];
  coverage?: CopilotSnapshotCoverageV2;
  synthesis: CanonicalInvestigationSynthesis | null;
  threadId?: string;
  threadRevision?: number;
}

/**
 * Convert a canonical investigation result into the fields every dedicated
 * surface renders the same way: narration (only when synthesis actually ran),
 * a policy/fallback degradation note, citations, and uncertainty. This is the
 * single presentation converter, so the standalone Copilot and the workspace
 * cannot drift in how they surface canonical semantics.
 *
 * A withheld or unavailable narrator never removes the specialists' own tool
 * evidence (D-09): `toolCalls` are preserved and `degradationNote` explains the
 * fallback instead of fabricating text.
 */
export function toCanonicalInvestigationView(data: CopilotInvestigation): CanonicalInvestigationView {
  const synthesis = data.synthesis ?? null;
  const synthesized = synthesis?.status === "synthesized";
  const narrationText = synthesized
    ? synthesis!.claims.map((claim) => claim.summary.trim()).filter(Boolean).join(" ")
    : "";
  const narration: CopilotAnswer | null = data.answer
    ?? (narrationText
      ? { text: narrationText, agent_name: "Executive synthesis", model: "Canonical", grounded: true }
      : null);
  const policyStatus = data.policy_status ?? "accepted";
  const fallbackReason = data.fallback_reason ?? "";
  const degraded = policyStatus === "fallback" || synthesis?.status === "degraded";
  const degradationNote = synthesis?.warning?.trim()
    || (policyStatus === "fallback"
      ? "Deterministic specialist evidence is shown; Foundry narration was not produced."
      : "");
  return {
    toolCalls: data.tool_calls ?? [],
    narration,
    policyStatus,
    fallbackReason,
    degraded,
    degradationNote,
    citations: data.citations ?? [],
    uncertainty: data.warnings ?? [],
    coverage: data.coverage,
    synthesis,
    threadId: data.thread_id,
    threadRevision: data.thread_revision,
  };
}

// ---------------------------------------------------------------------------
// Operations (incidents / remediation)
// ---------------------------------------------------------------------------

export const operationsApi = {
  incidents: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<IncidentReport>("/incidents", { query });
  },
  incident: (id: string, scope: ScopeSelection = {}) =>
    apiRequest<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`, { query: scopeToSearchParams(scope) }),
  remediationPlans: (scope: ScopeSelection = {}, offset = 0, limit = 100, resourceKey = "") => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    if (resourceKey) query.set("resource_key", resourceKey);
    return apiRequest<RemediationPlanReport>("/remediation-plans", { query });
  },
  remediationOpportunities: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<RemediationOpportunityReport>("/remediation-opportunities", { query });
  },
  defenderCases: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<DefenderRemediationCaseReport>("/remediation/defender-cases", { query });
  },
  decideRemediationPlan: (
    planId: string,
    payload: { decision: RemediationDecision["decision"]; reason: string; action_version: string; expires_at?: string },
    scope: ScopeSelection = {},
  ) =>
    apiRequest<RemediationDecision>(`/remediation-plans/${encodeURIComponent(planId)}/decisions`, {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { ...payload, expires_at: payload.expires_at ?? "" },
    }),
};

export type RemediationExecutionStatus =
  | "queued"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface RemediationAvailablePatch {
  patch_id: string;
  title?: string;
  classification?: string;
  severity?: string;
  cve_ids?: string[];
  reboot_required?: boolean;
  published_at?: string;
  source?: string;
  node_pool?: string;
  current_version?: string;
  target_version?: string;
}

export interface RemediationExecutionSnapshot {
  snapshot_kind?: "defender_configuration";
  target_id: string;
  patch_ids: string[];
  available_patches?: RemediationAvailablePatch[];
  target_kind: string;
  operation: string;
  action_id?: string;
  action_version: string;
  snapshot_hash: string;
  request?: {
    method: "PUT";
    path: string;
    api_version: string;
    body: { properties: Record<string, unknown> };
  };
  precondition?: {
    etag: string;
    state_hash: string;
  };
  prior_properties?: Record<string, unknown>;
  desired_properties?: Record<string, unknown>;
}

export interface RemediationEligibility {
  executable: boolean;
  ineligibility_reason: string;
}

export type RemediationPlanDetail = Omit<
  RemediationPlan,
  "resource" | "plan_id" | "title" | "status" | "action_version"
> &
  RemediationEligibility & {
    plan_id: string;
    title: string;
    status: string;
    action_version?: string;
    action_id?: string;
    opportunity_type?: string;
    resource?: Record<string, unknown> | string;
    resource_key?: string;
  };

export interface RemediationExecutionPreview extends RemediationEligibility {
  target: {
    resource: Record<string, unknown> | string;
    resource_key: string;
  };
  operation: string;
  preconditions: unknown[];
  expected_effect: Record<string, unknown>;
  collateral_impact: Record<string, unknown>;
  execution_snapshot: RemediationExecutionSnapshot | null;
}

export interface RemediationApprovalDecision extends RemediationDecision {
  execution_snapshot?: RemediationExecutionSnapshot | null;
}

export interface RemediationApprovalRequirement {
  policy_id: string;
  role: string;
  /**
   * Stable, RBAC-capacity-compatible identifier satisfaction matching keys
   * on -- separate from `role`'s presentation text (Phase 03.5 CR-01 fix).
   * Absent on a requirement row generated before this fix (legacy/durable
   * plan snapshot).
   */
  role_id?: string;
  stage: string;
  satisfied: boolean;
  unmet_reason?: string;
  approval_evidence_required: string[];
  status?: string;
  approval_recorded?: boolean;
  /** Present only when `satisfied` -- the decision that satisfied this row. */
  approver?: string;
  decision_id?: string;
}

export interface RemediationApprovalContext {
  plan_id: string;
  approval_requirements: RemediationApprovalRequirement[];
  decisions: RemediationApprovalDecision[];
}

export interface RemediationBusinessDecision {
  disposition?: "act_now" | "schedule" | "defer" | "not_applicable" | "escalate";
  urgency_rationale?: {
    reason_code?: string;
    message?: string;
    evidence_citations?: Array<Record<string, unknown>>;
  };
  cost_of_action?: Record<string, unknown> | string;
  cost_of_inaction?: Record<string, unknown> | string;
  business_impact?: Record<string, unknown> | string;
  confidence?: unknown;
  review_requirements?: unknown[] | Record<string, unknown>;
  unknowns?: unknown[];
  evidence_citations?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface RemediationExecutionTransition {
  sequence?: number;
  status: RemediationExecutionStatus;
  actor?: string;
  timestamp?: string;
  provider_job_id?: string;
  verified_state?: string;
  failure_details?: string;
  outcome?: string;
  message?: string;
}

export interface RemediationExecutionAttempt {
  attempt_number: number;
  status: RemediationExecutionStatus;
  actor?: string;
  created_at?: string;
  updated_at?: string;
  provider_job_id?: string;
  verified_state?: string;
  failure_details?: string;
  outcome?: string;
  execution_snapshot?: RemediationExecutionSnapshot;
  transitions: RemediationExecutionTransition[];
  provider_submitted?: boolean;
  failure_class?: string;
}

export interface RemediationExecution {
  execution_id: string;
  plan_id: string;
  status: RemediationExecutionStatus;
  requested_by: string;
  approved_by: string;
  created_at: string;
  updated_at: string;
  provider_job_id: string;
  message: string;
  attempt_count: number;
  rollback_guidance: string[];
  verified_state: string;
  failure_details: string;
  outcome?: string;
  execution_snapshot: RemediationExecutionSnapshot;
  attempts: RemediationExecutionAttempt[];
  history: RemediationExecutionTransition[];
  retryable: boolean;
  cancellable: boolean;
  remaining_attempts: number;
  ineligibility_reason: string;
  provider_submitted?: boolean;
  failure_class?: string;
  submitted_attempt_count?: number;
  supersedes?: string;
  superseded_by?: string;
  superseded_reason?: string;
  supersedable?: boolean;
  supersede_ineligibility_reason?: string;
  verification_deadline_at?: string;
  next_verification_at?: string;
  verification_attempts?: number;
  evidence_reconciliation?: RemediationEvidenceReconciliation;
}

export interface RemediationExecutionList {
  plan_id: string;
  executions: RemediationExecution[];
}

export interface RemediationBlocker {
  code: string;
  message?: string;
  step: "select" | "review" | "approve" | "run" | "verify";
  next_action?: string;
  severity?: "warning" | "critical";
}

export interface RemediationDegradation {
  source: string;
  availability: "degraded" | "unavailable" | "partial";
  reason: string;
  dropped_count?: number;
  unmatched_count?: number;
  freshness?: string;
}

export interface RemediationEvidenceReconciliation {
  status:
    | ""
    | "pending"
    | "reconciled_clean"
    | "reconciled_incomplete"
    | "unreconciled"
    | "unreconciled_timed_out";
  kbs_cleared: string[];
  kbs_remaining: string[];
  assessed_at: string;
}

export type RemediationActionFamily =
  | "patch"
  | "defender"
  | "policy"
  | "configuration"
  | "unsupported";

export interface ExposureRemediationCase {
  contract_version: string;
  case_id: string;
  handoff_id: string;
  exposure_id: string;
  resource_key: string;
  weakness_key: string;
  target_kind: "server" | "container_image";
  tenant_id?: string;
  connection_ids?: string[];
  source_families?: string[];
  read_model_generation_id: string;
  completeness?: string;
  coverage?: {
    represented?: number;
    total?: number;
    excluded?: number;
    excluded_reasons?: string[];
    [key: string]: unknown;
  };
  freshness?: {
    state?: string;
    as_of?: string;
    [key: string]: unknown;
  };
  evidence_refs?: Array<Record<string, unknown>>;
  action_id: string;
  direct_execution_supported: boolean;
  outcome: "governed_action" | "review_handoff" | "no_safe_action";
  outcome_reason_code: string;
  outcome_reason: string;
  review_handoff: {
    target_kind: string;
    registry_id?: string;
    repository?: string;
    image_digest?: string;
    workload_state?: string;
    application_id?: string;
    business_service_id?: string;
    safe_blast_radius_known?: boolean;
  };
  read_only: boolean;
}

export interface ExposureHandoffCollection {
  contract_version?: string;
  cases: ExposureRemediationCase[];
  read_only: true;
  execution_transition: false;
}

export interface ExposureReviewHandoffResult extends ExposureRemediationCase {
  handoff_reason: string;
  created_by: string;
  created_at: string;
  risk_acknowledged: boolean;
  risk_exception_id: string;
  execution_transition: false;
}

export interface RemediationWorkflow {
  plan: RemediationPlanDetail;
  action: {
    action_id: string;
    family: RemediationActionFamily;
    executable: boolean;
    manual_review_reason: string;
    can_operate: boolean;
    operate_ineligible_reason?: string;
  };
  preview: RemediationExecutionPreview | null;
  preview_error: string;
  business_decision: RemediationBusinessDecision;
  approval: {
    requirements: RemediationApprovalRequirement[];
    decisions: RemediationApprovalDecision[];
    latest: RemediationApprovalDecision | null;
    current: boolean;
    status: "none" | "current" | "stale" | "rejected" | "expired";
    stale_reasons: string[];
    can_approve: boolean;
    approve_ineligible_reason?: string;
    allow_self_approval: boolean;
  };
  execution: RemediationExecution | null;
  executions: RemediationExecution[];
  steps: Array<{
    id: "select" | "review" | "approve" | "run" | "verify";
    label: string;
    status: "complete" | "current" | "pending" | "blocked";
  }>;
  recommended_step: "review" | "approve" | "run" | "verify" | "manual_review";
  blockers: RemediationBlocker[];
  degradation: RemediationDegradation[];
  evidence: Array<Record<string, unknown>>;
  audit: {
    decisions: RemediationApprovalDecision[];
    executions: RemediationExecution[];
  };
}

export const remediationApi = {
  exposureHandoffs: (scope: ScopeSelection = {}) =>
    apiRequest<ExposureHandoffCollection>("/remediation/exposure-handoffs", {
      query: scopeToSearchParams(scope),
    }),
  createExposureHandoff: (
    payload: {
      exposure_id: string;
      reason: string;
      risk_acknowledged: boolean;
      risk_exception_id?: string;
    },
    scope: ScopeSelection = {},
  ) =>
    apiRequest<ExposureReviewHandoffResult>("/remediation/exposure-handoffs", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: {
        ...payload,
        risk_exception_id: payload.risk_exception_id ?? "",
      },
    }),
  plans: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<{ plans: RemediationPlanDetail[]; generated_at?: string }>("/remediation/plans", { query });
  },
  plan: (planId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationPlanDetail>(`/remediation/plans/${encodeURIComponent(planId)}`, {
      query: scopeToSearchParams(scope),
    }),
  workflow: (planId: string, scope: ScopeSelection = {}, patchIds: string[] = []) => {
    const query = scopeToSearchParams(scope);
    for (const id of patchIds) query.append("patch_id", id);
    return apiRequest<RemediationWorkflow>(`/remediation/plans/${encodeURIComponent(planId)}/workflow`, { query });
  },
  preview: (planId: string, scope: ScopeSelection = {}, patchIds: string[] = []) => {
    const query = scopeToSearchParams(scope);
    for (const id of patchIds) query.append("patch_id", id);
    return apiRequest<RemediationExecutionPreview>(`/remediation/plans/${encodeURIComponent(planId)}/preview`, { query });
  },
  approvals: (planId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationApprovalContext>(`/remediation/plans/${encodeURIComponent(planId)}/approvals`, {
      query: scopeToSearchParams(scope),
    }),
  businessDecision: (planId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationBusinessDecision>(`/remediation/plans/${encodeURIComponent(planId)}/business-decision`, {
      query: scopeToSearchParams(scope),
    }),
  approve: (
    planId: string,
    payload: {
      decision: RemediationDecision["decision"];
      reason: string;
      action_version: string;
      expires_at?: string;
      preview_snapshot_hash?: string;
      selected_patch_ids?: string[];
      /** Which single approval_requirements row (by role_id) this decision
       * attests (Phase 03.5 CR-05 fix). Required by the server whenever
       * more than one currently-unmet requirement row is eligible for the
       * calling principal to attest; omit/"" when at most one is
       * eligible. */
      role_id?: string;
    },
    scope: ScopeSelection = {},
  ) =>
    apiRequest<RemediationApprovalDecision>(`/remediation-plans/${encodeURIComponent(planId)}/decisions`, {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: {
        ...payload,
        expires_at: payload.expires_at ?? "",
        preview_snapshot_hash: payload.preview_snapshot_hash ?? "",
        selected_patch_ids: payload.selected_patch_ids ?? [],
        role_id: payload.role_id ?? "",
      },
    }),
  execute: (planId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/plans/${encodeURIComponent(planId)}/execute`, {
      method: "POST",
      query: scopeToSearchParams(scope),
    }),
  execution: (executionId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/executions/${encodeURIComponent(executionId)}`, {
      query: scopeToSearchParams(scope),
    }),
  executions: (planId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecutionList>(`/remediation/plans/${encodeURIComponent(planId)}/executions`, {
      query: scopeToSearchParams(scope),
    }),
  retry: (executionId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/executions/${encodeURIComponent(executionId)}/retry`, {
      method: "POST",
      query: scopeToSearchParams(scope),
    }),
  cancel: (executionId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/executions/${encodeURIComponent(executionId)}/cancel`, {
      method: "POST",
      query: scopeToSearchParams(scope),
    }),
  supersede: (executionId: string, reason: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/executions/${encodeURIComponent(executionId)}/supersede`, {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { reason },
    }),
};

// ---------------------------------------------------------------------------
// Network intelligence
// ---------------------------------------------------------------------------

export const networkApi = {
  topology: (
    scope: ScopeSelection = {},
    options: { detail: "summary" | "full" } = { detail: "full" },
    requestOptions: { signal?: AbortSignal } = {},
  ) => {
    const query = scopeToSearchParams(scope);
    query.set("detail", options.detail);
    return apiRequest<{ topology: NetworkTopology; summary: NetworkSummary }>(
      "/network/topology",
      { query, signal: requestOptions.signal },
    );
  },

  summary: (scope: ScopeSelection = {}) =>
    apiRequest<NetworkSummary>("/network/summary", { query: scopeToSearchParams(scope) }),

  /** "What depends on the hub?" */
  hubDependents: (vnetId: string, scope: ScopeSelection = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("vnet_id", vnetId);
    return apiRequest<HubDependents>("/network/topology/hubs/dependents", {
      query,
    });
  },

  topologyResourceDetails: (
    resourceId: string,
    scope: ScopeSelection = {},
    offset = 0,
    limit = 50,
  ) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    const resourcePath = resourceId
      .split("/")
      .filter(Boolean)
      .map((segment) => encodeURIComponent(segment))
      .join("/");
    return apiRequest<NetworkTopologyResourceDetails>(
      `/network/topology/resources/${resourcePath}/details`,
      { query },
    );
  },

  /** "Which spokes bypass the firewall?" */
  firewallBypass: (scope: ScopeSelection = {}) =>
    apiRequest<{ gaps: NetworkGap[]; count: number }>("/network/firewall-bypass", {
      query: scopeToSearchParams(scope),
    }),

  /** "Can UAT reach PROD, and which rules decide it?" A verdict of
   * `indeterminate` is a real answer and must not be shown as allowed. */
  trafficFlow: (params: {
    source: string;
    destination: string;
    port?: number;
    protocol?: string;
    environmentScope?: string;
    scope?: ScopeSelection;
  }) => {
    const query = scopeToSearchParams(params.scope ?? {});
    query.set("source", params.source);
    query.set("destination", params.destination);
    if (params.port != null) query.set("port", String(params.port));
    if (params.protocol) query.set("protocol", params.protocol);
    if (params.environmentScope) query.set("environment_scope", params.environmentScope);
    return apiRequest<FlowResult>("/network/traffic-flow", { query });
  },

  gaps: (
    scope: ScopeSelection = {},
    options: { severity?: NetworkSeverity; category?: string; offset?: number; limit?: number } = {},
  ) => {
    const query = scopeToSearchParams(scope);
    if (options.severity) query.set("severity", options.severity);
    if (options.category) query.set("category", options.category);
    if (options.offset != null) query.set("offset", String(options.offset));
    if (options.limit != null) query.set("limit", String(options.limit));
    return apiRequest<{
      gaps: NetworkGap[];
      intended_design_declared: boolean;
      summary: NetworkSummary;
      coverage?: import("./types").CollectionCoverage;
    }>(
      "/network/gaps",
      { query }
    );
  },

  ruleFindings: (
    scope: ScopeSelection = {},
    options: { severity?: NetworkSeverity; category?: string; offset?: number; limit?: number } = {},
  ) => {
    const query = scopeToSearchParams(scope);
    if (options.severity) query.set("severity", options.severity);
    if (options.category) query.set("category", options.category);
    if (options.offset != null) query.set("offset", String(options.offset));
    if (options.limit != null) query.set("limit", String(options.limit));
    return apiRequest<{
      findings: RuleFinding[];
      summary: NetworkSummary;
      coverage?: import("./types").CollectionCoverage;
    }>("/network/rule-findings", { query });
  },

  /** The rule-based, UI-editable design policy gap analysis is checked against. */
  policy: (scope: ScopeSelection = {}) =>
    apiRequest<NetworkDesignPolicy>("/network/policy", { query: scopeToSearchParams(scope) }),

  updatePolicy: (changes: Record<string, unknown>) =>
    apiRequest<NetworkDesignPolicy>("/network/policy", {
      method: "PATCH",
      body: changes,
    }),

  previewPolicy: (changes: Record<string, unknown>, scope: ScopeSelection = {}) =>
    apiRequest<{ policy: NetworkDesignPolicy; gaps: NetworkGap[]; summary: NetworkSummary }>("/network/policy/preview", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: changes,
    }),
};

export const vulnerabilityApi = {
  exposureItems: (
    queryState: ExposureQueryState,
    options: { signal?: AbortSignal } = {},
  ): Promise<ExposureEnvelope<ExposurePage>> =>
    apiRequest<ExposurePage, import("./types").ExposureCursorPagination>(
      "/vulnerabilities/exposure/items",
      {
        query: toExposureApiSearchParams(queryState),
        signal: options.signal,
      },
    ),
  exposureOverview: (
    queryState: ExposureQueryState,
    options: { signal?: AbortSignal } = {},
  ): Promise<ExposureEnvelope<ExposureOverview>> =>
    apiRequest<ExposureOverview, import("./types").ExposureCursorPagination>(
      "/vulnerabilities/exposure/overview",
      {
        query: toExposureApiSearchParams(queryState, {
          includePagination: false,
          includeSort: false,
        }),
        signal: options.signal,
      },
    ),
  exposureFacets: (
    queryState: ExposureQueryState,
    facets: Array<
      | "severity"
      | "target_kind"
      | "source_family"
      | "sla_state"
      | "completeness"
      | "current_state"
    > = [],
    options: { signal?: AbortSignal } = {},
  ): Promise<ExposureEnvelope<ExposureFacets>> => {
    const query = toExposureApiSearchParams(queryState, {
      includePagination: false,
      includeSort: false,
    });
    for (const facet of facets) query.append("facet", facet);
    return apiRequest<ExposureFacets, import("./types").ExposureCursorPagination>(
      "/vulnerabilities/exposure/facets",
      { query, signal: options.signal },
    );
  },
  exposureCatalog: (scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<ExposureQueryCatalog>("/vulnerabilities/exposure/catalog", {
      query: scopeToSearchParams(scope),
      signal: options.signal,
    }),
  exposureExternalCatalog: <TItem = Record<string, unknown>>(
    weaknessId: string,
    scope: ScopeSelection = {},
    options: { signal?: AbortSignal } = {},
  ) =>
    apiRequest<ExposureExternalCatalog<TItem>>(
      `/vulnerabilities/exposure/external-catalog/${encodeURIComponent(weaknessId)}`,
      {
        query: scopeToSearchParams(scope),
        signal: options.signal,
      },
    ),
  summary: (scope: ScopeSelection = {}) =>
    apiRequest<VulnerabilitySummary>("/vulnerabilities/summary", { query: scopeToSearchParams(scope) }),
  exposures: (scope: ScopeSelection = {}, filters?: { q?: string; reachableOnly?: boolean }) => {
    const query = scopeToSearchParams(scope);
    if (filters?.q) query.set("q", filters.q);
    if (filters?.reachableOnly) query.set("reachable_only", "true");
    return apiRequest<VulnerabilityExposure[]>("/vulnerabilities/exposures", { query });
  },
  authoritativeExposures: (
    scope: ScopeSelection = {},
    filters?: { q?: string; reachableOnly?: boolean },
  ) => {
    const query = scopeToSearchParams(scope);
    if (filters?.q) query.set("q", filters.q);
    if (filters?.reachableOnly) query.set("reachable_only", "true");
    return apiRequest<ExposureCollection>("/vulnerabilities/exposures", { query });
  },
  patchPriorities: (scope: ScopeSelection = {}, filters?: { q?: string; reachableOnly?: boolean }) => {
    const query = scopeToSearchParams(scope);
    if (filters?.q) query.set("q", filters.q);
    if (filters?.reachableOnly) query.set("reachable_only", "true");
    return apiRequest<PatchPriority[]>("/vulnerabilities/patch-priorities", { query });
  },
  assetExposures: (scope: ScopeSelection = {}, filters?: { q?: string; reachableOnly?: boolean }) => {
    const query = scopeToSearchParams(scope);
    if (filters?.q) query.set("q", filters.q);
    if (filters?.reachableOnly) query.set("reachable_only", "true");
    return apiRequest<AssetExposure[]>("/vulnerabilities/asset-exposures", { query });
  },
  defenderPosture: (scope: ScopeSelection = {}, q?: string) => {
    const query = scopeToSearchParams(scope);
    if (q) query.set("q", q);
    return apiRequest<DefenderPostureFinding[]>("/vulnerabilities/defender-posture", { query });
  },
  containerImageExposures: (scope: ScopeSelection = {}, q?: string) => {
    const query = scopeToSearchParams(scope);
    if (q) query.set("q", q);
    return apiRequest<ContainerImageExposure[]>("/vulnerabilities/container-image-exposures", { query });
  },
  defenderOverview: (scope: ScopeSelection = {}) =>
    apiRequest<DefenderOverview>("/defender/overview", { query: scopeToSearchParams(scope) }),
  defenderAlerts: (scope: ScopeSelection = {}, activeOnly = true) => {
    const query = scopeToSearchParams(scope);
    query.set("active_only", String(activeOnly));
    return apiRequest<DefenderAlert[]>("/defender/alerts", { query });
  },
  defenderAttackPaths: (scope: ScopeSelection = {}) =>
    apiRequest<DefenderAttackPath[]>("/defender/attack-paths", { query: scopeToSearchParams(scope) }),
  defenderSecureScore: (scope: ScopeSelection = {}) =>
    apiRequest<DefenderSecureScore[]>("/defender/secure-score", { query: scopeToSearchParams(scope) }),
  defenderSecureScoreControls: (scope: ScopeSelection = {}) =>
    apiRequest<DefenderSecureScoreControl[]>("/defender/secure-score-controls", {
      query: scopeToSearchParams(scope),
    }),
  cves: (scope: ScopeSelection = {}, q?: string) => {
    const query = scopeToSearchParams(scope);
    if (q) query.set("q", q);
    return apiRequest<CveDetail[]>("/cves", { query });
  },
  cve: (
    id: string,
    scope: ScopeSelection = {},
    options: { signal?: AbortSignal } = {},
  ) =>
    apiRequest<CveDetail>(`/cves/${encodeURIComponent(id)}`, {
      query: scopeToSearchParams(scope),
      signal: options.signal,
    }),
  riskExceptions: (scope: ScopeSelection = {}) =>
    apiRequest<RiskException[]>("/vulnerabilities/risk-exceptions", {
      query: scopeToSearchParams(scope),
    }),
  acceptRisk: (payload: { cve_id: string; server_id?: string; reason: string; approved_by?: string; expires_at?: string }) =>
    apiRequest<RiskException>("/vulnerabilities/risk-exceptions", { method: "POST", body: payload }),
  revokeRiskException: (exceptionId: string) =>
    apiRequest<void>(`/vulnerabilities/risk-exceptions/${encodeURIComponent(exceptionId)}`, { method: "DELETE" }),
  slaCompliance: (scope: ScopeSelection = {}) =>
    apiRequest<SlaComplianceReport>("/vulnerabilities/sla-compliance", { query: scopeToSearchParams(scope) }),
  attackPath: (
    cveId: string,
    scope: ScopeSelection = {},
    options: { signal?: AbortSignal } = {},
  ) =>
    apiRequest<AttackPathGraph>(`/cves/${encodeURIComponent(cveId)}/attack-path`, {
      query: scopeToSearchParams(scope),
      signal: options.signal,
    }),
};

/**
 * Read-only patch inventory and historical runs. All mutation is routed
 * through approval-bound remediation execution.
 */
export const patchingApi = {
  targets: (scope: ScopeSelection = {}) =>
    apiRequest<PatchTarget[]>("/patching/targets", { query: scopeToSearchParams(scope) }),
  target: (targetId: string, scope: ScopeSelection = {}) =>
    apiRequest<PatchTarget>(`/patching/targets/${encodeURIComponent(targetId)}`, {
      query: scopeToSearchParams(scope),
    }),
  runs: (scope: ScopeSelection = {}) =>
    apiRequest<PatchRun[]>("/patching/runs", { query: scopeToSearchParams(scope) }),
};

/**
 * Compliance posture: policy/security baseline deviations, configuration
 * drift, and change-authorization findings from `ChangeIntelligence`. Unlike
 * the network/vulnerability derived view this previously replaced, these
 * come from evidence-backed ontology entities (`PolicyDeviation`,
 * `SecurityDeviation`, `ConfigurationDrift`).
 */
export const complianceApi = {
  posture: (scope: ScopeSelection = {}) =>
    apiRequest<ComplianceResourcePosture[]>("/compliance/posture", { query: scopeToSearchParams(scope) }),
  policyDeviations: (scope: ScopeSelection = {}) =>
    apiRequest<ComplianceDeviation[]>("/compliance/policy-deviations", { query: scopeToSearchParams(scope) }),
  securityDeviations: (scope: ScopeSelection = {}) =>
    apiRequest<ComplianceDeviation[]>("/compliance/security-deviations", { query: scopeToSearchParams(scope) }),
  configurationDrift: (scope: ScopeSelection = {}) =>
    apiRequest<ComplianceResourcePosture[]>("/compliance/configuration-drift", { query: scopeToSearchParams(scope) }),
  summary: (scope: ScopeSelection = {}) =>
    apiRequest<ComplianceSummary>("/compliance/summary", { query: scopeToSearchParams(scope) }),
};

export const twinApi = {
  query: (q = "", scope: ScopeSelection = {}) => {
    const query = scopeToSearchParams(scope);
    if (q) query.set("q", q);
    return apiRequest<TwinQueryResult>("/twin", { query });
  },
  graph: (scope: ScopeSelection = {}) =>
    apiRequest<TwinSnapshot>("/twin/graph", { query: scopeToSearchParams(scope) }),
  timeline: (scope: ScopeSelection = {}) =>
    apiRequest<Pick<TwinSnapshot, "version" | "observed_at" | "timeline"> & TwinSnapshot["temporal"]>(
      "/twin/timeline",
      { query: scopeToSearchParams(scope) }
    ),
  compare: (scope: ScopeSelection = {}) =>
    apiRequest<TwinComparison>("/twin/compare", { query: scopeToSearchParams(scope) }),
  scenario: (scenario: string, target: string, scope: ScopeSelection = {}) =>
    apiRequest<TwinScenarioResult>("/twin/scenarios", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { scenario, target },
    }),
  traverse: (resourceId: string, scope: ScopeSelection = {}) =>
    apiRequest<TwinTraversal>(`/twin/traverse/${encodeURIComponent(resourceId)}`, {
      query: scopeToSearchParams(scope),
    }),
  export: (scope: ScopeSelection = {}) =>
    apiRequest<TwinExport>("/twin/export", { query: scopeToSearchParams(scope) }),
};

export const multiAgentApi = {
  catalog: (scope: ScopeSelection = {}) =>
    apiRequest<{ agents: AutonomousAgent[] }>("/agents/catalog", { query: scopeToSearchParams(scope) }),
  investigate: (objective: string, scope: ScopeSelection = {}, timeoutSeconds = 8) =>
    apiRequest<MultiAgentLedger>("/agents/investigations", {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { objective, timeout_seconds: timeoutSeconds },
    }),
  ledger: (ledgerId: string, scope: ScopeSelection = {}) =>
    apiRequest<MultiAgentLedger>(`/agents/investigations/${encodeURIComponent(ledgerId)}`, {
      query: scopeToSearchParams(scope),
    }),
  action: (ledgerId: string, action: string, payload: Record<string, unknown>, scope: ScopeSelection = {}) =>
    apiRequest<MultiAgentLedger>(`/agents/investigations/${encodeURIComponent(ledgerId)}/actions`, {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { action, payload },
    }),
};

export const kbApi = {
  detail: (
    kbId: string,
    scope: ScopeSelection = {},
    options: { signal?: AbortSignal } = {},
  ) =>
    apiRequest<KbDetail>(`/kbs/${encodeURIComponent(kbId)}`, {
      query: scopeToSearchParams(scope),
      signal: options.signal,
    }),
};

// ---------------------------------------------------------------------------
// Planned / contract-only endpoints (Prompt 17) — always 501 today.
// Exposed so UI code can call them and handle ApiError.isNotImplemented
// uniformly rather than special-casing "the route doesn't exist yet".
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
  semantic_snapshot_loaded: boolean;
  readiness: "ready" | "partial" | "stale" | "degraded";
  ontology_version: string;
  freshness: string;
  last_discovery_run: string;
  last_ontology_publication: string;
  degraded_reason: string;
  providers: Record<
    string,
    {
      configured: boolean;
      required: boolean;
      state: string;
      loaded: boolean;
      freshness: string;
      degraded_reason: string;
      retry: { attempts: number; next_retry_at: string };
    }
  >;
}

export const healthApi = {
  /** /health is a plain JSON dict, not an envelope — it must work before any snapshot is loaded. */
  health: async (): Promise<HealthResponse> => {
    const url = `${await resolveApiBaseUrl()}/health`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`health check failed: ${response.status}`);
    return (await response.json()) as HealthResponse;
  },
};

export const resourceHealthApi = {
  /** Live CPU/network/disk utilization for in-scope compute resources.
   * Requires an explicit subscription scope -- unlike most routes there is
   * no snapshot fallback, since a stale utilization reading would actively
   * mislead an operator. */
  snapshot: (scope: ScopeSelection = {}, forceRefresh = false) => {
    const query = scopeToSearchParams(scope);
    if (forceRefresh) query.set("force_refresh", "true");
    return apiRequest<ResourceHealthSnapshot>("/resource-health", { query });
  },
};


export type { Envelope };

/**
 * Governance surface: FinOps, identity risk, SPN posture, access reviews,
 * audit evidence, and enterprise administration. Every read carries the
 * global scope so the API applies subscription isolation server-side.
 */
export const governanceApi = {
  finopsSummary: (scope: ScopeSelection = {}) =>
    apiRequest<FinOpsSummary>("/governance/finops/summary", {
      query: scopeToSearchParams(scope),
    }),

  finopsOpportunities: (scope: ScopeSelection = {}) =>
    apiRequest<{ opportunities: SavingsOpportunity[]; count: number }>(
      "/governance/finops/opportunities",
      { query: scopeToSearchParams(scope) },
    ),

  finopsWaste: (scope: ScopeSelection = {}) =>
    apiRequest<{ waste: WasteItem[]; count: number }>("/governance/finops/waste", {
      query: scopeToSearchParams(scope),
    }),

  finopsAttribution: (dimension: string, scope: ScopeSelection = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("dimension", dimension);
    return apiRequest<{
      dimension: string;
      groups: FinOpsAttributionGroup[];
      count: number;
    }>("/governance/finops/attribution", { query });
  },

  identitySummary: (scope: ScopeSelection = {}) =>
    apiRequest<IdentitySummary>("/governance/identity/summary", {
      query: scopeToSearchParams(scope),
    }),

  identityPrincipals: (scope: ScopeSelection = {}) =>
    apiRequest<{ principals: PrincipalRisk[]; count: number }>(
      "/governance/identity/principals",
      { query: scopeToSearchParams(scope) },
    ),

  subscriptionOwners: (scope: ScopeSelection = {}) =>
    apiRequest<{ owners: SubscriptionOwnerRecord[]; count: number }>(
      "/governance/identity/subscription-owners",
      { query: scopeToSearchParams(scope) },
    ),

  staleAccess: (scope: ScopeSelection = {}) =>
    apiRequest<{ assignments: StaleAccessRecord[]; count: number }>(
      "/governance/identity/stale-access",
      { query: scopeToSearchParams(scope) },
    ),

  nonHumanIdentities: (scope: ScopeSelection = {}) =>
    apiRequest<{ identities: NonHumanIdentity[]; count: number }>(
      "/governance/identity/non-human",
      { query: scopeToSearchParams(scope) },
    ),

  spnCredentials: (scope: ScopeSelection = {}) =>
    apiRequest<{
      credentials: ServicePrincipalGovernance[];
      summary: SpnSummary;
      count: number;
    }>("/governance/spn/credentials", { query: scopeToSearchParams(scope) }),

  accessReviewKinds: () =>
    apiRequest<{ audiences: string[] }>("/governance/access-reviews"),

  accessReview: (audience: string, scope: ScopeSelection = {}) =>
    apiRequest<AccessReviewPack>(
      `/governance/access-reviews/${encodeURIComponent(audience)}`,
      { query: scopeToSearchParams(scope) },
    ),

  exportKinds: () => apiRequest<{ kinds: string[] }>("/governance/exports"),

  auditExport: (kind: string, scope: ScopeSelection = {}) =>
    apiRequest<AuditExportPack>(`/governance/exports/${encodeURIComponent(kind)}`, {
      query: scopeToSearchParams(scope),
    }),

  settings: (scope: ScopeSelection = {}) =>
    apiRequest<EnterpriseSettings>("/governance/settings", {
      query: scopeToSearchParams(scope),
    }),

  updateSettings: (payload: Record<string, unknown>) =>
    apiRequest<EnterpriseSettings>("/governance/settings", {
      method: "PATCH",
      body: payload,
    }),
};

/** Pre-deployment change risk and impact assessment. */
export const predeployApi = {
  sources: () => apiRequest<ChangeAssessmentSources>("/changes/assessment-sources"),

  assess: (source: string, payload: Record<string, unknown>, changeId = "") =>
    apiRequest<ChangeAssessment>("/changes/assess", {
      method: "POST",
      body: { source, payload, change_id: changeId },
    }),

  assessments: (scope: ScopeSelection = {}) =>
    apiRequest<{ assessments: ChangeAssessmentSummary[]; count: number }>(
      "/changes/assessments",
      { query: scopeToSearchParams(scope) },
    ),

  assessment: (assessmentId: string) =>
    apiRequest<ChangeAssessment>(
      `/changes/assessments/${encodeURIComponent(assessmentId)}`,
    ),
};

/** Durable Phase 1 situation reads; unlike the legacy incident API these IDs and records are persisted. */
export const situationsApi = {
  list: (scope: ScopeSelection = {}, query = "", priority = "", offset = 0, limit = 100) => {
    const params = scopeToSearchParams(scope);
    if (query) params.set("q", query);
    if (priority) params.set("priority", priority);
    params.set("offset", String(offset));
    params.set("limit", String(limit));
    return apiRequest<import("./types").DurableSituation[]>("/situations", { query: params });
  },
  get: (id: string, scope: ScopeSelection = {}) =>
    apiRequest<import("./types").DurableSituation>(`/situations/${encodeURIComponent(id)}`, {
      query: scopeToSearchParams(scope),
    }),
  audit: (id: string, scope: ScopeSelection = {}) =>
    apiRequest<import("./types").SituationAuditEvent[]>(`/situations/${encodeURIComponent(id)}/audit`, {
      query: scopeToSearchParams(scope),
    }),
  evidence: (id: string, scope: ScopeSelection = {}) =>
    apiRequest<import("./types").DurableEvidence>(`/evidence/${encodeURIComponent(id)}`, {
      query: scopeToSearchParams(scope),
    }),
};
