import { apiRequest, resolveApiBaseUrl } from "./api-client";
import type { ScopeSelection } from "./scope";
import { scopeToSearchParams } from "./scope";
import type {
  BusinessMetadata,
  ConnectionCreateRequest,
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
  NetworkSeverity,
  NetworkSummary,
  NetworkTopology,
  RuleFinding,
  SearchResult,
  SemanticContext,
  SubscriptionConnection,
  CveDetail,
  KbDetail,
  PatchPriority,
  RiskException,
  SlaComplianceReport,
  AttackPathGraph,
  VulnerabilityExposure,
  VulnerabilitySummary,
  EvidenceItem,
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
    apiRequest<SubscriptionConnection>("/subscription-connections", { method: "POST", body: payload }),

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

  businessService: (name: string) => apiRequest<SemanticContext>(`/business-services/${encodeURIComponent(name)}`),
  application: (name: string) => apiRequest<SemanticContext>(`/applications/${encodeURIComponent(name)}`),
  environment: (name: string) => apiRequest<SemanticContext>(`/environments/${encodeURIComponent(name)}`),
  subscription: (name: string) => apiRequest<SemanticContext>(`/subscriptions/${encodeURIComponent(name)}`),
  subscriptionConnectionContext: (name: string) =>
    apiRequest<SemanticContext>(`/subscription-connections/${encodeURIComponent(name)}/context`),
  resource: (resourceId: string) => apiRequest<SemanticContext>(`/resources/${encodeURIComponent(resourceId)}`),
  risk: (subject: string) => apiRequest<SemanticContext>(`/risk/${encodeURIComponent(subject)}`),
  impact: (subject: string) => apiRequest<SemanticContext>(`/impact/${encodeURIComponent(subject)}`),
  dependencyGraph: (application: string, direction: "upstream" | "downstream" | "both" = "both") =>
    apiRequest<DependencyGraph>(`/graph/dependencies/${encodeURIComponent(application)}`, {
      query: { direction },
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
  incident: (id: string) => apiRequest<IncidentDetail>(`/incidents/${encodeURIComponent(id)}`),
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
};

export const vulnerabilityApi = {
  summary: (scope: ScopeSelection = {}) =>
    apiRequest<VulnerabilitySummary>("/vulnerabilities/summary", { query: scopeToSearchParams(scope) }),
  exposures: (scope: ScopeSelection = {}) =>
    apiRequest<VulnerabilityExposure[]>("/vulnerabilities/exposures", { query: scopeToSearchParams(scope) }),
  patchPriorities: (scope: ScopeSelection = {}) =>
    apiRequest<PatchPriority[]>("/vulnerabilities/patch-priorities", { query: scopeToSearchParams(scope) }),
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
