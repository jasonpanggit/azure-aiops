"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
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
import type { BusinessMetadata, ConnectionCreateRequest, SubscriptionConnection, SyncState } from "@/lib/types";

const SYNC_POLL_INTERVAL_MS = 1500;
// Discovery + merge + ontology + Fabric publish can take well past 10 minutes
// for large subscriptions (observed ~16 min for ~12.7k records); the poll
// window must comfortably exceed that so the UI doesn't report a false
// timeout while the background sync is still healthy and progressing.
const SYNC_POLL_TIMEOUT_MS = 20 * 60 * 1000;

const SYNC_STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  discovering: "Discovering resources",
  merging: "Merging inventory",
  publishing_ontology: "Publishing ontology",
  writing_fabric_tables: "Writing Fabric tables",
  succeeded: "Completed",
  failed: "Failed",
};

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

const EMPTY_EDIT_FORM = {
  name: "",
  businessService: "",
  application: "",
  environment: "",
  owner: "",
  supportTeam: "",
  criticality: "medium",
  region: "",
  costCenter: "",
};

/** Subscription onboarding and data-confidence operating view. */
export default function ConnectionsPage() {
  const { scope } = useScope();
  const [refreshKey, setRefreshKey] = useState(0);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [runningAction, setRunningAction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [editingConnection, setEditingConnection] = useState<SubscriptionConnection | null>(null);
  const [editForm, setEditForm] = useState(EMPTY_EDIT_FORM);
  const [editLoading, setEditLoading] = useState(false);
  const [editSubmitting, setEditSubmitting] = useState(false);
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
  const healthy = rows.filter((connection) => connection.health_status === "healthy").length;
  const stale = rows.filter((connection) => connection.health_status === "stale").length;
  const failed = rows.filter((connection) => ["failed", "unhealthy"].includes(connection.health_status)).length;
  const unmapped = rows.filter((connection) => !connection.business_service || !connection.environment).length;
  const staleConnections = useMemo(
    () => rows.filter((connection) => connection.health_status === "stale"),
    [rows],
  );

  useEffect(() => {
    if (!connections.loading && !connections.error && rows.length === 0) {
      setShowOnboarding(true);
    }
  }, [connections.error, connections.loading, rows.length]);

  useEffect(() => {
    // Set default subscription when switching to fabric-medallion tab
    if (tab === "fabric-medallion" && !selectedSubscriptionId && rows.length > 0) {
      setSelectedSubscriptionId(rows[0].subscription_id);
    }
  }, [tab, selectedSubscriptionId, rows]);

  function update(key: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateEdit(key: keyof typeof editForm, value: string) {
    setEditForm((current) => ({ ...current, [key]: value }));
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

  /** Polls connection health until the background sync reaches a terminal stage, updating live progress. */
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
    setActionError("");
    setActionMessage("");
    setRunningAction(`delete:${connection.connection_id}`);
    try {
      await connectionsApi.delete(connection.connection_id);
      setActionMessage(`Subscription connection ${connection.name} was deleted.`);
      if (editingConnection?.connection_id === connection.connection_id) {
        setEditingConnection(null);
        setEditForm(EMPTY_EDIT_FORM);
      }
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to delete subscription connection.");
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
      setSyncProgress(null);
      if (finalState.status.toLowerCase() === "failed") {
        setActionError(finalState.message ?? finalState.stage_message ?? `Sync failed for ${connection.name}.`);
      } else {
        setActionMessage(`${connection.name} is up to date (${finalState.record_count ?? 0} records synced).`);
      }
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setSyncProgress(null);
      setActionError(reason instanceof Error ? reason.message : `Unable to sync ${connection.name}.`);
    } finally {
      setRunningAction("");
    }
  }

  /** Syncs every stale connection sequentially, reporting a single combined result. */
  async function syncAllStale() {
    if (staleConnections.length === 0) return;
    setActionError("");
    setActionMessage("");
    setRunningAction("sync-all-stale");
    const failures: string[] = [];
    try {
      for (const connection of staleConnections) {
        try {
          const result = await connectionsApi.sync(connection.connection_id, "manual");
          setSyncProgress({ connectionId: connection.connection_id, state: result.data.sync_state });
          const finalState = await pollSyncState(connection.connection_id);
          if (finalState.status.toLowerCase() === "failed") {
            failures.push(connection.name);
          }
        } catch {
          failures.push(connection.name);
        }
      }
      setSyncProgress(null);
      if (failures.length > 0) {
        setActionError(`Sync failed for: ${failures.join(", ")}.`);
      } else {
        setActionMessage(`Synced ${staleConnections.length} stale subscription connection${staleConnections.length === 1 ? "" : "s"}.`);
      }
      setRefreshKey((value) => value + 1);
    } finally {
      setRunningAction("");
    }
  }

  async function startEdit(connection: SubscriptionConnection) {
    setShowOnboarding(false);
    setActionError("");
    setActionMessage("");
    setEditingConnection(connection);
    setEditLoading(true);
    try {
      const envelope = await connectionsApi.get(connection.connection_id);
      const detail = envelope.data;
      const metadata = detail.business_metadata ?? {};
      setEditingConnection(detail);
      setEditForm({
        name: detail.name,
        businessService: metadata.business_service ?? detail.business_service ?? "",
        application: metadata.application ?? "",
        environment: metadata.environment ?? detail.environment ?? "",
        owner: metadata.project_owner ?? "",
        supportTeam: metadata.support_team ?? "",
        criticality: metadata.criticality ?? detail.criticality ?? "medium",
        region: metadata.region ?? "",
        costCenter: metadata.cost_center ?? "",
      });
    } catch (reason) {
      setEditingConnection(null);
      setActionError(reason instanceof Error ? reason.message : "Unable to load subscription connection details.");
    } finally {
      setEditLoading(false);
    }
  }

  async function saveEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingConnection) return;

    setEditSubmitting(true);
    setActionError("");
    setActionMessage("");
    let nameSaved = false;
    const metadata: BusinessMetadata = {
      business_service: editForm.businessService.trim(),
      application: editForm.application.trim(),
      environment: editForm.environment.trim(),
      project_owner: editForm.owner.trim(),
      support_team: editForm.supportTeam.trim(),
      criticality: editForm.criticality,
      region: editForm.region.trim(),
      cost_center: editForm.costCenter.trim(),
    };

    try {
      await connectionsApi.update(editingConnection.connection_id, { name: editForm.name.trim() });
      nameSaved = true;
      await connectionsApi.mapMetadata(editingConnection.connection_id, metadata);
      setActionMessage(`Subscription connection ${editForm.name.trim()} was updated.`);
      setEditingConnection(null);
      setEditForm(EMPTY_EDIT_FORM);
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Unable to update subscription connection.";
      setActionError(nameSaved ? `The name was saved, but business metadata was not updated: ${message}` : message);
    } finally {
      setEditSubmitting(false);
    }
  }

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Data & integrations"
        title="Subscription connections"
        description="Operational coverage, freshness, credential health, and business context for every onboarded Azure subscription, plus Fabric medallion dataset health, governance gaps, ingestion history, and readiness signals."
        actions={
          tab === "subscriptions" ? (
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                setEditingConnection(null);
                setShowOnboarding((value) => !value);
              }}
            >
              {showOnboarding ? "Close onboarding" : "Onboard subscription"}
            </button>
          ) : (
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
          )
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
          Fabric medallion
        </button>
      </div>

      <section
        id="subscriptions-panel"
        role="tabpanel"
        aria-labelledby="subscriptions-tab"
        tabIndex={0}
        hidden={tab !== "subscriptions"}
      >
      {connections.data && (
        <EvidenceBar
          evidence={connections.data.evidence}
          knowledgeVersion={connections.data.knowledge_version}
          warnings={connections.data.warnings}
        />
      )}

      <div className="metric-grid connection-metrics">
        <MetricCard label="Connections" value={rows.length} detail={`${healthy} healthy and current`} tone={rows.length && healthy === rows.length ? "success" : "default"} />
        <MetricCard label="Stale" value={stale} detail="Connections beyond the freshness objective" tone={stale ? "warning" : "success"} />
        <MetricCard label="Failed" value={failed} detail="Validation, access, or sync failures" tone={failed ? "critical" : "success"} />
        <MetricCard label="Context gaps" value={unmapped} detail="Missing business service or environment metadata" tone={unmapped ? "warning" : "success"} />
      </div>

      {staleConnections.length > 0 && (
        <div className="callout callout-warning stale-connections-callout">
          <strong>
            {staleConnections.length} subscription connection{staleConnections.length === 1 ? "" : "s"} need{staleConnections.length === 1 ? "s" : ""} a knowledge sync
          </strong>
          <ul className="stale-connections-list">
            {staleConnections.map((connection) => (
              <li key={connection.connection_id}>
                <span>
                  {connection.name} <span className="table-secondary">({connection.subscription_id})</span> — last synced{" "}
                  {relativeTime(connection.last_successful_sync_at)}
                </span>
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={Boolean(runningAction)}
                  onClick={() => syncConnection(connection)}
                >
                  {runningAction === `sync:${connection.connection_id}` ? "Syncing…" : "Sync now"}
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="button button-primary"
            disabled={Boolean(runningAction)}
            onClick={() => syncAllStale()}
          >
            {runningAction === "sync-all-stale" ? "Syncing all…" : "Sync all stale"}
          </button>
        </div>
      )}

      {showOnboarding && (
        <form className="card onboarding-form" onSubmit={onboard}>
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
              <FormField
                label="Client secret"
                value={form.clientSecret}
                onChange={(value) => update("clientSecret", value)}
                type="password"
                autoComplete="new-password"
                required
              />
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
              <button type="button" className="button" onClick={() => setShowOnboarding(false)}>Close onboarding form</button>
              <button type="submit" className="button button-primary" disabled={submitting}>{submitting ? "Onboarding…" : "Add subscription"}</button>
            </div>
          </div>
        </form>
      )}

      {editingConnection && (
        <form className="card edit-connection-form" onSubmit={saveEdit} aria-busy={editLoading || editSubmitting}>
          <div className="card-header">
            <div>
              <h2>Edit subscription connection</h2>
              <p>Update the operator-facing name and business context. Azure subscription and tenant identifiers are immutable.</p>
            </div>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                setEditingConnection(null);
                setEditForm(EMPTY_EDIT_FORM);
              }}
            >
              Close
            </button>
          </div>
          {editLoading ? (
            <StatePanel
              title="Loading connection details"
              message="Retrieving business metadata and immutable Azure identifiers."
              tone="loading"
            />
          ) : (
            <div className="card-body">
              <div className="immutable-grid" aria-label="Immutable Azure connection identifiers">
                <div>
                  <span>Connection ID</span>
                  <strong>{editingConnection.connection_id}</strong>
                </div>
                <div>
                  <span>Subscription ID</span>
                  <strong>{editingConnection.subscription_id}</strong>
                </div>
                <div>
                  <span>Tenant ID</span>
                  <strong>{editingConnection.tenant_id}</strong>
                </div>
              </div>

              <h3 className="form-section-title">Connection</h3>
              <div className="form-grid">
                <FormField
                  label="Connection name"
                  value={editForm.name}
                  onChange={(value) => updateEdit("name", value)}
                  required
                />
              </div>

              <h3 className="form-section-title">Business context</h3>
              <div className="form-grid">
                <FormField label="Business service" value={editForm.businessService} onChange={(value) => updateEdit("businessService", value)} />
                <FormField label="Application" value={editForm.application} onChange={(value) => updateEdit("application", value)} />
                <FormField label="Environment" value={editForm.environment} onChange={(value) => updateEdit("environment", value)} />
                <FormField label="Project owner" value={editForm.owner} onChange={(value) => updateEdit("owner", value)} />
                <FormField label="Support team" value={editForm.supportTeam} onChange={(value) => updateEdit("supportTeam", value)} />
                <label className="form-field">
                  <span>Criticality</span>
                  <select className="form-control" value={editForm.criticality} onChange={(event) => updateEdit("criticality", event.target.value)}>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </label>
                <FormField label="Region" value={editForm.region} onChange={(value) => updateEdit("region", value)} />
                <FormField label="Cost center" value={editForm.costCenter} onChange={(value) => updateEdit("costCenter", value)} />
              </div>

              <div className="form-actions">
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    setEditingConnection(null);
                    setEditForm(EMPTY_EDIT_FORM);
                  }}
                >
                  Discard connection edits
                </button>
                <button type="submit" className="button button-primary" disabled={editSubmitting || !editForm.name.trim()}>
                  {editSubmitting ? "Saving…" : "Save changes"}
                </button>
              </div>
            </div>
          )}
        </form>
      )}

      {syncProgress && (
        <div className="callout sync-progress-callout">
          <strong>Syncing {rows.find((row) => row.connection_id === syncProgress.connectionId)?.name ?? syncProgress.connectionId}</strong>
          <span>
            {SYNC_STAGE_LABELS[syncProgress.state.stage ?? ""] ?? syncProgress.state.stage ?? "Working"}
            {typeof syncProgress.state.progress_pct === "number" ? ` — ${syncProgress.state.progress_pct}%` : ""}
            {syncProgress.state.stage_message ? `: ${syncProgress.state.stage_message}` : ""}
          </span>
          <div className="sync-progress-bar" role="progressbar" aria-valuenow={syncProgress.state.progress_pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <div className="sync-progress-bar-fill" style={{ width: `${syncProgress.state.progress_pct ?? 0}%` }} />
          </div>
        </div>
      )}
      {tab === "subscriptions" && (actionMessage && <div className="callout callout-success"><strong>Complete</strong><span>{actionMessage}</span></div>)}
      {tab === "subscriptions" && (actionError && <div className="callout callout-critical"><strong>Action failed</strong><span>{actionError}</span></div>)}

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
                        <Link
                          className="button button-quiet"
                          href={`/connections/fabric?subscription=${encodeURIComponent(connection.subscription_id)}`}
                        >
                          Fabric
                        </Link>
                        <button type="button" className="button button-quiet" onClick={() => startEdit(connection)}>Edit</button>
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
      </section>

      {tab === "fabric-medallion" && !selectedSubscriptionId ? (
        <section id="fabric-medallion-panel" role="tabpanel" aria-labelledby="fabric-medallion-tab" tabIndex={0}>
          <StatePanel 
            title="Select a subscription" 
            message="Choose a subscription from the dropdown above to view its Fabric medallion data, including Bronze, Silver, and Gold layer health, lifecycle status, and governance gaps."
            tone="empty"
          />
        </section>
      ) : (
        <FabricMedallionPanel 
          hidden={tab !== "fabric-medallion"} 
          refreshKey={fabricRefreshKey} 
          scope={scope} 
          subscriptionId={selectedSubscriptionId}
        />
      )}
    </div>
  );
}


function FormField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  autoComplete,
  required,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
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
        placeholder={placeholder}
        type={type}
        autoComplete={autoComplete}
        required={required}
      />
    </label>
  );
}
