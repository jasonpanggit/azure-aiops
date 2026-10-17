"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { vulnerabilityApi } from "@/lib/services";
import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import type { Envelope, ExposureHistory, ExposureObservation } from "@/lib/types";
import { ExposureRecovery } from "./ExposureRecovery";

function scoped(result: Envelope<ExposureHistory>, scope: ScopeSelection): ExposureHistory {
  const agrees = (actual: Record<string, string[]>) => SCOPE_DIMENSIONS.every(dimension =>
    JSON.stringify([...(actual[dimension] ?? [])].sort()) === JSON.stringify([...(scope[dimension] ?? [])].sort()));
  if (!agrees(result.scope) || !agrees(result.data.scope)) throw new Error("Retained observation scope does not match the selected scope.");
  if (result.data.schema_version !== 1 || result.data.revision !== result.data.observations.length || result.data.revision > 30) {
    throw new Error("Retained observation history is inconsistent.");
  }
  const ids = new Set<string>();
  const count = (value: number) => Number.isSafeInteger(value) && value >= 0;
  for (const row of result.data.observations) {
    if (!/^exo-[a-f0-9]{32}$/.test(row.observation_id) || ids.has(row.observation_id)
      || !Number.isFinite(Date.parse(row.captured_at)) || !count(row.total_count) || !row.generation
      || !Object.keys(row.facets).length
      || Object.entries(row.facets).some(([group, values]) =>
        !["severity", "target_kind", "source_family", "sla_state", "completeness", "current_state"].includes(group)
        || values.length > 40 || values.some(item => !item.value || !count(item.count))
        || new Set(values.map(item => item.value.toLowerCase())).size !== values.length
        || values.reduce((sum, item) => sum + item.count, 0) > row.total_count)) {
      throw new Error("Retained observation evidence is inconsistent.");
    }
    ids.add(row.observation_id);
  }
  return result.data;
}

function delta(before: number | null, after: number | null) {
  return before === null || after === null ? "Unavailable" : `${after - before > 0 ? "+" : ""}${after - before}`;
}

/** Explicit private aggregate receipts; never infer finding identities or resolved risk. */
export function ExposureMovement({ scope, generation }: { scope: ScopeSelection; generation: string }) {
  return <MovementWorkspace key={`${JSON.stringify(scope)}::${generation}`} scope={scope} generation={generation} />;
}

function MovementWorkspace({ scope, generation }: { scope: ScopeSelection; generation: string }) {
  const [history, setHistory] = useState<ExposureHistory | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [notice, setNotice] = useState("");
  const [beforeId, setBeforeId] = useState("");
  const [afterId, setAfterId] = useState("");
  const active = useRef(false);
  const requestId = useRef(0);
  const apply = useCallback((result: Envelope<ExposureHistory>) => {
    const data = scoped(result, scope);
    setHistory(data);
    setBeforeId(data.observations.at(-2)?.observation_id ?? "");
    setAfterId(data.observations.at(-1)?.observation_id ?? "");
  }, [scope]);
  useEffect(() => {
    active.current = true;
    const id = ++requestId.current, controller = new AbortController();
    vulnerabilityApi.exposureHistory(scope, controller.signal).then(result => {
      if (active.current && id === requestId.current) apply(result);
    }).catch((reason: unknown) => {
      if (active.current && id === requestId.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Retained observations unavailable.");
    }).finally(() => { if (active.current && id === requestId.current) setBusy(false); });
    return () => { active.current = false; controller.abort(); };
  }, [scope, apply]);

  async function load(capture: boolean) {
    if (busy || (capture && (!history || uncertain || history.revision >= 30 || !generation))) return;
    const id = ++requestId.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = capture
        ? await vulnerabilityApi.captureExposureObservation(scope, history!.revision, generation)
        : await vulnerabilityApi.exposureHistory(scope);
      if (!active.current || id !== requestId.current) return;
      if (capture && (result.data.revision !== history!.revision + 1
        || result.data.observations.at(-1)?.generation !== generation
        || JSON.stringify(result.data.observations.slice(0, -1)) !== JSON.stringify(history!.observations))) {
        throw new Error("Capture response does not preserve the reviewed history and exact generation.");
      }
      apply(result);
      setUncertain(false);
      setNotice(capture ? "Server aggregate observation retained. Live cards are a separate read." : "Retained observations reloaded; review the revision before capturing again.");
    } catch (reason) {
      if (!active.current || id !== requestId.current) return;
      setError(reason instanceof Error ? reason.message : "Observation outcome could not be confirmed.");
      if (capture) setUncertain(true);
    } finally {
      if (active.current && id === requestId.current) setBusy(false);
    }
  }
  const rows = history?.observations ?? [];
  const before = rows.find(row => row.observation_id === beforeId);
  const after = rows.find(row => row.observation_id === afterId);
  const chronological = before && after && rows.indexOf(before) < rows.indexOf(after);
  const groups = Array.from(new Set([...(before ? Object.keys(before.facets) : []), ...(after ? Object.keys(after.facets) : [])]));
  function provenance(row: ExposureObservation) {
    return <div key={row.observation_id}><h3>{row.captured_at}</h3>
      <p>Receipt {row.observation_id}; generation {row.generation}; source {row.source_table}.
        Source observed {row.source_observed_at || "unreported"}; freshness {row.freshness_state};
        evidence {row.completeness_state}; connections {row.represented_connections ?? "unknown"} / {row.expected_connections ?? "unknown"};
        excluded findings {row.excluded_count ?? "unknown"}; source coverage total {row.coverage_total_count ?? "unknown"}.</p></div>;
  }
  return <><section className="card queue-card overview-history exposure-movement" aria-label="Retained Exposure movement">
    <div className="card-header"><div><h2>Compare retained exposure observations</h2>
      <p>Explicit server aggregate receipts for your principal and exact effective scope, not a continuous risk trend.</p></div></div>
    <div className="card-body">
      <p>Up to 30 observations and 256 KiB are retained without silent eviction. Capture reads the selected generation again; it does not save browser counts.
        Collection time is not source freshness. No automatic backfill or provider refresh is implied.</p>
      <div className="overview-history-controls">
        <button className="button button-primary" type="button" disabled={busy || !history || uncertain || history.revision >= 30 || !generation} onClick={() => void load(true)}>Capture exposure observation</button>
        <button className="button" type="button" disabled={busy} onClick={() => void load(false)}>Reload exposure observations</button>
      </div>
      {busy && <p role="status">Reading retained observation state…</p>}
      {error && <p role="alert">{error} No capture success is asserted. Reload before retrying; a lost reply may still have retained an observation.</p>}
      {notice && <p role="status">{notice}</p>}
      {history && <p>History revision {history.revision}; {rows.length}/30 observations retained.</p>}
      {history?.revision === 30 && <p role="status">Observation capacity reached. Existing receipts are preserved; no automatic pruning is performed.</p>}
      {!busy && rows.length < 2 && <p>Capture two observations to compare actual retained aggregates. No historical baseline is inferred.</p>}
      {rows.length >= 2 && <>
        <div className="overview-history-controls">
          <label>Earlier exposure observation <select value={beforeId} onChange={event => setBeforeId(event.target.value)}>{rows.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.generation}</option>)}</select></label>
          <label>Later exposure observation <select value={afterId} onChange={event => setAfterId(event.target.value)}>{rows.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.generation}</option>)}</select></label>
        </div>
        {!chronological ? <p role="status">Choose two different observations in retained capture order.</p> : <>
          <p>{before.generation === after.generation ? "Same generation; differences are still aggregate observations, not finding identity changes." : "Different generations: source population, mapping or classification rules may have changed."}
            {" "}A decrease is not verified remediation; deltas do not identify new or resolved findings. Missing facet groups remain unavailable.</p>
          <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Exposure aggregate comparison, horizontally scrollable">
            <table className="data-table"><caption>Retained finding-count arithmetic, not causal or like-for-like risk movement</caption>
              <thead><tr><th>Classification</th><th>Earlier findings</th><th>Later findings</th><th>Arithmetic change</th></tr></thead>
              <tbody><tr><th scope="row">All represented findings</th><td>{before.total_count}</td><td>{after.total_count}</td><td>{delta(before.total_count, after.total_count)}</td></tr>
                {groups.flatMap(group => {
                  const left = before.facets[group], right = after.facets[group];
                  const values = Array.from(new Set([...(left ?? []).map(row => row.value.toLowerCase()), ...(right ?? []).map(row => row.value.toLowerCase())]));
                  return values.map(value => {
                    const a = left ? left.find(row => row.value.toLowerCase() === value)?.count ?? 0 : null;
                    const b = right ? right.find(row => row.value.toLowerCase() === value)?.count ?? 0 : null;
                    return <tr key={`${group}:${value}`}><th scope="row">{group}: {value}</th><td>{a ?? "Unavailable"}</td><td>{b ?? "Unavailable"}</td><td>{delta(a, b)}</td></tr>;
                  });
                })}
              </tbody>
            </table>
          </div>
          <details><summary>Inspect retained source extents and generations</summary>{provenance(before)}{provenance(after)}</details>
        </>}
      </>}
    </div>
  </section>{history ? <ExposureRecovery scope={scope} historyRevision={history.revision} /> : <section id="exposure-recovery" className="card queue-card" aria-label="Exposure recovery review"><div className="card-body"><h2>Recovery review requires retained observations</h2><p>Reload observation history above before reading recorded evidence gaps. Current provider health is not inferred from unavailable history.</p></div></section>}</>;
}
