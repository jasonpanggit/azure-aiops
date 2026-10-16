"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { CountBarChart } from "@/components/ui/CountBarChart";
import { DonutChart } from "@/components/ui/DonutChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { DEFAULT_PAGE_SIZE } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { downloadCsv, serializeCsv } from "@/lib/csv";
import { formatDateTime } from "@/lib/format";
import {
  buildInventoryCopilotContext,
  type InventoryCopilotRecord,
} from "@/lib/copilot/page-adapters";
import { useScope } from "@/lib/scope-context";
import { scopeToSearchParams } from "@/lib/scope";
import { inventoryApi } from "@/lib/services";
import { ApiError } from "@/lib/types";
import type {
  Envelope,
  FlatInventoryResource,
  InventorySourceStatus,
  InventoryNarrative,
  LifecycleReview,
  OsInventoryGroup,
  OsInventoryMachine,
  PaasInventoryGroup,
  PaasInventoryResource,
  Pagination,
  SoftwareInventoryGroup,
  SoftwareInventoryDetail,
  SoftwareInventoryMachine,
  SoftwareMapping,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

type InventoryTab = "os" | "software" | "azure";

// Page sizes for the server-paginated tables. Kept below the API's `limit`
// cap (500). The top-level tables let the operator pick their own row count;
// the inline drill-downs stay fixed so a nested table can't dominate the page.
const AZURE_DETAIL_PAGE_SIZE = 25;
const OS_DETAIL_PAGE_SIZE = 25;
const SOFTWARE_DETAIL_PAGE_SIZE = 25;

/**
 * Readable display names for Azure resource types.
 * ARG lowercases type names, so they cannot be reliably re-split
 * programmatically ("networksecuritygroups" has no casing to key on).
 * Known types are mapped explicitly; unknown types fall back to the
 * raw leaf segment so nothing is ever mislabelled.
 */
const RESOURCE_TYPE_LABELS: Record<string, string> = {
  "microsoft.alertsmanagement/smartdetectoralertrules": "Smart Detector Alert Rules",
  "microsoft.app/agents": "Container App Agents",
  "microsoft.app/containerapps": "Container Apps",
  "microsoft.app/jobs": "Container App Jobs",
  "microsoft.app/managedenvironments": "Container App Environments",
  "microsoft.cognitiveservices/accounts": "Cognitive Services Accounts",
  "microsoft.cognitiveservices/accounts/projects": "Cognitive Services Projects",
  "microsoft.compute/disks": "Managed Disks",
  "microsoft.compute/virtualmachines": "Virtual Machines",
  "microsoft.compute/virtualmachines/extensions": "VM Extensions",
  "microsoft.containerregistry/registries": "Container Registries",
  "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL Flexible Servers",
  "microsoft.documentdb/databaseaccounts": "Cosmos DB Accounts",
  "microsoft.eventgrid/systemtopics": "Event Grid System Topics",
  "microsoft.fabric/capacities": "Fabric Capacities",
  "microsoft.hybridcompute/machines": "Arc-enabled Servers",
  "microsoft.hybridcompute/machines/extensions": "Arc Machine Extensions",
  "microsoft.hybridcompute/machines/runcommands": "Arc Run Commands",
  "microsoft.insights/actiongroups": "Action Groups",
  "microsoft.insights/components": "Application Insights",
  "microsoft.insights/datacollectionendpoints": "Data Collection Endpoints",
  "microsoft.insights/datacollectionrules": "Data Collection Rules",
  "microsoft.insights/scheduledqueryrules": "Scheduled Query Rules",
  "microsoft.keyvault/vaults": "Key Vaults",
  "microsoft.maintenance/maintenanceconfigurations": "Maintenance Configurations",
  "microsoft.managedidentity/userassignedidentities": "User-assigned Identities",
  "microsoft.network/azurefirewalls": "Azure Firewalls",
  "microsoft.network/bastionhosts": "Bastion Hosts",
  "microsoft.network/loadbalancers": "Load Balancers",
  "microsoft.network/networkinterfaces": "Network Interfaces",
  "microsoft.network/networksecuritygroups": "Network Security Groups",
  "microsoft.network/networkwatchers": "Network Watchers",
  "microsoft.network/privatednszones": "Private DNS Zones",
  "microsoft.network/privatednszones/virtualnetworklinks": "Private DNS Zone Links",
  "microsoft.network/privateendpoints": "Private Endpoints",
  "microsoft.network/publicipaddresses": "Public IP Addresses",
  "microsoft.network/routetables": "Route Tables",
  "microsoft.network/virtualnetworks": "Virtual Networks",
  "microsoft.operationalinsights/workspaces": "Log Analytics Workspaces",
  "microsoft.operationsmanagement/solutions": "Management Solutions",
  "microsoft.portal/dashboards": "Portal Dashboards",
  "microsoft.storage/storageaccounts": "Storage Accounts",
  "microsoft.web/serverfarms": "App Service Plans",
  "microsoft.web/sites": "App Services",
  "microsoft.sql/servers": "SQL Servers",
  "microsoft.sql/servers/databases": "SQL Databases",
};

function resourceTypeLabel(resourceType: string): string {
  const known = RESOURCE_TYPE_LABELS[resourceType.toLowerCase()];
  if (known) return known;
  const leaf = (resourceType.split("/").pop() ?? resourceType).trim();
  if (!leaf) return resourceType;
  // Unknown type: surface the leaf with camelCase/separators respected,
  // rather than guessing at word boundaries and risking a wrong label.
  const spaced = leaf.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/[-_]/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Provider namespace, e.g. "microsoft.app/containerapps" -> "App". */
function providerLabel(resourceType: string): string {
  const namespace = resourceType.split("/")[0] ?? "";
  const provider = namespace.replace(/^microsoft\./i, "");
  return provider ? provider.replace(/\b\w/g, (c) => c.toUpperCase()) : "Azure";
}

function provisioningTone(state: string): "success" | "warning" | "critical" | "unknown" {
  const value = state.toLowerCase();
  if (value === "succeeded") return "success";
  if (["failed", "canceled", "cancelled"].includes(value)) return "critical";
  if (!value) return "unknown";
  return "warning";
}

function lifecycleLabel(group: OsInventoryGroup): string {
  return group.review_required ? "EOL date needs review" : group.lifecycle_status;
}

function sourceLabel(source: string): string {
  if (source === "azure_vm") return "Azure VM";
  if (source === "logs") return "Log Analytics";
  if (source === "unlinked") return "Unlinked";
  return "Arc";
}

function sourceTone(state: string): "success" | "warning" | "critical" | "unknown" {
  if (state === "ready") return "success";
  if (state === "partial" || state === "stale") return "warning";
  if (state === "unknown") return "unknown";
  return "critical";
}

function riskBucket(group: OsInventoryGroup): "expired" | "expiring" | "supported" | "review" {
  if (group.review_required || group.lifecycle_status.toLowerCase() === "unknown") return "review";
  if (["eol", "expired"].includes(group.lifecycle_status.toLowerCase())) return "expired";
  if (group.days_remaining !== null && group.days_remaining >= 0 && group.days_remaining <= 90) return "expiring";
  return "supported";
}

function lifecycleTone(group: OsInventoryGroup) {
  if (group.review_required) return "unknown" as const;
  if (riskBucket(group) === "expired") return "critical" as const;
  if (riskBucket(group) === "expiring") return "warning" as const;
  return "success" as const;
}

function uniqueOptions(values: string[]): Array<{ value: string; label: string }> {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)))
    .sort((a, b) => a.localeCompare(b))
    .map((value) => ({ value, label: value }));
}

async function withRequestFingerprint<T>(
  request: Promise<Envelope<T>>,
  requestFingerprint: string,
): Promise<Envelope<T> & { requestFingerprint: string }> {
  return {
    ...await request,
    requestFingerprint,
  };
}

function optionLabel(value: string, label: string): { value: string; label: string } {
  return { value, label };
}

function safeFilenamePart(value: string): string {
  return value.trim().replace(/[^a-z0-9._-]+/gi, "_").replace(/^[._-]+|[._-]+$/g, "") || "software";
}

function isInventoryProviderUnavailable(error: Error | ApiError | null): error is ApiError {
  return (
    error instanceof ApiError &&
    error.code === "provider_unavailable" &&
    error.details?.capability === "inventory"
  );
}

function inventoryUnavailableMessage(error: Error | ApiError): string {
  if (!isInventoryProviderUnavailable(error)) return error.message;
  return "The API has no active inventory snapshot. Run the ARG/Log Analytics inventory ingestion job with `uv run aiops-inventory sync --config config.yaml`, or set `AIOPS_INVENTORY_FIXTURE` for local demo data. Installed Software also requires server-owned Log Analytics workspace mappings for ConfigurationData.";
}

function InventorySetupHint({ error }: { error: Error | ApiError | null }) {
  if (!isInventoryProviderUnavailable(error)) return null;
  return (
    <StatePanel
      title="Inventory data is not loaded"
      message="You do not need the AIOps semantic graph or operations agent. Inventory data is published by the Fabric ingestion pipeline; installed software additionally needs ConfigurationData workspace mappings."
      tone="error"
      action={(
        <div className="setup-hint">
          <code>uv run aiops-inventory sync --config config.yaml</code>
          <span className="muted">Local demo alternative: set AIOPS_INVENTORY_FIXTURE=tests/fixtures/mock_inventory_arg.json before starting the API.</span>
        </div>
      )}
    />
  );
}

function NarrativePanel({ narrative }: { narrative: ReturnType<typeof useApi<Envelope<InventoryNarrative>>> }) {
  const citationSources = narrative.data
    ? Array.from(new Map(
      narrative.data.data.citations.map((citation) => [
        JSON.stringify([citation.source_engine, citation.source_table]),
        citation,
      ]),
    ).values())
    : [];

  return (
    <section aria-label="Inventory risk narrative" className="detail-panel">
      <div className="card-header">
        <h2>Inventory risk narrative</h2>
        {narrative.data && (
          <StatusBadge
            label={`${narrative.data.data.confidence} confidence`}
            tone={narrative.data.data.confidence === "high" ? "success" : "warning"}
            compact
          />
        )}
      </div>
      {narrative.loading && (
        <StatePanel title="Loading risk narrative" message="Summarizing scoped inventory aggregates." tone="loading" />
      )}
      {narrative.error && (
        <StatePanel title="Risk narrative unavailable" message={inventoryUnavailableMessage(narrative.error)} tone="error" />
      )}
      {narrative.data && (
        <div className="narrative-body">
          <div className="narrative-section narrative-summary">
            <h3>Summary</h3>
            {narrative.data.data.narrated_summary ? (
              <p>{narrative.data.data.narrated_summary}</p>
            ) : (
              <p className="muted">Model narration is unavailable; deterministic facts remain authoritative.</p>
            )}
            {/* The deterministic summary is computed from the aggregates, not
                generated, so it is shown alongside the narration rather than
                only as a fallback. It is what the narration is accountable to:
                a reader can compare the two and see if they agree. Claiming
                "deterministic facts remain authoritative" while never showing
                them would leave that claim unverifiable. */}
            {narrative.data.data.fact_summary && (
              <p className="narrative-fact-summary">{narrative.data.data.fact_summary}</p>
            )}
            {narrative.data.data.narrated_by && (
              <p className="muted narrative-attribution">Narrated by {narrative.data.data.narrated_by}</p>
            )}
          </div>
          {narrative.data.data.fact_items.length > 0 && (
            <div className="narrative-section">
              <h3>Deterministic facts</h3>
              <dl className="narrative-fact-grid">
                {narrative.data.data.fact_items.map((fact) => (
                  <div className="narrative-fact" key={fact.label}>
                    <dt>{fact.label}</dt>
                    <dd>{fact.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {citationSources.length > 0 && (
            <div className="narrative-section">
              <h3>Sources</h3>
              <ul className="narrative-citation-list">
                {citationSources.map((citation) => (
                  <li key={JSON.stringify([citation.source_engine, citation.source_table])}>
                    {citation.source_engine} / {citation.source_table}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {narrative.data.warnings && narrative.data.warnings.length > 0 && (
            <div className="narrative-section narrative-warnings">
              <h3>Warnings</h3>
              <ul>
                {narrative.data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default function InventoryPage() {
  const { scope } = useScope();
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [tab, setTab] = useState<InventoryTab>("os");
  const [subscriptionFilter, setSubscriptionFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "azure_vm" | "arc">("all");
  const [lifecycleFilter, setLifecycleFilter] = useState<"all" | "expired" | "expiring" | "supported" | "review">("all");
  const [osNameFilter, setOsNameFilter] = useState("all");
  const [osVersionFilter, setOsVersionFilter] = useState("all");
  const [softwareSearch, setSoftwareSearch] = useState("");
  const [softwareSourceFilter, setSoftwareSourceFilter] = useState<"all" | "azure_vm" | "arc" | "unlinked">("all");
  const [softwareNameFilter, setSoftwareNameFilter] = useState("all");
  const [softwarePublisherFilter, setSoftwarePublisherFilter] = useState("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<OsInventoryMachine[]>([]);
  const [, setDetailGroup] = useState<OsInventoryGroup | null>(null);
  const [softwareDetail, setSoftwareDetail] = useState<SoftwareInventoryMachine[]>([]);
  const [softwareDetailGroup, setSoftwareDetailGroup] = useState<SoftwareInventoryGroup | null>(null);
  const [softwareDetailEnvelope, setSoftwareDetailEnvelope] = useState<Envelope<SoftwareInventoryDetail> | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [review, setReview] = useState<LifecycleReview | null>(null);
  const [reviewGroup, setReviewGroup] = useState<OsInventoryGroup | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [manualDate, setManualDate] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [mappingSubmitting, setMappingSubmitting] = useState<string | null>(null);
  const [azureSearch, setAzureSearch] = useState("");
  const [azureProviderFilter, setAzureProviderFilter] = useState("all");
  const [azureTypeFilter, setAzureTypeFilter] = useState("all");
  const [azureSkuFilter, setAzureSkuFilter] = useState("all");
  const [azureSelectedKey, setAzureSelectedKey] = useState<string | null>(null);
  const [azureDetail, setAzureDetail] = useState<PaasInventoryResource[]>([]);
  const [azureDetailGroup, setAzureDetailGroup] = useState<PaasInventoryGroup | null>(null);
  const [azureDetailError, setAzureDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailPagination, setDetailPagination] = useState<Pagination | null>(null);
  const [detailPage, setDetailPage] = useState(0);
  const [azureDetailLoading, setAzureDetailLoading] = useState(false);
  const [azureDetailPagination, setAzureDetailPagination] = useState<Pagination | null>(null);
  const [azureDetailPage, setAzureDetailPage] = useState(0);
  const [azurePage, setAzurePage] = useState(0);
  const [osPage, setOsPage] = useState(0);
  const [softwarePage, setSoftwarePage] = useState(0);
  const [azurePageSize, setAzurePageSize] = useState(DEFAULT_PAGE_SIZE);
  const [osPageSize, setOsPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [softwarePageSize, setSoftwarePageSize] = useState(DEFAULT_PAGE_SIZE);
  const [allResourcesExporting, setAllResourcesExporting] = useState(false);
  const [allResourcesError, setAllResourcesError] = useState<string | null>(null);
  const effectiveScope = useMemo(
    () => subscriptionFilter === "all"
      ? scope
      : { ...scope, subscription: [subscriptionFilter] },
    [scope, subscriptionFilter],
  );
  const scopeKey = useMemo(() => JSON.stringify(effectiveScope), [effectiveScope]);
  const inventoryRequestFingerprint = JSON.stringify({
    scope: scopeKey,
    refreshKey,
    page: osPage,
    pageSize: osPageSize,
  });
  const softwareRequestFingerprint = JSON.stringify({
    scope: scopeKey,
    refreshKey,
    page: softwarePage,
    pageSize: softwarePageSize,
  });
  const azureRequestFingerprint = JSON.stringify({
    scope: scopeKey,
    refreshKey,
    page: azurePage,
    pageSize: azurePageSize,
  });
  const inventory = useApi(
    () => withRequestFingerprint(
      inventoryApi.os(effectiveScope, osPage * osPageSize, osPageSize),
      inventoryRequestFingerprint,
    ),
    [inventoryRequestFingerprint],
  );
  const softwareInventory = useApi(
    () => withRequestFingerprint(
      inventoryApi.software(effectiveScope, softwarePage * softwarePageSize, softwarePageSize),
      softwareRequestFingerprint,
    ),
    [softwareRequestFingerprint],
  );
  const narrative = useApi(() => inventoryApi.narrative(effectiveScope), [scopeKey, refreshKey]);
  const mappings = useApi(
    () => inventoryApi.mappings(effectiveScope),
    [scopeKey, refreshKey],
  );
  const azureInventory = useApi(
    () => withRequestFingerprint(
      inventoryApi.paas(effectiveScope, azurePage * azurePageSize, azurePageSize),
      azureRequestFingerprint,
    ),
    [azureRequestFingerprint],
  );

  const azureGroups = useMemo(() => azureInventory.data?.data.groups ?? [], [azureInventory.data]);
  const azureProviders = useMemo(
    () => Array.from(new Set(azureGroups.map((group) => providerLabel(group.resource_type)))).sort(),
    [azureGroups],
  );
  const azureTypeOptions = useMemo(
    () => Array.from(new Set(azureGroups.map((group) => group.resource_type)))
      .map((resourceType) => ({
        value: resourceType,
        label: resourceTypeLabel(resourceType),
      }))
      .sort((left, right) => left.label.localeCompare(right.label)),
    [azureGroups],
  );
  const azureSkuOptions = useMemo(
    () => uniqueOptions(azureGroups.map((group) => group.sku || group.tier ? `${group.sku || "—"} / ${group.tier || "—"}` : "No SKU")),
    [azureGroups],
  );
  const filteredAzureGroups = useMemo(
    () => azureGroups.filter((group) => {
      const haystack = `${group.resource_type} ${group.sku} ${group.tier}`.toLowerCase();
      const skuTier = group.sku || group.tier ? `${group.sku || "—"} / ${group.tier || "—"}` : "No SKU";
      return (
        haystack.includes(azureSearch.toLowerCase()) &&
        (azureProviderFilter === "all" || providerLabel(group.resource_type) === azureProviderFilter) &&
        (azureTypeFilter === "all" || group.resource_type === azureTypeFilter) &&
        (azureSkuFilter === "all" || skuTier === azureSkuFilter)
      );
    }),
    [azureGroups, azureProviderFilter, azureSearch, azureSkuFilter, azureTypeFilter],
  );
  const azureResourceTotal = filteredAzureGroups.reduce((total, group) => total + group.resource_count, 0);
  const azureTopGroups = useMemo(
    () => [...filteredAzureGroups].sort((a, b) => b.resource_count - a.resource_count).slice(0, 5),
    [filteredAzureGroups],
  );
  const azureTopBarData = useMemo(
    () =>
      azureTopGroups.map((group) => ({
        id: group.key,
        label: resourceTypeLabel(group.resource_type),
        value: group.resource_count,
      })),
    [azureTopGroups],
  );
  const azureProviderMix = useMemo(() => {
    const palette = ["var(--color-brand)", "#3ea3e0", "var(--color-success)", "var(--color-warning)", "var(--color-text-muted)"];
    const counts = new Map<string, number>();
    for (const group of filteredAzureGroups) {
      const provider = providerLabel(group.resource_type);
      counts.set(provider, (counts.get(provider) ?? 0) + group.resource_count);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([label, value], index) => ({ label, value, color: palette[index % palette.length] }));
  }, [filteredAzureGroups]);

  const groups = useMemo(() => inventory.data?.data.groups ?? [], [inventory.data]);
  const osNameOptions = useMemo(
    () => uniqueOptions(groups.map((group) => group.os_name)),
    [groups],
  );
  const osVersionOptions = useMemo(
    () => uniqueOptions(groups.map((group) => group.os_version)),
    [groups],
  );
  const filteredGroups = useMemo(
    () => groups.filter((group) => {
      const haystack = `${group.os_name} ${group.os_version}`.toLowerCase();
      return (
        haystack.includes(search.toLowerCase()) &&
        (osNameFilter === "all" || group.os_name === osNameFilter) &&
        (osVersionFilter === "all" || group.os_version === osVersionFilter) &&
        (sourceFilter === "all" || group.source_types.includes(sourceFilter)) &&
        (lifecycleFilter === "all" || riskBucket(group) === lifecycleFilter)
      );
    }),
    [groups, lifecycleFilter, osNameFilter, osVersionFilter, search, sourceFilter],
  );
  const totalMachines = filteredGroups.reduce((total, group) => total + group.machine_count, 0);
  const reviewCount = filteredGroups.filter((group) => group.review_required).length;
  const machinesInBucket = (bucket: ReturnType<typeof riskBucket>) =>
    filteredGroups
      .filter((group) => riskBucket(group) === bucket)
      .reduce((total, group) => total + group.machine_count, 0);
  const expiredCount = machinesInBucket("expired");
  const expiringCount = machinesInBucket("expiring");
  const osRiskMix = useMemo(() => {
    const bucketMeta: Record<ReturnType<typeof riskBucket>, { label: string; color: string }> = {
      expired: { label: "Expired", color: "var(--color-critical)" },
      expiring: { label: "Expiring within 90 days", color: "var(--color-warning)" },
      supported: { label: "Supported", color: "var(--color-success)" },
      review: { label: "Needs review", color: "var(--color-text-muted)" },
    };
    return (["expired", "expiring", "supported", "review"] as const).map((bucket) => ({
      label: bucketMeta[bucket].label,
      value: filteredGroups
        .filter((group) => riskBucket(group) === bucket)
        .reduce((total, group) => total + group.machine_count, 0),
      color: bucketMeta[bucket].color,
    }));
  }, [filteredGroups]);
  const osTopBarData = useMemo(
    () =>
      [...filteredGroups]
        .sort((a, b) => b.machine_count - a.machine_count)
        .slice(0, 6)
        .map((group) => ({
          id: group.key,
          label: `${group.os_name} ${group.os_version}`,
          value: group.machine_count,
        })),
    [filteredGroups],
  );
  const sourceStates: Record<string, InventorySourceStatus> = useMemo(
    () => inventory.data?.data.source_status ?? {},
    [inventory.data],
  );
  const partialSource = Object.values(sourceStates).find((source) => source.state !== "ready");
  const softwareGroups = useMemo(() => softwareInventory.data?.data.groups ?? [], [softwareInventory.data]);
  const softwareNameOptions = useMemo(
    () => uniqueOptions(softwareGroups.map((group) => group.software_name)),
    [softwareGroups],
  );
  const softwarePublisherOptions = useMemo(
    () => uniqueOptions(softwareGroups.flatMap((group) => group.publishers)),
    [softwareGroups],
  );
  const filteredSoftwareGroups = useMemo(
    () => softwareGroups.filter((group) => {
      const haystack = `${group.software_name} ${group.software_version}`.toLowerCase();
      return (
        haystack.includes(softwareSearch.toLowerCase()) &&
        (softwareNameFilter === "all" || group.software_name === softwareNameFilter) &&
        (softwarePublisherFilter === "all" || group.publishers.includes(softwarePublisherFilter)) &&
        (softwareSourceFilter === "all" || group.source_types.includes(softwareSourceFilter))
      );
    }),
    [softwareGroups, softwareNameFilter, softwarePublisherFilter, softwareSearch, softwareSourceFilter],
  );
  const softwareTotal = filteredSoftwareGroups.reduce((total, group) => total + group.install_count, 0);
  const unlinkedSoftware = filteredSoftwareGroups.reduce((total, group) => total + group.unlinked_count, 0);
  const softwareTopBarData = useMemo(
    () =>
      [...filteredSoftwareGroups]
        .sort((a, b) => b.install_count - a.install_count)
        .slice(0, 6)
        .map((group) => ({
          id: group.key,
          label: `${group.software_name} ${group.software_version}`,
          value: group.install_count,
        })),
    [filteredSoftwareGroups],
  );
  const softwareSourceMix = useMemo(() => {
    const labels: Record<string, string> = { azure_vm: "Azure VM", arc: "Arc", unlinked: "Unlinked" };
    const colors: Record<string, string> = {
      azure_vm: "var(--color-brand)",
      arc: "#3ea3e0",
      unlinked: "var(--color-text-muted)",
    };
    const counts = new Map<string, number>();
    for (const group of filteredSoftwareGroups) {
      for (const source of group.source_types) {
        counts.set(source, (counts.get(source) ?? 0) + group.install_count);
      }
    }
    return Array.from(counts.entries()).map(([key, value]) => ({
      label: labels[key] ?? key,
      value,
      color: colors[key] ?? "var(--color-text-muted)",
    }));
  }, [filteredSoftwareGroups]);
  const softwareSourceStates: Record<string, InventorySourceStatus> = useMemo(
    () => softwareInventory.data?.data.source_status ?? {},
    [softwareInventory.data],
  );
  const softwarePartialSource = Object.values(softwareSourceStates).find((source) => source.state !== "ready");
  const softwarePartialWithRows = softwarePartialSource?.state === "partial"
    && softwarePartialSource.row_count > 0
    && softwareGroups.length > 0;
  const mappingItems: SoftwareMapping[] = mappings.data?.data.mappings ?? [];
  const activeCopilotState = tab === "software"
    ? softwareInventory
    : tab === "azure"
      ? azureInventory
      : inventory;
  const activeCopilotRequestFingerprint = tab === "software"
    ? softwareRequestFingerprint
    : tab === "azure"
      ? azureRequestFingerprint
      : inventoryRequestFingerprint;
  const activeCopilotScope = activeCopilotState.data?.data.requested_scope;
  const copilotContext = useMemo(() => {
    let records: InventoryCopilotRecord[];
    let totalCount: number;
    let observedAt: string | undefined;
    let selectedIdentity: string | null;
    let sourceStatus: Record<string, InventorySourceStatus>;
    let filters: Record<string, string>;

    if (tab === "software") {
      records = filteredSoftwareGroups.map((group) => ({
        identity: group.key,
        kind: "software_group",
        source: "inventory/software_observations",
        data: {
          software_name: group.software_name,
          software_version: group.software_version,
          install_count: group.install_count,
          linked_count: group.linked_count,
          unlinked_count: group.unlinked_count,
          source_types: group.source_types,
          publishers: group.publishers,
        },
      }));
      totalCount = softwareInventory.data?.pagination?.total ?? softwareGroups.length;
      observedAt = softwareInventory.data?.data.observed_at;
      selectedIdentity = selectedKey;
      sourceStatus = softwareSourceStates;
      filters = {
        tab,
        search: softwareSearch,
        source: softwareSourceFilter,
        software: softwareNameFilter,
        publisher: softwarePublisherFilter,
        subscription: subscriptionFilter,
      };
    } else if (tab === "azure") {
      records = filteredAzureGroups.map((group) => ({
        identity: group.key,
        kind: "azure_group",
        source: "inventory/resource_observations",
        data: {
          resource_type: group.resource_type,
          sku: group.sku,
          tier: group.tier,
          resource_count: group.resource_count,
        },
      }));
      totalCount = azureInventory.data?.pagination?.total ?? azureGroups.length;
      observedAt = azureInventory.data?.data.observed_at;
      selectedIdentity = azureSelectedKey;
      sourceStatus = azureInventory.data?.data.source_status ?? {};
      filters = {
        tab,
        search: azureSearch,
        provider: azureProviderFilter,
        resource_type: azureTypeFilter,
        sku: azureSkuFilter,
        subscription: subscriptionFilter,
      };
    } else {
      records = filteredGroups.map((group) => ({
        identity: group.key,
        kind: "os_group",
        source: "inventory/os_observations",
        data: {
          os_name: group.os_name,
          os_version: group.os_version,
          machine_count: group.machine_count,
          source_types: group.source_types,
          lifecycle_status: group.lifecycle_status,
          support_end: group.support_end,
          days_remaining: group.days_remaining,
          review_required: group.review_required,
        },
      }));
      totalCount = inventory.data?.pagination?.total ?? groups.length;
      observedAt = inventory.data?.data.observed_at;
      selectedIdentity = selectedKey;
      sourceStatus = sourceStates;
      filters = {
        tab,
        search,
        source: sourceFilter,
        lifecycle: lifecycleFilter,
        os_name: osNameFilter,
        os_version: osVersionFilter,
        subscription: subscriptionFilter,
      };
    }

    return buildInventoryCopilotContext({
      scope: activeCopilotScope ?? {},
      tab,
      filters,
      records,
      selectedIdentity,
      totalCount,
      observedAt,
      sourceStatuses: Object.entries(sourceStatus).map(([source, status]) => ({
        source,
        observedAt: status.observed_at || observedAt,
        status: status.state,
      })),
    });
  }, [
    azureGroups.length,
    azureInventory.data,
    azureProviderFilter,
    azureSearch,
    azureSelectedKey,
    azureSkuFilter,
    azureTypeFilter,
    activeCopilotScope,
    filteredAzureGroups,
    filteredGroups,
    filteredSoftwareGroups,
    groups.length,
    inventory.data,
    lifecycleFilter,
    osNameFilter,
    osVersionFilter,
    search,
    selectedKey,
    softwareGroups.length,
    softwareInventory.data,
    softwareNameFilter,
    softwarePublisherFilter,
    softwareSearch,
    softwareSourceFilter,
    sourceFilter,
    sourceStates,
    softwareSourceStates,
    subscriptionFilter,
    tab,
  ]);
  const copilotReady = Boolean(
    activeCopilotScope
    && !activeCopilotState.loading
    && !activeCopilotState.error
    && activeCopilotState.data?.requestFingerprint === activeCopilotRequestFingerprint,
  );

  useEffect(() => {
    if (!copilotReady) setCopilotOpen(false);
  }, [copilotReady]);

  const loadOsGroup = useCallback(async (key: string, page: number) => {
    setDetailError(null);
    setDetailLoading(true);
    try {
      const response = await inventoryApi.osGroup(key, effectiveScope, page * OS_DETAIL_PAGE_SIZE, OS_DETAIL_PAGE_SIZE);
      setDetail(response.data.machines);
      setDetailGroup(response.data.group);
      setDetailPagination(response.pagination ?? null);
    } catch (error) {
      setDetail([]);
      setDetailGroup(null);
      setDetailPagination(null);
      setDetailError(error instanceof Error ? error.message : "Machine detail is unavailable.");
    } finally {
      setDetailLoading(false);
    }
  }, [effectiveScope]);

  function openGroup(group: OsInventoryGroup) {
    setSelectedKey(group.key);
    setSoftwareDetailGroup(null);
    setSoftwareDetailEnvelope(null);
    setDetailPage(0);
    void loadOsGroup(group.key, 0);
  }

  function closeGroup() {
    setSelectedKey(null);
    setDetail([]);
    setDetailGroup(null);
    setDetailPagination(null);
    setDetailError(null);
    setDetailPage(0);
  }

  const loadSoftwareGroup = useCallback(async (key: string, page: number) => {
    setDetailError(null);
    setDetailLoading(true);
    try {
      const response = await inventoryApi.softwareGroup(key, effectiveScope, page * SOFTWARE_DETAIL_PAGE_SIZE, SOFTWARE_DETAIL_PAGE_SIZE);
      setSoftwareDetail(response.data.machines);
      setSoftwareDetailGroup(response.data.group);
      setSoftwareDetailEnvelope(response);
      setDetailPagination(response.pagination ?? null);
    } catch (error) {
      setSoftwareDetail([]);
      setSoftwareDetailGroup(null);
      setDetailPagination(null);
      setDetailError(error instanceof Error ? error.message : "Software detail is unavailable.");
    } finally {
      setDetailLoading(false);
    }
  }, [effectiveScope]);

  function openSoftwareGroup(group: SoftwareInventoryGroup) {
    setSelectedKey(group.key);
    setDetailGroup(null);
    setDetailPage(0);
    void loadSoftwareGroup(group.key, 0);
  }

  function closeSoftwareGroup() {
    setSelectedKey(null);
    setSoftwareDetail([]);
    setSoftwareDetailGroup(null);
    setSoftwareDetailEnvelope(null);
    setDetailPagination(null);
    setDetailError(null);
    setDetailPage(0);
  }

  // Scope changes re-query the server, so any page offset from the previous
  // scope is meaningless and would land the operator on an empty page.
  useEffect(() => {
    setOsPage(0);
    setSoftwarePage(0);
    setAzurePage(0);
    setSelectedKey(null);
    setAzureSelectedKey(null);
    setDetailPage(0);
    setAzureDetailPage(0);
  }, [scopeKey, refreshKey]);

  useEffect(() => {
    setOsPage(0);
    closeGroup();
  }, [lifecycleFilter, osNameFilter, osVersionFilter, search, sourceFilter]);

  useEffect(() => {
    setSoftwarePage(0);
    closeSoftwareGroup();
  }, [softwareNameFilter, softwarePublisherFilter, softwareSearch, softwareSourceFilter]);

  useEffect(() => {
    setAzurePage(0);
    closeAzureGroup();
  }, [azureProviderFilter, azureSearch, azureSkuFilter, azureTypeFilter]);

  // Reload the open OS/software drill-down on page change. Page 0 is already
  // loaded by the open handlers, so skip it to avoid a duplicate request.
  useEffect(() => {
    if (!selectedKey || detailPage === 0) return;
    if (tab === "software") void loadSoftwareGroup(selectedKey, detailPage);
    else if (tab === "os") void loadOsGroup(selectedKey, detailPage);
  }, [selectedKey, detailPage, tab, loadOsGroup, loadSoftwareGroup]);

  function exportSoftwareDetail() {
    if (!softwareDetailGroup || softwareDetail.length === 0) return;
    const rows = softwareDetail.map((machine) => ({
      canonical_name: machine.canonical_name,
      canonical_version: machine.canonical_version,
      canonical_identity: machine.canonical_identity,
      raw_software_name: machine.raw_identity.name,
      raw_software_version: machine.raw_identity.version,
      machine_name: machine.machine_name,
      resource_id: machine.resource_id || machine.source_computer_id,
      source_type: machine.source_type ?? "unlinked",
      subscription_id: machine.subscription_id,
      resource_group: machine.resource_group,
      environment: machine.environment,
      observed_at: machine.observed_at || machine.time_generated,
    }));
    const columns = [
      "canonical_name",
      "canonical_version",
      "canonical_identity",
      "raw_software_name",
      "raw_software_version",
      "machine_name",
      "resource_id",
      "source_type",
      "subscription_id",
      "resource_group",
      "environment",
      "observed_at",
    ] as const;
    downloadCsv(
      serializeCsv(rows, columns),
      `inventory-${safeFilenamePart(softwareDetailGroup.software_name)}-${safeFilenamePart(softwareDetailGroup.software_version)}.csv`,
    );
  }

  const loadAzureGroup = useCallback(async (key: string, page: number) => {
    setAzureDetailError(null);
    setAzureDetailLoading(true);
    try {
      const response = await inventoryApi.paasGroup(key, effectiveScope, page * AZURE_DETAIL_PAGE_SIZE, AZURE_DETAIL_PAGE_SIZE);
      setAzureDetail(response.data.resources);
      setAzureDetailGroup(response.data.group);
      setAzureDetailPagination(response.pagination ?? null);
    } catch (error) {
      setAzureDetail([]);
      setAzureDetailGroup(null);
      setAzureDetailPagination(null);
      setAzureDetailError(error instanceof Error ? error.message : "Resource detail is unavailable.");
    } finally {
      setAzureDetailLoading(false);
    }
  }, [effectiveScope]);

  function openAzureGroup(group: PaasInventoryGroup) {
    setAzureSelectedKey(group.key);
    setAzureDetailPage(0);
    void loadAzureGroup(group.key, 0);
  }

  function closeAzureGroup() {
    setAzureSelectedKey(null);
    setAzureDetail([]);
    setAzureDetailGroup(null);
    setAzureDetailPagination(null);
    setAzureDetailError(null);
    setAzureDetailPage(0);
  }

  // Reload the open drill-down when its page changes. openAzureGroup already
  // loads page 0, so skip that case to avoid a duplicate request.
  useEffect(() => {
    if (!azureSelectedKey || azureDetailPage === 0) return;
    void loadAzureGroup(azureSelectedKey, azureDetailPage);
  }, [azureSelectedKey, azureDetailPage, loadAzureGroup]);

  function exportAzureDetail() {
    if (!azureDetailGroup || azureDetail.length === 0) return;
    const rows = azureDetail.map((resource) => ({
      resource_name: resource.resource_name,
      resource_type: resource.resource_type,
      resource_id: resource.resource_id,
      subscription_id: resource.subscription_id,
      resource_group: resource.resource_group,
      location: resource.location,
      sku: resource.sku,
      tier: resource.tier,
      provisioning_state: resource.provisioning_state,
      observed_at: resource.observed_at,
    }));
    const columns = [
      "resource_name",
      "resource_type",
      "resource_id",
      "subscription_id",
      "resource_group",
      "location",
      "sku",
      "tier",
      "provisioning_state",
      "observed_at",
    ] as const;
    downloadCsv(
      serializeCsv(rows, columns),
      `azure-inventory-${safeFilenamePart(azureDetailGroup.resource_type)}.csv`,
    );
  }

  async function exportAllResources() {
    setAllResourcesExporting(true);
    setAllResourcesError(null);
    try {
      // The API caps `limit` at 500, so page until the envelope stops
      // handing back a next offset rather than assuming one page holds
      // every resource as the estate grows.
      const collected: FlatInventoryResource[] = [];
      let offset = 0;
      for (let guard = 0; guard < 100; guard += 1) {
        const response = await inventoryApi.resources(effectiveScope, offset, 500);
        collected.push(...response.data.resources);
        const next = response.pagination?.next_offset;
        if (next === null || next === undefined) break;
        offset = next;
      }
      if (collected.length === 0) {
        setAllResourcesError("No resources are in scope to export.");
        return;
      }
      const columns = [
        "family",
        "resource_name",
        "resource_type",
        "resource_id",
        "subscription_id",
        "resource_group",
        "environment",
      ] as const;
      const rows = collected.map((resource) => ({
        family: resource.family,
        resource_name: resource.resource_name,
        resource_type: resource.resource_type,
        resource_id: resource.resource_id,
        subscription_id: resource.subscription_id,
        resource_group: resource.resource_group,
        environment: resource.environment,
      }));
      downloadCsv(serializeCsv(rows, columns), "azure-inventory-all-resources.csv");
    } catch (error) {
      setAllResourcesError(
        error instanceof Error ? inventoryUnavailableMessage(error) : "Resource export is unavailable.",
      );
    } finally {
      setAllResourcesExporting(false);
    }
  }

  async function openLifecycleReview(group: OsInventoryGroup) {
    setReviewGroup(group);
    setReview(null);
    setReviewError(null);
    setManualDate("");
    try {
      const response = await inventoryApi.lifecycleReview(group.key, effectiveScope);
      setReview(response.data);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Lifecycle review is unavailable.");
    }
  }

  async function confirmLifecycle(candidateId?: string) {
    if (!review) return;
    setReviewSubmitting(true);
    setReviewError(null);
    try {
      const response = await inventoryApi.confirmLifecycle(
        reviewGroup?.key ?? review.normalized_os_key,
        {
          normalized_os_key: review.normalized_os_key,
          expected_revision: review.catalog_revision,
          ...(candidateId ? { candidate_id: candidateId } : { manual_date: manualDate }),
        },
        effectiveScope,
      );
      setReview(response.data);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Lifecycle confirmation failed.");
    } finally {
      setReviewSubmitting(false);
    }

  }

  async function decideMapping(mapping: SoftwareMapping, decision: "approve" | "reject") {
    setMappingSubmitting(mapping.mapping_id);
    setMappingError(null);
    try {
      const response = decision === "approve"
        ? await inventoryApi.approveMapping(mapping.mapping_id, mapping.revision, effectiveScope)
        : await inventoryApi.rejectMapping(mapping.mapping_id, mapping.revision, effectiveScope);
      void response;
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setMappingError(error instanceof Error ? error.message : "Mapping decision failed.");
    } finally {
      setMappingSubmitting(null);
    }
  }

  return (
    <main className="page-shell inventory-page">
      <PageHeader
        eyebrow="Inventory"
        title="Inventory"
        description="Find authorized operating-system, installed-software, and Azure resource coverage across native Azure VMs, Arc-enabled servers, and platform services."
        actions={<>
          <Link className="button" href={`/inventory/assets?${scopeToSearchParams(effectiveScope)}`}>Explore assets</Link>
          {copilotReady && <CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about inventory" />}
        </>}
        metadata={
          inventory.data && (
            <EvidenceBar
              evidence={inventory.data.evidence}
              sourceStatus={Object.fromEntries(
                Object.entries(inventory.data.data.source_status).map(([source, status]) => [source, status.state]),
              )}
              warnings={inventory.data.warnings}
            />
          )
        }
      />

      <CopilotInsights
        snapshot={copilotContext.snapshot}
        ready={!inventory.loading}
        requestedScope={copilotContext.requestedScope}
        contextLabel="Inventory and data health"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <div role="tablist" aria-label="Inventory views" className="tab-list">
        <button
          id="os-inventory-tab"
          type="button"
          role="tab"
          aria-selected={tab === "os"}
          aria-controls="os-inventory-panel"
          tabIndex={tab === "os" ? 0 : -1}
          onClick={() => setTab("os")}
        >
          OS Inventory
        </button>
        <button
          id="installed-software-tab"
          type="button"
          role="tab"
          aria-selected={tab === "software"}
          aria-controls="installed-software-panel"
          tabIndex={tab === "software" ? 0 : -1}
          onClick={() => setTab("software")}
        >
          Installed Software
        </button>
        <button
          id="azure-inventory-tab"
          type="button"
          role="tab"
          aria-selected={tab === "azure"}
          aria-controls="azure-inventory-panel"
          tabIndex={tab === "azure" ? 0 : -1}
          onClick={() => setTab("azure")}
        >
          Azure Inventory
        </button>
      </div>

      {tab !== "azure" && <NarrativePanel narrative={narrative} />}
      <InventorySetupHint
        error={
          tab === "azure"
            ? azureInventory.error
            : inventory.error ?? softwareInventory.error ?? mappings.error ?? narrative.error
        }
      />

      {tab === "software" ? (
        <section id="installed-software-panel" role="tabpanel" aria-labelledby="installed-software-tab" tabIndex={0}>
          <section aria-label="Installed software summary" className="metric-grid">
            <MetricCard label="Software groups" value={filteredSoftwareGroups.length} detail="Canonical name and version" />
            <MetricCard label="Installations" value={softwareTotal} detail="Authorized current rows" />
            <MetricCard
              label="Unlinked rows"
              value={unlinkedSoftware}
              detail="Exact resource join required"
              tone={unlinkedSoftware > 0 ? "warning" : "success"}
            />
          </section>
          <section aria-label="Installed software dashboard" className="dashboard-charts-row">
            <div className="chart-card">
              <h3 className="chart-card-title">Top software by install count</h3>
              <CountBarChart data={softwareTopBarData} unit="software" />
            </div>
            <div className="chart-card">
              <h3 className="chart-card-title">Discovery source mix</h3>
              <DonutChart
                segments={softwareSourceMix}
                centerValue={softwareTotal}
                centerLabel="installs"
              />
            </div>
          </section>
          <div className="inventory-filters" aria-label="Installed software filters">
            <label>
              Search software
              <input value={softwareSearch} onChange={(event) => setSoftwareSearch(event.target.value)} placeholder="Name or version" />
            </label>
            <label>
              Source
              <select value={softwareSourceFilter} onChange={(event) => setSoftwareSourceFilter(event.target.value as typeof softwareSourceFilter)}>
                <option value="all">All sources</option>
                <option value="azure_vm">Azure VM</option>
                <option value="arc">Arc</option>
                <option value="unlinked">Unlinked</option>
              </select>
            </label>
            <label>
              Subscription
              <select value={subscriptionFilter} onChange={(event) => setSubscriptionFilter(event.target.value)}>
                <option value="all">All authorized subscriptions</option>
                {(scope.subscription ?? []).map((subscription) => (
                  <option key={subscription} value={subscription}>{subscription}</option>
                ))}
              </select>
            </label>
            <div className="inventory-source-badges" aria-label="Installed software source status">
              {Object.values(softwareSourceStates).map((source) => (
                <StatusBadge key={source.source_type} label={`${sourceLabel(source.source_type)} · ${source.state}`} tone={sourceTone(source.state)} compact />
              ))}
            </div>
          </div>
          <TableColumnFilters
            totalCount={softwareGroups.length}
            resultCount={filteredSoftwareGroups.length}
            onReset={() => {
              setSoftwareNameFilter("all");
              setSoftwarePublisherFilter("all");
              setSoftwareSourceFilter("all");
            }}
            filters={[
              {
                id: "software-name",
                label: "Software column",
                value: softwareNameFilter,
                allLabel: "All software",
                options: softwareNameOptions,
                onChange: setSoftwareNameFilter,
              },
              {
                id: "software-publisher",
                label: "Publisher column",
                value: softwarePublisherFilter,
                allLabel: "All publishers",
                options: softwarePublisherOptions,
                onChange: setSoftwarePublisherFilter,
              },
              {
                id: "software-source",
                label: "Sources column",
                value: softwareSourceFilter,
                allLabel: "All sources",
                options: [
                  optionLabel("azure_vm", "Azure VM"),
                  optionLabel("arc", "Arc"),
                  optionLabel("unlinked", "Unlinked"),
                ],
                onChange: (value) => setSoftwareSourceFilter(value as typeof softwareSourceFilter),
              },
            ]}
          />
          {softwareInventory.loading && (
            <StatePanel title="Loading installed software" message="Reading ConfigurationData observations." tone="loading" />
          )}
          {softwareInventory.error && (
            <StatePanel title="Installed software unavailable" message={inventoryUnavailableMessage(softwareInventory.error)} tone="error" />
          )}
          {!softwareInventory.loading && !softwareInventory.error && softwareGroups.length === 0 && (
            <StatePanel title="No installed software observations" message="The authorized scope has no successful ConfigurationData rows." />
          )}
          {!softwareInventory.loading && !softwareInventory.error && softwareGroups.length > 0 && filteredSoftwareGroups.length === 0 && (
            <StatePanel title="No matching installed software" message="Adjust the search, source, or subscription filters." />
          )}
          {softwarePartialSource && (
            <StatePanel
              title={softwarePartialWithRows
                ? "Installed software source is partial"
                : "Installed software source is unavailable"}
              message={softwarePartialWithRows
                ? "Log Analytics source is partial; successful rows are shown, but coverage may be incomplete."
                : `Log Analytics source is ${softwarePartialSource.state}; rows are not presented as a successful empty result.`}
              tone={softwarePartialWithRows ? "partial" : "error"}
            />
          )}
          {filteredSoftwareGroups.length > 0 && (
            <section aria-label="Installed software groups" className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Software</th>
                    <th>Installations</th>
                    <th>Sources</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSoftwareGroups.map((group) => {
                    const expanded = selectedKey === group.key;
                    return (
                    <Fragment key={group.key}>
                    <tr aria-selected={expanded} className={expanded ? "is-expanded" : undefined}>
                      <td>
                        <strong>{group.software_name}</strong>
                        <span className="table-subtitle">{group.software_version}</span>
                      </td>
                      <td>{group.install_count}</td>
                      <td>{group.source_types.map((source) => source === "azure_vm" ? "Azure VM" : source === "arc" ? "Arc" : "Unlinked").join(", ")}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => (expanded ? closeSoftwareGroup() : openSoftwareGroup(group))}
                          aria-expanded={expanded}
                          aria-label={`View machines for ${group.software_name} ${group.software_version}`}
                        >
                          {expanded ? "Hide machines" : "View machines"}
                        </button>
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="detail-row">
                        <td colSpan={4}>
                          {detailError ? (
                            <StatePanel title="Software detail unavailable" message={detailError} tone="error" />
                          ) : detailLoading ? (
                            <StatePanel title="Loading machines" message="Reading ConfigurationData observations." tone="loading" />
                          ) : softwareDetail.length === 0 ? (
                            <StatePanel title="No machines" message="This software group has no rows in the authorized scope." />
                          ) : (
                            <section aria-label="Installed software machine details" className="inline-detail">
                              <div className="inline-detail-header">
                                <span className="muted">{softwareDetail.length} of {group.install_count} installations · exact server lookup</span>
                                <div className="detail-actions">
                                  <button type="button" onClick={exportSoftwareDetail}>Export CSV</button>
                                  <button type="button" onClick={closeSoftwareGroup}>Close</button>
                                </div>
                              </div>
                              {softwareDetailEnvelope && (
                                <EvidenceBar
                                  evidence={softwareDetailEnvelope.evidence}
                                  sourceStatus={Object.fromEntries(
                                    Object.entries(softwareDetailEnvelope.data.source_status).map(([source, status]) => [source, status.state]),
                                  )}
                                  warnings={softwareDetailEnvelope.warnings}
                                />
                              )}
                              <div className="table-scroll">
                                <table className="data-table detail-table">
                                  <thead>
                                    <tr>
                                      <th>Machine</th>
                                      <th>Source / environment</th>
                                      <th>Subscription / resource group</th>
                                      <th>Canonical identity</th>
                                      <th>Raw identity</th>
                                      <th>Observed</th>
                                      <th>Actions</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {softwareDetail.map((machine, index) => (
                                      <tr key={`${machine.resource_id || machine.source_computer_id || machine.machine_name}-${index}`}>
                                        <td><strong>{machine.machine_name}</strong><span className="table-subtitle resource-id-cell" title={machine.resource_id || machine.source_computer_id}>{machine.resource_id || machine.source_computer_id}</span></td>
                                        <td>{machine.source_type ? sourceLabel(machine.source_type) : "Unlinked"}<span className="table-subtitle">{machine.environment}</span></td>
                                        <td>{machine.subscription_id || "Unknown"}<span className="table-subtitle">{machine.resource_group || "Unknown"}</span></td>
                                        <td>{machine.canonical_identity}<span className="table-subtitle">{machine.canonical_name} {machine.canonical_version}</span></td>
                                        <td>{machine.raw_identity.name || "Unknown"}<span className="table-subtitle">{machine.raw_identity.version || "Unknown"} · {machine.join_status === "linked" ? "exact resource join" : "resource join unavailable"}</span></td>
                                        <td>{formatDateTime(machine.observed_at)}</td>
                                        <td>
                                          {machine.resource_id && (
                                            <Link
                                              className="table-primary-link"
                                              href={`/remediation?resource_key=${encodeURIComponent(machine.resource_id)}`}
                                            >
                                              Remediate
                                            </Link>
                                          )}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              <TablePagination
                                pagination={detailPagination}
                                pageRows={softwareDetail.length}
                                page={detailPage}
                                onPageChange={setDetailPage}
                                label="installations"
                              />
                            </section>
                          )}
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                  })}
                </tbody>
              </table>
              <TablePagination
                pagination={softwareInventory.data?.pagination}
                pageRows={softwareGroups.length}
                page={softwarePage}
                onPageChange={setSoftwarePage}
                pageSize={softwarePageSize}
                onPageSizeChange={(size) => {
                  setSoftwarePageSize(size);
                  setSoftwarePage(0);
                }}
                label="software titles"
              />
            </section>
          )}
          {mappingError && <StatePanel title="Mapping decision unavailable" message={mappingError} tone="error" />}
          {mappingItems.length > 0 && (
            <section aria-label="Software normalization review" className="detail-panel">
              <h2>Normalization review</h2>
              <p>Only approved mappings change software group counts.</p>
              <ul>
                {mappingItems.map((mapping) => (
                  <li key={mapping.mapping_id}>
                    <strong>{mapping.raw_name} {mapping.raw_version}</strong>
                    {mapping.publisher && <span className="table-subtitle">Publisher: {mapping.publisher}</span>}
                    <span className="table-subtitle">
                      Suggests: {mapping.canonical_name} {mapping.canonical_version} · {mapping.status} · confidence {mapping.confidence}
                    </span>
                    <span className="table-subtitle">
                      Source: {mapping.method} · observed {mapping.source_timestamp}
                    </span>
                    {mapping.status === "suggested" && (
                      <>
                        <button
                          type="button"
                          disabled={mappingSubmitting === mapping.mapping_id}
                          onClick={() => void decideMapping(mapping, "approve")}
                        >
                          Approve mapping
                        </button>
                        <button
                          type="button"
                          disabled={mappingSubmitting === mapping.mapping_id}
                          onClick={() => void decideMapping(mapping, "reject")}
                        >
                          Reject mapping
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </section>
      ) : tab === "azure" ? (
        <section id="azure-inventory-panel" role="tabpanel" aria-labelledby="azure-inventory-tab" tabIndex={0}>
          <section aria-label="Azure inventory summary" className="metric-grid">
            <MetricCard label="Resource types" value={filteredAzureGroups.length} detail="Grouped by type, SKU, and tier" />
            <MetricCard label="Azure resources" value={azureResourceTotal} detail="Authorized current rows" />
            <MetricCard label="Providers" value={azureProviders.length} detail="Distinct Azure resource providers" />
          </section>

          <div className="inventory-export-bar">
            <div>
              <strong>Full resource export</strong>
              <span className="muted">
                Every in-scope resource across OS and platform families, for topology, policy, and audit joins.
              </span>
            </div>
            <button type="button" onClick={exportAllResources} disabled={allResourcesExporting}>
              {allResourcesExporting ? "Preparing export…" : "Export all resources (CSV)"}
            </button>
          </div>
          {allResourcesError && (
            <StatePanel title="Resource export unavailable" message={allResourcesError} tone="error" />
          )}

          <section aria-label="Azure inventory dashboard" className="dashboard-charts-row">
            <div className="chart-card">
              <h3 className="chart-card-title">Top resource types by count</h3>
              <CountBarChart data={azureTopBarData} unit="resource type" />
            </div>
            <div className="chart-card">
              <h3 className="chart-card-title">Resource provider mix</h3>
              <DonutChart
                segments={azureProviderMix}
                centerValue={azureResourceTotal}
                centerLabel="resources"
              />
            </div>
          </section>

          <div className="inventory-filters" aria-label="Azure inventory filters">
            <label>
              Search resources
              <input
                value={azureSearch}
                onChange={(event) => setAzureSearch(event.target.value)}
                placeholder="Type, SKU, or tier"
              />
            </label>
            <label>
              Provider
              <select value={azureProviderFilter} onChange={(event) => setAzureProviderFilter(event.target.value)}>
                <option value="all">All providers</option>
                {azureProviders.map((provider) => (
                  <option key={provider} value={provider}>{provider}</option>
                ))}
              </select>
            </label>
            <label>
              Subscription
              <select value={subscriptionFilter} onChange={(event) => setSubscriptionFilter(event.target.value)}>
                <option value="all">All authorized subscriptions</option>
                {(scope.subscription ?? []).map((subscription) => (
                  <option key={subscription} value={subscription}>{subscription}</option>
                ))}
              </select>
            </label>
          </div>
          <TableColumnFilters
            totalCount={azureGroups.length}
            resultCount={filteredAzureGroups.length}
            onReset={() => {
              setAzureProviderFilter("all");
              setAzureTypeFilter("all");
              setAzureSkuFilter("all");
            }}
            filters={[
              {
                id: "azure-provider",
                label: "Provider column",
                value: azureProviderFilter,
                allLabel: "All providers",
                options: azureProviders.map((provider) => optionLabel(provider, provider)),
                onChange: setAzureProviderFilter,
              },
              {
                id: "azure-type",
                label: "Resource type column",
                value: azureTypeFilter,
                allLabel: "All resource types",
                options: azureTypeOptions,
                onChange: setAzureTypeFilter,
              },
              {
                id: "azure-sku",
                label: "SKU / tier column",
                value: azureSkuFilter,
                allLabel: "All SKU / tiers",
                options: azureSkuOptions,
                onChange: setAzureSkuFilter,
              },
            ]}
          />

          {azureInventory.loading && (
            <StatePanel title="Loading Azure inventory" message="Reading the active immutable generation." tone="loading" />
          )}
          {azureInventory.error && (
            <StatePanel title="Azure inventory unavailable" message={inventoryUnavailableMessage(azureInventory.error)} tone="error" />
          )}
          {!azureInventory.loading && !azureInventory.error && azureGroups.length === 0 && (
            <StatePanel title="No Azure resources" message="The authorized scope has no published Azure resource inventory rows." />
          )}
          {!azureInventory.loading && !azureInventory.error && azureGroups.length > 0 && filteredAzureGroups.length === 0 && (
            <StatePanel title="No matching Azure resources" message="Adjust the search, provider, or subscription filters." />
          )}

          {filteredAzureGroups.length > 0 && (
            <section aria-label="Azure inventory groups" className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Resource type</th>
                    <th>Provider</th>
                    <th>SKU / tier</th>
                    <th>Resources</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAzureGroups.map((group) => {
                    const expanded = azureSelectedKey === group.key;
                    return (
                    <Fragment key={group.key}>
                    <tr aria-selected={expanded} className={expanded ? "is-expanded" : undefined}>
                      <td>
                        <strong>{resourceTypeLabel(group.resource_type)}</strong>
                        <span className="table-subtitle">{group.resource_type}</span>
                      </td>
                      <td>{providerLabel(group.resource_type)}</td>
                      <td>{group.sku || group.tier ? `${group.sku || "—"} / ${group.tier || "—"}` : "—"}</td>
                      <td>{group.resource_count}</td>
                      <td>
                        <button
                          type="button"
                          onClick={() => (expanded ? closeAzureGroup() : openAzureGroup(group))}
                          aria-expanded={expanded}
                          aria-label={`View resources for ${resourceTypeLabel(group.resource_type)}`}
                        >
                          {expanded ? "Hide resources" : "View resources"}
                        </button>
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="detail-row">
                        <td colSpan={5}>
                          {azureDetailError ? (
                            <StatePanel title="Azure resource detail unavailable" message={azureDetailError} tone="error" />
                          ) : azureDetailLoading ? (
                            <StatePanel title="Loading resources" message="Reading the active immutable generation." tone="loading" />
                          ) : azureDetail.length === 0 ? (
                            <StatePanel title="No resources" message="This resource type has no rows in the authorized scope." />
                          ) : (
                            <section aria-label="Azure resource detail" className="inline-detail">
                              <div className="inline-detail-header">
                                <span className="muted">{azureDetail.length} of {group.resource_count} resources</span>
                                <div className="detail-actions">
                                  <button type="button" onClick={exportAzureDetail}>Export CSV</button>
                                  <button type="button" onClick={closeAzureGroup}>Close</button>
                                </div>
                              </div>
                              <div className="table-scroll">
                                <table className="detail-table">
                                  <thead>
                                    <tr>
                                      <th>Resource</th>
                                      <th>Resource group</th>
                                      <th>Location</th>
                                      <th>SKU / tier</th>
                                      <th>State</th>
                                      <th>Observed</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {azureDetail.map((resource) => (
                                      <tr key={resource.resource_id}>
                                        <td>
                                          <strong>{resource.resource_name}</strong>
                                        </td>
                                        <td>{resource.resource_group || "—"}</td>
                                        <td>{resource.location || "—"}</td>
                                        <td>{resource.sku || resource.tier ? `${resource.sku || "—"} / ${resource.tier || "—"}` : "—"}</td>
                                        <td>
                                          <StatusBadge
                                            label={resource.provisioning_state || "Unknown"}
                                            tone={provisioningTone(resource.provisioning_state)}
                                            compact
                                          />
                                        </td>
                                        <td>{formatDateTime(resource.observed_at)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              <TablePagination
                                pagination={azureDetailPagination}
                                pageRows={azureDetail.length}
                                page={azureDetailPage}
                                onPageChange={setAzureDetailPage}
                                label="resources"
                              />
                            </section>
                          )}
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                  })}
                </tbody>
              </table>
              <TablePagination
                pagination={azureInventory.data?.pagination}
                pageRows={azureGroups.length}
                page={azurePage}
                onPageChange={setAzurePage}
                pageSize={azurePageSize}
                onPageSizeChange={(size) => {
                  setAzurePageSize(size);
                  setAzurePage(0);
                }}
                label="resource types"
              />
            </section>
          )}
        </section>
      ) : (
        <section id="os-inventory-panel" role="tabpanel" aria-labelledby="os-inventory-tab" tabIndex={0}>
          <section aria-label="OS inventory summary" className="metric-grid">
            <MetricCard label="OS groups" value={groups.length} detail="Authorized OS identities" />
            <MetricCard label="Machines" value={totalMachines} detail="After scope filtering" />
            <MetricCard
              label="At risk"
              value={expiredCount + expiringCount}
              detail={`${expiredCount} expired · ${expiringCount} expiring within 90 days`}
              tone={expiredCount > 0 ? "critical" : expiringCount > 0 ? "warning" : "success"}
            />
            <MetricCard
              label="Needs review"
              value={reviewCount}
              detail="Unknown lifecycle mapping"
              tone={reviewCount > 0 ? "warning" : "success"}
            />
          </section>
          <section aria-label="OS inventory dashboard" className="dashboard-charts-row">
            <div className="chart-card">
              <h3 className="chart-card-title">EOL risk distribution</h3>
              <DonutChart
                segments={osRiskMix}
                centerValue={totalMachines}
                centerLabel="machines"
              />
            </div>
            <div className="chart-card">
              <h3 className="chart-card-title">Top OS versions</h3>
              <CountBarChart data={osTopBarData} unit="OS version" />
            </div>
          </section>
          <div className="inventory-filters" aria-label="OS inventory filters">
            <label>
              Search OS
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name or version" />
            </label>
            <label>
              Source
              <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as typeof sourceFilter)}>
                <option value="all">All sources</option>
                <option value="azure_vm">Azure VM</option>
                <option value="arc">Arc</option>
              </select>
            </label>
            <label>
              EOL status
              <select value={lifecycleFilter} onChange={(event) => setLifecycleFilter(event.target.value as typeof lifecycleFilter)}>
                <option value="all">All lifecycle states</option>
                <option value="expired">Expired</option>
                <option value="expiring">Expiring within 90 days</option>
                <option value="supported">Supported</option>
                <option value="review">Needs review</option>
              </select>
            </label>
            <label>
              Subscription
              <select value={subscriptionFilter} onChange={(event) => setSubscriptionFilter(event.target.value)}>
                <option value="all">All authorized subscriptions</option>
                {(scope.subscription ?? []).map((subscription) => (
                  <option key={subscription} value={subscription}>{subscription}</option>
                ))}
              </select>
            </label>
            <div className="inventory-source-badges" aria-label="OS source status">
              {Object.values(sourceStates).map((source) => (
                <StatusBadge key={source.source_type} label={`${sourceLabel(source.source_type)} · ${source.state}`} tone={sourceTone(source.state)} compact />
              ))}
            </div>
          </div>
          <TableColumnFilters
            totalCount={groups.length}
            resultCount={filteredGroups.length}
            onReset={() => {
              setOsNameFilter("all");
              setOsVersionFilter("all");
              setSourceFilter("all");
              setLifecycleFilter("all");
            }}
            filters={[
              {
                id: "os-name",
                label: "OS column",
                value: osNameFilter,
                allLabel: "All operating systems",
                options: osNameOptions,
                onChange: setOsNameFilter,
              },
              {
                id: "os-version",
                label: "Version column",
                value: osVersionFilter,
                allLabel: "All versions",
                options: osVersionOptions,
                onChange: setOsVersionFilter,
              },
              {
                id: "os-source",
                label: "Sources column",
                value: sourceFilter,
                allLabel: "All sources",
                options: [
                  optionLabel("azure_vm", "Azure VM"),
                  optionLabel("arc", "Arc"),
                ],
                onChange: (value) => setSourceFilter(value as typeof sourceFilter),
              },
              {
                id: "os-lifecycle",
                label: "Lifecycle column",
                value: lifecycleFilter,
                allLabel: "All lifecycle states",
                options: [
                  optionLabel("expired", "Expired"),
                  optionLabel("expiring", "Expiring within 90 days"),
                  optionLabel("supported", "Supported"),
                  optionLabel("review", "Needs review"),
                ],
                onChange: (value) => setLifecycleFilter(value as typeof lifecycleFilter),
              },
            ]}
          />

          {inventory.loading && <StatePanel title="Loading OS inventory" message="Reading the active immutable generation." tone="loading" />}
          {inventory.error && (
            <StatePanel title="OS inventory unavailable" message={inventoryUnavailableMessage(inventory.error)} tone="error" />
          )}
          {!inventory.loading && !inventory.error && groups.length === 0 && (
            <StatePanel title="No OS observations" message="The authorized scope has no published OS inventory rows." />
          )}
          {!inventory.loading && !inventory.error && groups.length > 0 && filteredGroups.length === 0 && (
            <StatePanel title="No matching OS observations" message="Adjust the search, source, lifecycle, or subscription filters." />
          )}
          {partialSource && (
            <StatePanel
              title="Inventory source is partial"
              message={`${sourceLabel(partialSource.source_type)} source is ${partialSource.state}; successful rows are shown without treating the source as empty.`}
              tone="error"
            />
          )}

          {filteredGroups.length > 0 && (
            <section aria-label="OS inventory groups" className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>OS</th>
                    <th>Machines</th>
                    <th>Sources</th>
                    <th>Lifecycle</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredGroups.map((group) => {
                    const expanded = selectedKey === group.key;
                    return (
                    <Fragment key={group.key}>
                    <tr aria-selected={expanded} className={expanded ? "is-expanded" : undefined}>
                      <td>
                        <strong>{group.os_name}</strong>
                        <span className="table-subtitle">{group.os_version}</span>
                      </td>
                      <td>{group.machine_count}</td>
                      <td>{group.source_types.map(sourceLabel).join(", ")}</td>
                      <td>
                        <StatusBadge label={lifecycleLabel(group)} tone={lifecycleTone(group)} />
                        {group.support_end && <span className="table-subtitle">ends {group.support_end}</span>}
                      </td>
                      <td>
                        <button
                          type="button"
                          onClick={() => (expanded ? closeGroup() : openGroup(group))}
                          aria-expanded={expanded}
                          aria-label={`View machines for ${group.os_name} ${group.os_version}`}
                        >
                          {expanded ? "Hide machines" : "View machines"}
                        </button>
                        {group.review_required && (
                          <button type="button" onClick={() => openLifecycleReview(group)}>
                            Review EOL date
                          </button>
                        )}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="detail-row">
                        <td colSpan={5}>
                          {detailError ? (
                            <StatePanel title="Machine detail unavailable" message={detailError} tone="error" />
                          ) : detailLoading ? (
                            <StatePanel title="Loading machines" message="Reading the active immutable generation." tone="loading" />
                          ) : detail.length === 0 ? (
                            <StatePanel title="No machines" message="This OS group has no rows in the authorized scope." />
                          ) : (
                            <section aria-label="OS machine details" className="inline-detail">
                              <div className="inline-detail-header">
                                <span className="muted">{detail.length} of {group.machine_count} machines</span>
                                <div className="detail-actions">
                                  <button type="button" onClick={closeGroup}>Close</button>
                                </div>
                              </div>
                              <div className="table-scroll">
                                <table className="data-table detail-table">
                                  <thead>
                                    <tr>
                                      <th>Machine</th>
                                      <th>Source / environment</th>
                                      <th>Subscription / resource group</th>
                                      <th>Lifecycle</th>
                                      <th>Observed / evidence</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {detail.map((machine) => (
                                      <tr key={machine.resource_id}>
                                        <td><strong>{machine.machine_name}</strong><span className="table-subtitle resource-id-cell" title={machine.resource_id}>{machine.resource_id}</span></td>
                                        <td>{sourceLabel(machine.source_type)}<span className="table-subtitle">{machine.environment}</span></td>
                                        <td>{machine.subscription_id}<span className="table-subtitle">{machine.resource_group}</span></td>
                                        <td><StatusBadge label={machine.review_required ? "EOL date needs review" : machine.lifecycle_status} tone={machine.review_required ? "unknown" : lifecycleTone({ ...machine, key: machine.resource_id, machine_count: 1, source_types: [machine.source_type] })} /></td>
                                        <td>{formatDateTime(machine.observed_at)}<span className="table-subtitle">{machine.evidence.map((item) => `${item.source_engine} / ${item.source_table}`).join(" · ") || "Evidence retained by API envelope"}</span></td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              <TablePagination
                                pagination={detailPagination}
                                pageRows={detail.length}
                                page={detailPage}
                                onPageChange={setDetailPage}
                                label="machines"
                              />
                            </section>
                          )}
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                  })}
                </tbody>
              </table>
              <TablePagination
                pagination={inventory.data?.pagination}
                pageRows={groups.length}
                page={osPage}
                onPageChange={setOsPage}
                pageSize={osPageSize}
                onPageSizeChange={(size) => {
                  setOsPageSize(size);
                  setOsPage(0);
                }}
                label="OS groups"
              />
            </section>
          )}

          {reviewGroup && (
            <section aria-label="EOL lifecycle review" className="detail-panel">
              <h2>Review lifecycle: {reviewGroup.os_name} {reviewGroup.os_version}</h2>
              {reviewError && <StatePanel title="Lifecycle review unavailable" message={reviewError} tone="error" />}
              {review && (
                <>
                  <p>
                    {review.status === "catalog_hit" || review.status === "confirmed"
                      ? `Confirmed ${review.classification.support_end ?? "without a support end date"}.`
                      : "No catalog winner was selected. Review every cited candidate before confirming."}
                  </p>
                  {review.candidates.length > 0 && (
                    <ul>
                      {review.candidates.map((candidate) => (
                        <li key={candidate.candidate_id}>
                          <strong>{candidate.date}</strong> · {candidate.source_kind} · confidence {candidate.confidence}
                          <span className="table-subtitle">Claim: {candidate.extracted_claim}</span>
                          <span className="table-subtitle">Retrieved: {candidate.retrieved_at}</span>
                          <a href={candidate.citation} target="_blank" rel="noreferrer">
                            Citation
                          </a>
                          {review.status === "review_required" && (
                            <button
                              type="button"
                              disabled={reviewSubmitting}
                              onClick={() => confirmLifecycle(candidate.candidate_id)}
                            >
                              Confirm this date
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {review.status === "review_required" && (
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        void confirmLifecycle();
                      }}
                    >
                      <label>
                        Or enter a date
                        <input
                          type="date"
                          value={manualDate}
                          onChange={(event) => setManualDate(event.target.value)}
                          required
                        />
                      </label>
                      <button type="submit" disabled={reviewSubmitting || !manualDate}>
                        Confirm manual date
                      </button>
                    </form>
                  )}
                </>
              )}
            </section>
          )}
        </section>
      )}
      <CopilotDrawer
        open={copilotOpen && copilotReady}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Inventory and data health"
        requestedScope={copilotContext.requestedScope}
        snapshot={copilotContext.snapshot}
        starterQuestions={copilotContext.starterQuestions}
      />
    </main>
  );
}
