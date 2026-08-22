"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { adminApi, type AdminAkvConfig } from "@/lib/services";

const initialValues: AdminAkvConfig = {
  entra_web_client_id: "",
  entra_tenant_id: "",
  entra_api_audience: "",
  entra_api_scope: "",
  entra_grants_json: '{\n  "admin@example.com": [{"role": "admin"}]\n}',
};

/** Governance and administrator configuration page. */
export default function AdministrationPage() {
  const [values, setValues] = useState(initialValues);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const result = await adminApi.saveAkvConfig(values);
      setMessage(`Saved ${result.data.saved.length} settings to Key Vault.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Governance"
        title="Administration"
        description="Manage trust, access, operating context, and approval boundaries behind workbench decisions."
      />
      <div className="admin-grid">
        <article className="card">
          <div className="card-header">
            <div><h2>Identity & access</h2><p>Authentication settings for the deployed Entra application.</p></div>
            <StatusBadge label="Admin only" tone="warning" />
          </div>
          <form className="card-body admin-form" onSubmit={save}>
            <label>Web client ID<input required value={values.entra_web_client_id} onChange={(e) => setValues({ ...values, entra_web_client_id: e.target.value })} /></label>
            <label>Tenant ID<input required value={values.entra_tenant_id} onChange={(e) => setValues({ ...values, entra_tenant_id: e.target.value })} /></label>
            <label>API audience<input required value={values.entra_api_audience} onChange={(e) => setValues({ ...values, entra_api_audience: e.target.value })} /></label>
            <label>API scope<input required value={values.entra_api_scope} onChange={(e) => setValues({ ...values, entra_api_scope: e.target.value })} /></label>
            <label>Gateway grants JSON<textarea required rows={5} value={values.entra_grants_json} onChange={(e) => setValues({ ...values, entra_grants_json: e.target.value })} /></label>
            <p className="muted">Values are written server-side with the app managed identity. Secret values are never returned.</p>
            <button className="button" type="submit" disabled={saving}>{saving ? "Saving..." : "Save to Key Vault"}</button>
            {message && <p role="status">{message}</p>}
          </form>
        </article>
        <article className="card">
          <div className="card-header"><div><h2>Data & integrations</h2><p>Subscription coverage, credentials, freshness, and business metadata.</p></div><StatusBadge label="Operator managed" tone="info" /></div>
          <div className="card-body"><Link className="button" href="/connections">Manage connections</Link></div>
        </article>
        <article className="card">
          <div className="card-header"><div><h2>Decision policy</h2><p>Situation ranking, evidence confidence, suppression, and escalation policy.</p></div><StatusBadge label="Advisory" tone="warning" /></div>
          <div className="card-body"><p className="muted">Recommendations remain read-only until an authorized operator creates and approves a governed action plan.</p></div>
        </article>
        <article className="card">
          <div className="card-header"><div><h2>Network design intent</h2><p>Approved hub-spoke patterns and mandatory inspection policy.</p></div><StatusBadge label="Review required" tone="warning" /></div>
          <div className="card-body"><Link className="button" href="/network">Review topology evidence</Link></div>
        </article>
      </div>
    </div>
  );
}
