"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, relativeTime } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, fabricMedallionApi } from "@/lib/services";
import type { BusinessMetadata, ConnectionCreateRequest, Envelope, FabricCapabilities, FabricDataset, FabricGovernanceSummary, FabricIngestionRun, FabricManifestEntry, FabricLayerCounts, SubscriptionConnection, SyncState } from "@/lib/types";

const SYNC_POLL_INTERVAL_MS = 1500;
// Discovery + merge + ontology + Fabric publish can take well past 10 minutes
// for large subscriptions (observed ~16 min for ~12.7k records); the poll
// window must comfortably exceed that so the UI doesn't report a false
// timeout while the background sync is still healthy and progressing.
const SYNC_POLL_TIMEOUT_MS = 20 * 60 * 1000;

type FabricLayerKey = "bronze" | "silver" | "gold";

const FABRIC_LAYER_KEYS: FabricLayerKey[] = ["bronze", "silver", "gold"];

const FABRIC_LAYER_LABELS: Record<FabricLayerKey, string> = {
  bronze: "Bronze",
  silver: "Silver",
  gold: "Gold",
};

const FABRIC_LAYER_DESCRIPTIONS: Record<FabricLayerKey, string> = {
  bronze: "Raw source-aligned datasets published from subscription ingestion.",
  silver: "Normalized operational datasets with quality and freshness objectives.",
  gold: "Curated products used by semantic models, Data Agent grounding, and operator workflows.",
};

const EMPTY_FABRIC_COUNTS: Record<FabricLayerKey, FabricLayerCounts> = {
  bronze: { healthy: 0, total: 0 },
  silver: { healthy: 0, total: 0 },
  gold: { healthy: 0, total: 0 },
};

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
            <button
              type="button"
              className="button button-primary"
              onClick={() => setFabricRefreshKey((value) => value + 1)}
            >
              Refresh Fabric health
            </button>
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
      {actionMessage && <div className="callout callout-success"><strong>Complete</strong><span>{actionMessage}</span></div>}
      {actionError && <div className="callout callout-critical"><strong>Action failed</strong><span>{actionError}</span></div>}

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

      <FabricMedallionPanel hidden={tab !== "fabric-medallion"} refreshKey={fabricRefreshKey} />
    </div>
  );
}

function FabricMedallionPanel({ hidden, refreshKey }: { hidden: boolean; refreshKey: number }) {
  const layerSummary = useApi(() => fabricMedallionApi.layers(), [refreshKey]);
  const manifest = useApi(() => fabricMedallionApi.manifest(), [refreshKey]);
  const governance = useApi(() => fabricMedallionApi.governance(), [refreshKey]);
  const ingestionHistory = useApi(() => fabricMedallionApi.ingestionHistory(), [refreshKey]);
  const capabilities = useApi(() => fabricMedallionApi.capabilities(), [refreshKey]);
  const counts = layerSummary.data?.data.layers ?? EMPTY_FABRIC_COUNTS;
  const tableNames = useMemo(() => tableNamesByLayer(capabilities.data?.data), [capabilities.data]);
  const totalTables = FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].total, 0);
  const healthyTables = FABRIC_LAYER_KEYS.reduce((total, layer) => total + counts[layer].healthy, 0);

  return (
    <section
      id="fabric-medallion-panel"
      role="tabpanel"
      aria-labelledby="fabric-medallion-tab"
      tabIndex={0}
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
  refreshKey,
}: {
  layer: FabricLayerKey;
  tableNames: string[];
  counts: FabricLayerCounts;
  refreshKey: number;
}) {
  const datasets = useApi(() => loadLayerDatasets(tableNames), [refreshKey, tableNames.join("|")]);
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
            <div className="table-scroll">
              <table className="operations-table">
                <thead><tr><th>Dataset</th><th>Status</th><th>Freshness</th><th>Lineage</th></tr></thead>
                <tbody>
                  {paging.pageRows.map((dataset) => (
                    <tr key={dataset.table_name}>
                      <td><strong>{dataset.table_name}</strong><div className="table-secondary">{datasetRowsCopy(dataset)} · observed {relativeTime(dataset.observed_at)}</div></td>
                      <td><StatusBadge label={datasetStatusLabel(dataset.availability)} tone={statusTone(dataset.availability)} /></td>
                      <td><StatusBadge label={dataset.freshness || "unknown"} tone={statusTone(dataset.freshness)} /><div className="table-secondary">watermark {dataset.watermark || "unknown"}</div></td>
                      <td><span title={dataset.lineage_ref}>{dataset.lineage_ref || "No lineage reference"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TablePagination total={paging.total} pageRows={paging.pageRows.length} page={paging.page} onPageChange={paging.setPage} pageSize={paging.pageSize} onPageSizeChange={paging.setPageSize} label={`${layer} datasets`} />
          </>
        )}
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
          <div className="table-scroll">
            <table className="operations-table">
              <thead><tr><th>Projection</th><th>Disposition</th><th>Compatibility</th><th>Updated</th></tr></thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.projection_name}>
                    <td><strong>{entry.projection_name}</strong><div className="table-secondary">{entry.retired_reason || "Lifecycle tracked in publication manifest"}</div></td>
                    <td><StatusBadge label={datasetStatusLabel(entry.disposition)} tone={statusTone(entry.disposition)} /></td>
                    <td>{entry.compatibility_version || "Not versioned"}</td>
                    <td>{formatDateTime(entry.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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

async function loadLayerDatasets(tableNames: string[]): Promise<FabricDataset[]> {
  if (tableNames.length === 0) return [];
  const results = await Promise.allSettled(tableNames.map((tableName) => fabricMedallionApi.dataset(tableName)));
  const datasets: FabricDataset[] = [];
  for (const result of results) {
    if (result.status === "rejected") {
      throw result.reason instanceof Error ? result.reason : new Error(String(result.reason));
    }
    datasets.push(result.value.data);
  }
  return datasets;
}

function tableNamesByLayer(capabilities?: FabricCapabilities): Record<FabricLayerKey, string[]> {
  const layers: Record<FabricLayerKey, string[]> = { bronze: [], silver: [], gold: [] };
  for (const dataset of capabilities?.lineage.datasets ?? []) {
    const layer = FABRIC_LAYER_KEYS.find((key) => dataset.table_name.startsWith(`${key}_`));
    if (layer) layers[layer].push(dataset.table_name);
  }
  return layers;
}

function formatHealthCount(counts: FabricLayerCounts): string {
  return `${counts.healthy}/${counts.total}`;
}

function fabricMetricTone(counts: FabricLayerCounts): "default" | "critical" | "warning" | "success" {
  if (counts.total === 0) return "default";
  if (counts.healthy === counts.total) return "success";
  if (counts.healthy === 0) return "critical";
  return "warning";
}

function datasetStatusLabel(value?: string | null): string {
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
