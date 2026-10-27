import { apiRequest, resolveApiBaseUrl } from "./api-client";
import type { ScopeSelection } from "./scope";
import { scopeToSearchParams } from "./scope";
import type { SavedView, SavedViewCollection } from "./saved-views";
import type {
  NetworkReviewReference,
  NetworkFindingReview,
  NetworkTopologyHistory,
  NetworkTopologyComparison,
  NetworkIntentSuite,
  NetworkIntentTest,
  BusinessMetadata,
  ChangeAssessment,
  ChangeObservationFeed,
  ChangeAssessmentSources,
  ChangeAssessmentSummary,
  ComplianceDeviation,
  ComplianceResourcePosture,
  ComplianceSummary,
  ComplianceDesignPolicy,
  CompliancePolicyState,
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
  FabricManifestSummary,
  TwinComparison,
  TwinExport,
  TwinQueryResult,
  TwinScenarioResult,
  TwinSnapshot,
  TwinTraversal,
  AutonomousAgent,
  MultiAgentLedger,
  FinOpsSummary,
  FinOpsVerifiedRemediation,
  FinOpsRemediationCostComparison,
  SavingsOpportunity,
  WasteItem,
  FinOpsAttributionGroup,
  IdentitySummary,
  IdentityLeastPrivilegeReview,
  PrincipalRisk,
  SubscriptionOwnerRecord,
  StaleAccessRecord,
  NonHumanIdentity,
  SpnSummary,
  ServicePrincipalGovernance,
  AccessReviewPack,
  AuditExportPack,
  EnterpriseSettings,
  EnterpriseSettingsChange,
  OsInventoryCollection,
  OsInventoryDetail,
  InventoryNarrative,
  OntologyAutomationStatus,
  OntologyAgentCapabilities,
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

/** Personal exact-scope navigation preferences; mutations do not query source providers. */
export const savedViewsApi = {
  read: (scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<SavedViewCollection>("/saved-views", {
      query: scopeToSearchParams(scope), signal: options.signal,
    }),
  replace: (scope: ScopeSelection, expectedRevision: number, views: SavedView[], options: { signal?: AbortSignal } = {}) =>
    apiRequest<SavedViewCollection>("/saved-views", {
      method: "PUT", query: scopeToSearchParams(scope), signal: options.signal,
      body: { expected_revision: expectedRevision, views },
    }),
};

export const overviewApi = {
  /** Recover exact-caller/scope observations without resolving active source providers. */
  history: (scope: ScopeSelection = {}) =>
    apiRequest<import("./types").OverviewHistory>("/overview/history", { query: scopeToSearchParams(scope) }),
  /** Capture fresh server reads, never client-supplied metrics, using history CAS. */
  capture: (scope: ScopeSelection, expected_revision: number) =>
    apiRequest<import("./types").OverviewHistory>("/overview/history", {
      method: "POST", query: scopeToSearchParams(scope), body: { expected_revision },
    }),
};

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
  /** Probe a proposed connection without storing its secret or starting a sync. */
  preflight: (payload: ConnectionCreateRequest) =>
    apiRequest<import("./types").ConnectionPreflightReport>("/subscription-connections/preflight", { method: "POST", body: payload }),

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
      gold_declarations?: import("./types").FabricGoldDeclarations;
    }>("/fabric-medallion/layers", {
      query: scopeToSearchParams(scope),
    }),

  dataset: (tableName: string, scope: ScopeSelection = {}) =>
    apiRequest<FabricDataset>(`/fabric-medallion/datasets/${encodeURIComponent(tableName)}`, {
      query: scopeToSearchParams(scope),
    }),

  /** Read a declared schema and recorded source diagnostics without probing or publishing data. */
  datasetContract: (tableName: string, scope: ScopeSelection = {}) =>
    apiRequest<import("./types").FabricDatasetContract>(`/fabric-medallion/datasets/${encodeURIComponent(tableName)}/contract`, {
      query: scopeToSearchParams(scope),
    }),

  manifest: (scope: ScopeSelection = {}) =>
    apiRequest<FabricManifestSummary>("/fabric-medallion/manifest", {
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
  /** Read the scoped native entry point without invoking an agent or a run. */
  agentCapabilities: (connectionId: string, scope: ScopeSelection) =>
    apiRequest<OntologyAgentCapabilities>("/ontology-discovery/agent-capabilities", {
      query: ontologyQuery(connectionId, scope),
    }),

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

/** Exact-principal, exact-scope durable export operations; every request reauthorizes. */
export const inventoryExportApi = {
  /** Recover this caller's exact effective-scope capture without the active provider. */
  current: (scope: ScopeSelection) =>
    apiRequest<{ export: import("./types").InventoryExportManifest | null }>("/inventory/exports/current", {
      query: scopeToSearchParams(scope),
    }),
  /** Capture only the publication generation the caller reviewed. */
  create: (scope: ScopeSelection, expectedGenerationId: string) =>
    apiRequest<{ export: import("./types").InventoryExportManifest }>("/inventory/exports", {
      method: "POST", query: scopeToSearchParams(scope),
      body: { expected_generation_id: expectedGenerationId },
    }),
  /** Read a repeatable aligned 500-row batch, with independent scope authorization. */
  batch: (scope: ScopeSelection, exportId: string, offset: number) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    return apiRequest<import("./types").InventoryExportBatch>(`/inventory/exports/${encodeURIComponent(exportId)}/batches`, { query });
  },
  /** Revoke future reads only if the capture still has the reviewed revision. */
  cancel: (scope: ScopeSelection, exportId: string, expectedRevision: number) =>
    apiRequest<{ export: import("./types").InventoryExportManifest }>(`/inventory/exports/${encodeURIComponent(exportId)}/cancel`, {
      method: "POST", query: scopeToSearchParams(scope), body: { expected_revision: expectedRevision },
    }),
};

export const inventoryApi = {
  /** Filter authorized OS groups before the server selects a page. */
  os: (scope: ScopeSelection = {}, offset = 0, limit = 100, filters: Record<string, string> = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
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
  /** Query installation groups at their own grain, not asset-list counts. */
  software: (scope: ScopeSelection = {}, offset = 0, limit = 100, filters: Record<string, string> = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
    return apiRequest<SoftwareInventoryCollection>("/inventory/software", { query });
  },
  softwareGroup: (key: string, scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<SoftwareInventoryDetail>(`/inventory/software/${encodeURIComponent(key)}`, { query });
  },
  /** Query complete authorized resource-type/SKU/tier groups and facets. */
  paas: (scope: ScopeSelection = {}, offset = 0, limit = 200, filters: Record<string, string> = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
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
  resources: (scope: ScopeSelection = {}, offset = 0, limit = 500, filters: import("./types").InventoryResourceQuery = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    Object.entries(filters).forEach(([key, value]) => { if (value) query.set(key, value); });
    return apiRequest<import("./types").FlatResourceCollection>("/inventory/resources", { query });
  },
  /** Resolve an exact identity using the caller's current effective scope. */
  asset: (resourceId: string, scope: ScopeSelection = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("resource_id", resourceId);
    return apiRequest<{ resource: import("./types").InventoryAsset; generation_id: string; query_version: string }>("/inventory/asset", { query });
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

/** Retained service portfolio reads and server-side acquisitions; counts cannot be submitted. */
/** Explicit exact-scope component targets and resource-context aggregate telemetry. */
export const serviceReliabilityApi = {
  /** Recover declarations without a current component or telemetry read. */
  objectives: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./service-reliability").ServiceObjectivePolicy>("/service-reliability/objectives", { query: scopeToSearchParams(scope), signal }),
  /** Search one page of currently authorized published component mappings. */
  components: (scope: ScopeSelection, q: string, offset: number, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("q", q); query.set("offset", String(offset)); query.set("limit", "25");
    return apiRequest<{ components: import("./service-reliability").ServiceComponent[] }>("/service-reliability/components", { query, signal });
  },
  /** Save one explicit administrator target against the reviewed revision. */
  save: (scope: ScopeSelection, objective: Pick<import("./service-reliability").ServiceObjective, "resource_id" | "success_target_basis_points" | "window_hours">, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./service-reliability").ServiceObjectivePolicy>("/service-reliability/objectives", {
      method: "PUT", query: scopeToSearchParams(scope), body: { ...objective, expected_revision: expectedRevision }, signal,
    }),
  /** Remove only the identified declaration, never its Azure resource. */
  remove: (scope: ScopeSelection, resourceId: string, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./service-reliability").ServiceObjectivePolicy>("/service-reliability/objectives/remove", {
      method: "POST", query: scopeToSearchParams(scope), body: { resource_id: resourceId, expected_revision: expectedRevision }, signal,
    }),
  /** Request fresh aggregate telemetry under the server-authorized saved objective. */
  metrics: (scope: ScopeSelection, resourceId: string, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope); query.set("resource_id", resourceId);
    return apiRequest<import("./service-reliability").ServiceRequestMetrics>("/service-reliability/metrics", { query, signal });
  },
};

export const servicePortfolioApi = {
  history: (scope: ScopeSelection = {}) =>
    apiRequest<import("./types").ServicePortfolioHistory>("/service-portfolio/history", { query: scopeToSearchParams(scope) }),
  capture: (scope: ScopeSelection, expectedRevision: number) =>
    apiRequest<import("./types").ServicePortfolioHistory>("/service-portfolio/history", {
      method: "POST", query: scopeToSearchParams(scope), body: { expected_revision: expectedRevision },
    }),
};

export const contextApi = {
  /** Inspect configuration prerequisites without hydrating deferred providers. */
  searchCapabilities: (scope: ScopeSelection = {}) =>
    apiRequest<import("./types").SearchCapabilities>("/search/capabilities", { query: scopeToSearchParams(scope) }),
  search: (q: string, scope: ScopeSelection = {}, exploration?: {
    offset: number; limit: number; entity_type: string; source: string;
  }) => {
    const query = scopeToSearchParams(scope);
    query.set("q", q);
    if (exploration) {
      query.set("offset", String(exploration.offset));
      query.set("limit", String(exploration.limit));
      if (exploration.entity_type) query.set("entity_type", exploration.entity_type);
      if (exploration.source) query.set("source", exploration.source);
    }
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
  agent_version?: string;
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
  status: "ok" | "partial" | "empty" | "unavailable" | "denied";
  data: unknown;
  evidence: EvidenceItem[];
  warning: string;
}

/** The outcome of a `/copilot/investigate` turn: every tool call plus the narration. */
export interface CopilotInvestigation extends CanonicalInvestigationSemantics {
  request_key?: string;
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
  signal?: AbortSignal,
): Promise<Envelope<CanonicalCopilotResult>> {
  return apiRequest<CanonicalCopilotResult>("/copilot/investigations", {
    method: "POST",
    query: scopeToSearchParams(scope),
    body: request,
    signal,
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
  /** Discover a bounded authorized storage page, never execute or renew threads. */
  retainedThreads: (scope: ScopeSelection, page = 0, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("page", String(page));
    return apiRequest<import("./types").RetainedCopilotThreads>("/copilot/threads", { query, signal });
  },
  /** Inspect one exact admitted request without polling or redispatching work. */
  requestReceipt: (requestKey: string, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").CopilotRequestReceipt>(`/copilot/requests/${encodeURIComponent(requestKey)}`, { query: scopeToSearchParams(scope), signal }),
  /** Read exact authorized historical turns without renewing or executing a thread. */
  retainedHistory: (threadId: string, scope: ScopeSelection, options: { signal?: AbortSignal; expectedRevision?: number } = {}) => {
    const query = scopeToSearchParams(scope);
    if (options.expectedRevision !== undefined) query.set("expected_revision", String(options.expectedRevision));
    return apiRequest<import("./types").RetainedCopilotHistory>(`/copilot/threads/${encodeURIComponent(threadId)}/history`, {
      query, signal: options.signal,
    });
  },
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
  options: { sessionId?: string; tool?: string; toolArguments?: Record<string, unknown>; signal?: AbortSignal; requestKey?: string; continuation?: { threadId: string; threadRevision: number } } = {},
): Promise<Envelope<CopilotInvestigation>> {
  return apiRequest<CopilotInvestigation>("/copilot/investigate", {
    method: "POST",
    signal: options.signal,
    query: scopeToSearchParams(scope),
    body: {
      question,
      session_id: options.sessionId ?? ROOT_COPILOT_SESSION,
      tool: options.tool ?? "",
      tool_arguments: options.toolArguments ?? {},
      ...(options.requestKey ? { request_key: options.requestKey } : {}),
      ...(options.continuation ? { thread_id: options.continuation.threadId, expected_thread_revision: options.continuation.threadRevision } : {}),
    },
  });
}

/** Display-ready projection of a canonical turn, shared across surfaces. */
export interface CanonicalInvestigationView {
  toolCalls: CopilotToolCall[];
  narration: CopilotAnswer | null;
  narrationMode: "foundry" | "deterministic";
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

/** Returns only grounded retained answers with explicit deterministic or complete provider provenance. */
export function retainedCopilotAnswer(
  synthesis: CanonicalInvestigationSynthesis | null | undefined,
): CopilotAnswer | null {
  const answer = synthesis?.status === "compatibility" ? synthesis.compatibility_answer : null;
  if (answer?.grounded !== true || !answer.text.trim() || !answer.model.trim()) return null;
  if (answer.model.trim().toLowerCase() !== "deterministic"
    && (!answer.agent_name.trim() || !answer.agent_version?.trim())) return null;
  return answer;
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
export function toCanonicalInvestigationView(
  data: CopilotInvestigation | CanonicalCopilotResult,
): CanonicalInvestigationView {
  const canonical = "tool_results" in data;
  const synthesis = data.synthesis ?? null;
  const hasCitedClaims = Boolean(synthesis?.claims.length);
  const narrationText = hasCitedClaims
    ? synthesis!.claims.map((claim) => claim.summary.trim()).filter(Boolean).join(" ")
    : "";
  const compatibilityAnswer = canonical ? retainedCopilotAnswer(synthesis) : data.answer;
  const narration: CopilotAnswer | null = compatibilityAnswer
    ?? (narrationText
      ? {
          text: narrationText,
          agent_name: synthesis?.status === "synthesized"
            ? synthesis.coordinator?.name ?? "Executive synthesis"
            : "Deterministic page evidence",
          model: synthesis?.status === "synthesized"
            ? synthesis.coordinator?.version
              ? `Foundry · v${synthesis.coordinator.version}`
              : "Canonical"
            : "Deterministic",
          grounded: true,
        }
      : null);
  const policyStatus = data.policy_status ?? "accepted";
  const fallbackReason = data.fallback_reason ?? "";
  const retainedFoundry = Boolean(compatibilityAnswer?.grounded === true
    && compatibilityAnswer.model.trim()
    && compatibilityAnswer.model.trim().toLowerCase() !== "deterministic"
    && compatibilityAnswer.agent_name.trim() && compatibilityAnswer.agent_version?.trim());
  const degraded = (policyStatus === "fallback" && !retainedFoundry) || synthesis?.status === "degraded";
  const degradationNote = synthesis?.warning?.trim()
    || (policyStatus === "fallback" && !retainedFoundry
      ? "Deterministic specialist evidence is shown; Foundry narration was not produced."
      : "");
  return {
    toolCalls: canonical
      ? data.tool_results.map((call) => ({
          tool: call.tool,
          arguments: {},
          status: call.status,
          data: call.data,
          evidence: [],
          warning: call.warning,
        }))
      : data.tool_calls ?? [],
    narration,
    narrationMode: retainedFoundry || synthesis?.status === "synthesized" ? "foundry" : "deterministic",
    policyStatus,
    fallbackReason,
    degraded,
    degradationNote,
    citations: data.citations ?? [],
    uncertainty: Array.from(new Set(
      canonical ? data.uncertainty : data.warnings ?? [],
    )),
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
  /** Read independent governed changes without accepting filter overrides of the authorized scope. */
  changeObservations: (scope: ScopeSelection, filters: Record<string, string>, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    for (const key of ["q", "category", "source", "since", "until", "order", "offset", "limit"]) {
      if (filters[key]) query.set(key, filters[key]);
    }
    return apiRequest<ChangeObservationFeed>("/changes/observations", { query, signal });
  },
  incidents: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<IncidentReport>("/incidents", { query });
  },
  incident: (id: string, scope: ScopeSelection = {}) =>
    apiRequest<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`, { query: scopeToSearchParams(scope) }),
  remediationPlans: (scope: ScopeSelection = {}, offset = 0, limit = 100, resourceKey = "", context?: { cve: string; kb: string }) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    if (resourceKey) query.set("resource_key", resourceKey);
    if (context?.cve) query.set("cve", context.cve);
    if (context?.kb) query.set("kb", context.kb);
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
  reboot_required?: boolean | null;
  published_at?: string;
  source?: string;
  node_pool?: string;
  current_version?: string;
  target_version?: string;
}

export interface RemediationExecutionSnapshot {
  rollout?: { rollout_id: string; terms_hash: string; wave: number };
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
    remediation_context?: RemediationPlan["remediation_context"];
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

export interface RemediationProviderReview {
  kind: "az_cli_execution";
  execution_id: string;
  status: string;
  command: string;
  required_scopes?: string | string[] | null;
}

export interface RemediationExecution {
  execution_id: string;
  approval_decision_id?: string;
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
  can_abandon?: boolean;
  abandon_ineligibility_reason?: string;
  abandoned?: boolean;
  provider_cancelled?: boolean;
  verification_deadline_at?: string;
  next_verification_at?: string;
  verification_attempts?: number;
  evidence_reconciliation?: RemediationEvidenceReconciliation;
  verification_evidence?: Record<string, unknown>;
  provider_review?: RemediationProviderReview | null;
  provider_reviewable?: boolean;
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
  /** Read stored outcome notifications without polling providers or changing verification. */
  notifications: (scope: ScopeSelection, kind: "" | "attention" | "complete" | "cancelled" = "", offset = 0, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset)); query.set("limit", "25");
    if (kind) query.set("kind", kind);
    return apiRequest<import("./remediation-notifications").RemediationNotificationInbox>("/remediation/verification-inbox", { query, signal });
  },
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
  approveProviderReview: (executionId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(
      `/remediation/executions/${encodeURIComponent(executionId)}/provider-review/approve`,
      {
        method: "POST",
        query: scopeToSearchParams(scope),
      },
    ),
  supersede: (executionId: string, reason: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/executions/${encodeURIComponent(executionId)}/supersede`, {
      method: "POST",
      query: scopeToSearchParams(scope),
      body: { reason },
    }),
  abandon: (executionId: string, scope: ScopeSelection = {}) =>
    apiRequest<RemediationExecution>(`/remediation/executions/${encodeURIComponent(executionId)}/abandon`, {
      method: "POST",
      query: scopeToSearchParams(scope),
    }),
};

// ---------------------------------------------------------------------------
// Network intelligence
// ---------------------------------------------------------------------------

export const networkApi = {
  /** Reauthorize exact current finding evidence without writing or generating a fix. */
  review: (scope: ScopeSelection, reference: NetworkReviewReference, options: { signal?: AbortSignal } = {}) => {
    const query = scopeToSearchParams(scope);
    Object.entries(reference).forEach(([key, value]) => query.set(key, value));
    return apiRequest<NetworkFindingReview>("/network/review", { query, signal: options.signal });
  },
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

  /** Read personal saved declarations and receipts without current Network acquisition. */
  intents: (scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<NetworkIntentSuite>("/network/intents", {
      query: scopeToSearchParams(scope), signal: options.signal,
    }),

  /** Replace only reviewed declarations; this does not change network policy. */
  saveIntents: (
    scope: ScopeSelection, expectedRevision: number, tests: NetworkIntentTest[],
    options: { signal?: AbortSignal } = {},
  ) => apiRequest<NetworkIntentSuite>("/network/intents", {
    method: "PUT", query: scopeToSearchParams(scope), signal: options.signal,
    body: { expected_revision: expectedRevision, tests },
  }),

  /** Explicitly analyze the saved reviewed suite, never browser-submitted results. */
  runIntents: (
    scope: ScopeSelection, expectedRevision: number, options: { signal?: AbortSignal } = {},
  ) => apiRequest<NetworkIntentSuite>("/network/intents/run", {
    method: "POST", query: scopeToSearchParams(scope), signal: options.signal,
    body: { expected_revision: expectedRevision },
  }),

  /** Read retained safe topology projections, never implicitly capture current data. */
  topologyHistory: (scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<NetworkTopologyHistory>("/network/topology/history", {
      query: scopeToSearchParams(scope), signal: options.signal,
    }),

  /** Retain one currently authorized server projection at the reviewed revision. */
  captureTopology: (
    scope: ScopeSelection, expectedRevision: number, options: { signal?: AbortSignal } = {},
  ) => apiRequest<NetworkTopologyHistory>("/network/topology/history", {
    method: "POST", query: scopeToSearchParams(scope), signal: options.signal,
    body: { expected_revision: expectedRevision },
  }),

  /** Compare only the selected retained captures with bounded server paging. */
  compareTopology: (
    scope: ScopeSelection, baselineId: string, targetId: string, offset = 0,
    options: { signal?: AbortSignal } = {},
  ) => {
    const query = scopeToSearchParams(scope);
    query.set("baseline_id", baselineId); query.set("target_id", targetId);
    query.set("offset", String(offset)); query.set("limit", "50");
    return apiRequest<NetworkTopologyComparison>("/network/topology/history/compare", {
      query, signal: options.signal,
    });
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
  /** Read exact-principal/scope retained aggregates without current source acquisition. */
  exposureHistory: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").ExposureHistory>("/vulnerabilities/exposure/history", {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Explicitly reacquire server aggregates and append against the reviewed history revision. */
  captureExposureObservation: (scope: ScopeSelection, expectedRevision: number, generation?: string) =>
    apiRequest<import("./types").ExposureHistory>("/vulnerabilities/exposure/history", {
      method: "POST", query: scopeToSearchParams(scope),
      body: { expected_revision: expectedRevision, ...(generation ? { generation } : {}) },
    }),
  /** Read retained-evidence candidates and personal workflow declarations, without providers. */
  exposureRecovery: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").ExposureRecoveryState>("/vulnerabilities/exposure/recovery", {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Append one explicit revision-bound review declaration; never repairs sources. */
  reviewExposureRecovery: (scope: ScopeSelection, review: import("./types").ExposureRecoveryReview) =>
    apiRequest<import("./types").ExposureRecoveryState>("/vulnerabilities/exposure/recovery", {
      method: "POST", query: scopeToSearchParams(scope), body: review,
    }),
  /** Read personal immutable patch-review snapshots without current provider acquisition. */
  patchReviews: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").PatchReviewHistory>("/vulnerabilities/exposure/patch-reviews", { query: scopeToSearchParams(scope), signal }),
  /** Reacquire and retain selected finding identities, never executing a patch. */
  createPatchReview: (query: ExposureQueryState, expectedRevision: number, exposureIds: string[], owner: string, note: string) =>
    apiRequest<import("./types").PatchReviewHistory>("/vulnerabilities/exposure/patch-reviews", {
      method: "POST", query: scopeToSearchParams(query.scope),
      body: {
        expected_revision: expectedRevision, generation: query.generation, cursor: query.cursor,
        page_size: query.pageSize, sort_by: query.sort.field, sort_direction: query.sort.direction,
        filters: query.filters, exposure_ids: exposureIds, owner, note,
      },
    }),
  exposureCatalog: (scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<ExposureQueryCatalog>("/vulnerabilities/exposure/catalog", {
      query: scopeToSearchParams(scope),
      signal: options.signal,
    }),
  /** Read personal retained CVE receipts without acquiring current sources. */
  cveEvidence: (cveId: string, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").CveEvidenceHistory>(`/cves/${encodeURIComponent(cveId)}/evidence`, { query: scopeToSearchParams(scope), signal }),
  /** Reacquire one authorized page/catalog pair; never accepts client evidence. */
  captureCveEvidence: (cveId: string, query: ExposureQueryState, expectedRevision: number) =>
    apiRequest<import("./types").CveEvidenceHistory>(`/cves/${encodeURIComponent(cveId)}/evidence`, {
      method: "POST", query: scopeToSearchParams(query.scope),
      body: { expected_revision: expectedRevision, generation: query.generation, cursor: query.cursor,
        page_size: query.pageSize, sort_by: query.sort.field, sort_direction: query.sort.direction, filters: query.filters },
    }),
  /** Reauthorize exact retained bytes before client checksum verification/download. */
  cveEvidenceBundle: (cveId: string, receiptId: string, scope: ScopeSelection) =>
    apiRequest<import("./types").CveEvidenceBundle>(`/cves/${encodeURIComponent(cveId)}/evidence/${encodeURIComponent(receiptId)}`, {
      query: scopeToSearchParams(scope),
    }),
  exposureExternalCatalog: <TItem = Record<string, unknown>>(
    weaknessId: string,
    scope: ScopeSelection = {},
    options: { signal?: AbortSignal; generation?: string } = {},
  ) =>
    {
      const query = scopeToSearchParams(scope);
      if (options.generation) query.set("generation", options.generation);
      return apiRequest<
        ExposureExternalCatalog<TItem>,
        import("./types").ExposureCursorPagination
      >(
        `/vulnerabilities/exposure/external-catalog/${encodeURIComponent(weaknessId)}`,
        {
          query,
          signal: options.signal,
        },
      );
    },
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
  /** Read the exact selected scope's durable assessment policy and decisions. */
  designPolicy: (scope: ScopeSelection = {}) =>
    apiRequest<CompliancePolicyState>("/compliance/design-policy", { query: scopeToSearchParams(scope) }),
  /** Replace a reviewed policy only if its revision is still current. */
  saveDesignPolicy: (expected_revision: number, policy: ComplianceDesignPolicy, reason: string, scope: ScopeSelection = {}) =>
    apiRequest<CompliancePolicyState>("/compliance/design-policy", {
      method: "PUT", query: scopeToSearchParams(scope), body: { expected_revision, policy, reason },
    }),
  /** Record a revision-bound architecture risk decision with server actor identity. */
  decideException: (body: { expected_revision: number; action: "accept" | "revoke"; violationId: string; owner: string; reason: string; expiresAt: string }, scope: ScopeSelection = {}) =>
    apiRequest<CompliancePolicyState>("/compliance/design-policy/exceptions", {
      method: "POST", query: scopeToSearchParams(scope), body,
    }),
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
  /** Recover exact personal retained captures without current provider acquisition. */
  snapshots: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./twin-history").TwinHistory>("/twin/snapshots", { query: scopeToSearchParams(scope), signal }),
  /** Explicitly capture a fresh server projection, not the previously displayed graph. */
  captureSnapshot: (scope: ScopeSelection, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./twin-history").TwinHistory>("/twin/snapshots", {
      method: "POST", query: scopeToSearchParams(scope), body: { expected_revision: expectedRevision }, signal,
    }),
  /** Explicit removal from a reviewed history revision; source observations are untouched. */
  removeSnapshot: (scope: ScopeSelection, snapshotId: string, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./twin-history").TwinHistory>("/twin/snapshots/remove", {
      method: "POST", query: scopeToSearchParams(scope),
      body: { snapshot_id: snapshotId, expected_revision: expectedRevision }, signal,
    }),
  /** Compare two owned same-scope captures without re-reading current providers. */
  compareSnapshots: (scope: ScopeSelection, baselineId: string, candidateId: string, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("baseline_id", baselineId); query.set("candidate_id", candidateId);
    return apiRequest<import("./twin-history").TwinCaptureComparison>("/twin/snapshots/compare", { query, signal });
  },
  /** Provider-free scenario pair bound to one exact immutable retained projection. */
  retainedScenarios: (scope: ScopeSelection, snapshotId: string, left: string, right: string, target: string, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("left", left); query.set("right", right); query.set("target", target);
    return apiRequest<import("./twin-history").TwinScenarioPair>(`/twin/snapshots/${encodeURIComponent(snapshotId)}/scenarios`, { query, signal });
  },
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
  /** Admit one caller-known background job; the same identity never redispatches. */
  startJob: (jobId: string, objective: string, scope: ScopeSelection = {}, timeoutSeconds = 30) =>
    apiRequest<import("./types").InvestigationJob>("/agents/investigation-jobs", {
      method: "POST", query: scopeToSearchParams(scope),
      body: { job_id: jobId, objective, timeout_seconds: timeoutSeconds },
    }),
  /** Recover exact outcome metadata without acquiring sources or restarting work. */
  job: (jobId: string, scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<import("./types").InvestigationJob>(`/agents/investigation-jobs/${encodeURIComponent(jobId)}`, {
      query: scopeToSearchParams(scope), signal: options.signal,
    }),
  /** Request stop of new scheduling; already dispatched provider work is not cancelled. */
  stopJob: (jobId: string, scope: ScopeSelection = {}) =>
    apiRequest<import("./types").InvestigationJob>(`/agents/investigation-jobs/${encodeURIComponent(jobId)}/stop`, {
      method: "POST", query: scopeToSearchParams(scope),
    }),
  /** Read cached provider observations without refreshing or starting tools. */
  runtimeReadiness: (scope: ScopeSelection = {}, options: { signal?: AbortSignal } = {}) =>
    apiRequest<import("./types").AgentRuntimeReadiness>("/agents/runtime-readiness", { query: scopeToSearchParams(scope), signal: options.signal }),
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
  /** Read personal retained KB source observations without provider acquisition. */
  observations: (kbId: string, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").KbObservationHistory>(`/kbs/${encodeURIComponent(kbId)}/observations`, {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Explicitly retain the latest authorized Silver projection with optimistic revision. */
  captureObservation: (kbId: string, scope: ScopeSelection, expectedRevision: number, generation: string) =>
    apiRequest<import("./types").KbObservationHistory>(`/kbs/${encodeURIComponent(kbId)}/observations`, {
      method: "POST", query: scopeToSearchParams(scope), body: { expected_revision: expectedRevision, generation },
    }),
  /** Read private exact-scope KB declarations without refreshing provider data. */
  reviews: (kbId: string, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").KbReviewHistory>(`/kbs/${encodeURIComponent(kbId)}/reviews`, {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Reauthorize/reacquire Silver metadata before retaining an operator declaration. */
  createReview: (kbId: string, scope: ScopeSelection, expectedRevision: number, declaration: import("./types").KbReviewDeclaration) =>
    apiRequest<import("./types").KbReviewHistory>(`/kbs/${encodeURIComponent(kbId)}/reviews`, {
      method: "POST", query: scopeToSearchParams(scope), body: { ...declaration, expected_revision: expectedRevision },
    }),
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
  /** Read personal retained receipts after current Inventory membership authorization. */
  history: (resourceId: string, scope: ScopeSelection, options: { signal?: AbortSignal } = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("resource_id", resourceId);
    return apiRequest<import("./types").ResourceHealthHistory>("/resource-health/resource/history", {
      query, signal: options.signal,
    });
  },
  /** Acquire measurements on the server and append with the reviewed revision only. */
  captureHistory: (resourceId: string, scope: ScopeSelection, expectedRevision: number, options: { signal?: AbortSignal } = {}) => {
    const query = scopeToSearchParams(scope);
    query.set("resource_id", resourceId);
    return apiRequest<import("./types").ResourceHealthHistory>("/resource-health/resource/history", {
      method: "POST", query, body: { expected_revision: expectedRevision }, signal: options.signal,
    });
  },
  /** Live CPU/network/disk utilization for in-scope compute resources. */
  snapshot: (scope: ScopeSelection = {}, forceRefresh = false) => {
    const query = scopeToSearchParams(scope);
    if (forceRefresh) query.set("force_refresh", "true");
    return apiRequest<ResourceHealthSnapshot>("/resource-health", { query });
  },
  /**
   * Fetch live utilization for one inventory-authorized resource.
   *
   * The caller may abort an obsolete card request without affecting sibling
   * cards. Scope and resource identity are still re-authorized by the server.
   */
  resource: (
    resourceId: string,
    scope: ScopeSelection = {},
    forceRefresh = false,
    options: { signal?: AbortSignal } = {},
  ) => {
    const query = scopeToSearchParams(scope);
    query.set("resource_id", resourceId);
    if (forceRefresh) query.set("force_refresh", "true");
    return apiRequest<ResourceHealthSnapshot>("/resource-health/resource", {
      query,
      signal: options.signal,
    });
  },
};


export type { Envelope };

/**
 * Governance surface: FinOps, identity risk, SPN posture, access reviews,
 * audit evidence, and enterprise administration. Every read carries the
 * global scope so the API applies subscription isolation server-side.
 */
export const governanceApi = {
  /** Recover shared exact-scope advisory campaign metadata under current grants. */
  campaigns: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./access-campaigns").AccessCampaignCollection>("/governance/access-campaigns", { query: scopeToSearchParams(scope), signal }),
  /** Read frozen source and attributed recommendations without current providers. */
  campaign: (scope: ScopeSelection, campaignId: string, signal?: AbortSignal) =>
    apiRequest<import("./access-campaigns").AccessCampaignDetail>(`/governance/access-campaigns/${encodeURIComponent(campaignId)}`, { query: scopeToSearchParams(scope), signal }),
  /** Explicit assigned-source capture; only manager authority over the full scope suffices. */
  createCampaign: (scope: ScopeSelection, body: import("./access-campaigns").CampaignCreate, signal?: AbortSignal) =>
    apiRequest<import("./access-campaigns").AccessCampaignCollection>("/governance/access-campaigns", { method: "POST", body, query: scopeToSearchParams(scope), signal }),
  /** Record only the authenticated assigned reviewer's immutable recommendation. */
  decideCampaign: (scope: ScopeSelection, body: import("./access-campaigns").CampaignDecisionRequest, signal?: AbortSignal) =>
    apiRequest<import("./access-campaigns").AccessCampaignCollection>("/governance/access-campaigns/decisions", { method: "POST", body, query: scopeToSearchParams(scope), signal }),
  /** Complete/cancel reviewed work, never Azure access or execution approvals. */
  closeCampaign: (scope: ScopeSelection, action: "complete" | "cancel", body: import("./access-campaigns").CampaignClosure, signal?: AbortSignal) =>
    apiRequest<import("./access-campaigns").AccessCampaignCollection>(`/governance/access-campaigns/${action}`, { method: "POST", body, query: scopeToSearchParams(scope), signal }),
  /** Remove only a reviewed terminal stored copy; downloaded records remain. */
  removeCampaign: (scope: ScopeSelection, body: import("./access-campaigns").CampaignAddress, signal?: AbortSignal) =>
    apiRequest<import("./access-campaigns").AccessCampaignCollection>("/governance/access-campaigns/remove", { method: "POST", body, query: scopeToSearchParams(scope), signal }),
  /** Recover personal exact-scope metadata without acquiring live evidence. */
  retainedExports: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./audit-exports").AuditCaptureCollection>("/governance/exports/retained", {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Explicitly generate a current pack and retain its standard-redacted bytes. */
  captureExport: (scope: ScopeSelection, kind: import("./audit-exports").AuditCaptureKind, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./audit-exports").AuditCaptureCollection>("/governance/exports/retained", {
      method: "POST", query: scopeToSearchParams(scope), signal,
      body: { kind, expected_revision: expectedRevision },
    }),
  /** Read immutable content independently of current providers. */
  retainedExport: (scope: ScopeSelection, exportId: string, signal?: AbortSignal) =>
    apiRequest<import("./audit-exports").AuditCaptureDetail>(`/governance/exports/retained/${encodeURIComponent(exportId)}`, {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Remove only the reviewed stored copy; downloaded copies cannot be revoked. */
  removeExport: (scope: ScopeSelection, exportId: string, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./audit-exports").AuditCaptureCollection>("/governance/exports/retained/remove", {
      method: "POST", query: scopeToSearchParams(scope), signal,
      body: { export_id: exportId, expected_revision: expectedRevision },
    }),
  finopsSummary: (scope: ScopeSelection = {}) =>
    apiRequest<FinOpsSummary>("/governance/finops/summary", {
      query: scopeToSearchParams(scope),
    }),

  finopsVerifiedRemediations: (
    scope: ScopeSelection = {},
    offset = 0,
    limit = 50,
    signal?: AbortSignal,
  ) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<{
      executions: FinOpsVerifiedRemediation[];
      count: number;
      read_only: boolean;
      boundary: string;
    }>("/governance/finops/verified-remediations", { query, signal });
  },

  finopsRemediationCostComparison: (
    scope: ScopeSelection,
    input: {
      execution_id: string;
      baseline_start: string;
      baseline_end: string;
      followup_start: string;
      followup_end: string;
    },
    signal?: AbortSignal,
  ) => {
    const query = scopeToSearchParams(scope);
    for (const [name, value] of Object.entries(input)) query.set(name, value);
    return apiRequest<FinOpsRemediationCostComparison>(
      "/governance/finops/remediation-cost-comparison",
      { query, signal },
    );
  },

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

  /** Read a bounded, scoped advisory queue; it never evaluates or changes access. */
  identityLeastPrivilege: (scope: ScopeSelection = {}, offset = 0, limit = 50) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<IdentityLeastPrivilegeReview>(
      "/governance/identity/least-privilege",
      { query },
    );
  },

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

  settings: (scope: ScopeSelection = {}, signal?: AbortSignal) =>
    apiRequest<EnterpriseSettings>("/governance/settings", {
      query: scopeToSearchParams(scope),
      signal,
    }),

  updateSettings: (payload: EnterpriseSettingsChange, signal?: AbortSignal) =>
    apiRequest<EnterpriseSettings>("/governance/settings", {
      method: "PATCH",
      body: payload,
      signal,
    }),
};

/** Pre-deployment change risk and impact assessment. */
export const predeployApi = {
  /** Export only the exact scoped retained receipt matching the reviewed artifact. */
  reviewContract: (scope: ScopeSelection, assessmentId: string, artifactSha256: string, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("artifact_sha256", artifactSha256);
    return apiRequest<import("./predeploy-history").CIReviewContract>(
      `/changes/retained-assessments/${encodeURIComponent(assessmentId)}/review-contract`, { query, signal },
    );
  },
  /** Provider-free personal exact-scope receipt recovery. */
  retained: (scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./predeploy-history").AssessmentHistory>("/changes/retained-assessments", {
      query: scopeToSearchParams(scope), signal,
    }),
  /** Retain only server-owned analysis matching the reviewed source digest and collection revision. */
  retain: (scope: ScopeSelection, assessmentId: string, artifactSha256: string, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./predeploy-history").AssessmentHistory>("/changes/retained-assessments", {
      method: "POST", query: scopeToSearchParams(scope), signal,
      body: { assessment_id: assessmentId, artifact_sha256: artifactSha256, expected_revision: expectedRevision },
    }),
  /** Explicitly remove a receipt, not its source assessment or artifact. */
  removeRetained: (scope: ScopeSelection, assessmentId: string, expectedRevision: number, signal?: AbortSignal) =>
    apiRequest<import("./predeploy-history").AssessmentHistory>("/changes/retained-assessments/remove", {
      method: "POST", query: scopeToSearchParams(scope), signal,
      body: { assessment_id: assessmentId, expected_revision: expectedRevision },
    }),
  /** Compare two authorized retained summaries without current provider acquisition. */
  compareRetained: (scope: ScopeSelection, baselineId: string, candidateId: string, signal?: AbortSignal) => {
    const query = scopeToSearchParams(scope);
    query.set("baseline_id", baselineId); query.set("candidate_id", candidateId);
    return apiRequest<import("./predeploy-history").AssessmentComparison>("/changes/retained-assessments/compare", { query, signal });
  },
  sources: (scope: ScopeSelection = {}) => apiRequest<ChangeAssessmentSources>("/changes/assessment-sources", {
    query: scopeToSearchParams(scope),
  }),

  /** Assess only the selected scope; optional exact finding context is rechecked server-side. */
  assess: (source: string, payload: Record<string, unknown>, changeId = "", options: {
    scope?: ScopeSelection; networkReview?: NetworkReviewReference; signal?: AbortSignal;
  } = {}) =>
    apiRequest<ChangeAssessment>("/changes/assess", {
      method: "POST", query: scopeToSearchParams(options.scope ?? {}), signal: options.signal,
      body: { source, payload, change_id: changeId, ...(options.networkReview ? { network_review: options.networkReview } : {}) },
    }),

  assessments: (scope: ScopeSelection = {}) =>
    apiRequest<ChangeAssessmentSummary[]>(
      "/changes/assessments",
      { query: scopeToSearchParams(scope) },
    ),

  assessment: (assessmentId: string, scope: ScopeSelection = {}) =>
    apiRequest<ChangeAssessment>(
      `/changes/assessments/${encodeURIComponent(assessmentId)}`,
      { query: scopeToSearchParams(scope) },
    ),
};

/** Durable Phase 1 situation reads; unlike the legacy incident API these IDs and records are persisted. */
export const situationsApi = {
  /** Read an authorized current case's run-bound response-review declaration. */
  deadline: (id: string, scope: ScopeSelection, signal?: AbortSignal) =>
    apiRequest<import("./types").SituationResponseDeadline>(`/situations/${encodeURIComponent(id)}/response-deadline`, { query: scopeToSearchParams(scope), signal }),
  /** Set or explicitly clear a declaration; never approve execution or certify an SLA. */
  declareDeadline: (id: string, scope: ScopeSelection, change: { expected_revision: number; evidence_run_id: string; due_at: string | null; reason: string }, signal?: AbortSignal) =>
    apiRequest<import("./types").SituationResponseDeadline>(`/situations/${encodeURIComponent(id)}/response-deadline`, {
      method: "PUT", query: scopeToSearchParams(scope), body: change, signal,
    }),
  /** Read exact-scope, server-attributed handover annotations. */
  notes: (id: string, scope: ScopeSelection) =>
    apiRequest<import("./types").SituationNotesState>(`/situations/${encodeURIComponent(id)}/notes`, { query: scopeToSearchParams(scope) }),
  /** Append one annotation against a reviewed history revision and evidence run. */
  appendNote: (id: string, scope: ScopeSelection, change: { expected_revision: number; evidence_run_id: string; text: string }) =>
    apiRequest<import("./types").SituationNotesState>(`/situations/${encodeURIComponent(id)}/notes`, {
      method: "POST", query: scopeToSearchParams(scope), body: change,
    }),
  list: (scope: ScopeSelection = {}, query = "", priority = "", offset = 0, limit = 100, triage?: {
    owner: string; lifecycle_state: string; older_than_hours: number | null; sort: "default" | "oldest" | "newest";
    response_deadline?: "" | "due" | "overdue" | "unknown" | "closed";
  }) => {
    const params = scopeToSearchParams(scope);
    if (query) params.set("q", query);
    if (priority) params.set("priority", priority);
    params.set("offset", String(offset));
    params.set("limit", String(limit));
    if (triage) {
      if (triage.owner) params.set("assigned_owner", triage.owner);
      if (triage.lifecycle_state) params.set("lifecycle_state", triage.lifecycle_state);
      if (triage.older_than_hours !== null) params.set("older_than_hours", String(triage.older_than_hours));
      if (triage.sort !== "default") params.set("sort", triage.sort);
      if (triage.response_deadline) params.set("response_deadline", triage.response_deadline);
    }
    return apiRequest<import("./types").DurableSituation[]>("/situations", { query: params });
  },
  /** Reauthorize a bounded selection of exact evidence runs for read-only handoff. */
  handoff: (scope: ScopeSelection, selections: Array<{ situation_id: string; run_id: string }>) =>
    apiRequest<{ artifact: Record<string, unknown>; sha256: string; count: number }>("/situations/handoff", {
      method: "POST", query: scopeToSearchParams(scope), body: { selections },
    }),
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
