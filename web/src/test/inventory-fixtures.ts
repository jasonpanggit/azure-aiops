import type {
  FlatResourceCollection, InventoryNarrative, LifecycleReview, OsInventoryCollection, OsInventoryDetail,
  PaasInventoryCollection, PaasInventoryDetail, SoftwareInventoryCollection, SoftwareInventoryDetail, SoftwareMappingCollection,
} from "@/lib/types";

/** Builds dense, source-qualified inventory records and revision-based review fixtures. */
export function buildInventoryFixtures() {
  const observedAt = "2026-09-20T12:00:00Z";
  const sourceStatus: OsInventoryCollection["source_status"] = {
    azure_vm: { source_type: "azure_vm", state: "ready", row_count: 27, observed_at: observedAt, query_version: "v1", error: "" },
    arc: { source_type: "arc", state: "partial", row_count: 4, observed_at: observedAt, query_version: "v1", error: "Coverage is incomplete." },
    logs: { source_type: "logs", state: "ready", row_count: 27, observed_at: observedAt, query_version: "v1", error: "" },
  };
  const meta = {
    source_status: sourceStatus, observed_at: observedAt, query_version: "v1", generation_id: "ui-generation",
    requested_scope: { subscription: ["sub-ui"] },
  };
  const os: OsInventoryCollection = {
    ...meta,
    groups: Array.from({ length: 23 }, (_, index) => ({
      key: `os-group-${index}`, os_name: index % 2 ? "Ubuntu Enterprise Server" : "Windows Server Datacenter",
      os_version: `2022-production-release-${index}`, machine_count: 27 - index, source_types: ["azure_vm", "arc"],
      lifecycle_status: index === 0 ? "Unknown" : index % 3 ? "Supported" : "Expired",
      support_end: index === 0 ? null : index % 3 ? "2030-01-01" : "2025-01-01",
      days_remaining: index === 0 ? null : index % 3 ? 1000 : -100,
      review_required: index === 0, support_channel: "mainstream", lifecycle_evidence: ["Scoped lifecycle catalog observation."],
    })),
  };
  const osDetail: OsInventoryDetail = {
    ...meta, group: os.groups[0],
    machines: Array.from({ length: 27 }, (_, index) => ({
      ...os.groups[0], resource_id: `/subscriptions/sub-ui/resourceGroups/rg-payments/providers/Microsoft.Compute/virtualMachines/payments-worker-${index}`,
      machine_name: `payments-production-worker-with-long-name-${index}`, source_type: "azure_vm", subscription_id: "sub-ui",
      resource_group: "rg-payments-production-platform", environment: "production", observed_at: observedAt, evidence: [], source_status: "ready",
    })),
  };
  const software: SoftwareInventoryCollection = {
    ...meta, source_status: { logs: sourceStatus.logs },
    groups: Array.from({ length: 23 }, (_, index) => ({
      key: `software-group-${index}`, software_name: `Payments enterprise runtime ${index}`, software_version: "2026.09",
      install_count: 27 - index, source_types: ["azure_vm", "unlinked"], linked_count: 26 - index, unlinked_count: 1,
      publishers: ["Payments platform engineering"],
    })),
  };
  const softwareDetail: SoftwareInventoryDetail = {
    ...meta, source_status: software.source_status, group: software.groups[0],
    machines: osDetail.machines.map((machine, index) => ({
      software_name: software.groups[0].software_name, software_version: "2026.09",
      canonical_name: software.groups[0].software_name, canonical_version: "2026.09", canonical_identity: "runtime|2026.09",
      raw_software_name: "Payments Enterprise Runtime raw", raw_software_version: "v2026.09",
      raw_identity: { name: "Payments Enterprise Runtime raw", version: "v2026.09" },
      resource_id: index === 0 ? "" : machine.resource_id, machine_name: machine.machine_name,
      computer: machine.machine_name, source_computer_id: `agent-${index}`, source_type: index === 0 ? null : "azure_vm",
      join_status: index === 0 ? "unlinked" : "linked", resource_join_status: index === 0 ? "unlinked" : "linked",
      subscription_id: "sub-ui", resource_group: machine.resource_group, environment: machine.environment,
      publisher: "Payments platform engineering", software_type: "Package", observed_at: observedAt, time_generated: observedAt, evidence: [],
    })),
  };
  const azure: PaasInventoryCollection = {
    ...meta, source_status: { azure_vm: sourceStatus.azure_vm },
    groups: Array.from({ length: 23 }, (_, index) => ({
      key: `azure-group-${index}`, resource_type: index % 2 ? "microsoft.storage/storageaccounts" : "microsoft.app/containerapps",
      sku: `production-sku-${index}`, tier: "Enterprise", resource_count: 27 - index,
    })),
  };
  const azureDetail: PaasInventoryDetail = {
    ...meta, source_status: azure.source_status, group: azure.groups[0],
    resources: osDetail.machines.map((machine, index) => ({
      resource_id: `/subscriptions/sub-ui/resourceGroups/rg-payments/providers/Microsoft.App/containerApps/payments-api-${index}`,
      resource_name: `payments-production-api-with-long-name-${index}`, resource_type: azure.groups[0].resource_type, family: "paas",
      tenant_id: "tenant-ui", subscription_id: "sub-ui", resource_group: machine.resource_group, location: "australiaeast",
      sku: "production-sku-0", tier: "Enterprise", runtime: "", provisioning_state: index === 0 ? "" : "Succeeded",
      os_name: "", os_version: "", observed_at: observedAt, query_version: "v1", tags: {},
    })),
  };
  const mappings: SoftwareMappingCollection = {
    repository_revision: 3, requested_scope: meta.requested_scope,
    mappings: [{
      mapping_id: "map-ui", raw_name: "Payments Enterprise Runtime", raw_version: "v2026.09",
      publisher: "Payments platform engineering", raw_identity: { name: "Payments Enterprise Runtime", version: "v2026.09", publisher: "Payments platform engineering" },
      canonical_name: "Payments runtime", canonical_version: "2026.09", canonical_identity: "runtime|2026.09",
      method: "ai", confidence: 0.8, status: "suggested", provenance: { model: "normalizer" },
      source_timestamp: observedAt, scope_predicate: meta.requested_scope, revision: 3, reason: "", created_at: observedAt, updated_at: observedAt,
    }],
  };
  const narrative: InventoryNarrative = {
    fact_summary: "Lifecycle coverage is incomplete; review unknown dates with the accountable owner.",
    fact_items: [{ label: "Coverage", value: "Authorized observed records only" }],
    narrated_summary: null, narrated_by: "", model: "", confidence: "low",
    citations: [{ source_engine: "InventoryService", source_table: "inventory/os_observations", timestamp: observedAt, reference: "" }],
    source_status: sourceStatus, requested_scope: { dimensions: ["subscription"] }, status: "fact_only",
  };
  const review: LifecycleReview = {
    normalized_os_key: "windows server|2022", os_name: os.groups[0].os_name, os_version: os.groups[0].os_version,
    status: "review_required", catalog_revision: 3,
    classification: { status: "Unknown", support_end: null, days_remaining: null, support_channel: "mainstream", confidence: 0,
      evidence: ["No lifecycle date is confirmed."] },
    candidates: [{ candidate_id: "candidate-ui", date: "2030-01-01", source_kind: "official_vendor",
      citation: "https://learn.microsoft.com/lifecycle/", retrieved_at: observedAt,
      extracted_claim: "Candidate support date requires operator review.", confidence: 0.8, support_channel: "mainstream" }],
    provenance: null,
  };
  const resources: FlatResourceCollection = {
    requested_scope: meta.requested_scope, family_availability: {}, query_version: "v1",
    resources: [...osDetail.machines, ...azureDetail.resources].map((resource) => ({
      family: "os_name" in resource && resource.os_name ? "os" : "paas", resource_id: resource.resource_id,
      resource_name: "machine_name" in resource ? resource.machine_name : resource.resource_name,
      resource_type: "resource_type" in resource ? resource.resource_type : "microsoft.compute/virtualmachines",
      subscription_id: resource.subscription_id, resource_group: resource.resource_group, environment: "production",
    })),
  };
  return { os, osDetail, software, softwareDetail, azure, azureDetail, mappings, narrative, review, resources };
}
