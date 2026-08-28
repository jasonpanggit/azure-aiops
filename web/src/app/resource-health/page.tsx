"use client";

import { useMemo } from "react";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { resourceHealthApi } from "@/lib/services";

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

/**
 * Live compute-resource utilization sourced from Azure Monitor platform
 * metrics (CPU, network, and disk I/O). Memory percentage and disk
 * free-space percentage are intentionally not shown here: an ordinary VM
 * only exposes those via a guest agent writing to Log Analytics, which this
 * workbench does not currently collect, so a banner names the gap rather
 * than fabricating or silently omitting the numbers.
 */
export default function ResourceHealthPage() {
  const { scope } = useScope();
  const health = useApi(() => resourceHealthApi.snapshot(scope), [scope]);

  const data = health.data?.data;
  const resources = useMemo(() => data?.resources ?? [], [data]);
  const summary = data?.summary;
  const hasScope = Boolean(scope.subscription?.length || scope.subscription_connection?.length);

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Resource health"
        title="Which servers are under CPU, disk, or network pressure right now?"
        description="Live Azure Monitor platform metrics for virtual machines and Arc-connected servers in scope. Readings are fetched at request time, not cached, so a critical reading reflects what Azure Monitor reports right now."
        metadata={
          <>
            <span>{summary?.total ?? 0} resources observed</span>
            <span>{summary?.critical ?? 0} critical</span>
            <span>{summary?.warning ?? 0} warning</span>
            <span>Memory % and disk free % are not available from platform metrics</span>
          </>
        }
      />

      {data?.unavailable_metrics && data.unavailable_metrics.length > 0 && (
        <div className="state-panel state-empty" role="status" style={{ marginBottom: "1.5rem" }}>
          <p>
            Memory utilization and disk free-space are not shown: they require the Azure Monitor
            Agent writing guest performance counters to Log Analytics, which is not wired into this
            workbench. CPU, network, and disk I/O below come directly from the Azure Monitor Metrics
            platform API and need no guest agent.
          </p>
        </div>
      )}

      {!hasScope && (
        <StatePanel
          title="Select a subscription to view resource health"
          message="Resource health is a live per-subscription reading with no cached fallback. Choose a scope above to fetch current utilization."
          tone="empty"
        />
      )}

      {hasScope && health.loading && (
        <StatePanel title="Fetching live utilization…" message="Querying Azure Monitor Metrics for in-scope resources." tone="loading" />
      )}

      {hasScope && health.error && (
        <StatePanel
          title="Resource health is unavailable"
          message={health.error.message || "Could not reach the resource health provider for this scope."}
          tone="error"
        />
      )}

      {hasScope && !health.loading && !health.error && resources.length === 0 && (
        <StatePanel
          title="No compute resources found in scope"
          message="No virtual machines or Arc-connected servers matched the current scope, or their connections are inactive."
          tone="empty"
        />
      )}

      {hasScope && resources.length > 0 && (
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

          {data?.warnings && data.warnings.length > 0 && (
            <div className="state-panel state-empty" role="status" style={{ marginBottom: "1.5rem" }}>
              <ul>
                {data.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Resource</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>CPU</th>
                  <th>Network in</th>
                  <th>Network out</th>
                  <th>Disk read</th>
                  <th>Disk write</th>
                  <th>Observed</th>
                </tr>
              </thead>
              <tbody>
                {resources.map((resource) => (
                  <tr key={resource.resource_id}>
                    <td>
                      <div>{resource.resource_name}</div>
                      <div className="cell-subtext">{resource.resource_group}</div>
                    </td>
                    <td>{resource.resource_type}</td>
                    <td>
                      <StatusBadge label={resource.status} tone={statusTone(resource.status)} compact />
                    </td>
                    <td>{formatPercent(resource.cpu_percent)}</td>
                    <td>{formatBytes(resource.network_in_bytes)}</td>
                    <td>{formatBytes(resource.network_out_bytes)}</td>
                    <td>{formatBytes(resource.disk_read_bytes)}</td>
                    <td>{formatBytes(resource.disk_write_bytes)}</td>
                    <td className="cell-subtext">
                      {resource.error ? resource.error : resource.observed_at}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
