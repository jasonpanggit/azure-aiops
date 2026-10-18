"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { formatDateTime, titleize } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import type { RemediationWorkflow } from "@/lib/services";
import { controlRollout, createRollout, readRollouts, type RemediationRollout, type RolloutCollection, type RolloutTarget } from "@/lib/remediation-rollouts";

type RolloutWorkflow = {
  plan: Pick<RemediationWorkflow["plan"], "plan_id">;
  action: Pick<RemediationWorkflow["action"], "can_operate">;
  preview: Pick<NonNullable<RemediationWorkflow["preview"]>, "execution_snapshot"> | null;
};

/** On-demand explicit rollout planning; no scheduler or automatic provider actions. */
export function RemediationRollouts({ scope, workflow, onChanged }: {
  scope: ScopeSelection; workflow: RolloutWorkflow | null; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const query = scopeToSearchParams(scope); query.sort();
  return <section className="card remediation-rollouts" aria-label="Governed rollouts">
    <div className="card-header"><div><h2>Governed rollouts</h2><p>Exact targets, explicit waves and backend-enforced submission windows.</p></div>
      <button className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "Close rollout planning" : "Open rollout planning"}</button></div>
    {open && <Workspace key={query.toString()} scope={scope} workflow={workflow} onChanged={onChanged} />}
  </section>;
}

function Workspace({ scope, workflow, onChanged }: {
  scope: ScopeSelection; workflow: RolloutWorkflow | null; onChanged: () => void;
}) {
  const [collection, setCollection] = useState<RolloutCollection | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [title, setTitle] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reconciled, setReconciled] = useState(true);
  const [targets, setTargets] = useState<Array<RolloutTarget & { target_id: string }>>([]);
  const [reviewed, setReviewed] = useState(false);
  const [control, setControl] = useState<{ row: RemediationRollout; action: "open" | "pause" | "resume" | "retire"; wave: number } | null>(null);
  const mounted = useRef(false);
  const generation = useRef(0);
  async function reload() {
    const request = ++generation.current;
    setBusy(true); setError(""); setControl(null); setReviewed(false);
    try {
      const response = await readRollouts(scope);
      if (!mounted.current || generation.current !== request) return;
      setCollection(response.data); setUncertain(false);
    } catch (failure) {
      if (mounted.current && generation.current === request) {
        setCollection(null); setError(failure instanceof Error ? failure.message : "Rollout terms could not be read.");
      }
    } finally {
      if (mounted.current && generation.current === request) setBusy(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => { mounted.current = false; generation.current += 1; };
    // Scope changes remount this exact-scope workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  async function mutate(operation: () => Promise<unknown>) {
    if (busy || uncertain) return;
    const request = ++generation.current;
    setBusy(true); setError("");
    let acknowledged = false;
    try {
      await operation(); acknowledged = true;
      if (!mounted.current || generation.current !== request) return;
      setTargets([]); setControl(null); setReviewed(false);
      onChanged();
      const response = await readRollouts(scope);
      if (!mounted.current || generation.current !== request) return;
      setCollection(response.data);
    } catch (failure) {
      if (!mounted.current || generation.current !== request) return;
      setUncertain(true);
      setError(`${acknowledged ? "Change saved, but follow-up read failed." : "Change not confirmed."} ${failure instanceof Error ? failure.message : "Rollout request failed."} Reload stored rollouts before another write; do not replay the request.`);
    } finally {
      if (mounted.current && generation.current === request) setBusy(false);
    }
  }
  const snapshot = workflow?.preview?.execution_snapshot;
  const eligible = Boolean(workflow?.action.can_operate && snapshot && !snapshot.rollout);
  const blocked = busy || uncertain || !collection;
  const query = scopeToSearchParams(scope);
  function draftChanged() { setReviewed(false); setControl(null); }
  return <div className="card-body">
    <p>Open one wave explicitly, then approve and run each target through the existing workflow. Opening a wave never submits its targets. The window gates submissions and retries, not completion time; pause does not cancel provider work already submitted.</p>
    <button className="button" disabled={busy} onClick={() => void reload()}>Reload stored rollouts</button>
    {busy && <p role="status">Reading or updating stored rollout terms...</p>}
    {error && <p role="alert">{error}</p>}
    {collection && <p>{collection.rollouts.length} authorized retained rollout{collection.rollouts.length === 1 ? "" : "s"}. Collection revision {collection.revision}.</p>}
    <details><summary>Create an exact-target rollout</summary>
      <p>Immutable terms: at most 20 distinct targets in 5 contiguous waves. Creating terms invalidates prior approvals. Retire unstarted or provider-succeeded terms explicitly to declare a new reviewed rollout; active, failed or cancelled history cannot be reassigned. Retirement never restores old approval authority.</p>
      <fieldset disabled={blocked} onChange={draftChanged}><legend>Submission window and stop conditions</legend>
        <label className="form-field">Rollout title<input className="form-control" maxLength={120} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <label className="form-field">Window starts (local time)<input className="form-control" type="datetime-local" value={start} onChange={event => setStart(event.target.value)} /></label>
        <label className="form-field">Window ends (local time)<input className="form-control" type="datetime-local" value={end} onChange={event => setEnd(event.target.value)} /></label>
        <p>Your browser converts these local times to explicit UTC timestamps on save. Maximum window: 24 hours. No scheduler or reminder is configured.</p>
        <p>Always enforced: failures/cancellations stop new targets; every prior-wave target requires recorded provider success. Explicit bounded retries may recover failed targets, but new work stays stopped until recovery verifies. Unknown or ambiguous outcomes are not success.</p>
        <label><input type="checkbox" checked={reconciled} onChange={event => setReconciled(event.target.checked)} /> Also require confirmed refreshed evidence before a later wave</label>
      </fieldset>
      <button className="button" disabled={blocked || !eligible || targets.length >= 20 || targets.some(row => row.plan_id === workflow?.plan.plan_id)} onClick={() => {
        if (!workflow || !snapshot || snapshot.rollout) return;
        setTargets(rows => [...rows, { plan_id: workflow.plan.plan_id, preview_snapshot_hash: snapshot.snapshot_hash, selected_patch_ids: [...snapshot.patch_ids], target_id: snapshot.target_id, wave: 1 }]); draftChanged();
      }}>Add current exact preview</button>
      {!eligible && <p>Choose a supported, unbound executable preview with operator capability to add a target.</p>}
      <ol className="remediation-rollout-targets">{targets.map((row, index) => <li key={row.plan_id}>
        <code>{row.target_id}</code><p>Plan <code>{row.plan_id}</code>; reviewed snapshot <code>{row.preview_snapshot_hash}</code>.</p>
        <p>Exact update selection: {row.selected_patch_ids.length ? row.selected_patch_ids.join(", ") : "No update IDs; configuration action"}.</p>
        <label>Wave for target {index + 1}<select className="form-control" disabled={blocked} value={row.wave} onChange={event => { setTargets(rows => rows.map(item => item.plan_id === row.plan_id ? { ...item, wave: Number(event.target.value) } : item)); draftChanged(); }}>{[1, 2, 3, 4, 5].map(wave => <option key={wave}>{wave}</option>)}</select></label>
        <button className="button" disabled={blocked} onClick={() => { setTargets(rows => rows.filter(item => item.plan_id !== row.plan_id)); draftChanged(); }}>Remove target {index + 1}</button>
      </li>)}</ol>
      <label><input type="checkbox" checked={reviewed} disabled={blocked} onChange={event => setReviewed(event.target.checked)} /> I reviewed these exact targets, wave order, UTC conversion and immutable stop conditions</label>
      <div><button className="button" disabled={blocked || !reviewed || !title.trim() || !start || !end || !targets.length} onClick={() => {
        const begins = new Date(start), ends = new Date(end);
        if (!Number.isFinite(begins.getTime()) || !Number.isFinite(ends.getTime()) || ends <= begins) { setError("Choose a valid increasing submission window."); return; }
        if (!collection) return;
        void mutate(() => createRollout(scope, { title: title.trim(), window_start: begins.toISOString(), window_end: ends.toISOString(), require_reconciled_evidence: reconciled, targets: targets.map(({ plan_id, preview_snapshot_hash, selected_patch_ids, wave }) => ({ plan_id, preview_snapshot_hash, selected_patch_ids, wave })), expected_revision: collection.revision }));
      }}>Save immutable rollout terms</button></div>
    </details>
    {collection?.rollouts.map(row => <article key={row.rollout_id} className="remediation-rollout-record">
      <h3>{row.terms.title}</h3>
      <p>{row.retired ? "Terms retired; declare and approve replacement terms" : row.paused ? "Admissions paused" : "Admissions not paused"}; opened wave {row.opened_wave || "none"}. Window {formatDateTime(row.terms.window_start)} to {formatDateTime(row.terms.window_end)}.</p>
      <details><summary>Exact terms and stored target progress</summary>
        <p>Recorded by {row.created_by} at {formatDateTime(row.created_at)}. Terms <code>{row.terms_hash}</code>; revision {row.revision}. Last control by {row.updated_by} at {formatDateTime(row.updated_at)}.</p>
        <p>Prior-wave refreshed evidence: {row.terms.require_reconciled_evidence ? "Required" : "Not required; provider success still required"}.</p>
        <p>Exact aware submission window: <code>{row.terms.window_start}</code> to <code>{row.terms.window_end}</code>.</p>
        <ol className="remediation-rollout-targets">{row.targets.map(target => {
          const resume = new URLSearchParams(query); resume.set("resource_key", target.target_id); resume.set("plan_id", target.plan_id); resume.set("step", "review");
          const member = row.terms.members.find(item => item.plan_id === target.plan_id);
          return <li key={target.plan_id}><code>{target.target_id}</code><p>Wave {target.wave}: {titleize(target.status)}. {target.admission_reason ? titleize(target.admission_reason) : "No admission blocker at this read; approval and execution gates still apply."}</p>
            <p>Action version <code>{member?.action_version}</code>; original exact action hash <code>{member?.snapshot_hash}</code>.</p>
            <p>Exact update selection: {member?.patch_ids.length ? member.patch_ids.join(", ") : "No update IDs; configuration action"}.</p>
            <Link className="button" href={`/remediation?${resume.toString()}`}>Review target workflow</Link>{target.execution_id && <p>Recorded execution <code>{target.execution_id}</code></p>}</li>;
        })}</ol>
      </details>
      {row.can_manage && !row.retired && <div className="remediation-rollout-controls">
        <button className="button" disabled={blocked || row.paused || row.opened_wave >= Math.max(...row.terms.members.map(member => member.wave))} onClick={() => setControl({ row, action: "open", wave: row.opened_wave + 1 })}>{row.opened_wave >= Math.max(...row.terms.members.map(member => member.wave)) ? "All declared waves opened" : `Review opening wave ${row.opened_wave + 1}`}</button>
        <button className="button" disabled={blocked} onClick={() => setControl({ row, action: row.paused ? "resume" : "pause", wave: 0 })}>{row.paused ? "Review resuming admissions" : "Review pausing admissions"}</button>
        {row.targets.every(target => !target.execution_id || target.status === "succeeded") && <button className="button" disabled={blocked} onClick={() => setControl({ row, action: "retire", wave: 0 })}>Review retiring settled terms</button>}
      </div>}
    </article>)}
    {control && <div className="callout" role="region" aria-label="Review rollout admission change">
      <p>{control.action === "open" ? `Open wave ${control.wave}` : control.action === "retire" ? "Retire unstarted or provider-succeeded immutable terms" : titleize(control.action) + " admissions"} for {control.row.terms.title}, revision {control.row.revision}? No target is submitted by this action. Existing provider work is not cancelled. {control.action === "retire" && "Terms and execution evidence remain retained; replacement declarations and new approvals are required before running any target."}</p>
      <button className="button" disabled={blocked} onClick={() => void mutate(() => controlRollout(scope, control.row.rollout_id, { action: control.action, wave: control.wave, expected_revision: control.row.revision }))}>Confirm admission change</button>
      <button className="button" disabled={busy} onClick={() => setControl(null)}>Keep current admission</button>
    </div>}
    <p>Stored progress is not live fleet health, a canary/rollback result or whole-estate clearance. Refresh explicitly. The server reapplies current grants and gates each target; deferred container execution remains unavailable.</p>
  </div>;
}
