"use client";

import { useMemo, useRef, useState } from "react";
import { FabricFreshnessBudget } from "@/components/fabric/FabricFreshnessBudget";
import { FabricDatasetContract } from "@/components/fabric/FabricDatasetContract";
import { FabricRecordedEvidence } from "@/components/fabric/FabricRecordedEvidence";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { scopedBookmark, ScopeBookmarkError, type ScopeSelection } from "@/lib/scope";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, relativeTime } from "@/lib/format";
import { fabricMedallionApi } from "@/lib/services";
import type { Envelope, FabricCapabilities, FabricDataset, FabricGoldDeclarations, FabricGovernanceSummary, FabricIngestionRun, FabricManifestEntry, FabricManifestSummary, FabricSourceObservation, FabricLayerCounts, SubscriptionConnection } from "@/lib/types";

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
  gold: "Curated products for downstream consumers. Semantic model and Data Agent readiness are reported separately.",
};

export const EMPTY_FABRIC_COUNTS: Record<FabricLayerKey, FabricLayerCounts> = {
  bronze: { healthy: 0, total: 0 },
  silver: { healthy: 0, total: 0 },
  gold: { healthy: 0, total: 0 },
};

type FabricPanelProps = {
  hidden?: boolean;
  refreshKey: number;
  scope: ScopeSelection;
  subscriptionId?: string;
  asTabPanel?: boolean;
  health?: ReturnType<typeof useFabricMedallionHealth>;
};

/** Loads independent scoped sections once for the panel and read-only page context. */
export function useFabricMedallionHealth(scope: ScopeSelection, refreshKey: number) {
  const scopeKey = JSON.stringify(scope);
  const layerSummary = useApi(() => fabricMedallionApi.layers(scope), [refreshKey, scopeKey]);
  const manifest = useApi(() => fabricMedallionApi.manifest(scope), [refreshKey, scopeKey]);
  const governance = useApi(() => fabricMedallionApi.governance(scope), [refreshKey, scopeKey]);
  const ingestionHistory = useApi(() => fabricMedallionApi.ingestionHistory(scope), [refreshKey, scopeKey]);
  const capabilities = useApi(() => fabricMedallionApi.capabilities(scope), [refreshKey, scopeKey]);
  return { scopeKey, layerSummary, manifest, governance, ingestionHistory, capabilities };
}

/** Applies an embedded subscription selector only when it preserves global constraints. */
export function FabricMedallionPanel(props: FabricPanelProps) {
  let scope: ScopeSelection;
  try {
    const params = new URLSearchParams();
    if (props.subscriptionId) params.set("subscription", props.subscriptionId);
    scope = scopedBookmark(params, props.scope);
  } catch (error) {
    if (!(error instanceof ScopeBookmarkError)) throw error;
    return props.hidden ? null : <StatePanel title="Fabric selection is outside the current scope" message={error.message} tone="error" />;
  }
  const scopeKey = JSON.stringify(scope);
  return props.health?.scopeKey === scopeKey
    ? <FabricMedallionPanelContent key={scopeKey} {...props} scope={scope} health={props.health} />
    : <FabricMedallionPanelLoader key={scopeKey} {...props} scope={scope} />;
}

function FabricMedallionPanelLoader(props: FabricPanelProps) {
  const health = useFabricMedallionHealth(props.scope, props.refreshKey);
  return <FabricMedallionPanelContent {...props} health={health} />;
}

function FabricMedallionPanelContent({
  hidden = false,
  refreshKey,
  scope,
  asTabPanel = true,
  health,
}: FabricPanelProps & { health: ReturnType<typeof useFabricMedallionHealth> }) {
  const subscriptionScope = scope;
  const { layerSummary, manifest, governance, ingestionHistory, capabilities } = health;
  const counts = layerSummary.data?.data.layers;
  const tableNames = useMemo(
    () => tableNamesByLayer(capabilities.data?.data, layerSummary.data?.data.tables),
    [capabilities.data, layerSummary.data],
  );
  const totalTables = counts ? FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].total, 0) : null;
  const healthyTables = counts ? FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].healthy, 0) : null;
  const relationshipCount = governance.data?.data.referential_integrity_blockers;
  const governanceEmptyQualified = isQualifiedEmptyObservation(governance.data?.data.observation);
  const governanceMetricTone = relationshipCount
    ? "critical"
    : governanceEmptyQualified && governance.data?.data.observation?.freshness !== "stale"
      ? "success"
      : "default";

  return (
    <section
      className="fabric-medallion-workspace"
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

      <nav className="section-nav" aria-label="Fabric sections">
        <a href="#bronze-layer">Bronze layer</a>
        <a href="#silver-layer">Silver layer</a>
        <a href="#gold-layer">Gold layer</a>
        <a href="#fabric-manifest">Publication lifecycle</a>
        <a href="#fabric-governance">Governance gaps</a>
        <a href="#fabric-ingestion">Ingestion history</a>
        <a href="#fabric-readiness">Readiness</a>
      </nav>

      <div className="metric-grid">
        <MetricCard label="Bronze tables" size="text" value={formatHealthCount(counts?.bronze)} detail="Dataset health, not row counts. Stale raw data can contain records." tone={fabricMetricTone(counts?.bronze)} />
        <MetricCard label="Silver tables" size="text" value={formatHealthCount(counts?.silver)} detail="Dataset health, not row counts. Freshness and quality determine health." tone={fabricMetricTone(counts?.silver)} />
        <MetricCard label="Gold tables" size="text" value={formatHealthCount(counts?.gold)} detail="Registered dataset health, not physical table inventory or downstream readiness." tone={fabricMetricTone(counts?.gold)} />
        <MetricCard
          label="Governed relationships"
          value={relationshipCount && relationshipCount > 0
            ? relationshipCount
            : governanceEmptyQualified ? 0 : null}
          detail={counts ? `${healthyTables}/${totalTables} datasets healthy; referential integrity blockers` : "Dataset counts unavailable; referential integrity blockers"}
          tone={governanceMetricTone}
        />
      </div>

      <section className="card" aria-label="Fabric section evidence">
        <div className="card-header"><div><h2>Reported evidence freshness</h2><p>A successful request does not prove fresh datasets or downstream readiness.</p></div></div>
        <div className="card-body compliance-list">
          {[
            { label: "Layer health", section: layerSummary },
            { label: "Publication manifest", section: manifest },
            { label: "Governance", section: governance },
            { label: "Ingestion history", section: ingestionHistory },
            { label: "Capabilities", section: capabilities },
          ].map(({ label, section }) => (
            <div key={label} className="compliance-row">
              <strong>{label}</strong>
              <span>{section.error ? "Request failed" : section.loading ? "Loading" : "Response received"} · Freshness: {datasetStatusLabel(fabricEvidenceFreshness(section.data))}</span>
            </div>
          ))}
        </div>
      </section>

      {layerSummary.error && <StatePanel title="Fabric layer counts unavailable" message={layerSummary.error.message} tone="error" />}
      <FabricCapabilityCallouts capabilities={capabilities.data?.data} error={capabilities.error} />

      {FABRIC_LAYER_KEYS.map((layer) => (
        <FabricLayerSection
          key={layer}
          layer={layer}
          tableNames={tableNames[layer]}
          counts={counts?.[layer]}
          goldDeclarations={layer === "gold" ? layerSummary.data?.data.gold_declarations : undefined}
          registrationLoading={!layerSummary.data && !capabilities.data && (layerSummary.loading || capabilities.loading)}
          registrationUnavailable={!layerSummary.data && !capabilities.data}
          scope={subscriptionScope}
          refreshKey={refreshKey}
        />
      ))}

      <FabricManifestPanel manifest={manifest} />
      <FabricGovernancePanel governance={governance} />
      <FabricIngestionPanel ingestionHistory={ingestionHistory} />
      <section id="fabric-readiness" className="card" aria-labelledby="fabric-readiness-heading">
        <div className="card-header">
          <div>
            <h2 id="fabric-readiness-heading">Semantic model and Data Agent readiness</h2>
            <p>Review deployment limits and grounding coverage before relying on these surfaces.</p>
          </div>
        </div>
        <div className="card-body">
          <FabricReadinessPanel capabilities={capabilities} />
        </div>
      </section>
    </section>
  );
}

function FabricLayerSection({
  layer,
  tableNames,
  counts,
  goldDeclarations,
  scope,
  refreshKey,
  registrationLoading,
  registrationUnavailable,
}: {
  layer: FabricLayerKey;
  tableNames: string[];
  counts?: FabricLayerCounts;
  goldDeclarations?: FabricGoldDeclarations;
  scope: ScopeSelection;
  refreshKey: number;
  registrationLoading: boolean;
  registrationUnavailable: boolean;
}) {
  const scopeKey = JSON.stringify(scope);
  const datasets = useApi(() => loadLayerDatasets(tableNames, scope), [refreshKey, tableNames.join("|"), scopeKey]);
  const rows = useMemo(() => datasets.data?.datasets ?? [], [datasets.data]);
  const failures = datasets.data?.failures ?? [];
  const { filteredRows, filters, resetFilters } = useColumnFilters(rows, [
    { id: "status", label: "Status", getValues: (dataset) => dataset.availability || "unknown" },
    { id: "freshness", label: "Freshness", getValues: (dataset) => dataset.freshness || "unknown" },
    { id: "lineage", label: "Lineage", getValues: (dataset) => dataset.lineage_ref || "No lineage reference" },
  ]);
  const paging = useTablePagination(filteredRows);
  const label = FABRIC_LAYER_LABELS[layer];
  const [selectedContract, setSelectedContract] = useState<string | null>(null);
  const contractTrigger = useRef<HTMLButtonElement | null>(null);

  return (
    <>
    <section id={`${layer}-layer`} className="card">
      <div className="card-header">
        <div>
          <h2>{label} layer</h2>
          <p>{FABRIC_LAYER_DESCRIPTIONS[layer]}</p>
        </div>
        <StatusBadge label={formatHealthCount(counts)} tone={statusTone(!counts || counts.total === 0 ? "unknown" : counts.healthy === counts.total ? "healthy" : "degraded")} />
      </div>
      <div className="card-body">
        {goldDeclarations && (
          <details aria-label="Declared Gold product contracts">
            <summary>Explore declared Gold products (source contracts only)</summary>
            <p>
              These definitions come from {goldDeclarations.source} version {goldDeclarations.version},
              not the selected subscription&apos;s table inventory. Physical presence, schema validation,
              readable-generation activation, and downstream readiness are not verified by this list.
            </p>
            <ul>
              {goldDeclarations.tables.map(tableName => <li key={tableName}><code>{tableName}</code></li>)}
            </ul>
            <p>
              Use the existing validated Gold transformation and publication path; table creation
              and publication need separate authorization. The Ontology Agent can propose semantic
              entities and relationships, but does not replace the Gold producer.
            </p>
          </details>
        )}
        {failures.length > 0 && (
          <div role="status" aria-label={`${label} dataset read failures`}>
            <StatePanel
              title={rows.length ? `${label} layer health is partial` : `${label} layer health is unavailable`}
              message={`${rows.length} of ${tableNames.length} registered dataset responses available. Refresh Fabric health to retry failed reads. Layer counts are reported independently.`}
              tone="error"
            />
            <ul>
              {failures.map(failure => <li key={failure.tableName}><strong>{failure.tableName}</strong>: {failure.message}</li>)}
            </ul>
          </div>
        )}
        {datasets.error ? (
          <StatePanel
            title={`${label} layer health is unavailable`}
            message={`${datasets.error.message} Check Fabric capacity and workspace connectivity, then retry.`}
            tone="error"
          />
        ) : datasets.loading || registrationLoading ? (
          <StatePanel title={`Loading ${label.toLowerCase()} layer health`} message="Checking dataset freshness, quality, row counts, and lineage." tone="loading" />
        ) : registrationUnavailable ? (
          <StatePanel title={`${label} dataset registration unavailable`} message="Refresh Fabric health to retry the layer and capability sources. Missing registration evidence is not an empty layer." tone="error" />
        ) : rows.length === 0 && failures.length > 0 ? null : rows.length === 0 ? (
          <StatePanel title={`No ${label} datasets registered`} message="No recorded dataset registrations were returned for this layer in the current scope. Physical table absence is not verified." />
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
                      <dt title={WATERMARK_HELP}>Recorded checkpoint</dt>
                      <dd title={WATERMARK_HELP}>{watermarkCopy(dataset)}</dd>
                    </div>
                    <div>
                      <dt>Lineage</dt>
                      <dd title={dataset.lineage_ref}>{dataset.lineage_ref || "Not traced"}</dd>
                    </div>
                  </dl>
                  <FabricFreshnessBudget budget={dataset.freshness_budget} />
                  <FabricRecordedEvidence tableName={dataset.table_name} evidence={dataset.recorded_evidence} />
                  <button type="button" className="button" aria-expanded={selectedContract === dataset.table_name}
                    aria-controls={`${layer}-dataset-contract`} onClick={event => {
                      contractTrigger.current = event.currentTarget;
                      setSelectedContract(dataset.table_name);
                    }}
                    aria-label={`Inspect contract and diagnostics for ${dataset.table_name}`}>
                    Inspect contract &amp; diagnostics
                  </button>
                </article>
              ))}
            </div>
            <TablePagination total={paging.total} pageRows={paging.pageRows.length} page={paging.page} onPageChange={paging.setPage} pageSize={paging.pageSize} onPageSizeChange={paging.setPageSize} label={`${layer} datasets`} />
          </>
        )}
      </div>
    </section>
    {selectedContract && <FabricDatasetContract key={selectedContract} id={`${layer}-dataset-contract`}
      tableName={selectedContract} scope={scope} refreshKey={refreshKey} onClose={() => {
        setSelectedContract(null);
        contractTrigger.current?.focus();
      }} />}
    </>
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
          <strong>Recorded checkpoint</strong> can be a watermark or a fallback metadata-status time.
          Its presence does not prove upstream catch-up; absence does not prove nonpublication.
        </p>
      </div>
    </section>
  );
}

function FabricManifestPanel({ manifest }: { manifest: { data: Envelope<FabricManifestSummary> | null; error: Error | null; loading: boolean } }) {
  const entries = manifest.data?.data.entries ?? [];
  const observation = manifest.data?.data.observation;
  return (
    <section id="fabric-manifest" className="card" aria-labelledby="fabric-manifest-heading">
      <div className="card-header"><div><h2 id="fabric-manifest-heading">Publication manifest & lifecycle</h2><p>Review active, dormant, retired, and blocked dataset publications.</p></div></div>
      <div className="card-body">
        {manifest.error ? (
          <StatePanel title="Publication manifest is unavailable" message={manifest.error.message} tone="error" />
        ) : manifest.loading ? (
          <StatePanel title="Loading publication manifest" message="Reading active, dormant, retired, and deployment-blocked dispositions." tone="loading" />
        ) : entries.length === 0 && isQualifiedEmptyObservation(observation) ? (
          <StatePanel title="No Fabric medallion datasets observed" message={lastObservationCopy(observation)} />
        ) : entries.length === 0 ? (
          <StatePanel title="Fabric medallion dataset absence unverified" message={unverifiedObservationCopy(observation, "No scoped source observation proves that the manifest is empty.")} />
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
  const observation = summary?.observation;
  return (
    <section id="fabric-governance" className="card" aria-labelledby="fabric-governance-heading">
      <div className="card-header"><div><h2 id="fabric-governance-heading">Governance gaps</h2><p>Review missing ownership, tags, and relationship integrity blockers.</p></div></div>
      <div className="card-body">
        {governance.error ? (
          <StatePanel title="Governance gaps are unavailable" message={governance.error.message} tone="error" />
        ) : governance.loading ? (
          <StatePanel title="Loading governance gaps" message="Checking quality reports for ownership, tag, and relationship blockers." tone="loading" />
        ) : gaps.length === 0 && isQualifiedEmptyObservation(observation) ? (
          <StatePanel title="No governance gaps observed" message={lastObservationCopy(observation)} />
        ) : gaps.length === 0 ? (
          <StatePanel title="Governance absence unverified" message={unverifiedObservationCopy(observation, "No scoped quality report proves a zero-gap result.")} />
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

function isQualifiedEmptyObservation(
  observation: FabricSourceObservation | undefined,
): observation is FabricSourceObservation {
  return observation?.state === "observed_empty"
    && observation.evidence_mode === "recorded_metadata"
    && Boolean(observation.observed_at)
    && observation.freshness !== "unknown";
}

function lastObservationCopy(observation: FabricSourceObservation | undefined): string {
  if (!isQualifiedEmptyObservation(observation)) {
    return "The source absence is not qualified.";
  }
  return `The last recorded source observation was empty ${relativeTime(observation.observed_at)} (freshness: ${datasetStatusLabel(observation.freshness)}). This does not guarantee the current state.`;
}

function unverifiedObservationCopy(
  observation: FabricSourceObservation | undefined,
  message: string,
): string {
  const reason = observation?.reason_code ? ` Reason: ${observation.reason_code}.` : "";
  return `${message}${reason}`;
}

function FabricIngestionPanel({ ingestionHistory }: { ingestionHistory: { data: Envelope<{ runs: FabricIngestionRun[] }> | null; error: Error | null; loading: boolean } }) {
  const runs = ingestionHistory.data?.data.runs ?? [];
  const paging = useTablePagination(runs);
  return (
    <section id="fabric-ingestion" className="card" aria-labelledby="fabric-ingestion-heading">
      <div className="card-header"><div><h2 id="fabric-ingestion-heading">Ingestion history / failed runs</h2><p>Review recent source and publication attempts, failures, and retry guidance.</p></div></div>
      <div className="card-body">
        {ingestionHistory.error ? (
          <StatePanel title="Ingestion history is unavailable" message={ingestionHistory.error.message} tone="error" />
        ) : ingestionHistory.loading ? (
          <StatePanel title="Loading ingestion history" message="Reading source-status and publication-state attempts." tone="loading" />
        ) : runs.length === 0 ? (
          <StatePanel title="No ingestion attempts reported" message="An empty history does not establish successful ingestion or publication for this scope." />
        ) : (
          <>
          <p>{runs.length} returned attempts; {runs.filter(run => run.status === "failed").length} failed. Counts describe this returned history, not all ingestion activity.</p>
          <div className="compliance-list">
            {paging.pageRows.map((run) => (
              <div key={`${run.source}:${run.projection_name}:${run.attempted_at}:${run.status}`} className="compliance-row">
                <div>
                  <strong>{run.projection_name}</strong>
                  <span>{ingestionRunCopy(run)}</span>
                </div>
                {run.status === "failed" && run.retry_eligible ? <span className="table-secondary">Retry via subscription sync</span> : <StatusBadge label={datasetStatusLabel(run.status)} tone={statusTone(run.status)} />}
              </div>
            ))}
          </div>
          <TablePagination pageRows={paging.pageRows.length} page={paging.page}
            onPageChange={paging.setPage} pageSize={paging.pageSize}
            onPageSizeChange={paging.setPageSize} total={paging.total} label="returned ingestion attempts" />
          </>
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
    <>
    <section className="metric-grid">
      <MetricCard label="Semantic model" value={datasetStatusLabel(data.semantic_readiness.status)} detail={semanticReadinessCopy(data.semantic_readiness)} tone={readinessTone(data.semantic_readiness.status)} size="text" />
      <MetricCard label="Data Agent grounding" value={datasetStatusLabel(data.data_agent_readiness.status)} detail={`${data.data_agent_readiness.configured ? "Gold grounding is configured" : "Gold grounding is not configured"}; configuration alone does not prove evaluation or query success.`} tone={readinessTone(data.data_agent_readiness.status)} size="text" />
      <MetricCard label="Recorded capability signals" value="Independent statuses" detail={Object.entries(coverage).map(([key, value]) => `${key}: ${datasetStatusLabel(value)}`).join(" · ")} tone="default" size="text" />
    </section>
    <section className="card" aria-label="Independent Fabric readiness evidence">
      <div className="card-header"><div><h2>Independent readiness stages</h2><p>Dataset publication, native ontology, and semantic validation, publication, and query qualification require separate recorded evidence.</p></div></div>
      <div className="card-body">
        {!data.readiness_evidence ? (
          <StatePanel title="Readiness stage evidence unavailable" message="This response does not supply independent stage receipts. Existing capability status is not stage verification." />
        ) : (
          <dl>
            {[
              { label: "Scoped projection publication", stage: data.readiness_evidence.projection_publication },
              { label: "Native ontology", stage: data.readiness_evidence.native_ontology },
              { label: "Semantic definition validation", stage: data.readiness_evidence.semantic_model.definition_validation },
              { label: "Semantic model publication", stage: data.readiness_evidence.semantic_model.publication },
              { label: "Semantic query qualification", stage: data.readiness_evidence.semantic_model.query_qualification },
            ].map(({ label, stage }) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{datasetStatusLabel(stage.status)} · {stage.evidence_mode === "not_recorded" ? "Not recorded" : "Unsupported receipt mode"} · {stage.reason_code}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </section>
    </>
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

async function loadLayerDatasets(tableNames: string[], scope: ScopeSelection): Promise<{
  datasets: FabricDataset[];
  failures: { tableName: string; message: string }[];
}> {
  const results = await Promise.allSettled(tableNames.map((tableName) => fabricMedallionApi.dataset(tableName, scope)));
  const datasets: FabricDataset[] = [];
  const failures: { tableName: string; message: string }[] = [];
  results.forEach((result, index) => {
    if (result.status === "rejected") {
      failures.push({
        tableName: tableNames[index],
        message: result.reason instanceof Error ? result.reason.message : String(result.reason),
      });
    } else {
      datasets.push(result.value.data);
    }
  });
  return { datasets, failures };
}

export function tableNamesByLayer(
  capabilities?: FabricCapabilities,
  fallbackTables?: Record<FabricLayerKey, string[]>,
): Record<FabricLayerKey, string[]> {
  const layers: Record<FabricLayerKey, string[]> = { bronze: [], silver: [], gold: [] };
  for (const dataset of capabilities?.lineage.datasets ?? []) {
    const layer = FABRIC_LAYER_KEYS.find((key) => dataset.table_name.startsWith(`${key}_`));
    if (layer) layers[layer].push(dataset.table_name);
  }
  for (const layer of FABRIC_LAYER_KEYS) {
    if (layers[layer].length === 0) layers[layer] = fallbackTables?.[layer] ?? [];
  }
  return layers;
}

/** Distinguishes metadata dataset health from record counts and physical inventory. */
export function formatHealthCount(counts?: FabricLayerCounts): string {
  return counts ? `${counts.healthy} healthy / ${counts.total} registered` : "—";
}

export function fabricMetricTone(counts?: FabricLayerCounts): "default" | "critical" | "warning" | "success" {
  if (!counts || counts.total === 0) return "default";
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
  "A reported watermark, or the metadata status time when a watermark is absent. This is not proof that all upstream records were published.";

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
  const observed = dataset.observed_at ? `newest observation ${relativeTime(dataset.observed_at)}` : "observation time unreported";
  return `${datasetRowsCopy(dataset)} · ${observed}`;
}

function freshnessCopy(dataset: FabricDataset): string {
  const freshness = (dataset.freshness || "").toLowerCase();
  if (freshness === "fresh") return "All reported source clocks within target";
  if (freshness === "stale") return "At least one source clock is past target";
  return "Freshness is not established for every source";
}

function qualityCopy(dataset: FabricDataset): string {
  const quality = (dataset.quality || "").toLowerCase();
  if (quality === "complete") return "Recorded quality: complete";
  if (quality === "degraded") return dataset.error || "Quality checks reported issues";
  return "No quality checks recorded yet";
}

function watermarkCopy(dataset: FabricDataset): string {
  if (!dataset.watermark) return "Unreported";
  return formatDateTime(dataset.watermark);
}

function missingResourceCopy(count: number, kind: "ownership" | "tags"): string {
  return `${count} resource${count === 1 ? "" : "s"} missing ${kind}`;
}

function ingestionRunCopy(run: FabricIngestionRun): string {
  if (run.status === "failed") {
    return `Ingestion failed — ${run.attempts} recorded attempt${run.attempts === 1 ? "" : "s"} · last error: ${run.message || "unknown"}`;
  }
  if (run.status === "unavailable") {
    return "Source unavailable — Fabric capacity or workspace could not be reached";
  }
  return `${datasetStatusLabel(run.status)} · attempted ${formatDateTime(run.attempted_at)}`;
}

function semanticReadinessCopy(readiness: { status: string; reason?: string }): string {
  if (readiness.status === "deployment-blocked") {
    return `Semantic model deployment blocked — ${readiness.reason || "cause not reported"}`;
  }
  return readiness.reason || "Semantic model readiness is reported by the Fabric medallion API.";
}

function fabricCoverage(capabilities: FabricCapabilities): Record<string, string> {
  return {
    roles: capabilities.data_access_roles.status || "unknown",
    maintenance: capabilities.maintenance.status || "unknown",
    "lineage reference": capabilities.lineage.native_lineage_url ? "reference reported (not lineage validation)" : "unknown",
  };
}

function readinessTone(status: string): "default" | "critical" | "warning" | "success" {
  if (status === "available" || status === "ready") return "success";
  const tone = statusTone(status);
  if (tone === "critical" || tone === "warning") return tone;
  return "default";
}

/** Summarizes reported evidence only; transport success and timestamps cannot establish freshness. */
export function fabricEvidenceFreshness(envelope?: Pick<Envelope<unknown>, "evidence"> | null): "fresh" | "aging" | "stale" | "unknown" {
  const evidence = envelope?.evidence ?? [];
  if (evidence.some(item => item.freshness === "stale")) return "stale";
  if (!evidence.length || evidence.some(item => !["fresh", "aging"].includes(item.freshness))) return "unknown";
  return evidence.some(item => item.freshness === "aging") ? "aging" : "fresh";
}
