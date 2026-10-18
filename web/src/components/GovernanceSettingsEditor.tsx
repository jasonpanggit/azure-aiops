"use client";

import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, titleize } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { governanceApi } from "@/lib/services";
import type { EnterpriseSettings } from "@/lib/types";

/** Existing portal-editable policy sections; roles and templates stay read only. */
export const EDITABLE_POLICY_SECTIONS = [
  "onboarding_policy", "architecture_policy", "vulnerability_policy",
  "agent_policy", "retention_policy",
] as const;
type Section = (typeof EDITABLE_POLICY_SECTIONS)[number];
type Draft = Record<string, Record<string, unknown>>;

/** Enterprise-wide policy review with an immutable base and no automatic replay. */
export function GovernanceSettingsEditor({ scope }: { scope: ScopeSelection }) {
  const query = scopeToSearchParams(scope); query.sort();
  return <Workspace key={query.toString()} scope={scope} />;
}

function Workspace({ scope }: { scope: ScopeSelection }) {
  const [readKey, setReadKey] = useState(0);
  return <Read key={readKey} scope={scope} reload={() => setReadKey(value => value + 1)} />;
}

function Read({ scope, reload }: { scope: ScopeSelection; reload: () => void }) {
  const result = useApi(signal => governanceApi.settings(scope, signal), []);
  if (result.loading) return <p role="status">Reading current enterprise-wide policy revision...</p>;
  if (result.error || !result.data?.data) return <div>
    <p role="alert">{result.error?.message ?? "Settings could not be read."} No editable defaults have been substituted.</p>
    <button className="button" onClick={reload}>Reload enterprise settings</button>
  </div>;
  return <Editor initial={result.data.data} reload={reload} />;
}

function Editor({ initial, reload }: { initial: EnterpriseSettings; reload: () => void }) {
  const [base, setBase] = useState(initial);
  const createDraft = (settings: EnterpriseSettings): Draft => Object.fromEntries(
    EDITABLE_POLICY_SECTIONS.map(section => [section, { ...settings[section] }]),
  );
  const [draft, setDraft] = useState(() => createDraft(initial));
  const [reason, setReason] = useState("");
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const changes = EDITABLE_POLICY_SECTIONS.flatMap(section =>
    Object.entries(draft[section]).filter(([key, value]) =>
      JSON.stringify(base[section]?.[key]) !== JSON.stringify(value),
    ).map(([key, value]) => ({ section, key, before: base[section]?.[key], after: value })),
  );
  const valid = changes.every(change => typeof change.before !== "number"
    || (typeof change.after === "number" && Number.isSafeInteger(change.after) && change.after > 0));
  const writable = base.can_write === true && base.persistent === true
    && typeof base.revision === "number" && Number.isSafeInteger(base.revision) && base.revision >= 0
    && base.revision < Number.MAX_SAFE_INTEGER;
  const locked = !writable || busy || blocked;

  function change(section: Section, key: string, value: unknown) {
    setReview(false); setNotice("");
    setDraft(previous => ({ ...previous, [section]: { ...previous[section], [key]: value } }));
  }

  async function save() {
    if (locked || request.current || !review || !valid || !changes.length || !reason.trim() || base.revision === undefined) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice("");
    const patch: Draft = {};
    for (const item of changes) (patch[item.section] ??= {})[item.key] = item.after;
    try {
      const response = await governanceApi.updateSettings({
        expected_revision: base.revision, reason: reason.trim(), changes: patch,
      }, controller.signal);
      if (!controller.signal.aborted) {
        setBase(response.data); setDraft(createDraft(response.data)); setReview(false); setReason("");
        setNotice(`Enterprise-wide settings saved at revision ${response.data.revision}.`);
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        setBlocked(true); setReview(false);
        setError(`${failure instanceof Error ? failure.message : "Save was not confirmed."} Reload and review the current revision before another attempt. No change will be replayed automatically.`);
      }
    } finally {
      if (!controller.signal.aborted) { setBusy(false); request.current = null; }
    }
  }

  return <div className="governance-settings-editor">
    <p><strong>Enterprise-wide settings</strong> affect all subscriptions. Inventory filters do not limit this change. An unrestricted administrator grant is required.</p>
    <p>Reviewed revision: {base.revision ?? "unavailable"}. Last attributed change only, not a complete audit history or proof that every subsystem has applied a policy.</p>
    {base.last_change && <p className="table-wrap">Last change by {base.last_change.actor} at {formatDateTime(base.last_change.recorded_at)}: {base.last_change.reason}</p>}
    {!writable && <p role="status">Read only: durable versioned settings and an unrestricted administrator grant are required.</p>}
    <button className="button" disabled={busy} onClick={reload}>Reload enterprise settings</button>
    <fieldset disabled={locked} className="governance-settings-fields">
      <legend>Policy settings</legend>
      <div className="policy-editor">
        {EDITABLE_POLICY_SECTIONS.map(section => <div key={section} className="policy-editor-group">
          <h3>{titleize(section.replace("_policy", ""))}</h3>
          {Object.entries(draft[section]).map(([key, value]) => <label key={key} className="policy-editor-field">
            <span>{titleize(key)}</span>
            {typeof value === "boolean" ? <input type="checkbox" checked={value} onChange={event => change(section, key, event.target.checked)} />
              : typeof base[section]?.[key] === "number" ? <input type="number" min={1} step={1} value={typeof value === "number" || typeof value === "string" ? value : ""} onChange={event => change(section, key, event.target.value === "" ? "" : Number(event.target.value))} />
                : <span className="table-wrap muted">{Array.isArray(value) ? value.join(", ") : String(value)}</span>}
          </label>)}
        </div>)}
      </div>
      <label className="governance-settings-reason">Change reason
        <textarea maxLength={1200} rows={3} value={reason} onChange={event => { setReason(event.target.value); setReview(false); }} />
      </label>
    </fieldset>
    {!valid && <p role="alert">Changed numeric settings must be positive whole numbers.</p>}
    {review && <div className="governance-settings-review">
      <h3>Review enterprise-wide change</h3>
      <p>Compare the current revision with your proposed values before confirming.</p>
      <div className="table-scroll" role="region" aria-label="Policy change comparison" tabIndex={0}>
        <table className="operations-table"><thead><tr><th>Setting</th><th>Before</th><th>Proposed</th></tr></thead>
          <tbody>{changes.map(item => <tr key={`${item.section}.${item.key}`}>
            <th scope="row">{titleize(item.section)}<br />{titleize(item.key)}</th>
            <td>{JSON.stringify(item.before)}</td><td>{JSON.stringify(item.after)}</td>
          </tr>)}</tbody></table>
      </div>
      <p className="table-wrap"><strong>Reason:</strong> {reason.trim()}</p>
    </div>}
    <div className="policy-editor-actions">
      {review ? <><button className="button" disabled={locked} onClick={() => void save()}>{busy ? "Saving..." : "Confirm enterprise-wide change"}</button>
        <button className="button" disabled={busy} onClick={() => setReview(false)}>Back to editing</button></>
        : <button className="button" disabled={locked || !changes.length || !reason.trim() || !valid} onClick={() => setReview(true)}>Review {changes.length} {changes.length === 1 ? "change" : "changes"}</button>}
    </div>
    {busy && <p role="status">Saving the reviewed enterprise-wide revision...</p>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
