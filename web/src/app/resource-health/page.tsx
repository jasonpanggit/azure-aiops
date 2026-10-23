"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { ResourceHealthHistory } from "@/components/ResourceHealthHistory";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { MetricCard } from "@/components/ui/MetricCard";
import { MetricSparkline } from "@/components/ui/MetricSparkline";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { UtilizationBarChart } from "@/components/ui/UtilizationBarChart";
import { buildResourceHealthCopilotContext, RESOURCE_HEALTH_INSIGHT_QUESTION } from "@/lib/copilot/page-adapters";
import type { ScopeSelection } from "@/lib/scope";
import { useScope } from "@/lib/scope-context";
import { inventoryApi, resourceHealthApi } from "@/lib/services";
import type {
  EvidenceItem,
  FlatInventoryResource,
  ResourceHealthSnapshot,
  ResourceUtilization,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const MAX_ACTIVE_HEALTH_REQUESTS = 6;
const SUPPORTED_RESOURCE_TYPES = new Set([
  "microsoft.compute/virtualmachines",
  "microsoft.app/containerapps",
]);

interface CardHealth {
  loading: boolean;
  data: ResourceUtilization | null;
  snapshot: ResourceHealthSnapshot | null;
  evidence: EvidenceItem[];
  error: string | null;
}

interface HealthJob {
  key: string;
  resourceId: string;
  scope: ScopeSelection;
  generation: number;
  forceRefresh: boolean;
}

function formatBytes(value: number | null): string {
  if (value == null) return "—";
  if (value >= 1_073_741_824) return `${(value / 1_073_741_824).toFixed(1)} GB`;
  if (value >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value.toFixed(0)} B`;
}

function formatPercent(value: number | null): string {
  return value == null ? "—" : `${value.toFixed(1)}%`;
}

function resourceTypeLabel(resourceType: string): string {
  const normalized = resourceType.trim().toLowerCase();
  if (normalized === "microsoft.app/containerapps") return "Container App";
  if (normalized === "microsoft.compute/virtualmachines") return "Virtual Machine";
  return resourceType.split("/").pop()?.trim() || "Resource";
}

function resourceKey(resourceId: string): string {
  return resourceId.toLocaleLowerCase();
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Could not load live health.";
}

function ResourceCard({
  resource,
  health,
  onRetry,
  onReviewHistory,
}: {
  resource: FlatInventoryResource;
  health: CardHealth | undefined;
  onRetry: () => void;
  onReviewHistory: (trigger: HTMLButtonElement) => void;
}) {
  const detail = health?.data;
  const isContainerApp =
    resource.resource_type.toLowerCase() === "microsoft.app/containerapps";

  return (
    <article className="card resource-health-card health-resource-card" aria-label={resource.resource_name}>
      <div className="health-resource-header">
        <div className="health-resource-title">
          <h3>{resource.resource_name}</h3>
          <div className="cell-subtext">{resource.resource_group}</div>
        </div>
        <div className="health-resource-badges">
          <StatusBadge
            label={resourceTypeLabel(resource.resource_type)}
            tone="info"
            compact
          />
          {detail ? (
            <StatusBadge
              label={detail.status}
              tone={statusTone(detail.status)}
              compact
            />
          ) : null}
        </div>
      </div>

      {health?.loading ? (
        <div
          className="cell-subtext"
          role="status"
          aria-label={`Loading health for ${resource.resource_name}`}
        >
          Fetching live utilization…
        </div>
      ) : null}

      {health?.error ? (
        <div
          className="state-panel state-error"
          role="alert"
          aria-label={`Health error for ${resource.resource_name}`}
        >
          <p>{health.error}</p>
          <button
            type="button"
            className="button button-secondary"
            aria-label={`Retry health for ${resource.resource_name}`}
            onClick={onRetry}
          >
            Retry
          </button>
        </div>
      ) : null}

      {detail ? (
        <>
          <div className="health-resource-cpu">
            <MetricSparkline data={detail.cpu_series ?? []} max={100} />
            <div>
              <div style={{ fontSize: "1.25rem", fontWeight: 700 }}>
                {formatPercent(detail.cpu_percent)}
              </div>
              <div className="cell-subtext">CPU</div>
            </div>
          </div>

          <div className="health-resource-metrics">
            <span className="cell-subtext">
              Memory: {formatPercent(detail.memory_percent)}
            </span>
            {!isContainerApp ? (
              <span className="cell-subtext">
                Disk free: {formatPercent(detail.disk_free_percent)}
              </span>
            ) : null}
            <span className="cell-subtext">
              Net in: {formatBytes(detail.network_in_bytes)}
            </span>
            <span className="cell-subtext">
              Net out: {formatBytes(detail.network_out_bytes)}
            </span>
            {!isContainerApp ? (
              <>
                <span className="cell-subtext">
                  Disk read: {formatBytes(detail.disk_read_bytes)}
                </span>
                <span className="cell-subtext">
                  Disk write: {formatBytes(detail.disk_write_bytes)}
                </span>
              </>
            ) : null}
          </div>

          <div className="cell-subtext resource-health-error">
            {detail.error ? detail.error : `Observed ${detail.observed_at}`}
          </div>
          {(detail.unavailable_metrics?.length ?? 0) > 0 ? (
            <details>
              <summary>Missing metric diagnostics</summary>
              <p>Unavailable: {detail.unavailable_metrics?.join(", ")}. A missing metric is not a healthy measurement.</p>
              <p>{isContainerApp
                ? "Check Azure Monitor platform metric availability and the connection's monitoring permissions."
                : "Check guest metric collection, workspace association, agent/collection-rule configuration, and monitoring permissions. These are checks to perform, not confirmed causes."}</p>
              <Link href="/connections">Review connection health</Link>
            </details>
          ) : null}
        </>
      ) : null}
      <button type="button" className="button button-secondary"
        aria-label={`Review retained health for ${resource.resource_name}`} onClick={event => onReviewHistory(event.currentTarget)}>
        Review retained health
      </button>
    </article>
  );
}

/**
 * Inventory-first compute utilization with independently hydrated health cards.
 *
 * One page-lifetime scheduler owns all live-card initial, retry, refresh, and scope-change
 * requests. Aborted requests continue occupying their slots until their
 * promises settle, keeping the active card request count at six or fewer.
 */
export default function ResourceHealthPage() {
  const { scope } = useScope();
  const [historyResourceId, setHistoryResourceId] = useState<string | null>(null);
  const historyTrigger = useRef<HTMLButtonElement | null>(null);
  const resourceSearchInput = useRef<HTMLInputElement | null>(null);
  const [resources, setResources] = useState<FlatInventoryResource[]>([]);
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [healthById, setHealthById] = useState<Record<string, CardHealth>>({});
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [healthFilter, setHealthFilter] = useState("all");
  const [resourceSearch, setResourceSearch] = useState("");

  function healthState(resource: FlatInventoryResource): string {
    const health = healthById[resourceKey(resource.resource_id)];
    if (!health || health.loading) return "loading";
    if (health.error) return "failed";
    return health.data?.status ?? "unknown";
  }
  const visibleResources = resources.filter(resource =>
    (healthFilter === "all" || healthState(resource) === healthFilter)
    && `${resource.resource_name} ${resource.resource_id} ${resource.resource_group}`.toLowerCase().includes(resourceSearch.trim().toLowerCase()),
  );
  const coverage = resources.reduce<Record<string, number>>((counts, resource) => {
    const state = healthState(resource);
    counts[state] = (counts[state] ?? 0) + 1;
    return counts;
  }, {});

  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const queueRef = useRef<HealthJob[]>([]);
  const activeCountRef = useRef(0);
  const requestSequenceRef = useRef(0);
  const activeControllersRef = useRef(new Map<number, AbortController>());

  const pump = useCallback(() => {
    if (!mountedRef.current) return;
    while (
      activeCountRef.current < MAX_ACTIVE_HEALTH_REQUESTS &&
      queueRef.current.length > 0
    ) {
      const job = queueRef.current.shift();
      if (!job || job.generation !== generationRef.current) continue;

      const controller = new AbortController();
      const requestId = requestSequenceRef.current + 1;
      requestSequenceRef.current = requestId;
      activeControllersRef.current.set(requestId, controller);
      activeCountRef.current += 1;

      let request: ReturnType<typeof resourceHealthApi.resource>;
      try {
        request = resourceHealthApi.resource(
          job.resourceId,
          job.scope,
          job.forceRefresh,
          { signal: controller.signal },
        );
      } catch (error) {
        request = Promise.reject(error);
      }

      void request
        .then((response) => {
          if (
            !mountedRef.current ||
            controller.signal.aborted ||
            job.generation !== generationRef.current
          ) {
            return;
          }
          const detail = response.data.resources[0];
          if (!detail) {
            throw new Error("No live health data was returned for this resource.");
          }
          setHealthById((current) => ({
            ...current,
            [job.key]: {
              loading: false,
              data: detail,
              snapshot: response.data,
              evidence: response.evidence,
              error: detail.error || null,
            },
          }));
        })
        .catch((error: unknown) => {
          if (
            !mountedRef.current ||
            controller.signal.aborted ||
            job.generation !== generationRef.current
          ) {
            return;
          }
          setHealthById((current) => ({
            ...current,
            [job.key]: {
              loading: false,
              data: null,
              snapshot: null,
              evidence: [],
              error: errorMessage(error),
            },
          }));
        })
        .finally(() => {
          activeControllersRef.current.delete(requestId);
          activeCountRef.current -= 1;
          pump();
        });
    }
  }, []);

  const startGeneration = useCallback(
    (
      nextResources: FlatInventoryResource[],
      requestScope: ScopeSelection,
      forceRefresh: boolean,
    ) => {
      const generation = generationRef.current + 1;
      generationRef.current = generation;
      queueRef.current = [];
      activeControllersRef.current.forEach((controller) => controller.abort());

      const nextHealth: Record<string, CardHealth> = {};
      const jobs: HealthJob[] = [];
      for (const resource of nextResources) {
        const key = resourceKey(resource.resource_id);
        nextHealth[key] = {
          loading: true,
          data: null,
          snapshot: null,
          evidence: [],
          error: null,
        };
        jobs.push({
          key,
          resourceId: resource.resource_id,
          scope: requestScope,
          generation,
          forceRefresh,
        });
      }
      setHealthById(nextHealth);
      queueRef.current = jobs;
      pump();
    },
    [pump],
  );

  useEffect(() => {
    mountedRef.current = true;
    const activeControllers = activeControllersRef.current;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      queueRef.current = [];
      activeControllers.forEach((controller) => controller.abort());
    };
  }, []);

  useEffect(() => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    queueRef.current = [];
    activeControllersRef.current.forEach((controller) => controller.abort());
    setResources([]);
    setHealthById({});
    setInventoryError(null);
    setInventoryLoading(true);

    void inventoryApi
      .resources(scope, 0, 500)
      .then((response) => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        const unique = new Map<string, FlatInventoryResource>();
        for (const resource of response.data.resources) {
          if (
            !SUPPORTED_RESOURCE_TYPES.has(
              resource.resource_type.toLocaleLowerCase(),
            )
          ) {
            continue;
          }
          const key = resourceKey(resource.resource_id);
          if (!unique.has(key)) unique.set(key, resource);
        }
        const nextResources = Array.from(unique.values());
        setResources(nextResources);
        setInventoryLoading(false);

        const nextHealth: Record<string, CardHealth> = {};
        for (const resource of nextResources) {
          const key = resourceKey(resource.resource_id);
          nextHealth[key] = {
            loading: true,
            data: null,
            snapshot: null,
            evidence: [],
            error: null,
          };
          queueRef.current.push({
            key,
            resourceId: resource.resource_id,
            scope,
            generation,
            forceRefresh: false,
          });
        }
        setHealthById(nextHealth);
        pump();
      })
      .catch((error: unknown) => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        setInventoryError(errorMessage(error));
        setInventoryLoading(false);
      });
  }, [pump, scope]);

  const handleRefresh = useCallback(() => {
    startGeneration(resources, scope, true);
  }, [resources, scope, startGeneration]);

  const retryResource = useCallback(
    (resource: FlatInventoryResource) => {
      const key = resourceKey(resource.resource_id);
      setHealthById((current) => ({
        ...current,
        [key]: {
          loading: true,
          data: null,
          snapshot: null,
          evidence: [],
          error: null,
        },
      }));
      queueRef.current.push({
        key,
        resourceId: resource.resource_id,
        scope,
        generation: generationRef.current,
        forceRefresh: true,
      });
      pump();
    },
    [pump, scope],
  );

  const successfulSnapshots = useMemo(
    () =>
      resources
        .map((resource) => healthById[resourceKey(resource.resource_id)]?.snapshot)
        .filter((snapshot): snapshot is ResourceHealthSnapshot => Boolean(snapshot)),
    [healthById, resources],
  );
  const details = useMemo(
    () =>
      successfulSnapshots.flatMap((snapshot) => snapshot.resources.slice(0, 1)),
    [successfulSnapshots],
  );
  const resourcesWithCpu = details.filter(
    (resource) => resource.cpu_percent != null && Number.isFinite(resource.cpu_percent),
  ).length;
  const summary = useMemo(
    () => ({
      total: resources.length,
      critical: details.filter((resource) => resource.status === "critical").length,
      warning: details.filter((resource) => resource.status === "warning").length,
      healthy: details.filter((resource) => resource.status === "healthy").length,
      unknown: details.filter((resource) => resource.status === "unknown").length,
    }),
    [details, resources.length],
  );
  const warnings = useMemo(
    () =>
      Array.from(
        new Set(successfulSnapshots.flatMap((snapshot) => snapshot.warnings)),
      ),
    [successfulSnapshots],
  );
  const unavailableMetrics = useMemo(
    () =>
      Array.from(
        new Set(
          successfulSnapshots.flatMap(
            (snapshot) => snapshot.unavailable_metrics,
          ),
        ),
      ),
    [successfulSnapshots],
  );
  const latestSnapshot = successfulSnapshots.at(-1);
  const evidence = useMemo(
    () =>
      resources.flatMap(
        (resource) =>
          healthById[resourceKey(resource.resource_id)]?.evidence ?? [],
      ),
    [healthById, resources],
  );
  const healthAvailable = details.length > 0;
  const resourceHealthCopilot = buildResourceHealthCopilotContext({
    scope,
    resources: details.map((resource) => ({
      resource_id: resource.resource_id,
      resource_name: resource.resource_name,
      resource_type: resource.resource_type,
      status: resource.status,
      cpu_percent: resource.cpu_percent,
      memory_percent: resource.memory_percent,
      disk_free_percent: resource.disk_free_percent,
      observed_at: resource.observed_at,
      unavailable_metrics: resource.unavailable_metrics ?? [],
      series_point_count: resource.cpu_series?.length ?? 0,
    })),
    loadedCount: details.length,
    totalCount: resources.length,
    summary,
    available: healthAvailable,
    cached:
      successfulSnapshots.length > 0 &&
      successfulSnapshots.every((snapshot) => snapshot.cached),
    observedAt: latestSnapshot?.observed_at,
    freshness: healthAvailable ? "fresh" : "unavailable",
    unavailableMetrics,
    warnings,
    evidence,
  });

  return (
    <div className="page-container operational-page resource-health-page health-workspace">
      <PageHeader
        eyebrow="Resource health"
        title="Compute resource health and utilization"
        description="Azure Monitor utilization metrics for VMs and Container Apps in scope, hydrated independently after inventory loads."
        metadata={
          <>
            <span>{summary.total} in scope</span>
            <span>{details.length} health responses</span>
            <span>{resourcesWithCpu} with CPU samples</span>
            <span>{summary.critical} critical</span>
            <span>{summary.warning} warning</span>
            {latestSnapshot ? (
              <span>
                {successfulSnapshots.every((snapshot) => snapshot.cached)
                  ? "Cached"
                  : "Live"}{" "}
                · observed {latestSnapshot.observed_at}
              </span>
            ) : null}
          </>
        }
        actions={
          <div className="page-header-actions-group">
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label="Ask Copilot about resource health"
            />
            <button
              type="button"
              className="button button-secondary"
              onClick={handleRefresh}
              disabled={inventoryLoading || resources.length === 0}
            >
              Refresh now
            </button>
          </div>
        }
      />

      <nav className="section-nav health-section-nav" aria-label="Health sections">
        <a className="button button-secondary" href="#health-resources">Resource utilization</a>
        {!inventoryLoading && !inventoryError && details.length > 0 && <a className="button button-secondary" href="#health-comparison">CPU comparison</a>}
      </nav>

      {unavailableMetrics.length > 0 ? (
        <StatePanel
          title="Some metrics are unavailable"
          message="VM memory % and disk free % need either a Log Analytics workspace with classic guest performance counters, or an Azure Monitor Workspace receiving OpenTelemetry host metrics; neither was discovered for this scope. Container Apps use platform memory metrics."
          tone="partial"
        />
      ) : null}

      <section id="health-resources" aria-labelledby="health-resources-heading">
        <div className="section-header">
          <div>
            <h2 id="health-resources-heading">Resource utilization</h2>
            <p>Review available measurements and retry individual failures. A returned health response may contain no metric samples; those resources remain unassessed.</p>
          </div>
          <span>{details.length} of {resources.length} health responses · {resourcesWithCpu} resources with CPU samples</span>
        </div>

      {inventoryLoading ? (
        <StatePanel
          title="Loading compute inventory…"
          message="Resolving the authorized resources in the current scope."
          tone="loading"
        />
      ) : null}

      {!inventoryLoading && inventoryError ? (
        <StatePanel
          title="Resource inventory is unavailable"
          message={inventoryError}
          tone="error"
        />
      ) : null}

      {!inventoryLoading && !inventoryError && resources.length === 0 ? (
        <StatePanel
          title="No supported resources found in scope"
          message="No virtual machines or Container Apps matched the current scope, or their connections are inactive."
          tone="empty"
        />
      ) : null}

      {!inventoryLoading && !inventoryError && resources.length > 0 ? (
        <>
          <section className="card" aria-label="Health coverage and triage">
            <div className="card-header"><h2>Health coverage and triage</h2></div>
            <div className="card-body health-triage-body">
              <p role="status">{details.length} of {resources.length} resources returned health evidence. {coverage.loading ?? 0} loading; {coverage.failed ?? 0} failed; {coverage.unknown ?? 0} unknown. Missing evidence is not healthy.</p>
              <div className="health-triage-controls">
                <label>Health state
                  <select className="form-control" value={healthFilter} onChange={event => setHealthFilter(event.target.value)}>
                    {["all", "critical", "warning", "healthy", "unknown", "failed", "loading"].map(state => <option key={state} value={state}>{state}</option>)}
                  </select>
                </label>
                <label>Find compute resource<input className="form-control" ref={resourceSearchInput} type="search" value={resourceSearch} onChange={event => setResourceSearch(event.target.value)} /></label>
              </div>
              <p>{visibleResources.length} matching resources of {resources.length} observed.</p>
            </div>
          </section>
          <div className="metric-grid health-summary-metrics">
            <MetricCard
              label="Resources in scope"
              value={summary.total}
              detail="In current scope"
            />
            <MetricCard
              label="Critical"
              value={summary.critical}
              detail="CPU ≥ 90%"
              tone={summary.critical > 0 ? "critical" : "default"}
            />
            <MetricCard
              label="Warning"
              value={summary.warning}
              detail="CPU ≥ 70%"
              tone={summary.warning > 0 ? "warning" : "default"}
            />
            <MetricCard
              label="Healthy"
              value={summary.healthy}
              detail="CPU below 70%"
              tone="success"
            />
          </div>

          {warnings.length > 0 ? (
            <div className="health-source-warnings" role="status">
              <h3>Metric coverage warnings</h3>
              <ul>
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="health-resource-grid">
            {visibleResources.map((resource) => (
              <ResourceCard
                key={resourceKey(resource.resource_id)}
                resource={resource}
                health={healthById[resourceKey(resource.resource_id)]}
                onRetry={() => retryResource(resource)}
                onReviewHistory={trigger => {
                  historyTrigger.current = trigger;
                  setHistoryResourceId(resource.resource_id);
                }}
              />
            ))}
          </div>
          {visibleResources.length === 0 ? <StatePanel title="No resources match these filters" message="Change the health state or resource search. This does not change the observed inventory." /> : null}
          {resources.filter(resource => resource.resource_id === historyResourceId).map(resource =>
            <ResourceHealthHistory key={resource.resource_id} scope={scope} resource={resource}
              onClose={() => {
                setHistoryResourceId(null);
                const target = historyTrigger.current?.isConnected ? historyTrigger.current : resourceSearchInput.current;
                target?.focus();
                historyTrigger.current = null;
              }} />
          )}
        </>
      ) : null}
      </section>

      {!inventoryLoading && !inventoryError && details.length > 0 && (
        <section id="health-comparison" className="card" aria-labelledby="health-comparison-heading">
          <div className="card-header">
            <div>
              <h2 id="health-comparison-heading">CPU comparison</h2>
              <p>Compare returned CPU samples. Unavailable values are not zero. Scroll the chart to see all labels on narrow screens.</p>
            </div>
          </div>
          <div className="card-body">
            <div className="table-scroll health-chart-scroll" tabIndex={0} role="region" aria-label="Scrollable CPU chart">
              <UtilizationBarChart data={details.filter(resource => visibleResources.some(row => resourceKey(row.resource_id) === resourceKey(resource.resource_id))).map((resource) => ({
                id: resource.resource_id,
                label: resource.resource_name,
                value: resource.cpu_percent,
              }))} />
            </div>
          </div>
        </section>
      )}


      <CopilotInsights
        snapshot={resourceHealthCopilot.snapshot}
        question={RESOURCE_HEALTH_INSIGHT_QUESTION}
        ready={!inventoryLoading}
        requestedScope={resourceHealthCopilot.requestedScope}
        contextLabel="Resource health"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Resource health"
        requestedScope={resourceHealthCopilot.requestedScope}
        snapshot={resourceHealthCopilot.snapshot}
        starterQuestions={resourceHealthCopilot.starterQuestions}
      />
    </div>
  );
}
