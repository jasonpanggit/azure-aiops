"use client";

import { useEffect, useRef, useState } from "react";
import { kbApi } from "@/lib/services";
import type { ScopeSelection } from "@/lib/scope";
import type { KbObservation, KbObservationHistory } from "@/lib/types";
import { compareKbTargets, validateKbObservations } from "@/lib/kb-observations";

/** Explicit retained source observations and qualified comparison, never verified fixes. */
export function KbObservations({ kbId, scope, generation }: { kbId: string; scope: ScopeSelection; generation?: string }) {
  const [history, setHistory] = useState<KbObservationHistory | null>(null);
  const [busy, setBusy] = useState(true), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [left, setLeft] = useState(""), [right, setRight] = useState("");
  const active = useRef(false), sequence = useRef(0);
  useEffect(() => {
    active.current = true;
    const id = ++sequence.current, controller = new AbortController();
    kbApi.observations(kbId, scope, controller.signal).then(result => {
      if (active.current && sequence.current === id) setHistory(validateKbObservations(result, kbId, scope, null));
    }).catch((reason: unknown) => {
      if (active.current && sequence.current === id && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "KB source history unavailable.");
    }).finally(() => { if (active.current && sequence.current === id) setBusy(false); });
    return () => { active.current = false; controller.abort(); };
  }, [kbId, scope]);
  async function load(capture: boolean) {
    if (busy || (capture && (!generation || !history || uncertain || history.revision >= 20))) return;
    const id = ++sequence.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = capture
        ? await kbApi.captureObservation(kbId, scope, history!.revision, generation!)
        : await kbApi.observations(kbId, scope);
      if (!active.current || sequence.current !== id) return;
      const data = validateKbObservations(result, kbId, scope, history);
      if (capture && (data.revision !== history!.revision + 1 || data.observations.at(-1)?.generation !== generation)) {
        throw new Error("KB capture response does not preserve the expected revision and Silver generation.");
      }
      setHistory(data); setUncertain(false);
      setNotice(capture ? "KB source observation retained. No fix or post-deploy health was verified." : "Retained KB observations reloaded; inspect before another capture.");
    } catch (reason) {
      if (!active.current || sequence.current !== id) return;
      setError(reason instanceof Error ? reason.message : "KB capture outcome unconfirmed."); setUncertain(true);
    } finally { if (active.current && sequence.current === id) setBusy(false); }
  }
  const first = history?.observations.find(row => row.observation_id === left);
  const second = history?.observations.find(row => row.observation_id === right);
  const difference = first && second && first.observation_id !== second.observation_id ? compareKbTargets(first, second) : null;
  return <section className="exposure-detail-section kb-update-evidence kb-observation-history" aria-label="Retained KB source observations">
    <div className="card-header"><h2>Recorded update observations</h2></div>
    <div className="card-body">
      <p>Capture current authorized Silver metadata explicitly for private comparison. Reads do not refresh or capture sources.
        Up to 20 observations / 512 KiB, without automatic eviction. Capture time is not source observation time.</p>
      <p>Recorded “installed” is inventory status, not proof of execution or a verified fix.
        This source does not collect post-deploy health or link an observed change causally to a maintenance review.</p>
      <div className="button-row">
        <button className="button" disabled={busy} onClick={() => void load(false)}>Reload KB observations</button>
        <button className="button button-primary" disabled={busy || !history || uncertain || !generation || history.revision >= 20} onClick={() => void load(true)}>Capture KB source observation</button>
      </div>
      {busy && <p role="status">Reading KB source observations…</p>}
      {error && <p role="alert">{error} No capture success is asserted. Reload retained observations before retrying; a lost reply may have persisted.</p>}
      {notice && <p role="status">{notice}</p>}
      {!generation && <p>Current KB metadata unavailable; capture is disabled. Retained observations remain readable.</p>}
      {history && <p>KB observation revision {history.revision}; {history.observations.length}/20 records.</p>}
      {history?.revision === 20 && <p role="status">Observation capacity reached; earlier observations are preserved.</p>}
      {history?.revision === 0 && <p>No retained source observations for this principal, exact scope and update.</p>}
      {history?.observations.map(row => <details className="exposure-recovery-event" key={row.observation_id}>
        <summary className="exposure-long-value">{row.observation_id} — captured {row.captured_at}</summary>
        <ObservationFacts row={row} />
        <p>{row.targets.length} sampled / {row.counts?.observed_targets ?? "unknown"} observed targets;
          {" "}{row.targets_truncated === true ? "sample truncated" : row.targets_truncated === false ? "complete snapshot sample" : "extent unknown"}.</p>
        <ul>{row.targets.map(target => <li className="exposure-long-value" key={target.target_id}>
          {target.target_id}: {target.status}; source observed {target.observed_at || "unreported"}</li>)}</ul>
      </details>)}
      <h3>Compare retained source observations</h3>
      <p>Select two distinct captures. Counts describe their respective source populations, not a fixed cohort.
        Sample membership differences are not newly exposed or resolved targets; source clocks, coverage and generations may differ.</p>
      <div className="exposure-definition-grid">
        <label className="exposure-recovery-field">First KB observation<select value={left} onChange={event => setLeft(event.target.value)}>
          <option value="">Select a retained observation</option>{history?.observations.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id}</option>)}
        </select></label>
        <label className="exposure-recovery-field">Second KB observation<select value={right} onChange={event => setRight(event.target.value)}>
          <option value="">Select a retained observation</option>{history?.observations.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id}</option>)}
        </select></label>
      </div>
      {difference && first && second ? <div aria-label="KB source observation comparison">
        <h3>Source populations and independent clocks</h3>
        <h4>First selected observation</h4><ObservationFacts row={first} />
        <h4>Second selected observation</h4><ObservationFacts row={second} />
        <h3>Recorded status differences on common sampled targets</h3>
        {!difference.changes.length && <p>No recorded status differences on common sampled targets. This does not establish no estate changes.</p>}
        <ul>{difference.changes.map(row => <li className="exposure-long-value" key={row.target_id}>{row.target_id}: {row.before.status} → {row.after.status};
          {" "}source observed {row.before.observed_at || "unreported"} → {row.after.observed_at || "unreported"}. Not a verified fix.</li>)}</ul>
        <p>First sample only ({difference.firstOnly.length}): {difference.firstOnly.join(", ") || "none"}.</p>
        <p>Second sample only ({difference.secondOnly.length}): {difference.secondOnly.join(", ") || "none"}.</p>
        <p>Membership is bounded source evidence, not remediation outcome or complete estate movement.</p>
      </div> : <p role="status">Choose two distinct retained observations to compare without acquiring providers.</p>}
    </div>
  </section>;
}

function ObservationFacts({ row }: { row: KbObservation }) {
  return <dl className="exposure-definition-grid">
    <div><dt>Capture / generation</dt><dd className="exposure-long-value">{row.captured_at} / {row.generation}</dd></div>
    <div><dt>Snapshot observed / coverage / freshness</dt><dd>{row.source_observed_at || "Unreported"} / {row.completeness} / {row.freshness}</dd></div>
    <div><dt>Recorded status population</dt><dd>{row.counts
      ? `${row.counts.observed_targets} observed; ${row.counts.missing} missing; ${row.counts.installation_failed} failed; ${row.counts.installed} installed; ${row.counts.other} other`
      : "Unknown; not inferred from sample"}</dd></div>
    <div><dt>MSRC independent state / time</dt><dd>{row.msrc
      ? `${row.msrc.status}; ${row.msrc.stale ? "stale" : "not marked stale"}; last-known-good ${row.msrc.has_last_known_good ? "retained" : "absent"}; ${row.msrc.source_at || "time unreported"}`
      : "Unreported"}</dd></div>
  </dl>;
}
