import type {
  AccessReviewPack, AuditExportPack, EnterpriseSettings, FinOpsAttributionGroup,
  FinOpsSummary, FlatInventoryResource, IdentitySummary, NonHumanIdentity,
  PrincipalRisk, ResourceHealthSnapshot, SavingsOpportunity, ServicePrincipalGovernance,
  SpnSummary, StaleAccessRecord, SubscriptionOwnerRecord, WasteItem,
} from "@/lib/types";

const resourceId = (index: number) =>
  `/subscriptions/sub-accountability/resourceGroups/production-payments/providers/Microsoft.Compute/virtualMachines/payments-worker-${index}`;

/** Builds dense, scoped cost signals including genuinely unquantified savings. */
export function buildCostSignals(count = 23) {
  const summary: FinOpsSummary = {
    identified_annual_savings: 125000, currency: "AUD",
    savings_opportunity_count: count, quantified_opportunity_count: Math.max(0, count - 1),
    waste_item_count: count, actual_spend: 15234, actual_spend_currency: "AUD",
    actual_spend_period_start: "2026-09-01", actual_spend_period_end: "2026-09-20",
    actual_spend_record_count: 42,
    unavailable_metrics: [{ metric: "forecast_spend", reason: "A forecast has not been returned for this scope." }],
  };
  const opportunities: SavingsOpportunity[] = Array.from({ length: count }, (_, index) => ({
    recommendation_id: `recommendation-${index}`, resource_id: resourceId(index),
    problem: `Rightsize payments worker ${index}`, solution: "Validate utilization with the service owner before resizing.",
    impact: index % 2 ? "Medium" : "High", annual_savings: index === 0 ? null : 1200,
    currency: "AUD", savings_source: "Azure Advisor", owner: "Payments operations",
    subscription: "sub-accountability", business_service: "Payments",
  }));
  const waste: WasteItem[] = Array.from({ length: count }, (_, index) => ({
    resource_id: resourceId(index), resource_type: "Virtual machine",
    reason: index % 2 ? "deallocated_resource" : "low_utilization_observed",
    detail: "Review the observation window before changing the resource.",
    annual_savings: index === 0 ? null : 600, currency: "AUD",
    savings_source: "Azure Advisor", owner: "Payments operations",
  }));
  const groups: FinOpsAttributionGroup[] = Array.from({ length: count }, (_, index) => ({
    subscription: `Cost subscription ${index}`, application: `Application ${index}`,
    business_service: `Service ${index}`, owner: `Owner ${index}`, environment: `Environment ${index}`,
    identified_annual_savings: 1200, savings_opportunity_count: 1, waste_item_count: 1,
  }));
  return { summary, opportunities, waste, groups };
}

/** Builds observed access records with explicit expiry and assignment gaps. */
export function buildAccessSignals(count = 23) {
  const summary: IdentitySummary = {
    principal_count: count, privileged_principal_count: count, subscription_owner_count: count,
    stale_assignment_count: count, non_human_principal_count: count,
    assignment_count: count, stale_threshold_days: 90,
  };
  const principals: PrincipalRisk[] = Array.from({ length: count }, (_, index) => ({
    principal_id: `principal-${index}`, principal_type: "service_principal", assignment_count: 1,
    privileged: true, widest_scope: "/subscriptions/sub-accountability",
    widest_scope_breadth: "subscription", roles: ["Owner"], stale: true,
    last_changed: "2026-01-01T00:00:00Z", blast_radius: { subscriptions: 1 },
  }));
  const owners: SubscriptionOwnerRecord[] = principals.map((principal) => ({
    principal_id: principal.principal_id, principal_type: principal.principal_type,
    scope: principal.widest_scope, scope_breadth: "subscription",
    subscription_id: "sub-accountability", assigned_on: principal.last_changed, stale: true,
  }));
  const assignments: StaleAccessRecord[] = principals.map((principal, index) => ({
    assignment_id: `assignment-${index}`, principal_id: principal.principal_id,
    principal_type: principal.principal_type, role: "Owner", scope: principal.widest_scope,
    privileged: true, last_changed: principal.last_changed, threshold_days: 90,
  }));
  const identities: NonHumanIdentity[] = principals.map((principal, index) => ({
    principal_id: principal.principal_id, principal_type: principal.principal_type,
    name: `Payments automation ${index}`, resource_id: resourceId(index), assignment_count: 1,
  }));
  const credentials: ServicePrincipalGovernance[] = principals.map((_, index) => ({
    credential_id: `credential-${index}`, connection_id: `connection-${index}`,
    connection_name: `Payments connection ${index}`, client_id: `client-${index}`,
    tenant_id: "tenant-accountability", subscription_id: "sub-accountability",
    kind: "service_principal", active: true, scopes: ["sub-accountability"],
    expires_at: "", days_to_expiry: null, rotation_status: "unknown",
    secret_ref: "", in_use: true, last_used: "2026-09-20T12:00:00Z",
    observed_assignment_count: null, assignment_lookup_state: "unresolved",
    issues: ["Expiry is not recorded; rotation cannot be verified."],
  }));
  const spnSummary: SpnSummary = {
    credential_count: count, expired_count: 0, expiring_soon_count: 0,
    unknown_expiry_count: count, healthy_count: 0, unused_count: 0, expiry_warning_days: 30,
  };
  return { summary, principals, owners, assignments, identities, credentials, spnSummary };
}

/** Builds editable governance settings without any provider credentials. */
export function buildEnterpriseSettings(): EnterpriseSettings {
  return {
    can_write: true, persistent: true, revision: 4,
    roles: Array.from({ length: 23 }, (_, index) => ({
      role_id: `role-${index}`, name: `Operations reviewer ${index}`,
      description: "Reviews scoped evidence before an accountable decision.",
      permissions: index % 2 ? ["read"] : ["read", "admin"],
    })),
    taxonomies: { environments: ["production", "test"] },
    onboarding_policy: { require_owner: true, review_days: 30 },
    architecture_policy: { require_review: true },
    vulnerability_policy: { exception_days: 7 },
    agent_policy: { allow_execution: false },
    retention_policy: { retention_days: 365 },
  };
}

/** Builds a partial downloadable pack whose caveats must remain visible. */
export function buildEvidencePack(label = "executive"): AccessReviewPack & AuditExportPack {
  return {
    audience: label, kind: label, generated_at: "2026-09-20T12:00:00Z",
    scope: { subscription: ["sub-accountability"] },
    provenance: { source: "Observed access assignments", coverage: "partial" },
    sections: { records: Array.from({ length: 40 }, (_, index) => ({ id: index, note: "Review source evidence before approval." })) },
    warnings: ["This pack excludes assignments outside the authorized subscription."],
  };
}

/** Builds authorized compute inventory, including a deliberately long name. */
export function buildHealthResources(): FlatInventoryResource[] {
  return Array.from({ length: 3 }, (_, index) => ({
    family: "compute", resource_id: resourceId(index),
    resource_name: index === 0 ? "payments-production-worker-with-a-long-resource-name" : `payments-worker-${index}`,
    resource_type: "microsoft.compute/virtualmachines", subscription_id: "sub-accountability",
    resource_group: "production-payments", environment: "production",
  }));
}

/** Builds a returned metric snapshot while preserving unavailable guest data. */
export function buildHealthSnapshot(resource: FlatInventoryResource): ResourceHealthSnapshot {
  return {
    resources: [{
      ...resource, connection_id: "connection-0", cpu_percent: 42, memory_percent: null,
      disk_free_percent: null, network_in_bytes: 1024, network_out_bytes: 2048,
      disk_read_bytes: 4096, disk_write_bytes: 1024, os_disk_queue_depth: null,
      status: "healthy", observed_at: "2026-09-20T12:00:00Z", error: "",
      unavailable_metrics: ["memory_percent", "disk_free_percent"], cpu_series: [],
    }],
    summary: { total: 1, critical: 0, warning: 0, healthy: 1, unknown: 0 },
    observed_at: "2026-09-20T12:00:00Z",
    warnings: ["Guest metric coverage is incomplete; inspect source configuration."],
    unavailable_metrics: ["memory_percent", "disk_free_percent"], cached: true, cache_ttl_seconds: 120,
  };
}
