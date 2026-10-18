"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatDateTime } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { situationsApi } from "@/lib/services";
import type { SituationResponseDeadline as Deadline } from "@/lib/types";

/** Explicit administrator commitment; never provider SLA evidence or execution authority. */
export function SituationResponseDeadline({ situationId, evidenceRunId, scope }: {
  situationId: string; evidenceRunId: string; scope: ScopeSelection;
}) {
  const query = scopeToSearchParams(scope); query.sort();
  return <Workspace key={`${query}:${situationId}:${evidenceRunId}`} situationId={situationId} evidenceRunId={evidenceRunId} scope={scope} />;
}

function Workspace(props: { situationId: string; evidenceRunId: string; scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  return <section className="card situation-response-deadline" aria-label="Declared response review">
    <div className="card-header"><div><h2>Declared response review</h2><p>A run-bound administrator commitment, separate from observed age and contractual SLA evidence.</p></div>
      <button className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "Close response review" : "Open response review"}</button></div>
    {open && <Panel {...props} />}
  </section>;
}

function Panel({ situationId, evidenceRunId, scope }: { situationId: string; evidenceRunId: string; scope: ScopeSelection }) {
  const [state, setState] = useState<Deadline | null>(null);
  const [due, setDue] = useState("");
  const [reason, setReason] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setState(null); setError(""); setNotice(""); setConfirmClear(false); setDue(""); setReason("");
    try {
      const response = await situationsApi.deadline(situationId, scope, controller.signal);
      if (!controller.signal.aborted) setState(response.data);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Response review could not be read.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }, [situationId, scope]);
  useEffect(() => { void reload(); return () => { request.current?.abort(); request.current = null; }; }, [reload]);

  async function save(clear: boolean) {
    if (!state?.can_write || state.policy_revision === null || !evidenceRunId || request.current) return;
    if (!reason.trim()) { setError("Enter a reason for this explicit declaration or removal."); return; }
    // A literal UTC input avoids interpreting local browser wall time as source time.
    const parsed = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?Z$/.test(due) ? Date.parse(due) : NaN;
    if (!clear && (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 16) !== due.slice(0, 16))) { setError("Enter an explicit UTC deadline, for example 2026-10-20T12:30:00Z."); return; }
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice(""); setConfirmClear(false);
    try {
      const response = await situationsApi.declareDeadline(situationId, scope, {
        expected_revision: state.policy_revision, evidence_run_id: evidenceRunId,
        due_at: clear ? null : new Date(parsed).toISOString(), reason: reason.trim(),
      }, controller.signal);
      if (!controller.signal.aborted) {
        setState(response.data); setDue(""); setReason("");
        setNotice(clear ? "Response-review declaration removed. No source case was changed." : "Response-review declaration saved. No completed response, SLA certification or execution approval is asserted.");
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        setState(null);
        setError(`${failure instanceof Error ? failure.message : "Write was not confirmed."} Outcome is unconfirmed; reload before explicitly retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  return <div className="card-body">
    <p>Shared only within this exact effective scope. No severity-based target, inherited hours or automatic acknowledgement is assumed. Up to 200 current declarations / 512 KiB per scope, with explicit removal rather than silent eviction. Last declaration/editor only, not a complete edit history.</p>
    <button className="button" disabled={busy} onClick={() => void reload()}>Reload response review</button>
    {busy && <p role="status">Response review request in progress...</p>}{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {state && <>
      <p><strong>Response-review state: {state.state}</strong>. {state.reason}</p>
      <p>Evaluated at {formatDateTime(state.evaluated_at)}; declaration collection revision {state.policy_revision ?? "unavailable"}. This is a read-time comparison, not a live countdown.</p>
      {state.declaration ? <dl>
        <div><dt>Declared deadline</dt><dd>{formatDateTime(state.declaration.due_at)} · <code>{state.declaration.due_at}</code></dd></div>
        <div><dt>Declared by</dt><dd>{state.declaration.actor} at {formatDateTime(state.declaration.declared_at)} · revision {state.declaration.revision}</dd></div>
        <div><dt>Reviewed evidence run</dt><dd><code>{state.declaration.evidence_run_id}</code></dd></div>
        <div><dt>Administrator reason</dt><dd>{state.declaration.reason}</dd></div>
      </dl> : <p>No response-review deadline is declared here. Unknown is not on-time or overdue.</p>}
      <p>{state.interpretation} Closed/resolved source state does not prove when a response occurred or historical target attainment. A changed evidence run invalidates the due/overdue inference until explicit review.</p>
      {state.can_write ? <form onSubmit={event => { event.preventDefault(); void save(false); }}>
        <fieldset disabled={busy || !evidenceRunId}><legend>Declare a response-review deadline</legend>
          <label className="form-field"><span>Deadline (UTC ISO timestamp)</span><input className="form-control" value={due} maxLength={40} placeholder="YYYY-MM-DDTHH:mm:ssZ" onChange={event => setDue(event.target.value)} /></label>
          <label className="form-field"><span>Declaration or removal reason</span><textarea className="form-control" rows={3} maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label>
          <p>Bound to currently displayed evidence run <code>{evidenceRunId || "unavailable"}</code>. Past deadlines are allowed as explicit commitments; start age and severity never choose the date. Do not include secrets.</p>
          <div className="situation-deadline-controls"><button className="button button-primary" disabled={!due || !reason.trim()} type="submit">Save response deadline</button>
            <button className="button" type="button" disabled={!state.declaration || !reason.trim()} onClick={() => setConfirmClear(true)}>Remove response deadline</button></div>
        </fieldset>
      </form> : <p>Read-only. Administrator permission across the complete selected scope and available storage are required to change a declaration.</p>}
      {confirmClear && <div role="group" aria-label="Confirm response deadline removal"><p>Remove the declaration at reviewed collection revision {state.policy_revision}? The source case is unchanged.</p>
        <button className="button" disabled={busy} onClick={() => void save(true)}>Confirm response deadline removal</button><button className="button" disabled={busy} onClick={() => setConfirmClear(false)}>Cancel removal</button></div>}
    </>}
    <p>Queue/detail source snapshots and handoff exports each carry their own evaluated deadline observation. Reload them after a declaration change. Source-only Copilot does not receive these administrator annotations; do not ask it to certify response timing.</p>
  </div>;
}
