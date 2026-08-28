import { apiRequest, resolveApiBaseUrl } from "./api-client";
import type { ScopeSelection } from "./scope";
import { scopeToSearchParams } from "./scope";
import type {
  BusinessMetadata,
  ChangeAssessment,
  ChangeAssessmentSources,
  ChangeAssessmentSummary,
  ConnectionCreateRequest,
  ConnectionCreateResult,
  ConnectionHealthReport,
  ConnectionSyncResult,
  ConnectionUpdateRequest,
  ConnectionValidationReport,
  DependencyGraph,
  Envelope,
  IncidentDetail,
  IncidentReport,
  RemediationOpportunityReport,
  RemediationPlanReport,
  FlowResult,
  HubDependents,
  NetworkGap,
  NetworkDesignPolicy,
  NetworkSeverity,
  NetworkSummary,
  NetworkTopology,
  RuleFinding,
  SearchResult,
  ServerExposure,
  SemanticContext,
  SubscriptionConnection,
  CveDetail,
  KbDetail,
  PatchPriority,
  PatchRun,
  PatchRunCreateRequest,
  PatchTarget,
  RiskException,
  SlaComplianceReport,
  AttackPathGraph,
  VulnerabilityExposure,
  VulnerabilitySummary,
  EvidenceItem,
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
  SoftwareInventoryCollection,
  SoftwareInventoryDetail,
  SoftwareMapping,
  SoftwareMappingCollection,
  ResourceHealthSnapshot,
  CopilotPageKind, CopilotPageSnapshot, CopilotSelectedResource, CopilotEvidenceRow, CopilotContextResult,
} from "./types";

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
export interface CopilotInvestigation {
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

export function buildCopilotSnapshot(input: CopilotPageSnapshotInput): CopilotPageSnapshot {
  return {
    version: "1", page_kind: input.pageKind, page_id: input.pageId,
    selected_resources: (input.selectedResources ?? []).slice(0, 50),
    filters: input.filters ?? {}, freshness: (input.freshness ?? []).slice(0, 32),
    scope: { declared: input.scope, authorized: true }, evidence: (input.evidence ?? []).slice(0, 200),
    question: input.question?.trim() || "Summarize the visible page evidence.", rechecks: input.rechecks ?? [],
  };
}

export function copilotEvidenceRows(
  section: string, evidence: EvidenceItem[], records: unknown[] = [],
  status: "ok" | "empty" | "unavailable" | "denied" = "ok",
): CopilotEvidenceRow[] {
  const rows: CopilotEvidenceRow[] = evidence.map((item, index) => ({
    evidence_id: `${section}:${item.source_table || "source"}:${index}`,
    resource_id: item.resource_id || undefined, section,
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
  remediationPlans: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<RemediationPlanReport>("/remediation-plans", { query });
  },
  remediationOpportunities: (scope: ScopeSelection = {}, offset = 0, limit = 100) => {
    const query = scopeToSearchParams(scope);
    query.set("offset", String(offset));
    query.set("limit", String(limit));
    return apiRequest<RemediationOpportunityReport>("/remediation-opportunities", { query });
  },
};

// ---------------------------------------------------------------------------
// Network intelligence
// ---------------------------------------------------------------------------

export const networkApi = {
  topology: (scope: ScopeSelection = {}) =>
    apiRequest<{ topology: NetworkTopology; summary: NetworkSummary }>("/network/topology", {
      query: scopeToSearchParams(scope),
    }),

  summary: (scope: ScopeSelection = {}) =>
    apiRequest<NetworkSummary>("/network/summary", { query: scopeToSearchParams(scope) }),

  /** "What depends on the hub?" */
  hubDependents: (vnetId: string) =>
    apiRequest<HubDependents>(`/network/topology/hubs/${encodeURIComponent(vnetId)}/dependents`),

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

  gaps: (scope: ScopeSelection = {}, options: { severity?: NetworkSeverity; category?: string } = {}) => {
    const query = scopeToSearchParams(scope);
    if (options.severity) query.set("severity", options.severity);
    if (options.category) query.set("category", options.category);
    return apiRequest<{ gaps: NetworkGap[]; intended_design_declared: boolean; summary: NetworkSummary }>(
      "/network/gaps",
      { query }
    );
  },

  ruleFindings: (scope: ScopeSelection = {}, options: { severity?: NetworkSeverity; category?: string } = {}) => {
    const query = scopeToSearchParams(scope);
    if (options.severity) query.set("severity", options.severity);
    if (options.category) query.set("category", options.category);
    return apiRequest<{ findings: RuleFinding[]; summary: NetworkSummary }>("/network/rule-findings", { query });
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
  summary: (scope: ScopeSelection = {}) =>
    apiRequest<VulnerabilitySummary>("/vulnerabilities/summary", { query: scopeToSearchParams(scope) }),
  exposures: (scope: ScopeSelection = {}) =>
    apiRequest<VulnerabilityExposure[]>("/vulnerabilities/exposures", { query: scopeToSearchParams(scope) }),
  patchPriorities: (scope: ScopeSelection = {}) =>
    apiRequest<PatchPriority[]>("/vulnerabilities/patch-priorities", { query: scopeToSearchParams(scope) }),
  serverExposures: (scope: ScopeSelection = {}) =>
    apiRequest<ServerExposure[]>("/vulnerabilities/server-exposures", { query: scopeToSearchParams(scope) }),
  cves: (scope: ScopeSelection = {}, q?: string) => {
    const query = scopeToSearchParams(scope);
    if (q) query.set("q", q);
    return apiRequest<CveDetail[]>("/cves", { query });
  },
  cve: (id: string, scope: ScopeSelection = {}) =>
    apiRequest<CveDetail>(`/cves/${encodeURIComponent(id)}`, { query: scopeToSearchParams(scope) }),
  riskExceptions: () => apiRequest<RiskException[]>("/vulnerabilities/risk-exceptions"),
  acceptRisk: (payload: { cve_id: string; server_id?: string; reason: string; approved_by?: string; expires_at?: string }) =>
    apiRequest<RiskException>("/vulnerabilities/risk-exceptions", { method: "POST", body: payload }),
  revokeRiskException: (exceptionId: string) =>
    apiRequest<void>(`/vulnerabilities/risk-exceptions/${encodeURIComponent(exceptionId)}`, { method: "DELETE" }),
  slaCompliance: (scope: ScopeSelection = {}) =>
    apiRequest<SlaComplianceReport>("/vulnerabilities/sla-compliance", { query: scopeToSearchParams(scope) }),
  attackPath: (cveId: string, scope: ScopeSelection = {}) =>
    apiRequest<AttackPathGraph>(`/cves/${encodeURIComponent(cveId)}/attack-path`, {
      query: scopeToSearchParams(scope),
    }),
};

/**
 * Patch remediation: patchable inventory, and the single guarded trigger.
 * The API re-validates every selection against the target's own available
 * patches, so the UI's job is only to make the operator's choice explicit.
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
  trigger: (payload: PatchRunCreateRequest) =>
    apiRequest<PatchRun>("/patching/runs", { method: "POST", body: payload }),
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
  detail: (kbId: string, scope: ScopeSelection = {}) =>
    apiRequest<KbDetail>(`/kbs/${encodeURIComponent(kbId)}`, { query: scopeToSearchParams(scope) }),
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

export interface AdminAkvConfig {
  entra_web_client_id: string;
  entra_tenant_id: string;
  entra_api_audience: string;
  entra_api_scope: string;
  entra_grants_json: string;
}

export const adminApi = {
  saveAkvConfig: (payload: AdminAkvConfig) =>
    apiRequest<{ saved: string[]; secret_names: string[] }>("/admin/akv-config", {
      method: "POST",
      body: payload,
    }),
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
