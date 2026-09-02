"use client";

import { useMemo } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import type { ScopeSelection } from "@/lib/scope";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, relativeTime } from "@/lib/format";
import { fabricMedallionApi } from "@/lib/services";
import type { Envelope, FabricCapabilities, FabricDataset, FabricGovernanceSummary, FabricIngestionRun, FabricManifestEntry, FabricLayerCounts, SubscriptionConnection } from "@/lib/types";

export type FabricLayerKey = "bronze" | "silver" | "gold";

export const FABRIC_LAYER_KEYS: FabricLayerKey[] = ["bronze", "silver", "gold"];

export const FABRIC_LAYER_LABELS: Record<FabricLayerKey, string> = {
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
};

export const FABRIC_LAYER_DESCRIPTIONS: Record<FabricLayerKey, string> = {
  bronze: "Raw source-aligned datasets published from subscription ingestion.",
  silver: "Normalized operational datasets with quality and freshness objectives.",
  gold: "Curated products used by semantic models, Data Agent grounding, and operator workflows.",
};

export const EMPTY_FABRIC_COUNTS: Record<FabricLayerKey, FabricLayerCounts> = {
  bronze: { healthy: 0, total: 0 },
  silver: { healthy: 0, total: 0 },
  gold: { healthy: 0, total: 0 },
};

export function FabricMedallionPanel({
  hidden = false,
  refreshKey,
  scope,
  subscriptionId,
  asTabPanel = true,
}: {
  hidden?: boolean;
  refreshKey: number;
  scope: ScopeSelection;
  subscriptionId?: string;
  asTabPanel?: boolean;
}) {
  // Create a subscription-scoped context if subscriptionId is provided
  const subscriptionScope = useMemo(
    () => (subscriptionId ? { ...scope, subscription: [subscriptionId] } : scope),
    [scope, subscriptionId],
  );
  const scopeKey = JSON.stringify(subscriptionScope);
  const layerSummary = useApi(() => fabricMedallionApi.layers(subscriptionScope), [refreshKey, scopeKey]);
  const manifest = useApi(() => fabricMedallionApi.manifest(subscriptionScope), [refreshKey, scopeKey]);
  const governance = useApi(() => fabricMedallionApi.governance(subscriptionScope), [refreshKey, scopeKey]);
  const ingestionHistory = useApi(() => fabricMedallionApi.ingestionHistory(subscriptionScope), [refreshKey, scopeKey]);
  const capabilities = useApi(() => fabricMedallionApi.capabilities(subscriptionScope), [refreshKey, scopeKey]);
  const counts = layerSummary.data?.data.layers ?? EMPTY_FABRIC_COUNTS;
  const tableNames = useMemo(() => tableNamesByLayer(capabilities.data?.data), [capabilities.data]);
  const totalTables = FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].total, 0);
  const healthyTables = FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].healthy, 0);

  return (
    <section
      id={asTabPanel ? "fabric-medallion-panel" : undefined}
      role={asTabPanel ? "tabpanel" : undefined}
      aria-labelledby={asTabPanel ? "fabric-medallion-tab" : undefined}
      aria-label={asTabPanel ? undefined : "Fabric medallion health"}
      tabIndex={asTabPanel ? 0 : undefined}
      hidden={hidden}
    >
      {layerSummary.data && (
        <EvidenceBar
          evidence={layerSummary.data.evidence}
          knowledgeVersion={layerSummary.data.knowledge_version}
          warnings={layerSummary.data.warnings}
        />
      )}

      <div className="metric-grid">
        <MetricCard label="Bronze tables" value={formatHealthCount(counts.bronze)} detail="Raw dataset health and source freshness" tone={fabricMetricTone(counts.bronze)} />
        <MetricCard label="Silver tables" value={formatHealthCount(counts.silver)} detail="Normalized dataset health and quality" tone={fabricMetricTone(counts.silver)} />
        <MetricCard label="Gold tables" value={formatHealthCount(counts.gold)} detail="Curated semantic and Data Agent products" tone={fabricMetricTone(counts.gold)} />
        <MetricCard
          label="Governed relationships"
          value={governance.data ? governance.data.data.referential_integrity_blockers : "—"}
          detail={`${healthyTables}/${totalTables} datasets healthy; referential integrity blockers`}
          tone={governance.data?.data.referential_integrity_blockers ? "critical" : "success"}
        />
      </div>

      <FabricCapabilityCallouts capabilities={capabilities.data?.data} error={capabilities.error} />

      {FABRIC_LAYER_KEYS.map((layer) => (
        <FabricLayerSection
          key={layer}
          layer={layer}
          tableNames={tableNames[layer]}
          counts={counts[layer]}
          scope={subscriptionScope}
          refreshKey={refreshKey}
        />
      ))}

      <FabricManifestPanel manifest={manifest} />
      <FabricGovernancePanel governance={governance} />
      <FabricIngestionPanel ingestionHistory={ingestionHistory} />
      <FabricReadinessPanel capabilities={capabilities} />
    </section>
  );
}

function FabricLayerSection({
  layer,
  tableNames,
  counts,
  scope,
  refreshKey,
}: {
  layer: FabricLayerKey;
  tableNames: string[];
  counts: FabricLayerCounts;
  scope: ScopeSelection;
  refreshKey: number;
}) {
  const scopeKey = JSON.stringify(scope);
  const datasets = useApi(() => loadLayerDatasets(tableNames, scope), [refreshKey, tableNames.join("|"), scopeKey]);
  const rows = useMemo(() => datasets.data ?? [], [datasets.data]);
  const { filteredRows, filters, resetFilters } = useColumnFilters(rows, [
    { id: "status", label: "Status", getValues: (dataset) => dataset.availability || "unknown" },
    { id: "freshness", label: "Freshness", getValues: (dataset) => dataset.freshness || "unknown" },
    { id: "lineage", label: "Lineage", getValues: (dataset) => dataset.lineage_ref || "No lineage reference" },
  ]);
  const paging = useTablePagination(filteredRows);
  const label = FABRIC_LAYER_LABELS[layer];

  return (
    <section id={`${layer}-layer`} className="card">
      <div className="card-header">
        <div>
          <h2>{label} layer</h2>
          <p>{FABRIC_LAYER_DESCRIPTIONS[layer]}</p>
        </div>
        <StatusBadge label={formatHealthCount(counts)} tone={statusTone(counts.total === 0 ? "unknown" : counts.healthy === counts.total ? "healthy" : "degraded")} />
      </div>
      <div className="card-body">
        {datasets.error ? (
          <StatePanel
            title={`${label} layer health is unavailable`}
            message={`${datasets.error.message} Check Fabric capacity and workspace connectivity, then retry.`}
            tone="error"
          />
        ) : datasets.loading ? (
          <StatePanel title={`Loading ${label.toLowerCase()} layer health`} message="Checking dataset freshness, quality, row counts, and lineage." tone="loading" />
        ) : rows.length === 0 ? (
          <StatePanel title={`No ${label} datasets registered`} message="No datasets are registered for this layer in the current scope." />
        ) : (
          <>
            <TableColumnFilters filters={filters} onReset={resetFilters} resultCount={filteredRows.length} totalCount={rows.length} />
            <div className="fabric-dataset-card-grid" aria-label={`${label} dataset health cards`}>
              {paging.pageRows.map((dataset) => (
                <article key={dataset.table_name} className="fabric-dataset-card">
                  <div className="fabric-dataset-card-head">
                    <strong>{dataset.table_name}</strong>
                    <StatusBadge label={datasetStatusLabel(dataset.availability)} tone={statusTone(dataset.availability)} />
                  </div>
                  <p className="fabric-dataset-card-summary">{datasetSummaryCopy(dataset)}</p>
                  <dl>
                    <div>
                      <dt>Freshness</dt>
                      <dd>{freshnessCopy(dataset)}</dd>
                    </div>
                    <div>
                      <dt>Quality</dt>
                      <dd>{qualityCopy(dataset)}</dd>
                    </div>
                    <div>
                      <dt title={WATERMARK_HELP}>Watermark</dt>
                      <dd title={WATERMARK_HELP}>{watermarkCopy(dataset)}</dd>
                    </div>
                    <div>
                      <dt>Lineage</dt>
                      <dd title={dataset.lineage_ref}>{dataset.lineage_ref || "Not traced"}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
            <TablePagination total={paging.total} pageRows={paging.pageRows.length} page={paging.page} onPageChange={paging.setPage} pageSize={paging.pageSize} onPageSizeChange={paging.setPageSize} label={`${layer} datasets`} />
          </>
        )}
      </div>
    </section>
  );
}

export function FabricSubscriptionSummary({
  scope,
  connections,
  counts,
  governanceGapCount,
  activeLifecycleCount,
  inactiveLifecycleCount,
}: {
  scope: ScopeSelection;
  connections: SubscriptionConnection[];
  counts: Record<FabricLayerKey, FabricLayerCounts>;
  governanceGapCount: number;
  activeLifecycleCount: number;
  inactiveLifecycleCount: number;
}) {
  const selectedSubscriptions = scope.subscription ?? [];
  const selectedConnections = selectedSubscriptions.length
    ? connections.filter((connection) => selectedSubscriptions.includes(connection.subscription_id))
    : connections;
  const scopeLabel = selectedSubscriptions.length
    ? selectedSubscriptions.join(", ")
    : "All onboarded subscriptions";
  const totalTables = FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].total, 0);
  const healthyTables = FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].healthy, 0);

  return (
    <section className="card fabric-subscription-summary" aria-label="Subscription-level Fabric medallion summary">
      <div className="card-header">
        <div>
          <h2>Subscription-level Fabric status</h2>
          <p>Bronze, Silver, Gold, lifecycle, and governance signals are filtered by the current subscription scope.</p>
        </div>
        <StatusBadge label={scopeLabel} tone={selectedSubscriptions.length ? "info" : "neutral"} />
      </div>
      <div className="card-body">
        <div className="fabric-summary-grid">
          <div>
            <span>Scope</span>
            <strong>{scopeLabel}</strong>
            <p>{selectedConnections.length} subscription connection{selectedConnections.length === 1 ? "" : "s"} included.</p>
          </div>
          <div>
            <span>Medallion health</span>
            <strong>{healthyTables}/{totalTables} datasets healthy</strong>
            <p>{FABRIC_LAYER_KEYS.map((layer) => `${FABRIC_LAYER_LABELS[layer]} ${formatHealthCount(counts[layer])}`).join(" · ")}</p>
          </div>
          <div>
            <span>Lifecycle</span>
            <strong>{activeLifecycleCount} active contracts</strong>
            <p>{inactiveLifecycleCount} dormant, retired, or deployment-blocked contract{inactiveLifecycleCount === 1 ? "" : "s"}.</p>
          </div>
          <div>
            <span>Governance</span>
            <strong>{governanceGapCount} open gap{governanceGapCount === 1 ? "" : "s"}</strong>
            <p>Ownership, tags, and referential integrity are tracked from Fabric quality reports.</p>
          </div>
        </div>
        <p className="fabric-summary-note">
          <strong>Watermark</strong> is the newest upstream record a dataset&apos;s last sync consumed. &ldquo;Not yet
          published&rdquo; means the dataset has no completed sync yet — it is not a health failure.
        </p>
      </div>
    </section>
  );
}

function FabricManifestPanel({ manifest }: { manifest: { data: Envelope<{ entries: FabricManifestEntry[] }> | null; error: Error | null; loading: boolean } }) {
  const entries = manifest.data?.data.entries ?? [];
  return (
    <section className="card">
      <div className="card-header"><div><h2>Publication manifest & lifecycle</h2><p>Disposition for every published Fabric dataset contract.</p></div></div>
      <div className="card-body">
        {manifest.error ? (
          <StatePanel title="Publication manifest is unavailable" message={manifest.error.message} tone="error" />
        ) : manifest.loading ? (
          <StatePanel title="Loading publication manifest" message="Reading active, dormant, retired, and deployment-blocked dispositions." tone="loading" />
        ) : entries.length === 0 ? (
          <StatePanel title="No Fabric medallion datasets registered" message="Complete an initial subscription sync to publish Bronze, Silver, and Gold datasets. Layer health appears here once the first sync completes." />
        ) : (
          <div className="fabric-lifecycle-groups">
            {groupByDisposition(entries).map(([disposition, group]) => (
              <div key={disposition} className="fabric-lifecycle-group">
                <div className="fabric-lifecycle-group-head">
                  <StatusBadge label={datasetStatusLabel(disposition)} tone={statusTone(disposition)} />
                  <span>{group.length} contract{group.length === 1 ? "" : "s"}</span>
                </div>
                <ul className="fabric-lifecycle-list">
                  {group.map((entry) => (
                    <li key={entry.projection_name}>
                      <strong>{entry.projection_name}</strong>
                      <span>
                        {entry.retired_reason || `Version ${entry.compatibility_version || "unversioned"}`}
                        {entry.updated_at ? ` · updated ${relativeTime(entry.updated_at)}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function FabricGovernancePanel({ governance }: { governance: { data: Envelope<FabricGovernanceSummary> | null; error: Error | null; loading: boolean } }) {
  const summary = governance.data?.data;
  const gaps = summary?.gaps ?? [];
  return (
    <section className="card">
      <div className="card-header"><div><h2>Governance gaps</h2><p>Ownership, tag coverage, and referential-integrity blockers.</p></div></div>
      <div className="card-body">
        {governance.error ? (
          <StatePanel title="Governance gaps are unavailable" message={governance.error.message} tone="error" />
        ) : governance.loading ? (
          <StatePanel title="Loading governance gaps" message="Checking quality reports for ownership, tag, and relationship blockers." tone="loading" />
        ) : gaps.length === 0 ? (
          <StatePanel title="No governance gaps for this scope" message="Ownership, tags, and referential integrity have no open blockers in the current Fabric medallion snapshot." />
        ) : (
          <div className="compliance-list">
            {gaps.map((gap) => (
              <div key={gap.table_name} className="compliance-row">
                <div><strong>{gap.table_name}</strong><span>{missingResourceCopy(gap.ownership_gap_count, "ownership")} · {missingResourceCopy(gap.tag_gap_count, "tags")}</span></div>
                <StatusBadge label={`${gap.referential_integrity_blockers} referential blockers`} tone={gap.referential_integrity_blockers ? "critical" : "success"} />
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function FabricIngestionPanel({ ingestionHistory }: { ingestionHistory: { data: Envelope<{ runs: FabricIngestionRun[] }> | null; error: Error | null; loading: boolean } }) {
  const runs = ingestionHistory.data?.data.runs ?? [];
  return (
    <section className="card">
      <div className="card-header"><div><h2>Ingestion history / failed runs</h2><p>Recent source and publication attempts with retry guidance.</p></div></div>
      <div className="card-body">
        {ingestionHistory.error ? (
          <StatePanel title="Ingestion history is unavailable" message={ingestionHistory.error.message} tone="error" />
        ) : ingestionHistory.loading ? (
          <StatePanel title="Loading ingestion history" message="Reading source-status and publication-state attempts." tone="loading" />
        ) : runs.length === 0 ? (
          <StatePanel title="All ingestion runs succeeded in the current window" message="No failed or unavailable Fabric ingestion runs are reported for the current scope." />
        ) : (
          <div className="compliance-list">
            {runs.map((run) => (
              <div key={`${run.source}:${run.projection_name}:${run.attempted_at}:${run.status}`} className="compliance-row">
                <div>
                  <strong>{run.projection_name}</strong>
                  <span>{ingestionRunCopy(run)}</span>
                </div>
                {run.status === "failed" && run.retry_eligible ? <span className="table-secondary">Retry via subscription sync</span> : <StatusBadge label={datasetStatusLabel(run.status)} tone={statusTone(run.status)} />}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function FabricReadinessPanel({ capabilities }: { capabilities: { data: Envelope<FabricCapabilities> | null; error: Error | null; loading: boolean } }) {
  const data = capabilities.data?.data;
  if (capabilities.error) {
    return <StatePanel title="Fabric medallion health is unavailable" message={`${capabilities.error.message} Check Fabric capacity and workspace connectivity, then retry.`} tone="error" />;
  }
  if (capabilities.loading || !data) {
    return <StatePanel title="Loading semantic and Data Agent readiness" message="Checking capacity, roles, maintenance, lineage, and semantic readiness." tone="loading" />;
  }
  const coverage = fabricCoverage(data);
  return (
    <section className="metric-grid">
      <MetricCard label="Semantic model" value={datasetStatusLabel(data.semantic_readiness.status)} detail={semanticReadinessCopy(data.semantic_readiness)} tone={statusTone(data.semantic_readiness.status) === "critical" ? "critical" : statusTone(data.semantic_readiness.status) === "warning" ? "warning" : "success"} size="text" />
      <MetricCard label="Data Agent grounding" value={datasetStatusLabel(data.data_agent_readiness.status)} detail={data.data_agent_readiness.configured ? "Gold grounding evaluation is configured" : "Gold grounding evaluation is not configured"} tone={data.data_agent_readiness.status === "available" ? "success" : "warning"} size="text" />
      <MetricCard label="Fabric preview coverage" value={Object.values(coverage).filter((value) => value === "available").length + "/" + Object.keys(coverage).length} detail={Object.entries(coverage).map(([key, value]) => `${key}: ${value}`).join(" · ")} tone={Object.values(coverage).every((value) => value === "available") ? "success" : "warning"} size="text" />
    </section>
  );
}

function FabricCapabilityCallouts({ capabilities, error }: { capabilities?: FabricCapabilities; error: Error | null }) {
  if (error || !capabilities) return null;
  const capacityState = String(capabilities.capacity.status || capabilities.capacity.state || "unknown").toLowerCase();
  const capacityName = String(capabilities.capacity.capacity_name || capabilities.capacity.name || "configured capacity");
  const paused = capacityState.includes("paused");
  const throttled = capacityState.includes("throttled");
  if (!paused && !throttled) return null;
  return (
    <div className={`callout ${paused ? "callout-warning" : "callout-critical"}`}>
      <strong>{paused ? `Fabric capacity ${capacityName} is paused.` : `Fabric capacity ${capacityName} is throttled.`}</strong>
      <span>{paused ? "Ingestion and publication are on hold until it resumes." : "Ingestion and publication may be delayed until capacity pressure clears."}</span>
    </div>
  );
}

async function loadLayerDatasets(tableNames: string[], scope: ScopeSelection): Promise<FabricDataset[]> {
  if (tableNames.length === 0) return [];
  const results = await Promise.allSettled(tableNames.map((tableName) => fabricMedallionApi.dataset(tableName, scope)));
  const datasets: FabricDataset[] = [];
  for (const result of results) {
    if (result.status === "rejected") {
      throw result.reason instanceof Error ? result.reason : new Error(String(result.reason));
    }
    datasets.push(result.value.data);
  }
  return datasets;
}

export function tableNamesByLayer(capabilities?: FabricCapabilities): Record<FabricLayerKey, string[]> {
  const layers: Record<FabricLayerKey, string[]> = { bronze: [], silver: [], gold: [] };
  for (const dataset of capabilities?.lineage.datasets ?? []) {
    const layer = FABRIC_LAYER_KEYS.find((key) => dataset.table_name.startsWith(`${key}_`));
    if (layer) layers[layer].push(dataset.table_name);
  }
  return layers;
}

export function formatHealthCount(counts: FabricLayerCounts): string {
  return `${counts.healthy}/${counts.total}`;
}

export function fabricMetricTone(counts: FabricLayerCounts): "default" | "critical" | "warning" | "success" {
  if (counts.total === 0) return "default";
  if (counts.healthy === counts.total) return "success";
  if (counts.healthy === 0) return "critical";
  return "warning";
}

export function datasetStatusLabel(value?: string | null): string {
  const normalized = value?.toLowerCase() ?? "";
  if (normalized === "healthy-empty") return "Healthy · Empty";
  if (normalized === "deployment-blocked") return "Deployment blocked";
  if (normalized === "unavailable") return "Unavailable";
  if (normalized === "failed") return "Failed";
  if (normalized === "dormant") return "Dormant";
  if (normalized === "retired") return "Retired";
  if (normalized === "available") return "Available";
  if (!normalized) return "Unknown";
  return normalized.split(/[-_ ]+/).filter(Boolean).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

function datasetRowsCopy(dataset: FabricDataset): string {
  if (dataset.availability === "healthy-empty") return "0 rows (expected)";
  return `${dataset.row_count} row${dataset.row_count === 1 ? "" : "s"}`;
}

const WATERMARK_HELP =
  "The newest upstream record the last sync consumed. Everything up to this point is published; anything newer arrives on the next sync.";

// Deployment-blocked and retired contracts lead, so lifecycle problems are
// visible without scrolling past the healthy majority.
const DISPOSITION_ORDER = ["deployment-blocked", "retired", "dormant", "active"];

function groupByDisposition(entries: FabricManifestEntry[]): [string, FabricManifestEntry[]][] {
  const groups = new Map<string, FabricManifestEntry[]>();
  for (const entry of entries) {
    const key = entry.disposition || "unknown";
    const existing = groups.get(key);
    if (existing) existing.push(entry);
    else groups.set(key, [entry]);
  }
  return Array.from(groups.entries()).sort(([a], [b]) => {
    const rankA = DISPOSITION_ORDER.indexOf(a);
    const rankB = DISPOSITION_ORDER.indexOf(b);
    return (rankA === -1 ? DISPOSITION_ORDER.length : rankA) - (rankB === -1 ? DISPOSITION_ORDER.length : rankB);
  });
}

function datasetSummaryCopy(dataset: FabricDataset): string {
  const observed = dataset.observed_at ? `last synced ${relativeTime(dataset.observed_at)}` : "never synced";
  return `${datasetRowsCopy(dataset)} · ${observed}`;
}

function freshnessCopy(dataset: FabricDataset): string {
  const freshness = (dataset.freshness || "").toLowerCase();
  if (freshness === "fresh") return "Within its freshness target";
  if (freshness === "stale") return `Past its freshness target${dataset.observed_at ? ` — last synced ${relativeTime(dataset.observed_at)}` : ""}`;
  return "No freshness target evaluated yet";
}

function qualityCopy(dataset: FabricDataset): string {
  const quality = (dataset.quality || "").toLowerCase();
  if (quality === "complete") return "All quality checks passed";
  if (quality === "degraded") return dataset.error || "Quality checks reported issues";
  return "No quality checks recorded yet";
}

/** Renders the upstream checkpoint in operator language instead of a bare
 *  timestamp, so an unpublished dataset never looks like a failure. */
function watermarkCopy(dataset: FabricDataset): string {
  if (!dataset.watermark) return "Not yet published";
  return `Caught up to ${formatDateTime(dataset.watermark)}`;
}

function missingResourceCopy(count: number, kind: "ownership" | "tags"): string {
  return `${count} resource${count === 1 ? "" : "s"} missing ${kind}`;
}

function ingestionRunCopy(run: FabricIngestionRun): string {
  if (run.status === "failed") {
    return `Ingestion failed — ${run.attempts} of ${run.attempts} attempts exhausted · last error: ${run.message || "unknown"}`;
  }
  if (run.status === "unavailable") {
    return "Source unavailable — Fabric capacity or workspace could not be reached";
  }
  return `${datasetStatusLabel(run.status)} · attempted ${formatDateTime(run.attempted_at)}`;
}

function semanticReadinessCopy(readiness: { status: string; reason?: string }): string {
  if (readiness.status === "deployment-blocked") {
    return `Semantic model definition validated, not yet deployed — ${readiness.reason || "deployment status unavailable"}`;
  }
  return readiness.reason || "Semantic model readiness is reported by the Fabric medallion API.";
}

function fabricCoverage(capabilities: FabricCapabilities): Record<string, "available" | "unknown"> {
  return {
    roles: capabilities.data_access_roles.status === "available" ? "available" : "unknown",
    maintenance: capabilities.maintenance.status && capabilities.maintenance.status !== "unknown" ? "available" : "unknown",
    lineage: capabilities.lineage.native_lineage_url ? "available" : "unknown",
  };
}
