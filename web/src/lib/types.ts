/**
 * TypeScript mirrors of the Operations API contract described in
 * docs/OPERATIONS_API.md and src/api/models.py. Kept intentionally close to
 * the Pydantic shapes so a schema drift is a visible diff, not a silent bug.
 */

export type Confidence = "high" | "medium" | "low" | "unknown";
export type Freshness = "fresh" | "aging" | "stale" | "unknown";

export interface EvidenceItem {
  source_engine: string;
  source_table: string;
  timestamp: string;
  subscription_connection?: string | null;
  resource_id?: string | null;
  confidence: Confidence;
  freshness: Freshness;
}

export interface Pagination {
  offset: number;
  limit: number;
  total: number;
  next_offset: number | null;
}

/** Every successful response body: `{ data, evidence[], scope{}, knowledge_version, warnings[], pagination? }`. */
export interface Envelope<T> {
  data: T;
  evidence: EvidenceItem[];
  scope: Record<string, string[]>;
  knowledge_version?: string;
  graph_freshness?: string;
  live_observed_at?: string;
  source_status?: Record<string, string>;
  warnings?: string[];
  pagination?: Pagination | null;
}

export type InventorySourceType = "azure_vm" | "arc" | "logs";
export type InventorySourceState = "ready" | "partial" | "stale" | "degraded" | "unavailable";

export interface InventoryEvidence {
  source_engine: string;
  source_table: string;
  observed_at: string;
  source_id: string;
  query_version: string;
}

export interface InventorySourceStatus {
  source_type: InventorySourceType;
  state: InventorySourceState;
  observed_at: string;
  query_version: string;
  row_count: number;
  error: string;
}

export interface OsInventoryGroup {
  key: string;
  os_name: string;
  os_version: string;
  machine_count: number;
  source_types: InventorySourceType[];
  lifecycle_status: string;
  support_end: string | null;
  days_remaining: number | null;
  review_required: boolean;
  support_channel: "mainstream" | "extended" | "";
  lifecycle_evidence: string[];
}

export interface OsInventoryMachine {
  resource_id: string;
  machine_name: string;
  source_type: InventorySourceType;
  os_name: string;
  os_version: string;
  subscription_id: string;
  resource_group: string;
  environment: string;
  observed_at: string;
  evidence: InventoryEvidence[];
  source_status: InventorySourceState;
  lifecycle_status: string;
  support_end: string | null;
  days_remaining: number | null;
  review_required: boolean;
  support_channel: "mainstream" | "extended" | "";
  lifecycle_evidence: string[];
}

export interface LifecycleCandidate {
  candidate_id: string;
  date: string;
  source_kind: "endoflife.date" | "official_vendor" | "web_search";
  citation: string;
  retrieved_at: string;
  extracted_claim: string;
  confidence: number;
  support_channel: "mainstream" | "extended";
}

export interface LifecycleReview {
  normalized_os_key: string;
  os_name: string;
  os_version: string;
  status: "catalog_hit" | "review_required" | "confirmed";
  catalog_revision: number;
  classification: {
    status: string;
    support_end: string | null;
    days_remaining: number | null;
    support_channel: "mainstream" | "extended";
    confidence: number;
    evidence: string[];
  };
  candidates: LifecycleCandidate[];
  provenance: Record<string, unknown> | null;
}

export interface OsInventoryCollection {
  groups: OsInventoryGroup[];
  source_status: Record<InventorySourceType, InventorySourceStatus>;
  observed_at: string;
  query_version: string;
  generation_id: string;
  requested_scope: Record<string, string[]>;
}

export interface OsInventoryDetail {
  group: OsInventoryGroup;
  machines: OsInventoryMachine[];
  source_status: Record<InventorySourceType, InventorySourceStatus>;
  observed_at: string;
  query_version: string;
  generation_id: string;
  requested_scope: Record<string, string[]>;
}

export interface PaasInventoryGroup {
  key: string;
  resource_type: string;
  sku: string;
  tier: string;
  resource_count: number;
}

export interface PaasInventoryResource {
  resource_id: string;
  resource_name: string;
  resource_type: string;
  family: string;
  tenant_id: string;
  subscription_id: string;
  resource_group: string;
  location: string;
  sku: string;
  tier: string;
  runtime: string;
  provisioning_state: string;
  os_name: string;
  os_version: string;
  observed_at: string;
  query_version: string;
  tags: Record<string, string>;
}

export interface PaasInventoryCollection {
  groups: PaasInventoryGroup[];
  source_status: Record<string, InventorySourceStatus>;
  observed_at: string;
  query_version: string;
  generation_id: string;
  requested_scope: Record<string, string[]>;
}

export interface PaasInventoryDetail {
  group: PaasInventoryGroup;
  resources: PaasInventoryResource[];
  source_status: Record<string, InventorySourceStatus>;
  observed_at: string;
  query_version: string;
  generation_id: string;
  requested_scope: Record<string, string[]>;
}

export interface FlatInventoryResource {
  family: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  subscription_id: string;
  resource_group: string;
  environment: string;
}

export interface InventoryFamilyAvailability {
  family: string;
  state: InventorySourceState;
  row_count: number;
  logical_dataset: string;
}

export interface FlatResourceCollection {
  resources: FlatInventoryResource[];
  family_availability: Record<string, InventoryFamilyAvailability>;
  requested_scope: Record<string, string[]>;
  query_version: string;
}

export interface InventoryNarrativeCitation {
  source_engine: string;
  source_table: string;
  timestamp: string;
  reference: string;
}

export interface InventoryNarrativeFact {
  label: string;
  value: string;
}

export interface InventoryNarrative {
  fact_summary: string;
  fact_items: InventoryNarrativeFact[];
  narrated_summary: string | null;
  narrated_by: string;
  model: string;
  confidence: Confidence;
  citations: InventoryNarrativeCitation[];
  source_status: Record<string, InventorySourceStatus>;
  requested_scope: { dimensions: string[] };
  status: "narrated" | "fact_only";
}

export interface TwinEntity {
  id: string;
  kind: string;
  name: string;
  version: string;
  state: string;
  confidence: Confidence;
  provenance: Array<Record<string, unknown>>;
  properties: Record<string, unknown>;
}

export interface TwinRelationship {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: Confidence;
  provenance: Array<Record<string, unknown>>;
}

export interface TwinTimelineEvent {
  timestamp: string;
  type: string;
  entity: string;
  summary: string;
  provenance?: Record<string, unknown>;
}

export interface TwinTemporalState {
  current_state_version: string;
  previous_state_version: string;
  change_history: Array<Record<string, unknown>>;
  risk_trend: Array<Record<string, unknown>>;
  dependency_evolution: Array<Record<string, unknown>>;
}

export interface TwinSnapshot {
  twin_id: string;
  version: string;
  previous_version: string;
  observed_at: string;
  scope: Record<string, string[]>;
  entities: TwinEntity[];
  relationships: TwinRelationship[];
  timeline: TwinTimelineEvent[];
  provenance: Array<Record<string, unknown>>;
  confidence: Confidence;
  temporal: TwinTemporalState;
  warnings?: string[];
  live_observed_at?: string;
  source_status?: Record<string, string>;
}

export interface TwinQueryResult {
  query: string;
  version: string;
  entities: TwinEntity[];
  relationships: TwinRelationship[];
  timeline: TwinTimelineEvent[];
}

export interface TwinComparison {
  current_version: string;
  previous_version: string;
  added: TwinEntity[];
  removed: TwinEntity[];
  changed: Array<Record<string, unknown>>;
  summary: string;
}

export interface TwinScenarioResult {
  scenario: string;
  target: string;
  version: string;
  likely_impact: string;
  risk_delta: number;
  impacted_entities: TwinEntity[];
  assumptions: string[];
}

export interface TwinTraversal {
  resource_id: string;
  path: TwinEntity[];
  relationships: TwinRelationship[];
  business_consequence: string[];
}

export interface TwinExport {
  format: string;
  exported_at: string;
  snapshot: TwinSnapshot;
}

export interface AutonomousAgent {
  id: string;
  name: string;
  role: string;
  tools: string[];
  keywords: string[];
  depends_on: string[];
}

export interface AgentToolCall {
  tool: string;
  arguments: Record<string, unknown>;
  status: "ok" | "empty" | "unavailable" | "denied" | "partial";
  warning: string;
  attempts: number;
}

export interface AgentFinding {
  finding_id: string;
  agent_id: string;
  summary: string;
  status: string;
  confidence: Confidence;
  evidence_count: number;
  unsupported?: boolean;
}

export interface AgentRun {
  agent_id: string;
  agent_name: string;
  status: string;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  tool_calls: AgentToolCall[];
  findings: AgentFinding[];
  evidence: EvidenceItem[];
  confidence: Confidence;
  hidden_reasoning_exposed: boolean;
}

export interface EvidenceReconciliation {
  conflicts: string[];
  stale_evidence: EvidenceItem[];
  missing_providers: AgentToolCall[];
  unsupported_conclusions: AgentFinding[];
  evidence_count: number;
  reconciled_confidence: Confidence;
}

export interface InvestigationSynthesis {
  summary: string;
  recommended_plan: string;
  required_decision: string;
  unresolved_questions: string[];
  confidence: Confidence;
  /** Optional Foundry narration of the evidence; empty when no agent is configured. */
  narration?: string;
  narrated_by?: string;
  narration_warning?: string;
  llm_calls?: number;
}

export interface HumanDecision {
  at: string;
  action: string;
  payload: Record<string, unknown>;
}

export interface InvestigationEvaluation {
  groundedness: number;
  scope_isolation: string;
  tool_correctness: number;
  convergence: string;
  latency_ms: number;
  cost: Record<string, number>;
}

export interface MultiAgentLedger {
  ledger_id: string;
  objective: string;
  scope: Record<string, string[]>;
  created_by: string;
  created_at: string;
  updated_at: string;
  status: string;
  selected_agents: AutonomousAgent[];
  agent_runs: AgentRun[];
  reconciliation: EvidenceReconciliation;
  synthesis: InvestigationSynthesis;
  human_controls: { available_actions: string[] };
  decisions: HumanDecision[];
  approvals: HumanDecision[];
  outcome: string;
  stop_reason: string;
  evaluation: InvestigationEvaluation;
}

export type ErrorCode =
  | "invalid_request"
  | "unauthenticated"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "already_exists"
  | "ambiguous_subject"
  | "not_implemented"
  | "upstream_unavailable"
  | "provider_unavailable"
  | "secret_unavailable"
  | "internal_error";

export interface ApiErrorBody {
  error: {
    code: ErrorCode;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface VulnerabilityExposure {
  cve_id: string;
  severity: string;
  missing_kb: string;
  affected_server_count: number;
  affected_application_count: number;
  affected_business_service_count: number;
  reachable_server_count: number;
  exploit_signal: string;
  internet_exposed: boolean;
  critical_business_count: number;
  priority_score: number;
  expected_risk_reduction: number;
  recommended_patch: string;
  epss_score: number;
  is_known_exploited: boolean;
  finding_ids: string[];
}

export interface VulnerabilitySummary {
  cve_count: number;
  finding_count: number;
  affected_server_count: number;
  affected_business_service_count: number;
  reachable_server_count: number;
  internet_exposed_count: number;
  critical_count: number;
  top_priority: VulnerabilityExposure[];
  freshness: string;
  metadata_source: string;
}

export interface ServerExposure {
  server_id: string;
  name: string;
  resource_type: string;
  inventory_kind: string;
  subscription_id: string;
  subscription_connection: string;
  environment: string;
  business_service: string;
  application: string;
  owner: string;
  region: string;
  criticality: string;
  network_exposure: string;
  reachable: boolean;
  internet_exposed: boolean;
  cve_count: number;
  finding_count: number;
  critical_count: number;
  overdue_count: number;
  max_days_open: number;
  missing_kbs: string[];
  cve_ids: string[];
  severities: string[];
  priority_score: number;
  expected_risk_reduction: number;
  finding_ids: string[];
}

export interface VulnerabilityFinding {
  finding_id: string;
  cve_id: string;
  server_id: string;
  missing_kb: string;
  application: string;
  business_service: string;
  owner: string;
  subscription_id: string;
  subscription_connection: string;
  environment: string;
  region: string;
  criticality: string;
  resource_type: string;
  resource_kind: string;
  resource_name: string;
  severity: string;
  exploit_signal: string;
  network_exposure: string;
  reachable: boolean;
  firewall_path: string[];
  nsg_path: string[];
  recommended_patch: string;
  first_observed_at: string;
  due_at: string;
  days_open: number;
  overdue: boolean;
  risk_accepted: boolean;
  risk_acceptance_reason: string;
  risk_acceptance_expires_at: string;
}

export interface AttackPathNode {
  id: string;
  kind: "origin" | "firewall" | "nsg" | "server";
  label: string;
  business_service?: string;
  criticality?: string;
  environment?: string;
  network_exposure?: string;
  reachable?: boolean;
}

export interface AttackPathEdge {
  source: string;
  target: string;
  label: string;
}

export interface AttackPathGraph {
  cve_id: string;
  nodes: AttackPathNode[];
  edges: AttackPathEdge[];
  reachable_server_count: number;
  internet_exposed: boolean;
}

export interface RiskException {
  exception_id: string;
  cve_id: string;
  server_id: string;
  reason: string;
  approved_by: string;
  created_at: string;
  expires_at: string;
}

export interface SlaComplianceSeverityRow {
  severity: string;
  open_count: number;
  tracked_count: number;
  compliant_count: number;
  overdue_count: number;
  compliance_rate: number | null;
  max_days_open: number;
  avg_days_open: number;
}

export interface SlaComplianceReport {
  open_count: number;
  tracked_count: number;
  compliant_count: number;
  overdue_count: number;
  overall_compliance_rate: number | null;
  by_severity: SlaComplianceSeverityRow[];
  aging_buckets: Record<string, number>;
  freshness: string;
}

export interface CveDetail {
  cve: {
    cve_id: string;
    title: string;
    description: string;
    severity: string;
    cvss: { version: string; base_score: number; vector: string; severity: string };
    associated_kbs: string[];
    epss_score: number;
    epss_percentile: number;
    is_known_exploited: boolean;
    kev_date_added: string;
    kev_due_date: string;
    kev_ransomware_use: string;
    exploit_references: { url: string; source: string }[];
  };
  exploitability_signals: { signal: string; source: string; confidence: string }[];
  affected_servers: string[];
  affected_applications: string[];
  affected_business_services: string[];
  findings: VulnerabilityFinding[];
  recommended_patch: string;
}

export interface KbDetail {
  kb_id: string;
  title: string;
  severity: string;
  published_at: string;
  cve_ids: string[];
  cves: { cve_id: string; title: string; severity: string; cvss: { base_score: number; vector: string; severity: string } }[];
  affected_servers: string[];
  affected_business_services: string[];
  findings: VulnerabilityFinding[];
}

export interface PatchPriority {
  kb_id: string;
  cve_ids: string[];
  affected_server_count: number;
  affected_application_count: number;
  affected_business_service_count: number;
  reachable_server_count: number;
  expected_risk_reduction: number;
  priority_score: number;
  overdue_count: number;
  max_days_open: number;
  recommended_action: string;
}

/** Thrown by the API client for any non-2xx response. Carries the parsed error contract when available. */
export class ApiError extends Error {
  readonly code: ErrorCode | "unknown";
  readonly status: number;
  readonly details?: Record<string, unknown>;
  readonly correlationId?: string;

  constructor(
    status: number,
    code: ErrorCode | "unknown",
    message: string,
    details?: Record<string, unknown>,
    correlationId?: string
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.correlationId = correlationId;
  }

  /** True for the 501 contract-only stubs (network topology, KB/CVE, etc). */
  get isNotImplemented(): boolean {
    return this.code === "not_implemented";
  }
}

// ---------------------------------------------------------------------------
// Subscription connections (src/api/models.py, src/api/routers/connections.py)
// ---------------------------------------------------------------------------

export type ConnectionHealthStatus =
  | "healthy"
  | "unhealthy"
  | "warning"
  | "failed"
  | "stale"
  | "onboarding_blocked"
  | "disabled"
  | "unknown";

export interface CredentialReference {
  credential_id?: string;
  kind?: string;
  client_id: string;
  tenant_id?: string;
  secret_ref?: string;
  client_secret?: string;
}

export interface BusinessMetadata {
  business_service?: string | null;
  application?: string | null;
  environment?: string | null;
  project_owner?: string | null;
  support_team?: string | null;
  criticality?: string | null;
  region?: string | null;
  cost_center?: string | null;
}

export interface SyncState {
  status: string;
  last_synced_at?: string | null;
  last_successful_sync_at?: string | null;
  run_id?: string | null;
  message?: string;
  stage?: string | null;
  stage_message?: string | null;
  progress_pct?: number | null;
}

export interface SubscriptionConnection {
  connection_id: string;
  name: string;
  subscription_id: string;
  tenant_id: string;
  scope_key: string;
  is_active: boolean;
  business_service: string;
  application?: string | null;
  environment: string;
  owner?: string | null;
  support_team?: string | null;
  criticality: string;
  region?: string | null;
  sync_status: string;
  sync_record_count?: number;
  last_synced_at?: string | null;
  last_successful_sync_at?: string | null;
  health_status: ConnectionHealthStatus;
  credential?: CredentialReference;
  business_metadata?: BusinessMetadata;
  missing_metadata?: string[];
  environment_mappings?: Array<Record<string, unknown>>;
  business_service_linkages?: Array<Record<string, unknown>>;
  freshness?: Record<string, unknown>;
  dataset_root?: string;
}

export interface ConnectionHealthDetail {
  connection_id: string;
  status: ConnectionHealthStatus;
  last_checked_at?: string;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  failure_count?: number;
  details?: string;
  healthy?: boolean;
}

export interface ConnectionHealthSummary {
  connection_id: string;
  name: string;
  subscription_id: string;
  tenant_id: string;
  is_active: boolean;
  overall: ConnectionHealthStatus;
  health: ConnectionHealthDetail | null;
  sync: SyncState;
  freshness: Record<string, unknown>;
  evaluated_at: string;
}

export interface ConnectionHealthReport {
  generated_at: string;
  total: number;
  status_counts: Record<string, number>;
  connections: ConnectionHealthSummary[];
}

export interface ConnectionValidationReport {
  status: string;
  passed: boolean;
  checks: Array<Record<string, unknown>>;
  failed_required?: string[];
  failed_optional?: string[];
  health: ConnectionHealthDetail;
}

export interface ConnectionSyncResult {
  connection_id: string;
  status: string;
  sync_state: SyncState;
  health: ConnectionHealthDetail;
  [key: string]: unknown;
}

export interface ConnectionInitialSync {
  connection_id: string;
  status: string;
  run_id?: string;
  reason?: string;
  sync_state: SyncState;
}

export interface ConnectionCreateResult extends SubscriptionConnection {
  validation: ConnectionValidationReport;
  initial_sync: ConnectionInitialSync;
}

export interface ConnectionCreateRequest {
  connection_id: string;
  name: string;
  subscription_id: string;
  tenant_id: string;
  credential: CredentialReference;
  metadata?: BusinessMetadata;
}

export interface ConnectionUpdateRequest {
  name?: string;
  credential?: CredentialReference;
  expected_revision?: number;
}

// ---------------------------------------------------------------------------
// Context / Semantic Knowledge Layer
// ---------------------------------------------------------------------------

export interface SemanticSubject {
  entity_type: string;
  name: string;
  lifecycle_status?: string;
  business_service?: string | null;
  application?: string | null;
  environment?: string | null;
  subscription_connection?: string | null;
  owner?: string | null;
  support_team?: string | null;
  region?: string | null;
  criticality?: string | null;
  resource_id?: string | null;
}

export interface SemanticContext {
  subject: SemanticSubject;
  sections: Record<string, unknown>;
  /** Durable graph and request-time observation metadata, when hybrid reads are enabled. */
  graph_freshness?: string;
  live_observed_at?: string;
  source_status?: Record<string, string>;
}

export interface SearchResult {
  query?: string;
  intent: string;
  /** Hybrid/live search returns results; graph search historically called these items. */
  results?: Array<Record<string, unknown>>;
  items?: Array<Record<string, unknown>>;
  count?: number;
  freshness?: string;
  graph_freshness?: string;
  live_observed_at?: string;
  source_status?: Record<string, string>;
  truncated?: boolean;
}

export interface DependencyGraphNode {
  id: string;
  entity_type: string;
  name: string;
}

export interface DependencyGraphEdge {
  source: string;
  target: string;
  relationship: string;
}

export interface DependencyGraph {
  subject: SemanticSubject;
  direction: "upstream" | "downstream" | "both";
  nodes: DependencyGraphNode[];
  edges: DependencyGraphEdge[];
}

// ---------------------------------------------------------------------------
// Operations (incidents / remediation)
// ---------------------------------------------------------------------------

export interface IncidentIdentity {
  incident_id: string;
  title: string;
  severity: string;
  status: string;
  started_at: string;
}

export interface IncidentCause {
  evidence_id?: string;
  evidence_type?: string;
  classification?: string;
  confidence?: number;
  causal_score?: number;
  summary?: string;
  evidence?: string[];
  [key: string]: unknown;
}

export interface IncidentTimelineEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  summary: string;
  source: string;
  evidence: string[];
  [key: string]: unknown;
}

export interface IncidentBlastRadius {
  applications: string[];
  services: string[];
  business_services: string[];
  business_functions?: string[];
  owners: string[];
  support_teams: string[];
  dependency_tree?: Record<string, unknown>;
  subscriptions: string[];
  network_paths: string[];
  hub_dependencies: string[];
  firewall_impact: Array<Record<string, unknown>>;
  nsg_impact: Array<Record<string, unknown>>;
  downstream_services: string[];
  notes?: string[];
  application_count: number;
  service_count: number;
  business_service_count: number;
}

export interface IncidentBusinessImpact {
  applications: string[];
  services: string[];
  business_services: string[];
  owners: string[];
  support_teams: string[];
  risk_score?: number | null;
  patch_score?: number | null;
  lifecycle_score?: number | null;
}

export interface RootCauseAnalysis {
  probable_causes: IncidentCause[];
  contributing_factors: IncidentCause[];
  confidence: number;
  evidence: unknown[];
  timeline: IncidentTimelineEvent[];
  impacted_systems: unknown[];
  reasoning_chain: string[];
  contradicting_evidence: Array<Record<string, unknown>>;
  unknowns: string[];
  next_steps: string[];
  confirmed_cause: boolean;
  conclusion: string;
}

export interface IncidentReportEntry {
  incident: IncidentIdentity;
  root_cause_analysis: RootCauseAnalysis;
  blast_radius: IncidentBlastRadius;
  timeline: IncidentTimelineEvent[];
  business_impact: IncidentBusinessImpact;
}

export interface IncidentReport {
  report_type: string;
  audience_summaries: Record<string, unknown>;
  incidents: IncidentReportEntry[];
  operational_patterns: Array<Record<string, unknown>>;
  freshness: string;
  read_only: boolean;
}

export interface IncidentFinding extends IncidentReportEntry {
  probable_causes?: IncidentCause[];
  contributing_factors?: IncidentCause[];
  related_events?: IncidentTimelineEvent[];
  reasoning_chain?: string[];
  recommended_action?: {
    priority?: string;
    impact?: string;
    confidence?: number;
    rationale?: string[];
    suggested_action?: string;
    advisory_only?: boolean;
  };
  impacted_applications?: string[];
  impacted_services?: string[];
  impacted_business_services?: string[];
  owner?: string;
  support_team?: string;
  resource?: unknown;
  [key: string]: unknown;
}

export interface IncidentDetail {
  finding: IncidentFinding;
  read_only: boolean;
  freshness: string;
}

export interface RemediationPlan {
  plan_id: string;
  title: string;
  status: string;
  resource?: string;
  application?: string;
  business_service?: string;
  simulation_result?: {
    risk_reduction_percent?: number;
    operational_debt_reduction_percent?: number;
    [key: string]: unknown;
  };
  approval_requirements?: Array<Record<string, unknown>>;
  rollback_plan?: Record<string, unknown>;
  recommended_action?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RemediationPlanReport {
  plans: RemediationPlan[];
  generated_at?: string;
  summary?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RemediationOpportunity {
  opportunity_id?: string;
  resource?: string;
  category?: string;
  priority?: string;
  rationale?: string[];
  recommended_action?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface RemediationOpportunityReport {
  opportunities: RemediationOpportunity[];
  generated_at?: string;
  summary?: Record<string, unknown>;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Network intelligence (src/network/, src/api/routers/network.py)
// ---------------------------------------------------------------------------

export type NetworkSeverity = "critical" | "high" | "medium" | "low";

/** `indeterminate` means an endpoint or a higher-priority rule could not be
 * resolved. It is a refusal to guess, and must never be rendered as allowed. */
export type FlowVerdict = "allowed" | "denied" | "indeterminate";

export interface HubClassification {
  vnet_id: string;
  name: string;
  role: "hub" | "spoke" | "isolated";
  score: number;
  signals: string[];
  connection_id: string;
  subscription_id: string;
  peer_count: number;
}

export interface PeeringLink {
  local_vnet_id: string;
  remote_vnet_id: string;
  local_connection_id: string;
  remote_connection_id: string;
  is_bidirectional: boolean;
  is_healthy: boolean;
  is_cross_subscription: boolean;
  local_state: string;
  remote_state: string;
  allow_forwarded_traffic: boolean;
  allow_gateway_transit: boolean;
  use_remote_gateways: boolean;
  /** False when the remote VNet lives in a subscription that is not onboarded. */
  remote_vnet_observed: boolean;
}

export interface SharedServiceSummary {
  resource_id: string;
  name: string;
  service_kind: string;
  hub_vnet_id: string;
  consumer_vnet_ids: string[];
  connection_id: string;
  subscription_id: string;
  environment: string;
}

export interface NetworkTopologyResource {
  id: string;
  name: string;
  entity_type: string;
  role?: "hub" | "spoke" | "isolated" | "unknown" | string;
  subscription_id: string;
  resource_group: string;
  location: string;
  connection_id: string;
  environment: string;
  business_service: string;
  application: string;
  owner: string;
  tags: Record<string, string>;
  details: Record<string, unknown>;
}

export interface NetworkTopologyRelationship {
  id: string;
  source: string;
  target: string;
  relationship_type: string;
  label: string;
  details: Record<string, unknown>;
}

export interface NetworkTopology {
  hubs: HubClassification[];
  spokes: HubClassification[];
  isolated: HubClassification[];
  links: PeeringLink[];
  shared_services: SharedServiceSummary[];
  /** Resource-level graph nodes for every discovered network entity. */
  resources?: NetworkTopologyResource[];
  /** Resource-level relationship edges with click-through details. */
  relationships?: NetworkTopologyRelationship[];
  /** Peers referenced by an observed VNet but never ingested — i.e. a
   * subscription that has not been onboarded. Rendered as a known unknown. */
  unresolved_peer_vnet_ids: string[];
  connection_ids: string[];
  counts: Record<string, number>;
}

export interface NetworkSummary {
  hub_count: number;
  spoke_count: number;
  isolated_vnet_count: number;
  peering_count: number;
  cross_subscription_peering_count: number;
  unhealthy_peering_count: number;
  shared_service_count: number;
  connection_count: number;
  gap_count: number;
  gaps_by_severity: Record<string, number>;
  gaps_by_category: Record<string, number>;
  rule_finding_count: number;
  rule_findings_by_severity: Record<string, number>;
  rule_findings_by_category: Record<string, number>;
  /** False when no hub-spoke design policy is declared: only structural gaps
   * can then be found, never conformance gaps. */
  intended_design_declared: boolean;
  resource_counts: Record<string, number>;
}

export interface NetworkGap {
  gap_id: string;
  category: string;
  severity: NetworkSeverity;
  title: string;
  detail: string;
  resource_id: string;
  resource_name: string;
  resource_type: string;
  evidence: Record<string, unknown>;
  recommendation: string;
  /** What the conclusion was drawn from. Present because no flow logs are
   * ingested — findings are structural inferences, and say so. */
  basis: string;
  connection_id: string;
  subscription_id: string;
  environment: string;
  vnet_id?: string;
}

/** One rule in the rule-based, UI-editable network design policy. */
export interface NetworkPolicyRule {
  rule_id: string;
  name: string;
  description: string;
  category: string;
  severity: NetworkSeverity;
  enabled: boolean;
  parameters: Record<string, unknown>;
  /** Whether the analyzer has a gap check for this rule. Absent on older
   * API responses, in which case evaluability is unknown. */
  evaluated?: boolean;
}

/** The full design policy gap analysis is checked against. */
export interface NetworkDesignPolicy {
  name: string;
  description: string;
  is_declared: boolean;
  source_path: string;
  hub_vnet_names: string[];
  require_firewall_in_hub: boolean;
  require_default_route_to_firewall: boolean;
  require_nsg_on_every_subnet: boolean;
  forbid_spoke_to_spoke_peering: boolean;
  forbid_public_ip_on_spoke_nics: boolean;
  require_private_endpoint_for_services: string[];
  require_private_dns_zone_link: boolean;
  require_bidirectional_peering: boolean;
  approved_peerings: Array<{ source: string; target: string; bidirectional: boolean }>;
  exempt_subnet_names: string[];
  exempt_vnet_names: string[];
  rules: NetworkPolicyRule[];
}

export interface RuleFinding {
  finding_id: string;
  category: string;
  severity: NetworkSeverity;
  rule_id: string;
  rule_name: string;
  control: string;
  control_id: string;
  title: string;
  detail: string;
  evidence: Record<string, unknown>;
  recommendation: string;
  connection_id: string;
  subscription_id: string;
  environment: string;
}

export interface FlowEndpoint {
  raw: string;
  ip_address: string;
  subnet_id: string;
  vnet_id: string;
  nsg_id: string;
  resource_id: string;
  environment: string;
  name: string;
  is_internet: boolean;
  resolved: boolean;
}

export interface FlowHop {
  stage: string;
  control: string;
  control_id: string;
  decision: string;
  rule_id: string;
  rule_name: string;
  priority: number | null;
  reason: string;
}

export interface FlowResult {
  query: {
    source: string;
    destination: string;
    port: number | null;
    protocol: string;
    environment_scope: string;
  };
  source: FlowEndpoint;
  destination: FlowEndpoint;
  verdict: FlowVerdict;
  hops: FlowHop[];
  missing_enforcement_points: string[];
  /** Non-empty means the verdict is qualified: something could not be resolved. */
  unknowns: string[];
  path_summary: string;
}

export interface HubDependents {
  hub_vnet_id: string;
  hub_name: string;
  dependent_vnets: Array<{
    vnet_id: string;
    name: string;
    connection_id: string;
    subscription_id: string;
    business_service: string;
    environment: string;
    observed: boolean;
  }>;
  dependent_count: number;
  shared_services?: SharedServiceSummary[];
}

// --------------------------------------------------------------------------
// FinOps, identity, SPN governance, access reviews, and audit evidence.
//
// `annual_savings` is deliberately nullable: Azure Advisor does not quantify
// every recommendation, and null means "not quantified" rather than "no
// saving". `unavailable_metrics` names the figures the platform genuinely
// cannot observe so the UI states the gap instead of implying zero spend.
// --------------------------------------------------------------------------

export interface UnavailableMetric {
  metric: string;
  reason: string;
}

export interface FinOpsSummary {
  identified_annual_savings: number;
  currency: string;
  savings_opportunity_count: number;
  quantified_opportunity_count: number;
  waste_item_count: number;
  actual_spend?: number;
  actual_spend_currency?: string;
  actual_spend_source?: string;
  actual_spend_period_start?: string;
  actual_spend_period_end?: string;
  actual_spend_record_count?: number;
  unavailable_metrics: UnavailableMetric[];
}

export interface SavingsOpportunity {
  recommendation_id: string;
  resource_id: string;
  problem: string;
  solution: string;
  impact: string;
  annual_savings: number | null;
  currency: string;
  savings_source: string;
  subscription?: string;
  application?: string;
  business_service?: string;
  owner?: string;
  environment?: string;
}

export interface WasteItem {
  resource_id: string;
  resource_type: string;
  reason: string;
  detail: string;
  annual_savings: number | null;
  currency: string;
  savings_source: string;
  subscription?: string;
  application?: string;
  business_service?: string;
  owner?: string;
  environment?: string;
}

export interface FinOpsAttributionGroup {
  identified_annual_savings: number;
  savings_opportunity_count: number;
  waste_item_count: number;
  [dimension: string]: string | number;
}

export interface IdentitySummary {
  principal_count: number;
  privileged_principal_count: number;
  subscription_owner_count: number;
  stale_assignment_count: number;
  non_human_principal_count: number;
  assignment_count: number;
  stale_threshold_days: number;
}

export interface PrincipalRisk {
  principal_id: string;
  principal_type: string;
  assignment_count: number;
  privileged: boolean;
  widest_scope: string;
  widest_scope_breadth: string;
  roles: string[];
  stale: boolean;
  last_changed: string;
  blast_radius: Record<string, number>;
}

export interface SubscriptionOwnerRecord {
  principal_id: string;
  principal_type: string;
  scope: string;
  scope_breadth: string;
  subscription_id: string;
  assigned_on: string;
  stale: boolean;
}

export interface StaleAccessRecord {
  assignment_id: string;
  principal_id: string;
  principal_type: string;
  role: string;
  scope: string;
  privileged: boolean;
  last_changed: string;
  threshold_days: number;
}

export interface NonHumanIdentity {
  principal_id: string;
  principal_type: string;
  name?: string;
  resource_id?: string;
  assignment_count?: number;
  privileged?: boolean;
}

export interface SpnSummary {
  credential_count: number;
  expired_count: number;
  expiring_soon_count: number;
  unknown_expiry_count: number;
  healthy_count: number;
  unused_count: number;
  expiry_warning_days: number;
}

export interface ServicePrincipalGovernance {
  credential_id: string;
  connection_id: string;
  connection_name: string;
  client_id: string;
  tenant_id: string;
  subscription_id: string;
  kind: string;
  active: boolean;
  scopes: string[];
  expires_at: string;
  days_to_expiry: number | null;
  rotation_status: string;
  secret_ref: string;
  in_use: boolean;
  last_used: string;
  /** Null when the SPN object id is unknown: role assignments reference the
   * object id, never the client id, so a count would otherwise be misleading. */
  observed_assignment_count: number | null;
  assignment_lookup_state: string;
  issues: string[];
}

export interface AccessReviewPack {
  audience: string;
  generated_at: string;
  scope: Record<string, string[]>;
  provenance: Record<string, unknown>;
  sections: Record<string, unknown>;
  [key: string]: unknown;
}

export interface AuditExportPack {
  kind: string;
  generated_at: string;
  scope: Record<string, string[]>;
  provenance: Record<string, unknown>;
  sections: Record<string, unknown>;
  warnings?: string[];
  [key: string]: unknown;
}

export interface EnterpriseRole {
  role_id: string;
  name: string;
  description: string;
  permissions: string[];
}

export interface EnterpriseSettings {
  roles: EnterpriseRole[];
  taxonomies: Record<string, string[]>;
  onboarding_policy: Record<string, unknown>;
  architecture_policy: Record<string, unknown>;
  vulnerability_policy?: Record<string, unknown>;
  agent_policy?: Record<string, unknown>;
  retention_policy?: Record<string, unknown>;
  report_templates?: unknown[];
  [key: string]: unknown;
}

// --------------------------------------------------------------------------
// Pre-deployment change risk
// --------------------------------------------------------------------------

export interface ChangeAssessmentSources {
  sources: string[];
  simulation_domains: string[];
  verdicts: string[];
  risk_levels: string[];
}

export interface ProposedResourceChange {
  address: string;
  action: string;
  resource_type: string;
  resource_id: string;
  name: string;
  provider: string;
  changed_properties: string[];
  is_destructive: boolean;
  source_ref: string;
}

export interface ProposedChange {
  change_id: string;
  source: string;
  title: string;
  author: string;
  submitted_at: string;
  repository: string;
  target_environment: string;
  target_subscriptions: string[];
  resource_changes: ProposedResourceChange[];
  effective_change_count: number;
  ingestion_warnings: string[];
}

export interface StateComparisonEntry {
  address: string;
  finding: string;
  action: string;
  resource_id: string;
  detail: string;
  drifted_properties: string[];
  discovered_observed_at: string;
}

export interface StateComparison {
  comparisons: StateComparisonEntry[];
  counts: Record<string, number>;
  compared_count: number;
  discovered_count: number;
  consistent: boolean;
  unknowns: string[];
}

export interface ImpactedResource {
  resource_id: string;
  resource_type: string;
  name: string;
  application: string;
  business_service: string;
  environment: string;
  subscription: string;
  owner: string;
  support_team: string;
  region: string;
  criticality: string;
  depth: number;
  relationship: string;
  depends_on: string[];
  observed_at: string;
}

export interface ChangeBlastRadius {
  impacted_resources: ImpactedResource[];
  total_impacted_count: number;
  directly_changed_count: number;
  applications: string[];
  business_services: string[];
  subscriptions: string[];
  environments: string[];
  owners: string[];
  support_teams: string[];
  regions: string[];
  network_controls_in_path: string[];
  vulnerable_resources_in_path: string[];
  max_depth_reached: number;
  truncated: boolean;
  unknowns: string[];
  interpretation: string;
  confirmed_impact: boolean;
}

export interface SimulatedEffect {
  domain: string;
  address: string;
  effect: string;
  severity: string;
  detail: string;
  basis: string;
  requires_validation: boolean;
}

export interface ChangeSimulation {
  effects: SimulatedEffect[];
  simulated_domains: string[];
  by_domain: Record<string, number>;
  by_severity: Record<string, number>;
  highest_severity: string;
  unclassified_addresses: string[];
  unknowns: string[];
  basis: string;
  interpretation: string;
  confirmed_outcome: boolean;
}

export interface RiskEvidenceItem {
  factor: string;
  observation: string;
  source: string;
}

export interface ChangeRisk {
  score: number;
  level: string;
  factors: Record<string, number>;
  contributing_factors: Record<string, number>;
  evidence: RiskEvidenceItem[];
  confidence: string;
  confidence_rationale: string;
  unknowns: string[];
  justification: string;
  interpretation: string;
  confirmed_cause: boolean;
}

export interface CabTrigger {
  trigger: string;
  reason: string;
}

export interface CabRecommendation {
  verdict: string;
  summary: string;
  conditions: string[];
  required_approvals: string[];
  triggers: CabTrigger[];
  risk_score: number;
  risk_level: string;
  confidence: string;
  unknowns: string[];
  interpretation: string;
  confirmed_cause: boolean;
}

export interface ChangeAssessment {
  assessment_id: string;
  assessed_at: string;
  source_engine: string;
  change: ProposedChange;
  state_comparison: StateComparison;
  blast_radius: ChangeBlastRadius;
  simulation: ChangeSimulation;
  risk: ChangeRisk;
  cab_recommendation: CabRecommendation;
  scope: Record<string, string[]>;
  scope_excluded_resource_count: number;
  confirmed_cause: boolean;
}

export interface ChangeAssessmentSummary {
  assessment_id: string;
  change_id: string;
  source: string;
  title: string;
  author: string;
  assessed_at: string;
  target_environment: string;
  resource_change_count: number;
  risk_score: number;
  risk_level: string;
  confidence: string;
  verdict: string;
  total_impacted_count: number;
  business_services: string[];
}

// --------------------------------------------------------------------------
// Patch remediation
// --------------------------------------------------------------------------

export interface AvailablePatch {
  patch_id: string;
  title: string;
  classification: string;
  severity: string;
  cve_ids: string[];
  reboot_required: boolean;
  published_at: string;
  /** Provenance of the availability claim, e.g. "derived:open-findings". */
  source: string;
  node_pool: string;
  current_version: string;
  target_version: string;
}

export type PatchOperation = "install_patches" | "node_image_upgrade";

export interface PatchTarget {
  target_id: string;
  name: string;
  inventory_kind: string;
  resource_type: string;
  subscription_id: string;
  subscription_connection: string;
  resource_group: string;
  environment: string;
  business_service: string;
  application: string;
  owner: string;
  region: string;
  criticality: string;
  os_family: string;
  reachable: boolean;
  internet_exposed: boolean;
  cve_count: number;
  critical_count: number;
  overdue_count: number;
  max_days_open: number;
  available_patches: AvailablePatch[];
  patchable: boolean;
  blocked_reason: string;
  requires_node_pool: boolean;
  operation: PatchOperation;
}

export interface PatchRun {
  run_id: string;
  target_id: string;
  inventory_kind: string;
  operation: PatchOperation;
  patch_ids: string[];
  state: string;
  requested_by: string;
  approved_by: string;
  reason: string;
  reboot_setting: string;
  dry_run: boolean;
  created_at: string;
  updated_at: string;
  provider: string;
  provider_job_id: string;
  message: string;
  subscription_id: string;
  subscription_connection: string;
  business_service: string;
  environment: string;
  details: Record<string, unknown>;
  terminal: boolean;
}

export interface PatchRunCreateRequest {
  target_id: string;
  patch_ids: string[];
  reason: string;
  approved_by?: string;
  reboot_setting?: "IfRequired" | "Never" | "Always";
  node_pool?: string;
  dry_run?: boolean;
}

export interface DurableEvidence {
  evidence_id: string;
  source_family: string;
  source_object_id: string;
  locator: string;
  resource_ids: string[];
  entity_ids: string[];
  observed_at: string;
  ingested_at: string;
  watermark: string;
  ingestion_status: string;
  provenance: Record<string, unknown>;
  freshness: Freshness;
  quality: string;
  availability: string;
  confidence: string;
  assertion: string;
  fingerprint: string;
  situation_id: string;
}

export interface DurableSourceStatus {
  source_family: string;
  run_id: string;
  status: string;
  observed_at: string;
  ingested_at: string;
  watermark: string;
  query_version: string;
  requested_scope: Record<string, string[]>;
  provider_status: string;
  freshness: Freshness;
  availability: string;
  quality: string;
  error: string;
}

export interface DurableSituationLink {
  link_id: string;
  situation_id: string;
  entity_type: string;
  entity_id: string;
  relation: string;
  quality: "resolved" | "unresolved" | "degraded" | string;
  provenance: Record<string, unknown>;
}

export interface SituationAuditEvent {
  event_id: string;
  actor: string;
  action: string;
  scope_snapshot: Record<string, string[]>;
  timestamp: string;
  situation_id: string;
  evidence_ids: string[];
  source_references: string[];
  run_id: string;
}

export interface DurableSituation {
  situation_id: string;
  resource_id: string;
  title: string;
  situation_type: string;
  lifecycle_state: string;
  severity: string;
  priority: "P1" | "P2" | "P3" | string;
  scope: Record<string, string[]>;
  owner: string;
  support_team: string;
  affected_resource_ids: string[];
  linked_evidence_ids: string[];
  started_at: string;
  last_observed_at: string;
  evidence_state: string;
  warnings: string[];
  contradiction_ids: string[];
  unknowns: string[];
  run_id: string;
  evidence?: DurableEvidence[];
  links?: DurableSituationLink[];
  source_status?: DurableSourceStatus[];
}

export type SoftwareSourceType = InventorySourceType | "unlinked";

export interface SoftwareInventoryGroup {
  key: string;
  software_name: string;
  software_version: string;
  install_count: number;
  source_types: SoftwareSourceType[];
  linked_count: number;
  unlinked_count: number;
  publishers: string[];
}

export interface SoftwareInventoryMachine {
  software_name: string;
  software_version: string;
  canonical_name: string;
  canonical_version: string;
  canonical_identity: string;
  raw_software_name: string;
  raw_software_version: string;
  raw_identity: { name: string; version: string };
  resource_id: string;
  machine_name: string;
  computer: string;
  source_computer_id: string;
  source_type: InventorySourceType | null;
  join_status: "linked" | "unlinked";
  resource_join_status: "linked" | "unlinked";
  subscription_id: string;
  resource_group: string;
  environment: string;
  publisher: string;
  software_type: string;
  observed_at: string;
  time_generated: string;
  evidence: InventoryEvidence[];
  mapping_id?: string;
  mapping_status?: SoftwareMappingStatus | "";
  mapping_revision?: number;
  mapping_method?: "deterministic" | "ai" | "operator" | "";
  mapping_confidence?: number;
  mapping_provenance?: Record<string, unknown> | null;
  mapping_source_timestamp?: string;
}

export interface SoftwareInventoryCollection {
  groups: SoftwareInventoryGroup[];
  source_status: Record<string, InventorySourceStatus>;
  observed_at: string;
  query_version: string;
  generation_id: string;
  requested_scope: Record<string, string[]>;
}

export interface SoftwareInventoryDetail {
  group: SoftwareInventoryGroup;
  machines: SoftwareInventoryMachine[];
  source_status: Record<string, InventorySourceStatus>;
  observed_at: string;
  query_version: string;
  generation_id: string;
  requested_scope: Record<string, string[]>;
}

export type SoftwareMappingStatus = "suggested" | "approved" | "rejected";

export interface SoftwareMapping {
  mapping_id: string;
  raw_name: string;
  raw_version: string;
  publisher: string;
  raw_identity: { name: string; version: string; publisher: string };
  canonical_name: string;
  canonical_version: string;
  canonical_identity: string;
  method: "deterministic" | "ai" | "operator";
  confidence: number;
  status: SoftwareMappingStatus;
  provenance: Record<string, unknown>;
  source_timestamp: string;
  scope_predicate: Record<string, string[]>;
  revision: number;
  reason: string;
  created_at: string;
  updated_at: string;
}

export interface SoftwareMappingCollection {
  mappings: SoftwareMapping[];
  repository_revision: number;
  requested_scope: Record<string, string[]>;
}

// ---------------------------------------------------------------------------
// Resource health -- live CPU/network/disk utilization via Azure Monitor
// Metrics. Memory % and disk free % are not available from platform metrics
// for an ordinary VM (they require Azure Monitor Agent + Log Analytics guest
// counters), so every response names them in `unavailable_metrics` rather
// than omitting the fields silently.
// ---------------------------------------------------------------------------

export type ResourceHealthStatus = "critical" | "warning" | "healthy" | "unknown";

export interface MetricSeriesPoint {
  timestamp: string;
  value: number;
}

export interface ResourceUtilization {
  resource_id: string;
  resource_name: string;
  resource_type: string;
  subscription_id: string;
  resource_group: string;
  connection_id: string;
  cpu_percent: number | null;
  network_in_bytes: number | null;
  network_out_bytes: number | null;
  disk_read_bytes: number | null;
  disk_write_bytes: number | null;
  os_disk_queue_depth: number | null;
  memory_percent: number | null;
  disk_free_percent: number | null;
  status: ResourceHealthStatus;
  observed_at: string;
  error: string;
  unavailable_metrics: string[];
  cpu_series: MetricSeriesPoint[];
}

export interface ResourceHealthSummary {
  total: number;
  critical: number;
  warning: number;
  healthy: number;
  unknown: number;
}

export interface ResourceHealthSnapshot {
  resources: ResourceUtilization[];
  summary: ResourceHealthSummary;
  observed_at: string;
  warnings: string[];
  unavailable_metrics: string[];
  cached: boolean;
  cache_ttl_seconds: number;
}

export type CopilotPageKind = "network" | "vulnerability" | "patch" | "incident" | "governance" | "resource";
export type CopilotSnapshotStatus = "ok" | "empty" | "unavailable" | "denied";
export interface CopilotSelectedResource { resource_id: string; resource_type: string; name?: string; attributes?: Record<string, string>; }
export interface CopilotFreshnessRecord { source: string; observed_at: string; status: "fresh" | "stale" | "partial" | "unavailable"; }
export interface CopilotScopeAuthorization { declared: Record<string, string[]>; authorized: boolean; }
export interface CopilotEvidenceRow { evidence_id: string; resource_id?: string; section: string; data: Record<string, unknown>; status: CopilotSnapshotStatus; observed_at?: string; }
export interface CopilotPageSnapshot {
  version: "1"; page_kind: CopilotPageKind; page_id: string;
  selected_resources: CopilotSelectedResource[]; filters: Record<string, string[]>;
  freshness: CopilotFreshnessRecord[]; scope: CopilotScopeAuthorization;
  evidence: CopilotEvidenceRow[]; question: string; rechecks: string[];
}
export interface CopilotContextFinding {
  finding_id: string; resource_ids: string[]; check_id: string; policy_id: string; source_status: string;
  status: "verified" | "hypothesis" | "partial" | "unavailable" | "denied"; summary: string;
  evidence_refs: string[]; confidence: Confidence; uncertainty: string[]; stale: boolean;
  next_check: string; actionable: boolean;
}
export interface CopilotContextResult {
  page_kind: CopilotPageKind; page_id: string; snapshot_hash: string; stages: string[];
  findings: CopilotContextFinding[]; tool_calls: Array<{ tool: string; arguments: Record<string, unknown>; status: CopilotSnapshotStatus; data: unknown; evidence: EvidenceItem[]; warning: string; }>;
  synthesis_mode: "foundry" | "deterministic"; synthesis_agent: string;
  synthesis: { text: string; agent_name: string; model: string; grounded: boolean } | null;
  warnings: string[]; ledger_id?: string;
}
