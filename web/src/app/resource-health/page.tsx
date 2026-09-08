"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { MetricCard } from "@/components/ui/MetricCard";
import { MetricSparkline } from "@/components/ui/MetricSparkline";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { UtilizationBarChart } from "@/components/ui/UtilizationBarChart";
import { useApi } from "@/hooks/useApi";
import { buildResourceHealthCopilotContext } from "@/lib/copilot/page-adapters";
import { useScope } from "@/lib/scope-context";
import { resourceHealthApi } from "@/lib/services";
import type { ResourceUtilization } from "@/lib/types";

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

function ResourceCard({ resource }: { resource: ResourceUtilization }) {
  return (
    <article className="card" style={{ padding: "1rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
        <div>
          <div style={{ fontWeight: 600 }}>{resource.resource_name}</div>
          <div className="cell-subtext">{resource.resource_group}</div>
        </div>
        <StatusBadge label={resource.status} tone={statusTone(resource.status)} compact />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <MetricSparkline data={resource.cpu_series ?? []} max={100} />
        <div>
          <div style={{ fontSize: "1.25rem", fontWeight: 700 }}>{formatPercent(resource.cpu_percent)}</div>
          <div className="cell-subtext">CPU</div>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "0.35rem 0.75rem",
          fontSize: "0.8125rem",
        }}
      >
        <span className="cell-subtext">Memory: {formatPercent(resource.memory_percent)}</span>
        <span className="cell-subtext">Disk free: {formatPercent(resource.disk_free_percent)}</span>
        <span className="cell-subtext">Net in: {formatBytes(resource.network_in_bytes)}</span>
        <span className="cell-subtext">Net out: {formatBytes(resource.network_out_bytes)}</span>
        <span className="cell-subtext">Disk read: {formatBytes(resource.disk_read_bytes)}</span>
        <span className="cell-subtext">Disk write: {formatBytes(resource.disk_write_bytes)}</span>
      </div>

      <div className="cell-subtext">{resource.error ? resource.error : `Observed ${resource.observed_at}`}</div>
    </article>
  );
}

/**
 * Live compute-resource utilization sourced from Azure Monitor platform
 * metrics (CPU, network, and disk I/O), merged with memory % and disk
 * free-space % from classic Log Analytics guest performance counters when a
 * workspace is auto-discovered in scope. If no workspace/guest counters are
 * found, a banner names the gap rather than fabricating or silently omitting
 * the numbers.
 */
export default function ResourceHealthPage() {
  const { scope } = useScope();
  const [refreshToken, setRefreshToken] = useState(0);
  const forceRefreshRef = useRef(false);
  const health = useApi(
    () => {
      const forceRefresh = forceRefreshRef.current;
      forceRefreshRef.current = false;
      return resourceHealthApi.snapshot(scope, forceRefresh);
    },
    [scope, refreshToken],
  );

  const data = health.data?.data;
  const resources = useMemo(() => data?.resources ?? [], [data]);
  const summary = data?.summary;

  const [copilotOpen, setCopilotOpen] = useState(false);
  const handleRefresh = useCallback(() => {
    forceRefreshRef.current = true;
    setRefreshToken((token) => token + 1);
  }, []);

  // Read-only contextual Copilot over the already-loaded utilization snapshot.
  // Resource/metric identities, observation windows, and missing-series status
  // stay explicit; a cached read is still fresh evidence (D-03, D-06, D-09).
  const healthAvailable = !health.error && Boolean(health.data);
  const resourceHealthCopilot = buildResourceHealthCopilotContext({
    scope,
    resources: resources.map((resource) => ({
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
    loadedCount: resources.length,
    totalCount: summary?.total ?? resources.length,
    summary: summary
      ? {
          total: summary.total,
          critical: summary.critical,
          warning: summary.warning,
          healthy: summary.healthy,
          unknown: summary.unknown,
        }
      : null,
    available: healthAvailable,
    cached: data?.cached,
    observedAt: data?.observed_at,
    freshness: healthAvailable ? "fresh" : "unavailable",
    unavailableMetrics: data?.unavailable_metrics ?? [],
    warnings: data?.warnings ?? [],
    evidence: health.data?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Resource health"
        title="CPU, disk, and network pressure"
        description="Azure Monitor metrics for VMs and Arc servers in scope, cached briefly to avoid throttling."
        metadata={
          <>
            <span>{summary?.total ?? 0} observed</span>
            <span>{summary?.critical ?? 0} critical</span>
            <span>{summary?.warning ?? 0} warning</span>
            {data && (
              <span>
                {data.cached ? "Cached" : "Live"} · observed {data.observed_at}
              </span>
            )}
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
              disabled={health.loading}
            >
              {health.loading && refreshToken > 0 ? "Refreshing…" : "Refresh now"}
            </button>
          </div>
        }
      />

      {(data?.unavailable_metrics?.length ?? 0) > 0 && (
        <div className="state-panel state-empty" role="status" style={{ marginBottom: "1.5rem" }}>
          <p>
            Memory % and disk free % need either a Log Analytics workspace with classic
            guest performance counters, or an Azure Monitor Workspace receiving
            OpenTelemetry host metrics; neither was discovered for this scope.
          </p>
        </div>
      )}

      {health.loading && (
        <StatePanel title="Fetching live utilization…" message="Querying Azure Monitor Metrics for in-scope resources." tone="loading" />
      )}

      {!health.loading && health.error && (
        <StatePanel
          title="Resource health is unavailable"
          message={health.error.message || "Could not reach the resource health provider for this scope."}
          tone="error"
        />
      )}

      {!health.loading && !health.error && resources.length === 0 && (
        <StatePanel
          title="No compute resources found in scope"
          message="No virtual machines or Arc-connected servers matched the current scope, or their connections are inactive."
          tone="empty"
        />
      )}

      {!health.loading && !health.error && resources.length > 0 && (
        <>
          <div className="metric-grid" style={{ marginBottom: "1.5rem" }}>
            <MetricCard label="Resources observed" value={summary?.total ?? 0} detail="In current scope" />
            <MetricCard
              label="Critical"
              value={summary?.critical ?? 0}
              detail="CPU ≥ 90%"
              tone={summary && summary.critical > 0 ? "critical" : "default"}
            />
            <MetricCard
              label="Warning"
              value={summary?.warning ?? 0}
              detail="CPU ≥ 70%"
              tone={summary && summary.warning > 0 ? "warning" : "default"}
            />
            <MetricCard
              label="Healthy"
              value={summary?.healthy ?? 0}
              detail="CPU below 70%"
              tone="success"
            />
          </div>

          {(data?.warnings?.length ?? 0) > 0 && (
            <div className="state-panel state-empty" role="status" style={{ marginBottom: "1.5rem" }}>
              <ul>
                {data?.warnings?.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="card" style={{ marginBottom: "1.5rem", padding: "1rem" }}>
            <UtilizationBarChart
              data={resources.map((r) => ({
                id: r.resource_id,
                label: r.resource_name,
                value: r.cpu_percent,
              }))}
            />
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: "1rem",
            }}
          >
            {resources.map((resource) => (
              <ResourceCard key={resource.resource_id} resource={resource} />
            ))}
          </div>
        </>
      )}

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
