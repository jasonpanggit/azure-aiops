"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { vulnerabilityApi } from "@/lib/services";
import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import type { Envelope, ExposureRecoveryCandidate, ExposureRecoveryDisposition, ExposureRecoveryState } from "@/lib/types";

const labels = {
  source_evidence: "Evidence exclusions or incomplete source",
  connection_coverage: "Connection coverage",
  freshness: "Unconfirmed source freshness",
  classification: "Incomplete classification vocabulary",
  sla_unknown: "Unclassified SLA findings",
};
const keyOf = (row: { observation_id: string; reason: string }) => `${row.observation_id}:${row.reason}`;

function validate(result: Envelope<ExposureRecoveryState>, scope: ScopeSelection) {
  const data = result.data;
  const agrees = (actual: Record<string, string[]>) => SCOPE_DIMENSIONS.every(dimension =>
    JSON.stringify([...(actual[dimension] ?? [])].sort()) === JSON.stringify([...(scope[dimension] ?? [])].sort()));
  if (!agrees(result.scope) || !agrees(data.scope)) throw new Error("Recovery review scope does not match the selected scope.");
  if (data.schema_version !== 1 || !data.actor || data.revision !== data.events.length || data.revision > 100
    || data.candidates.length > 150 || new Set(data.events.map(row => row.event_id)).size !== data.revision
    || new Set(data.candidates.map(keyOf)).size !== data.candidates.length) throw new Error("Recovery history is inconsistent.");
  const seen = new Set<string>();
  data.events.forEach((event, index) => {
    const key = keyOf(event);
    if (!/^exr-[a-f0-9]{32}$/.test(event.event_id) || event.expected_revision !== index || event.actor !== data.actor
      || !Number.isFinite(Date.parse(event.recorded_at)) || !event.note.trim()
      || !["queued", "in_review", "review_closed"].includes(event.disposition)
      || (!seen.has(key) && event.disposition !== "queued")
      || !data.candidates.some(row => keyOf(row) === key)) throw new Error("Recovery event attribution or transition is inconsistent.");
    seen.add(key);
  });
  for (const row of data.candidates) {
    const latest = data.events.filter(event => keyOf(event) === keyOf(row)).at(-1) ?? null;
    if (!/^exo-[a-f0-9]{32}$/.test(row.observation_id) || !Object.hasOwn(labels, row.reason)
      || !row.explanation || !row.generation || !Number.isFinite(Date.parse(row.captured_at))
      || JSON.stringify(row.review) !== JSON.stringify(latest)) throw new Error("Recovery candidate evidence does not match retained events.");
  }
  return data;
}

/** Private evidence-gap review declarations, with no provider or execution mutations. */
export function ExposureRecovery({ scope, historyRevision }: { scope: ScopeSelection; historyRevision: number }) {
  return <RecoveryWorkspace key={JSON.stringify(scope)} scope={scope} historyRevision={historyRevision} />;
}

function RecoveryWorkspace({ scope, historyRevision }: { scope: ScopeSelection; historyRevision: number }) {
  const [state, setState] = useState<ExposureRecoveryState | null>(null);
  const [selected, setSelected] = useState("");
  const [owner, setOwner] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [disposition, setDisposition] = useState<ExposureRecoveryDisposition>("queued");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(true), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const active = useRef(false), requestId = useRef(0);
  const choose = useCallback((row?: ExposureRecoveryCandidate) => {
    setSelected(row ? keyOf(row) : ""); setOwner(row?.review?.owner ?? "");
    setTargetDate(row?.review?.target_date ?? ""); setDisposition(row?.review?.disposition ?? "queued"); setNote("");
  }, []);
  const apply = useCallback((result: Envelope<ExposureRecoveryState>, selectedKey: string) => {
    const data = validate(result, scope);
    setState(data);
    choose(data.candidates.find(row => keyOf(row) === selectedKey) ?? data.candidates.at(-1));
  }, [scope, choose]);
  useEffect(() => {
    active.current = true;
    const id = ++requestId.current, controller = new AbortController();
    setBusy(true);
    vulnerabilityApi.exposureRecovery(scope, controller.signal).then(result => {
      if (active.current && id === requestId.current) { apply(result, ""); setUncertain(false); setError(""); }
    }).catch((reason: unknown) => {
      if (active.current && id === requestId.current && !controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "Retained recovery review unavailable."); setUncertain(true);
      }
    }).finally(() => { if (active.current && id === requestId.current) setBusy(false); });
    return () => { active.current = false; controller.abort(); };
  }, [scope, historyRevision, apply]);
  const candidate = state?.candidates.find(row => keyOf(row) === selected);
  async function load(save: boolean) {
    if (busy || (save && (!state || !candidate || uncertain || state.revision >= 100 || !note.trim()))) return;
    const id = ++requestId.current;
    setBusy(true); setError(""); setNotice("");
    const payload = candidate && state ? {
      expected_revision: state.revision, observation_id: candidate.observation_id, reason: candidate.reason,
      owner, target_date: targetDate, disposition, note,
    } : null;
    try {
      const result = save && payload
        ? await vulnerabilityApi.reviewExposureRecovery(scope, payload)
        : await vulnerabilityApi.exposureRecovery(scope);
      if (!active.current || id !== requestId.current) return;
      if (save && payload && (result.data.revision !== state!.revision + 1
        || JSON.stringify(result.data.events.slice(0, -1)) !== JSON.stringify(state!.events)
        || Object.entries(payload).some(([key, value]) => result.data.events.at(-1)?.[key as keyof typeof payload] !== value))) {
        throw new Error("Saved review does not match the reviewed revision, candidate and declaration.");
      }
      apply(result, selected); setUncertain(false);
      setNotice(save ? "Review declaration retained. Provider evidence is unchanged." : "Recovery review reloaded. Inspect the revision before submitting again.");
    } catch (reason) {
      if (!active.current || id !== requestId.current) return;
      setError(reason instanceof Error ? reason.message : "Recovery review outcome could not be confirmed.");
      setUncertain(true);
    } finally { if (active.current && id === requestId.current) setBusy(false); }
  }
  return <section className="card queue-card overview-history exposure-recovery" id="exposure-recovery" aria-label="Exposure recovery review">
    <div className="card-header"><div><h2>Recover missing exposure evidence</h2>
      <p>Review recorded gaps before interpreting coverage as an all-clear.</p></div></div>
    <div className="card-body">
      <p>Candidates come only from your retained server observations, not current provider health. Owners and target dates are your declarations, not assignments delivered to another user or provider SLAs.
        Closing a review never repairs a source, verifies remediation or authorizes execution.</p>
      <button type="button" className="button" disabled={busy} onClick={() => void load(false)}>Reload recovery review</button>
      {busy && <p role="status">Reading recovery review state…</p>}
      {error && <p role="alert">{error} No write success is asserted; reload before retrying because a lost reply may still have persisted.</p>}
      {notice && <p role="status">{notice}</p>}
      {state && <p>Recovery revision {state.revision}; {state.candidates.length} recorded gap candidates. {state.events.length}/100 immutable review events; 256 KiB maximum, no automatic eviction.</p>}
      {state?.revision === 100 && <p role="status">Review event capacity reached; existing declarations remain available.</p>}
      {state && !state.candidates.length && <p>No retained gap candidates. Capture an observation above to inspect recorded coverage; absence here is not a current health claim.</p>}
      {!!state?.candidates.length && <label className="exposure-recovery-field">Recorded evidence gap
        <select value={selected} disabled={busy} onChange={event => choose(state.candidates.find(row => keyOf(row) === event.target.value))}>
          {state.candidates.slice().reverse().map(row => <option key={keyOf(row)} value={keyOf(row)}>{labels[row.reason]} · {row.captured_at} · {row.review?.disposition ?? "not queued"}</option>)}
        </select>
      </label>}
      {candidate && <>
        <p><strong>{labels[candidate.reason]}:</strong> {candidate.explanation}</p>
        <p>Immutable receipt {candidate.observation_id}; generation {candidate.generation}; captured {candidate.captured_at}.
          This candidate remains anchored to that observation even after another capture.</p>
        <form onSubmit={event => { event.preventDefault(); void load(true); }}>
          <fieldset disabled={busy || uncertain || !state || state.revision >= 100}>
            <legend>{candidate.review ? "Update retained recovery review" : "Explicitly queue this recorded gap"}</legend>
            <div className="overview-history-controls">
              <label>Review owner <input value={owner} maxLength={160} onChange={event => setOwner(event.target.value)} /></label>
              <label>Review target date <input type="date" value={targetDate} onChange={event => setTargetDate(event.target.value)} /></label>
              <label>Review disposition <select value={disposition} onChange={event => setDisposition(event.target.value as ExposureRecoveryDisposition)}>
                <option value="queued">Queued</option>
                {candidate.review && <><option value="in_review">In review</option><option value="review_closed">Review closed, evidence unchanged</option></>}
              </select></label>
            </div>
            <label className="exposure-recovery-field">Review explanation <textarea required value={note} maxLength={1000} rows={3} onChange={event => setNote(event.target.value)} /></label>
            <button type="submit" className="button button-primary" disabled={!note.trim()}>{candidate.review ? "Save recovery review" : "Queue recovery review"}</button>
          </fieldset>
        </form>
        <details><summary>Inspect immutable review activity for this gap</summary>
          {state?.events.filter(row => keyOf(row) === selected).map(row => <div className="exposure-recovery-event" key={row.event_id}>
            <h3>{row.disposition.replaceAll("_", " ")} · {row.recorded_at}</h3>
            <p>{row.note}</p><p>Declared owner: {row.owner || "unassigned"}; target: {row.target_date || "not set"}; actor: {row.actor}; event: {row.event_id}.</p>
          </div>)}
          {!candidate.review && <p>No review has been queued for this receipt and reason.</p>}
        </details>
      </>}
    </div>
  </section>;
}
