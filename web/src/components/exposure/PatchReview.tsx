"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { vulnerabilityApi } from "@/lib/services";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import type { ExposureQueryState } from "@/lib/exposure-query-state";
import type { Envelope, ExposureFinding, PatchReviewHistory } from "@/lib/types";

function validate(result: Envelope<PatchReviewHistory>, query: ExposureQueryState) {
  const data = result.data;
  const agrees = (scope: Record<string, string[]>) => SCOPE_DIMENSIONS.every(dimension =>
    JSON.stringify([...(scope[dimension] ?? [])].sort()) === JSON.stringify([...(query.scope[dimension] ?? [])].sort()));
  if (!agrees(result.scope) || !agrees(data.scope)) throw new Error("Patch review scope does not match.");
  if (data.schema_version !== 1 || !data.actor || data.revision !== data.batches.length || data.revision > 20
    || new Set(data.batches.map(row => row.batch_id)).size !== data.revision
    || data.batches.some(row => !/^prb-[a-f0-9]{32}$/.test(row.batch_id) || !row.generation
      || !Number.isFinite(Date.parse(row.captured_at)) || !row.note.trim() || !row.findings.length || row.findings.length > 25
      || new Set(row.findings.map(finding => finding.exposure_id)).size !== row.findings.length
      || row.findings.some(finding => !finding.exposure_id || !finding.target_id || !finding.weakness_id
        || !["server", "container_image"].includes(finding.target_kind)))) throw new Error("Patch review history is inconsistent.");
  return data;
}

/** Explicit bounded personal review snapshots; no executable plans or approval transitions. */
export function PatchReview({ query, rows, ready, imageOwner = false }: { query: ExposureQueryState; rows: ExposureFinding[]; ready: boolean; imageOwner?: boolean }) {
  const [history, setHistory] = useState<PatchReviewHistory | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [owner, setOwner] = useState(""), [note, setNote] = useState("");
  const [busy, setBusy] = useState(true), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const active = useRef(false), requestId = useRef(0);
  const apply = useCallback((result: Envelope<PatchReviewHistory>) => setHistory(validate(result, query)), [query]);
  useEffect(() => {
    active.current = true;
    const id = ++requestId.current, controller = new AbortController();
    vulnerabilityApi.patchReviews(query.scope, controller.signal).then(result => {
      if (active.current && id === requestId.current) apply(result);
    }).catch((reason: unknown) => {
      if (active.current && id === requestId.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Patch reviews unavailable.");
    }).finally(() => { if (active.current && id === requestId.current) setBusy(false); });
    return () => { active.current = false; controller.abort(); };
  }, [query.scope, apply]);
  async function load(save: boolean) {
    if (busy || (save && (!ready || !history || uncertain || !selected.length || !note.trim() || history.revision >= 20))) return;
    const id = ++requestId.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = save
        ? await vulnerabilityApi.createPatchReview(query, history!.revision, selected, owner, note)
        : await vulnerabilityApi.patchReviews(query.scope);
      if (!active.current || id !== requestId.current) return;
      const data = validate(result, query), batch = data.batches.at(-1);
      if (save && (data.revision !== history!.revision + 1
        || JSON.stringify(data.batches.slice(0, -1)) !== JSON.stringify(history!.batches)
        || batch?.generation !== query.generation || batch?.owner !== owner || batch?.note !== note
        || JSON.stringify(batch?.findings.map(row => row.exposure_id)) !== JSON.stringify(selected))) {
        throw new Error("Patch review response does not preserve the reviewed history and exact selection.");
      }
      setHistory(data); setUncertain(false);
      if (save) { setSelected([]); setNote(""); }
      setNotice(save ? "Review batch retained. No patch was executed or approved." : "Saved batches reloaded. Inspect revision before saving again.");
    } catch (reason) {
      if (!active.current || id !== requestId.current) return;
      setError(reason instanceof Error ? reason.message : "Patch review outcome unconfirmed."); setUncertain(true);
    } finally { if (active.current && id === requestId.current) setBusy(false); }
  }
  return <section className="card queue-card exposure-recovery" aria-label={imageOwner ? "Review-only image owner batches" : "Review-only patch batches"}>
    <div className="card-header"><div><h2>{imageOwner ? "Prepare an image owner review" : "Prepare a review-only batch"}</h2>
      <p>Select up to 25 findings from this page for a personal immutable review snapshot.</p></div></div>
    <div className="card-body">
      <p>The server reauthorizes and reads this exact generation and query page again. Selection is not an execution plan, approval, maintenance schedule or verified fix.
        Owner is a declaration, not a delivered assignment. Up to 20 batches and 256 KiB are retained without automatic eviction.</p>
      {imageOwner && <p>This is the same private Exposure review history used by Patch priorities. Previous batches can include server findings; inspect each retained target kind and identity before review.</p>}
      <button type="button" className="button" disabled={busy} onClick={() => void load(false)}>Reload patch review batches</button>
      {busy && <p role="status">Reading patch review state…</p>}
      {error && <p role="alert">{error} No save success is asserted. Reload before retrying; a lost reply may still have persisted.</p>}
      {notice && <p role="status">{notice}</p>}
      {history && <p>Patch review revision {history.revision}; {history.batches.length}/20 batches.</p>}
      {history?.revision === 20 && <p role="status">Batch capacity reached; previous reviews are preserved.</p>}
      <form onSubmit={event => { event.preventDefault(); void load(true); }}>
        <fieldset disabled={busy || !history || uncertain || !ready || history.revision >= 20}>
          <legend>Current page selection ({selected.length}/25)</legend>
          {!rows.length && <p>No selectable findings on this page.</p>}
          {rows.map(row => <label className="patch-review-selection" key={row.exposure_id}>
            <input type="checkbox" checked={selected.includes(row.exposure_id)} disabled={selected.length >= 25 && !selected.includes(row.exposure_id)}
              onChange={event => setSelected(current => event.target.checked ? [...current, row.exposure_id] : current.filter(id => id !== row.exposure_id))} />
            <span>{row.weakness_id} — {row.target_id}</span>
          </label>)}
          <label className="exposure-recovery-field">Batch review owner <input value={owner} maxLength={160} onChange={event => setOwner(event.target.value)} /></label>
          <label className="exposure-recovery-field">Batch review explanation <textarea required rows={3} value={note} maxLength={1000} onChange={event => setNote(event.target.value)} /></label>
          <button className="button button-primary" type="submit" disabled={!selected.length || !note.trim()}>Save review-only batch</button>
        </fieldset>
      </form>
      <details><summary>Inspect retained review-only batches</summary>
        {!history?.batches.length && <p>No saved review batches for this exact principal and scope.</p>}
        {history?.batches.slice().reverse().map(batch => <div className="exposure-recovery-event" key={batch.batch_id}>
          <h3>{batch.batch_id}</h3><p>{batch.note}</p>
          <p>Declared owner: {batch.owner || "unassigned"}; capture: {batch.captured_at}; generation: {batch.generation};
            source observed: {batch.source_observed_at || "unreported"}; source evidence: {batch.source_completeness}.</p>
          <ul>{batch.findings.map(row => <li key={row.exposure_id}>{row.weakness_id}: {row.target_id}; target kind {row.target_kind}; severity {row.severity}; SLA {row.sla_state}; evidence {row.completeness}.</li>)}</ul>
        </div>)}
      </details>
    </div>
  </section>;
}
