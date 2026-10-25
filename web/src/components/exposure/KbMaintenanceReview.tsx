"use client";

import { useEffect, useRef, useState } from "react";
import { kbApi } from "@/lib/services";
import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import type { Envelope, KbReviewDeclaration, KbReviewHistory } from "@/lib/types";

const bounded = (value: string, limit: number) => typeof value === "string" && Boolean(value.trim()) && value.length <= limit;
const zoned = (value: string) => typeof value === "string" && /(Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));

function validate(result: Envelope<KbReviewHistory>, kbId: string, scope: ScopeSelection, previous: KbReviewHistory | null) {
  const data = result.data;
  const agrees = (returned: ScopeSelection) => SCOPE_DIMENSIONS.every(dimension =>
    JSON.stringify([...(returned[dimension] ?? [])].sort()) === JSON.stringify([...(scope[dimension] ?? [])].sort()));
  if (!agrees(result.scope) || !agrees(data.scope) || data.kb_id !== kbId || data.schema_version !== 1
    || !bounded(data.actor, 4096) || !Number.isInteger(data.revision) || data.revision < 0 || data.revision > 20
    || !Array.isArray(data.reviews) || data.reviews.length !== data.revision
    || new Set(data.reviews.map(row => row.review_id)).size !== data.revision
    || data.reviews.some((row, index) => !/^kbr-[a-f0-9]{32}$/.test(row.review_id) || row.expected_revision !== index
      || !bounded(row.generation, 256) || !bounded(row.owner, 160) || !bounded(row.note, 1000)
      || !zoned(row.recorded_at) || !zoned(row.window_start) || !zoned(row.window_end)
      || Date.parse(row.window_end) <= Date.parse(row.window_start)
      || !["needs_review", "deferred", "reviewed"].includes(row.disposition)
      || !Array.isArray(row.dependency_kbs) || row.dependency_kbs.length > 20
      || new Set(row.dependency_kbs).size !== row.dependency_kbs.length
      || row.dependency_kbs.some(value => !/^KB[0-9]{4,20}$/.test(value) || value === kbId)
      || typeof row.source_observed_at !== "string" || typeof row.source_freshness !== "string" || typeof row.source_completeness !== "string")) {
    throw new Error("KB review identity, revision or declaration is inconsistent.");
  }
  if (previous && (data.actor !== previous.actor || data.revision < previous.revision
    || JSON.stringify(data.reviews.slice(0, previous.revision)) !== JSON.stringify(previous.reviews))) {
    throw new Error("KB review response changed retained attribution or immutable history.");
  }
  return data;
}

/** Private maintenance declarations; proposed windows and dependencies remain unverified. */
export function KbMaintenanceReview({ kbId, scope, generation }: { kbId: string; scope: ScopeSelection; generation?: string }) {
  const [history, setHistory] = useState<KbReviewHistory | null>(null);
  const [owner, setOwner] = useState(""), [start, setStart] = useState(""), [end, setEnd] = useState("");
  const [dependencies, setDependencies] = useState(""), [note, setNote] = useState("");
  const [disposition, setDisposition] = useState<KbReviewDeclaration["disposition"]>("needs_review");
  const [busy, setBusy] = useState(true), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const active = useRef(false), sequence = useRef(0);
  useEffect(() => {
    active.current = true;
    const id = ++sequence.current, controller = new AbortController();
    kbApi.reviews(kbId, scope, controller.signal).then(result => {
      if (active.current && sequence.current === id) setHistory(validate(result, kbId, scope, null));
    }).catch((reason: unknown) => {
      if (active.current && sequence.current === id && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "KB reviews unavailable.");
    }).finally(() => { if (active.current && sequence.current === id) setBusy(false); });
    return () => { active.current = false; controller.abort(); };
  }, [kbId, scope]);
  const dependencyKbs = dependencies.split(/[\s,]+/).filter(Boolean);
  const valid = Boolean(generation && bounded(owner, 160) && bounded(note, 1000) && zoned(start) && zoned(end)
    && Date.parse(end) > Date.parse(start) && dependencyKbs.length <= 20 && new Set(dependencyKbs).size === dependencyKbs.length
    && dependencyKbs.every(value => /^KB[0-9]{4,20}$/.test(value) && value !== kbId));
  async function load(save: boolean) {
    if (busy || (save && (!valid || uncertain || !history || history.revision >= 20))) return;
    const id = ++sequence.current;
    const declaration: KbReviewDeclaration = {
      generation: generation ?? "", owner, window_start: start, window_end: end, dependency_kbs: dependencyKbs, disposition, note,
    };
    setBusy(true); setError(""); setNotice("");
    try {
      const result = save
        ? await kbApi.createReview(kbId, scope, history!.revision, declaration)
        : await kbApi.reviews(kbId, scope);
      if (!active.current || sequence.current !== id) return;
      const data = validate(result, kbId, scope, history), record = data.reviews.at(-1);
      if (save && (data.revision !== history!.revision + 1 || !record
        || Object.entries(declaration).some(([key, value]) => JSON.stringify(record[key as keyof KbReviewDeclaration]) !== JSON.stringify(value)))) {
        throw new Error("KB review response does not preserve the exact submitted declaration.");
      }
      setHistory(data); setUncertain(false);
      if (save) setNote("");
      setNotice(save ? "Maintenance review retained. No window was scheduled and no update was approved or executed." : "Retained reviews reloaded; inspect them before another save.");
    } catch (reason) {
      if (!active.current || sequence.current !== id) return;
      setError(reason instanceof Error ? reason.message : "KB review outcome unconfirmed.");
      setUncertain(true);
    } finally { if (active.current && sequence.current === id) setBusy(false); }
  }
  return <section className="exposure-detail-section kb-update-evidence exposure-recovery kb-maintenance-review" aria-label="KB maintenance review">
    <div className="card-header"><h2>Maintenance review</h2></div>
    <div className="card-body">
      <p>Optional private notes, not a required remediation step. Declare an owner, proposed window and dependency references for private review. This does not schedule work, deliver an assignment,
        verify prerequisites, approve execution or establish a fix. “Reviewed” is only your disposition.</p>
      <p>Each save rereads current authorized Silver metadata. Its generation must match the page; provider clocks remain independent.
        Up to 20 immutable reviews and 256 KiB are retained without eviction.</p>
      <button className="button" type="button" disabled={busy} onClick={() => void load(false)}>Reload KB maintenance reviews</button>
      {busy && <p role="status">Reading KB maintenance review state…</p>}
      {error && <p role="alert">{error} No save success is asserted. A lost reply may have persisted; reload retained reviews before retrying.</p>}
      {notice && <p role="status">{notice}</p>}
      {history && <p>KB review revision {history.revision}; {history.reviews.length}/20 records.</p>}
      {!generation && <p role="status">Current KB snapshot generation unavailable; new reviews are disabled. Retained reads remain available.</p>}
      {history?.revision === 20 && <p role="status">Review capacity reached; existing records are preserved.</p>}
      <form onSubmit={event => { event.preventDefault(); void load(true); }}>
        <fieldset disabled={busy || !history || uncertain || !generation || history.revision >= 20}>
          <legend>Review-only declaration</legend>
          <label className="exposure-recovery-field">Declared review owner<input required maxLength={160} value={owner} onChange={event => setOwner(event.target.value)} /></label>
          <label className="exposure-recovery-field">Proposed window start (ISO 8601 with time zone)<input required placeholder="2026-10-20T01:00:00Z" maxLength={64} value={start} onChange={event => setStart(event.target.value)} /></label>
          <label className="exposure-recovery-field">Proposed window end (ISO 8601 with time zone)<input required placeholder="2026-10-20T02:00:00Z" maxLength={64} value={end} onChange={event => setEnd(event.target.value)} /></label>
          <label className="exposure-recovery-field">Unverified dependency KB references<input value={dependencies} maxLength={480} placeholder="KB6000000, KB6000002" onChange={event => setDependencies(event.target.value)} /></label>
          <label className="exposure-recovery-field">Review disposition<select value={disposition} onChange={event => {
            const value = event.target.value;
            if (value === "needs_review" || value === "deferred" || value === "reviewed") setDisposition(value);
          }}><option value="needs_review">Needs review</option><option value="deferred">Deferred</option><option value="reviewed">Reviewed (not approved)</option></select></label>
          <label className="exposure-recovery-field">Maintenance review explanation<textarea required rows={3} maxLength={1000} value={note} onChange={event => setNote(event.target.value)} /></label>
          <p>Use offset-aware start/end times with end after start. Optional references must be unique uppercase KB identifiers (up to 20); they cannot reference this update.</p>
          <button className="button button-primary" type="submit" disabled={!valid}>Retain maintenance review</button>
        </fieldset>
      </form>
      <details><summary>Inspect retained maintenance reviews</summary>
        {!history?.reviews.length && <p>{history ? "No retained maintenance reviews for this principal, exact scope and KB." : "Retained maintenance review history is unavailable."}</p>}
        {history?.reviews.slice().reverse().map(row => <div className="exposure-recovery-event" key={row.review_id}>
          <h3 className="exposure-long-value">{row.review_id}</h3>
          <p>{row.note}</p><dl className="exposure-definition-grid">
            <div><dt>Declared owner / disposition</dt><dd>{row.owner} / {row.disposition}</dd></div>
            <div><dt>Proposed window (not scheduled)</dt><dd>{row.window_start} – {row.window_end}</dd></div>
            <div><dt>Unverified dependency references</dt><dd>{row.dependency_kbs.join(", ") || "None declared; not proof of no prerequisites"}</dd></div>
            <div><dt>Review recorded</dt><dd>{row.recorded_at}</dd></div>
            <div><dt>Snapshot generation</dt><dd className="exposure-long-value">{row.generation}</dd></div>
            <div><dt>Source observed / coverage / freshness</dt><dd>{row.source_observed_at || "Unreported"} / {row.source_completeness} / {row.source_freshness}</dd></div>
          </dl>
        </div>)}
      </details>
    </div>
  </section>;
}
