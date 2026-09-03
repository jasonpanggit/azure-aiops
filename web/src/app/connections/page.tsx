"use client";

import { useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { FabricMedallionPanel } from "@/components/fabric/medallion";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, relativeTime } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { connectionsApi } from "@/lib/services";
import type { SubscriptionConnection, SyncState } from "@/lib/types";

const SYNC_POLL_INTERVAL_MS = 1500;
// Discovery + merge + ontology + Fabric publish can take well past 10 minutes
// for large subscriptions (observed ~16 min for ~12.7k records); the poll
// window must comfortably exceed that so the UI doesn't report a false
// timeout while the background sync is still healthy and progressing.
const SYNC_POLL_TIMEOUT_MS = 20 * 60 * 1000;

/** Subscription connections and Fabric Medallion data-confidence operating view. */
export default function ConnectionsPage() {
  const { scope } = useScope();
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [runningAction, setRunningAction] = useState("");
  const [syncProgress, setSyncProgress] = useState<{ connectionId: string; state: SyncState } | null>(null);
  const [tab, setTab] = useState<"subscriptions" | "fabric-medallion">("subscriptions");
  const [fabricRefreshKey, setFabricRefreshKey] = useState(0);
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState<string>("");
  const connections = useApi(() => connectionsApi.list(scope), [scope, refreshKey]);
  const rows = useMemo(() => connections.data?.data ?? [], [connections.data]);
  const { filteredRows, filters, resetFilters } = useColumnFilters(rows, [
    { id: "health", label: "Health", getValues: (connection) => connection.health_status },
    { id: "sync", label: "Sync", getValues: (connection) => connection.sync_status || "unknown" },
    { id: "service", label: "Service", getValues: (connection) => connection.business_service || "Service not mapped" },
    { id: "environment", label: "Environment", getValues: (connection) => connection.environment || "Environment not mapped" },
    { id: "criticality", label: "Criticality", getValues: (connection) => connection.criticality || "Criticality not set" },
  ]);
  const rowsPaging = useTablePagination(filteredRows);

  useEffect(() => {
    // Set default subscription when switching to fabric-medallion tab
    if (tab === "fabric-medallion" && !selectedSubscriptionId && rows.length > 0) {
      setSelectedSubscriptionId(rows[0].subscription_id);
    }
  }, [tab, selectedSubscriptionId, rows]);

  /** Polls connection health until the background sync reaches a terminal stage. */
  async function pollSyncState(connectionId: string): Promise<SyncState> {
    const deadline = Date.now() + SYNC_POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      const report = await connectionsApi.health(connectionId);
      const summary = report.data.connections.find((entry) => entry.connection_id === connectionId);
      const state = summary?.sync;
      if (state) {
        setSyncProgress({ connectionId, state });
        if (["succeeded", "failed"].includes(state.status.toLowerCase())) {
          return state;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, SYNC_POLL_INTERVAL_MS));
    }
    throw new Error(
      "Still waiting for sync to reach a final state after 20 minutes. It may still be running in the background — check the connection's status and refresh shortly."
    );
  }

  async function deleteConnection(connection: SubscriptionConnection) {
    if (!window.confirm(`Delete subscription connection "${connection.name}"? This removes it from the registry.`)) {
      return;
    }
    setRunningAction(`delete:${connection.connection_id}`);
    try {
      await connectionsApi.delete(connection.connection_id);
      setRefreshKey((value) => value + 1);
    } finally {
      setRunningAction("");
    }
  }

  /** Kicks off a manual sync for one connection and polls until it reaches a terminal stage. */
  async function syncConnection(connection: SubscriptionConnection) {
    setActionError("");
    setActionMessage("");
    setRunningAction(`sync:${connection.connection_id}`);
    try {
      const result = await connectionsApi.sync(connection.connection_id, "manual");
      setSyncProgress({ connectionId: connection.connection_id, state: result.data.sync_state });
      const finalState = await pollSyncState(connection.connection_id);
      if (finalState.status.toLowerCase() === "failed") {
        setActionError(finalState.message ?? finalState.stage_message ?? `Sync failed for ${connection.name}.`);
      } else {
        setActionMessage(`${connection.name} is up to date (${finalState.record_count ?? 0} records synced).`);
      }
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : `Unable to sync ${connection.name}.`);
    } finally {
      setRunningAction("");
    }
  }

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Data & integrations"
        title={tab === "subscriptions" ? "Subscription connections" : "Fabric Medallion"}
        description={
          tab === "subscriptions"
            ? "Manage onboarded Azure subscription connections, credentials, health, sync status, and business context."
            : "Monitor Bronze, Silver, and Gold Fabric layers, ingestion history, governance gaps, and readiness for the selected subscription."
        }
        actions={
          tab === "fabric-medallion" ? (
            <div className="page-header-actions-group">
              <select 
                name="subscriptionId"
                className="form-control"
                value={selectedSubscriptionId}
                onChange={(e) => setSelectedSubscriptionId(e.target.value)}
                disabled={rows.length === 0}
              >
                <option value="">Select a subscription</option>
                {rows.map((conn) => (
                  <option key={conn.subscription_id} value={conn.subscription_id}>
                    {conn.name} ({conn.subscription_id})
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="button button-primary"
                onClick={() => setFabricRefreshKey((value) => value + 1)}
              >
                Refresh Fabric health
              </button>
            </div>
          ) : null
        }
      />

      <div role="tablist" aria-label="Data & integrations views" className="tab-list">
        <button
          id="subscriptions-tab"
          type="button"
          role="tab"
          aria-selected={tab === "subscriptions"}
          aria-controls="subscriptions-panel"
          tabIndex={tab === "subscriptions" ? 0 : -1}
          onClick={() => setTab("subscriptions")}
        >
          Subscriptions
        </button>
        <button
          id="fabric-medallion-tab"
          type="button"
          role="tab"
          aria-selected={tab === "fabric-medallion"}
          aria-controls="fabric-medallion-panel"
          tabIndex={tab === "fabric-medallion" ? 0 : -1}
          onClick={() => setTab("fabric-medallion")}
        >
          Fabric Medallion
        </button>
      </div>

      {(actionError || actionMessage || syncProgress) && (
        <div className={`callout ${actionError ? "callout-critical" : syncProgress?.state.status.toLowerCase() === "failed" ? "callout-critical" : "callout-info"}`} role="status">
          {syncProgress && (
            <strong>
              Sync {syncProgress.state.status.toLowerCase() === "succeeded" ? "completed" : syncProgress.state.status.toLowerCase() === "failed" ? "failed" : "in progress"}
              {syncProgress.state.stage ? `: ${syncProgress.state.stage}` : ""}
              {syncProgress.state.progress_pct != null ? ` (${syncProgress.state.progress_pct}%)` : ""}
            </strong>
          )}
          {actionMessage && <span>{actionMessage}</span>}
          {actionError && <span>{actionError}</span>}
        </div>
      )}

      {tab === "subscriptions" && <section
        id="subscriptions-panel"
        role="tabpanel"
        aria-labelledby="subscriptions-tab"
        tabIndex={0}
      >
        {connections.error ? (
          <StatePanel title="Connection health is unavailable" message={connections.error.message} tone="error" />
        ) : connections.loading ? (
          <StatePanel title="Loading subscription coverage" message="Checking health, sync state, freshness, and metadata." tone="loading" />
        ) : rows.length === 0 ? (
          <StatePanel title="No subscriptions onboarded" message="Complete the onboarding form above to establish operational coverage." />
        ) : (
          <div className="card connection-table">
            <TableColumnFilters
              filters={filters}
              onReset={resetFilters}
              resultCount={filteredRows.length}
              totalCount={rows.length}
            />
            <div className="table-scroll">
              <table className="operations-table">
                <thead><tr><th>Connection</th><th>Business context</th><th>Health</th><th>Sync</th><th>Last successful sync</th><th>Actions</th></tr></thead>
                <tbody>
                  {rowsPaging.pageRows.map((connection) => (
                    <tr key={connection.connection_id}>
                      <td><strong>{connection.name}</strong><div className="table-secondary">{connection.subscription_id}</div></td>
                      <td><strong>{connection.business_service || "Service not mapped"}</strong><div className="table-secondary">{connection.environment || "Environment not mapped"} · {connection.criticality || "Criticality not set"}</div></td>
                      <td><StatusBadge label={connection.health_status} tone={statusTone(connection.health_status)} /></td>
                      <td>
                        <StatusBadge label={connection.sync_status || "unknown"} tone={statusTone(connection.sync_status)} />
                        <div className="table-secondary">{connection.sync_record_count ?? 0} records discovered</div>
                      </td>
                      <td><strong>{relativeTime(connection.last_successful_sync_at)}</strong><div className="table-secondary">{formatDateTime(connection.last_successful_sync_at)}</div></td>
                      <td>
                        <div className="row-actions">
                          <button
                            type="button"
                            className="button button-quiet"
                            disabled={Boolean(runningAction)}
                            onClick={() => syncConnection(connection)}
                          >
                            {runningAction === `sync:${connection.connection_id}` ? "Syncing…" : "Sync now"}
                          </button>                    
                          <button
                            type="button"
                            className="button button-quiet"
                            disabled={Boolean(runningAction)}
                            onClick={() => deleteConnection(connection)}
                          >
                            {runningAction === `delete:${connection.connection_id}` ? "Deleting…" : "Delete"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TablePagination
              total={rowsPaging.total}
              pageRows={rowsPaging.pageRows.length}
              page={rowsPaging.page}
              onPageChange={rowsPaging.setPage}
              pageSize={rowsPaging.pageSize}
              onPageSizeChange={rowsPaging.setPageSize}
              label="connections"
            />
          </div>
        )}
      </section>}

      {tab === "fabric-medallion" && (!selectedSubscriptionId ? (
        <section id="fabric-medallion-panel" role="tabpanel" aria-labelledby="fabric-medallion-tab" tabIndex={0}>
          <StatePanel 
            title="Select a subscription" 
            message="Choose a subscription from the dropdown above to view its Fabric medallion data, including Bronze, Silver, and Gold layer health, lifecycle status, and governance gaps."
            tone="empty"
          />
        </section>
      ) : (
        <FabricMedallionPanel 
          refreshKey={fabricRefreshKey} 
          scope={scope} 
          subscriptionId={selectedSubscriptionId}
        />
      ))}
    </div>
  );
}
