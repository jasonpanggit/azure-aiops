"use client";

import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { FabricMedallionPanel } from "@/components/fabric/medallion";
import {
  OntologyAutomationPanel,
  type OntologyStatusState,
} from "@/components/ontology/OntologyAutomationPanel";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { buildConnectionsCopilotContext } from "@/lib/copilot/page-adapters";
import { formatDateTime, relativeTime } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, ontologyAutomationApi } from "@/lib/services";
import { ApiError, type ConnectionCreateRequest, type SubscriptionConnection, type SyncState } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const EMPTY_FORM = {
  connectionId: "",
  name: "",
  subscriptionId: "",
  tenantId: "",
  clientId: "",
  clientSecret: "",
  businessService: "",
  application: "",
  environment: "",
  owner: "",
  supportTeam: "",
  criticality: "medium",
  region: "",
  costCenter: "",
};

const SYNC_POLL_INTERVAL_MS = 1500;
// Discovery + merge + ontology + Fabric publish can take well past 10 minutes
// for large subscriptions (observed ~16 min for ~12.7k records); the poll
// window must comfortably exceed that so the UI doesn't report a false
// timeout while the background sync is still healthy and progressing.
const SYNC_POLL_TIMEOUT_MS = 20 * 60 * 1000;
const ACTIVE_SYNC_STATUSES = new Set([
  "queued",
  "discovering",
  "merging",
  "publishing_ontology",
  "writing_fabric_tables",
  "running",
  "in_progress",
]);
const TRANSIENT_SYNC_POLL_STATUSES = new Set([0, 502, 503, 504]);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isActiveSyncState(state: Pick<SyncState, "status" | "stage"> | null | undefined): boolean {
  if (!state) return false;
  const status = state.status.toLowerCase();
  return status === "running" || ACTIVE_SYNC_STATUSES.has(status) || ACTIVE_SYNC_STATUSES.has((state.stage ?? "").toLowerCase());
}

function isTransientSyncPollError(reason: unknown): boolean {
  return reason instanceof ApiError && TRANSIENT_SYNC_POLL_STATUSES.has(reason.status);
}

function readableSyncStage(stage: string | null | undefined): string {
  if (!stage) return "Sync in progress";
  return stage
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

/** Subscription connections and Fabric Medallion data-confidence operating view. */
export default function ConnectionsPage() {
  const { scope } = useScope();
  const [refreshKey, setRefreshKey] = useState(0);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [runningAction, setRunningAction] = useState("");
  const [syncProgress, setSyncProgress] = useState<{ connectionId: string; state: SyncState } | null>(null);
  const [tab, setTab] = useState<"subscriptions" | "fabric-medallion" | "ontology-automation">("subscriptions");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [fabricRefreshKey, setFabricRefreshKey] = useState(0);
  const [ontologyRefreshKey, setOntologyRefreshKey] = useState(0);
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState<string>("");
  const [selectedOntologyConnectionId, setSelectedOntologyConnectionId] = useState("");
  const [ontologyStatus, setOntologyStatus] = useState<OntologyStatusState>({
    data: null,
    error: null,
    loading: false,
  });
  const connections = useApi(() => connectionsApi.list(scope), [scope, refreshKey]);
  const rows = useMemo(() => connections.data?.data ?? [], [connections.data]);
  const activeConnections = useMemo(() => rows.filter((connection) => connection.is_active), [rows]);
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

  useEffect(() => {
    if (tab !== "ontology-automation") return;
    if (
      selectedOntologyConnectionId &&
      !activeConnections.some((connection) => connection.connection_id === selectedOntologyConnectionId)
    ) {
      setSelectedOntologyConnectionId("");
      return;
    }
    if (!selectedOntologyConnectionId && activeConnections.length > 0) {
      setSelectedOntologyConnectionId(activeConnections[0].connection_id);
    }
  }, [activeConnections, selectedOntologyConnectionId, tab]);

  useEffect(() => {
    let cancelled = false;
    if (tab !== "ontology-automation" || !selectedOntologyConnectionId) {
      setOntologyStatus({ data: null, error: null, loading: false });
      return () => {
        cancelled = true;
      };
    }
    setOntologyStatus({ data: null, error: null, loading: true });
    void ontologyAutomationApi
      .status(selectedOntologyConnectionId, scope)
      .then((data) => {
        if (!cancelled) setOntologyStatus({ data, error: null, loading: false });
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setOntologyStatus({
            data: null,
            error: reason instanceof Error ? reason : new Error(String(reason)),
            loading: false,
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ontologyRefreshKey, scope, selectedOntologyConnectionId, tab]);

  /** Polls connection health until the background sync reaches a terminal stage. */
  const pollSyncState = useCallback(async (
    connectionId: string,
    onState?: (state: SyncState) => void,
  ): Promise<SyncState> => {
    const deadline = Date.now() + SYNC_POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      let report;
      try {
        report = await connectionsApi.health(connectionId);
      } catch (reason) {
        if (isTransientSyncPollError(reason)) {
          await sleep(SYNC_POLL_INTERVAL_MS);
          continue;
        }
        throw reason;
      }
      const summary = report.data.connections.find((entry) => entry.connection_id === connectionId);
      const state = summary?.sync;
      if (state) {
        onState?.(state);
        if (!onState) {
          setSyncProgress(isActiveSyncState(state) ? { connectionId, state } : null);
        }
        if (!isActiveSyncState(state) || ["succeeded", "failed"].includes(state.status.toLowerCase())) {
          return state;
        }
      }
      await sleep(SYNC_POLL_INTERVAL_MS);
    }
    throw new Error(
      "Still waiting for sync to reach a final state after 20 minutes. It may still be running in the background — check the connection's status and refresh shortly."
    );
  }, []);

  useEffect(() => {
    const activeConnection = rows.find((connection) =>
      isActiveSyncState({ status: connection.sync_status, stage: null }),
    );
    if (!activeConnection) {
      setSyncProgress(null);
      return;
    }

    let cancelled = false;
    void pollSyncState(activeConnection.connection_id, (state) => {
      if (!cancelled) {
        setSyncProgress(isActiveSyncState(state) ? { connectionId: activeConnection.connection_id, state } : null);
      }
    }).then(() => {
      if (!cancelled) {
        setRefreshKey((value) => value + 1);
      }
    }).catch((reason) => {
      if (!cancelled) {
        setActionError(reason instanceof Error ? reason.message : "Unable to read sync progress.");
      }
    });

    return () => {
      cancelled = true;
    };
  }, [pollSyncState, rows]);

  function update(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function onboard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setActionError("");
    setActionMessage("");
    const payload: ConnectionCreateRequest = {
      connection_id: form.connectionId.trim().toLowerCase(),
      name: form.name.trim(),
      subscription_id: form.subscriptionId.trim(),
      tenant_id: form.tenantId.trim(),
      credential: {
        kind: "service_principal",
        client_id: form.clientId.trim(),
        tenant_id: form.tenantId.trim(),
        client_secret: form.clientSecret,
      },
      metadata: {
        business_service: form.businessService.trim(),
        application: form.application.trim(),
        environment: form.environment.trim(),
        project_owner: form.owner.trim(),
        support_team: form.supportTeam.trim(),
        criticality: form.criticality,
        region: form.region.trim(),
        cost_center: form.costCenter.trim(),
      },
    };
    try {
      const result = await connectionsApi.create(payload);
      const { validation, initial_sync: initialSync } = result.data;
      if (!validation.passed) {
        setActionError(`Validation failed: ${validation.health.details ?? validation.failed_required?.join(", ") ?? "required access checks did not pass"}`);
      } else if (initialSync.status.toLowerCase() === "failed") {
        setActionError(initialSync.sync_state.message ?? "Initial sync failed.");
      } else {
        setActionMessage(
          validation.status === "degraded"
            ? "Subscription connection validated with optional checks degraded. Initial sync queued."
            : "Subscription connection validated. Initial sync queued."
        );
        setSyncProgress({ connectionId: result.data.connection_id, state: initialSync.sync_state });
        const finalState = await pollSyncState(result.data.connection_id);
        setSyncProgress(null);
        if (finalState.status.toLowerCase() === "failed") {
          setActionError(finalState.message ?? finalState.stage_message ?? "Initial sync failed.");
        } else {
          setActionMessage(
            validation.status === "degraded"
              ? "Subscription connection validated with optional checks degraded. Initial sync completed."
              : "Subscription connection validated and initial sync completed."
          );
        }
      }
      setForm(EMPTY_FORM);
      setShowOnboarding(false);
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to create subscription connection.");
    } finally {
      setSubmitting(false);
    }
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
      setSyncProgress(null);
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : `Unable to sync ${connection.name}.`);
    } finally {
      setRunningAction("");
    }
  }

  async function runOntologyDiscovery() {
    const scheduler = ontologyStatus.data?.data.scheduler;
    if (!selectedOntologyConnectionId || !scheduler?.can_run_now) return;
    setActionError("");
    setActionMessage("");
    setRunningAction(`ontology-run:${selectedOntologyConnectionId}`);
    try {
      const suffix =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const result = await ontologyAutomationApi.runNow(selectedOntologyConnectionId, scope, {
        idempotency_key: `run-now:${selectedOntologyConnectionId}:${suffix}`,
        reason: "Manual discovery requested from the Connections page.",
      });
      setActionMessage(`Discovery run ${result.data.run_id} was queued for ${selectedOntologyConnectionId}.`);
      setOntologyRefreshKey((value) => value + 1);
    } catch (reason) {
      const safeReason = reason instanceof Error ? reason.message : "Request failed.";
      setActionError(
        `Discovery was not started for connection ${selectedOntologyConnectionId}. ${safeReason} Refresh connection status before trying again.`,
      );
    } finally {
      setRunningAction("");
    }
  }

  const connectionsCopilot = buildConnectionsCopilotContext({
    scope,
    connections: rows.map((connection) => ({
      connection_id: connection.connection_id,
      name: connection.name,
      subscription_id: connection.subscription_id,
      business_service: connection.business_service,
      environment: connection.environment,
      criticality: connection.criticality,
      health_status: connection.health_status,
      sync_status: connection.sync_status,
      sync_record_count: connection.sync_record_count,
      last_successful_sync_at: connection.last_successful_sync_at,
      is_active: connection.is_active,
    })),
    loadedCount: rows.length,
    totalCount: connections.data?.pagination?.total ?? rows.length,
    available: !connections.error && Boolean(connections.data),
    freshness: connections.error || !connections.data ? "unavailable" : "fresh",
    selectedConnectionId:
      rows.find((connection) => connection.subscription_id === selectedSubscriptionId)?.connection_id ?? null,
    evidence: connections.data?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Data & integrations"
        title={
          tab === "subscriptions"
            ? "Subscription connections"
            : tab === "fabric-medallion"
              ? "Fabric Medallion"
              : "Ontology automation"
        }
        description={
          tab === "subscriptions"
            ? "Manage onboarded Azure subscription connections, credentials, health, sync status, and business context."
            : tab === "fabric-medallion"
              ? "Monitor Bronze, Silver, and Gold Fabric layers, ingestion history, governance gaps, and readiness for the selected subscription."
              : "Monitor scheduled discovery, review proposed relationships, and manage validated Fabric ontology generations for one onboarded connection."
        }
        actions={
          <div className="page-header-actions-group">
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label="Ask Copilot about data health"
            />
            {tab === "subscriptions" && (
              <button
                type="button"
                className="button button-primary"
                onClick={() => setShowOnboarding(true)}
                disabled={submitting}
                aria-expanded={showOnboarding}
                aria-controls="subscription-onboarding-form"
              >
                Add subscription connection
              </button>
            )}
            {tab === "fabric-medallion" ? (
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
          ) : tab === "ontology-automation" ? (
            <div className="page-header-actions-group">
              <label className="ontology-connection-selector">
                <span>Connection</span>
                <select
                  name="ontologyConnectionId"
                  className="form-control"
                  value={selectedOntologyConnectionId}
                  onChange={(event) => setSelectedOntologyConnectionId(event.target.value)}
                  disabled={activeConnections.length === 0}
                >
                  <option value="">Select a connection</option>
                  {activeConnections.map((connection) => (
                    <option key={connection.connection_id} value={connection.connection_id}>
                      {connection.name} ({connection.connection_id})
                    </option>
                  ))}
                </select>
              </label>
              <div className="ontology-header-action">
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => void runOntologyDiscovery()}
                  disabled={
                    !selectedOntologyConnectionId ||
                    ontologyStatus.loading ||
                    !ontologyStatus.data?.data.scheduler.can_run_now ||
                    runningAction.startsWith("ontology-run:")
                  }
                >
                  {runningAction.startsWith("ontology-run:") ? "Starting discovery…" : "Run discovery now"}
                </button>
                <span>Uses the same durable coordinator as scheduled discovery. Closing this page does not stop the run.</span>
              </div>
            </div>
          ) : null}
          </div>
        }
      />

      <CopilotInsights
        snapshot={connectionsCopilot.snapshot}
        ready={!connections.loading}
        requestedScope={connectionsCopilot.requestedScope}
        contextLabel="Data & integrations"
        onOpenCopilot={() => setCopilotOpen(true)}
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
        <button
          id="ontology-automation-tab"
          type="button"
          role="tab"
          aria-selected={tab === "ontology-automation"}
          aria-controls="ontology-automation-panel"
          tabIndex={tab === "ontology-automation" ? 0 : -1}
          onClick={() => setTab("ontology-automation")}
        >
          Ontology automation
        </button>
      </div>

      {(actionError || actionMessage || syncProgress) && (
        <div className={`callout ${actionError ? "callout-critical" : syncProgress?.state.status.toLowerCase() === "failed" ? "callout-critical" : "callout-info"}`} role="status">
          {syncProgress && (
            <strong>
              {syncProgress.state.status.toLowerCase() === "succeeded"
                ? "Sync completed"
                : syncProgress.state.status.toLowerCase() === "failed"
                  ? "Sync failed"
                  : `Sync in progress: ${syncProgress.state.stage_message || readableSyncStage(syncProgress.state.stage)}${syncProgress.state.progress_pct != null ? ` (${syncProgress.state.progress_pct}%)` : ""}`}
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
        {showOnboarding && (
          <form id="subscription-onboarding-form" className="card onboarding-form" onSubmit={onboard} aria-busy={submitting}>
            <div className="card-header">
              <div><h2>Onboard an Azure subscription</h2><p>Enter the service principal secret once. The API stores it in Azure Key Vault and AIOps keeps only the Key Vault reference.</p></div>
            </div>
            <div className="card-body">
              <h3>Azure connection</h3>
              <div className="form-grid">
                <FormField label="Connection ID" value={form.connectionId} onChange={(value) => update("connectionId", value)} required />
                <FormField label="Display name" value={form.name} onChange={(value) => update("name", value)} required />
                <FormField label="Subscription ID" value={form.subscriptionId} onChange={(value) => update("subscriptionId", value)} required />
                <FormField label="Tenant ID" value={form.tenantId} onChange={(value) => update("tenantId", value)} required />
                <FormField label="Service principal client ID" value={form.clientId} onChange={(value) => update("clientId", value)} required />
                <FormField label="Client secret" value={form.clientSecret} onChange={(value) => update("clientSecret", value)} type="password" autoComplete="new-password" required />
              </div>
              <h3 className="form-section-title">Business context</h3>
              <div className="form-grid">
                <FormField label="Business service" value={form.businessService} onChange={(value) => update("businessService", value)} />
                <FormField label="Application" value={form.application} onChange={(value) => update("application", value)} />
                <FormField label="Environment" value={form.environment} onChange={(value) => update("environment", value)} />
                <FormField label="Project owner" value={form.owner} onChange={(value) => update("owner", value)} />
                <FormField label="Support team" value={form.supportTeam} onChange={(value) => update("supportTeam", value)} />
                <label className="form-field"><span>Criticality</span><select className="form-control" value={form.criticality} onChange={(event) => update("criticality", event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
                <FormField label="Region" value={form.region} onChange={(value) => update("region", value)} />
                <FormField label="Cost center" value={form.costCenter} onChange={(value) => update("costCenter", value)} />
              </div>
              <div className="form-actions">
                <button type="button" className="button" onClick={() => setShowOnboarding(false)} disabled={submitting}>Close onboarding form</button>
                <button type="submit" className="button button-primary" disabled={submitting}>{submitting ? "Onboarding…" : "Add subscription"}</button>
              </div>
            </div>
          </form>
        )}
        {connections.error ? (
          <StatePanel title="Connection health is unavailable" message={connections.error.message} tone="error" />
        ) : connections.loading ? (
          <StatePanel title="Loading subscription coverage" message="Checking health, sync state, freshness, and metadata." tone="loading" />
        ) : rows.length === 0 ? (
          <StatePanel title="No subscriptions onboarded" message="Select Add subscription connection to open the onboarding form and establish operational coverage." />
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
                      <td><strong>{connection.name}</strong><div className="table-secondary"><span className="resource-id-cell" title={connection.subscription_id}>{connection.subscription_id}</span></div></td>
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

      {tab === "ontology-automation" && (rows.length === 0 && !connections.loading ? (
        <section id="ontology-automation-panel" role="tabpanel" aria-labelledby="ontology-automation-tab" tabIndex={0}>
          <StatePanel
            title="No subscriptions onboarded"
            message="Onboard an Azure subscription connection before configuring or running ontology discovery."
            tone="empty"
          />
        </section>
      ) : !selectedOntologyConnectionId ? (
        <section id="ontology-automation-panel" role="tabpanel" aria-labelledby="ontology-automation-tab" tabIndex={0}>
          <StatePanel
            title="Select a connection to view ontology automation"
            message="Choose an in-scope connection above. Discovery, proposal review, and generation actions are connection-specific."
            tone={connections.loading ? "loading" : "empty"}
          />
        </section>
      ) : (
        <OntologyAutomationPanel
          connectionId={selectedOntologyConnectionId}
          scope={scope}
          refreshKey={ontologyRefreshKey}
          status={ontologyStatus}
          onRunNow={() => void runOntologyDiscovery()}
          onRefresh={() => setOntologyRefreshKey((value) => value + 1)}
        />
      ))}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Data & integrations"
        requestedScope={connectionsCopilot.requestedScope}
        snapshot={connectionsCopilot.snapshot}
        starterQuestions={connectionsCopilot.starterQuestions}
      />
    </div>
  );
}

function FormField({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
  required?: boolean;
}) {
  return (
    <label className="form-field">
      <span>{label}{required ? " *" : ""}</span>
      <input
        className="form-control"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        type={type}
        autoComplete={autoComplete}
        required={required}
      />
    </label>
  );
}
