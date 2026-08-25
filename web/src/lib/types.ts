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
  warnings?: string[];
  pagination?: Pagination | null;
}

export type InventorySourceType = "azure_vm" | "arc";
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

export interface VulnerabilityFinding {
  finding_id: string;
  cve_id: string;
  server_id: string;
  missing_kb: string;
  application: string;
  business_service: string;
  owner: string;
  subscription_id: string;
  environment: string;
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
  health: ConnectionHealthDetail;
}

export interface ConnectionSyncResult {
  connection_id: string;
  status: string;
  sync_state: SyncState;
  health: ConnectionHealthDetail;
  [key: string]: unknown;
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
}

export interface SearchResult {
  query: string;
  intent: string;
  results: Array<Record<string, unknown>>;
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
