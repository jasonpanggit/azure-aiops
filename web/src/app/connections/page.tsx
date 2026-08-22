"use client";

import { type FormEvent, useEffect, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, relativeTime } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { connectionsApi } from "@/lib/services";
import type { BusinessMetadata, ConnectionCreateRequest, SubscriptionConnection } from "@/lib/types";

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
  const connections = useApi(() => connectionsApi.list(scope), [scope, refreshKey]);
  const rows = connections.data?.data ?? [];
  const healthy = rows.filter((connection) => connection.health_status === "healthy").length;
  const stale = rows.filter((connection) => connection.health_status === "stale").length;
  const failed = rows.filter((connection) => ["failed", "unhealthy"].includes(connection.health_status)).length;
  const unmapped = rows.filter((connection) => !connection.business_service || !connection.environment).length;

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
      await connectionsApi.create(payload);
      setActionMessage("Subscription connection created. Validate access, then run the initial sync.");
      setForm(EMPTY_FORM);
      setShowOnboarding(false);
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to create subscription connection.");
    } finally {
      setSubmitting(false);
    }
  }

  async function runAction(connection: SubscriptionConnection, action: "validate" | "sync") {
    setActionError("");
    setActionMessage("");
    setRunningAction(`${action}:${connection.connection_id}`);
    try {
      if (action === "validate") {
        const result = await connectionsApi.validate(connection.connection_id);
        if (result.data.status.toLowerCase() === "failed") {
          setRefreshKey((value) => value + 1);
          throw new Error("Validation failed");
        }
        setActionMessage(`Validation completed for ${connection.name}.`);
      } else {
        const result = await connectionsApi.sync(connection.connection_id, "initial");
        if (result.data.status.toLowerCase() === "failed") {
          setRefreshKey((value) => value + 1);
          throw new Error(String(result.data.sync_state.message ?? result.data.message ?? "Sync failed"));
        }
        setActionMessage(
          `Sync completed for ${connection.name}: ${result.data.record_count ?? 0} records discovered.`,
        );
      }
      setRefreshKey((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : `Unable to ${action} connection.`);
    } finally {
      setRunningAction("");
    }
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
        description="Operational coverage, freshness, credential health, and business context for every onboarded Azure subscription."
        actions={
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
        }
      />

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

      {showOnboarding && (
        <form className="card onboarding-form" onSubmit={onboard}>
          <div className="card-header">
            <div><h2>Onboard an Azure subscription</h2><p>Enter the service principal secret once. The API stores it in Azure Key Vault and Hermes keeps only the Key Vault reference.</p></div>
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
              <button type="button" className="button" onClick={() => setShowOnboarding(false)}>Cancel</button>
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
                  Cancel
                </button>
                <button type="submit" className="button button-primary" disabled={editSubmitting || !editForm.name.trim()}>
                  {editSubmitting ? "Saving…" : "Save changes"}
                </button>
              </div>
            </div>
          )}
        </form>
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
          <div className="table-scroll">
            <table className="operations-table">
              <thead><tr><th>Connection</th><th>Business context</th><th>Health</th><th>Sync</th><th>Last successful sync</th><th>Actions</th></tr></thead>
              <tbody>
                {rows.map((connection) => (
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
                        <button type="button" className="button button-quiet" onClick={() => startEdit(connection)}>Edit</button>
                        <button
                          type="button"
                          className="button button-quiet"
                          disabled={Boolean(runningAction)}
                          onClick={() => runAction(connection, "validate")}
                        >
                          {runningAction === `validate:${connection.connection_id}` ? "Validating…" : "Validate"}
                        </button>
                        <button
                          type="button"
                          className="button button-quiet"
                          disabled={Boolean(runningAction)}
                          onClick={() => runAction(connection, "sync")}
                        >
                          {runningAction === `sync:${connection.connection_id}` ? "Syncing…" : "Sync"}
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
        </div>
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
