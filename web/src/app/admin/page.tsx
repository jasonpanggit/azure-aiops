"use client";

import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { adminApi, type AdminAkvConfig } from "@/lib/services";

const initialValues: AdminAkvConfig = {
  entra_web_client_id: "",
  entra_tenant_id: "",
  entra_api_audience: "",
  entra_api_scope: "",
  entra_grants_json: '{\n  "admin@example.com": [{"role": "admin"}]\n}',
};

/** Entra application configuration. Policy and role settings live on the
 * Governance page's Administration tab -- this page is only for the
 * identity values Key Vault needs to authenticate the deployed app. */
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
        eyebrow="Identity"
        title="Entra application"
        description="Values Key Vault needs to authenticate the deployed app."
      />
      <article className="card">
        <div className="card-header">
          <div>
            <p>Authentication settings for the deployed Entra application.</p>
          </div>
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
    </div>
  );
}
