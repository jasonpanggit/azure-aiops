"use client";

import { useEffect, useRef, useState } from "react";
import { overviewPosture } from "@/lib/overview";
import { CountBarChart } from "@/components/ui/CountBarChart";
import type { ScopeSelection } from "@/lib/scope";
import { overviewApi } from "@/lib/services";
import type { OverviewHistory as History, OverviewObservation } from "@/lib/types";

function score(row: OverviewObservation) {
  return overviewPosture(row.critical_situations, row.exposed_findings, row.network_gaps).score;
}

/** Retained explicit observations, not invented historical trends or causal explanations. */
export function OverviewHistory({ scope }: { scope: ScopeSelection }) {
  return <HistoryWorkspace key={JSON.stringify(scope)} scope={scope} />;
}

function HistoryWorkspace({ scope }: { scope: ScopeSelection }) {
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [beforeId, setBeforeId] = useState("");
  const [afterId, setAfterId] = useState("");
  const mounted = useRef(false);
  const requestId = useRef(0);
  function apply(next: History) {
    setHistory(next);
    setBeforeId(next.observations.at(-2)?.observation_id ?? "");
    setAfterId(next.observations.at(-1)?.observation_id ?? "");
  }
  useEffect(() => {
    mounted.current = true;
    const id = ++requestId.current;
    overviewApi.history(scope).then(response => {
      if (mounted.current && requestId.current === id) apply(response.data);
    }).catch((reason: unknown) => {
      if (mounted.current && requestId.current === id) setError(reason instanceof Error ? reason.message : "Overview history could not be loaded");
    }).finally(() => {
      if (mounted.current && requestId.current === id) setBusy(false);
    });
    return () => { mounted.current = false; };
  }, [scope]);

  async function load(capture: boolean) {
    if (busy || (capture && !history)) return;
    const id = ++requestId.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = capture ? await overviewApi.capture(scope, history!.revision) : await overviewApi.history(scope);
      if (!mounted.current || requestId.current !== id) return;
      apply(response.data);
      setNotice(capture ? "Server observation retained. The live cards above are a separate read." : "Retained observations reloaded.");
    } catch (reason) {
      if (mounted.current && requestId.current === id) setError(reason instanceof Error ? reason.message : "Overview observation failed; reload history before retrying");
    } finally {
      if (mounted.current && requestId.current === id) setBusy(false);
    }
  }
  const rows = history?.observations ?? [];
  const before = rows.find(row => row.observation_id === beforeId);
  const after = rows.find(row => row.observation_id === afterId);
  const chronological = before && after && Date.parse(before.captured_at) < Date.parse(after.captured_at);
  return <section className="card dashboard-section overview-history overview-history-workspace" aria-label="Retained Overview observations">
    <div className="card-header"><div><h2>Compare retained observations</h2>
      <p>Capture an explicit server read now, then compare two retained collections in this exact authorized scope.</p></div>
      <div className="overview-history-controls overview-history-actions">
        <button type="button" className="button button-primary" disabled={busy || !history} onClick={() => void load(true)}>{busy ? "Working…" : "Capture server observation"}</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void load(false)}>Reload observations</button>
      </div>
    </div>
    <div className="card-body">
      {error && <p role="alert">{error} No successful capture is asserted. Reload before retrying after a conflict.</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="overview-history-summary">
        <div className="overview-history-status">
          {history && <p>History revision {history.revision}; {rows.length}/30 observations retained. Current cards above do not change this history automatically.</p>}
          {rows.length < 2 && !busy && <p>Two retained observations are needed for a comparison. No prior trend is inferred.</p>}
        </div>
        <details className="source-section-details overview-history-guidance">
          <summary>Retention and source limitations</summary>
          <p>Private to your principal and exact effective scope. Latest 30 explicit captures retained; the oldest is replaced on the 31st.
            No automatic schedule, seven-day backfill, or continuous monitoring is implied. Only three aggregate inputs and their provenance are stored, not raw resources.
            Sources are read separately and may have different observation times; capture time does not mean fresh source data.
            All source reads must succeed or no observation is saved.</p>
        </details>
      </div>
      {rows.length >= 2 && <>
        <div className="overview-history-controls"><label>Earlier observation <select aria-label="Earlier observation" value={beforeId} onChange={event => setBeforeId(event.target.value)}>
          {rows.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id.slice(0, 8)}</option>)}
        </select></label>{" "}
        <label>Later observation <select aria-label="Later observation" value={afterId} onChange={event => setAfterId(event.target.value)}>
          {rows.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id.slice(0, 8)}</option>)}
        </select></label></div>
        {!chronological ? <p role="status">Choose two different observations in chronological order.</p> : <>
          <div className="overview-comparison-charts" role="group" aria-label="Retained count comparison charts">
            {([
              ["Loaded P1 situations", before.critical_situations, after.critical_situations],
              ["Internet-exposed findings", before.exposed_findings, after.exposed_findings],
              ["Network gaps", before.network_gaps, after.network_gaps],
            ] as const).map(([label, earlier, later]) => (
              <figure key={label}>
                <figcaption>{label}</figcaption>
                {earlier === null || later === null
                  ? <p>Comparison unavailable: a retained count was not reported.</p>
                  : <CountBarChart unit={label} data={[
                    { id: "earlier", label: "Earlier", value: earlier },
                    { id: "later", label: "Later", value: later },
                  ]} />}
              </figure>
            ))}
          </div>
          <p className="table-secondary">Each measure uses its own scale. Two retained observations, not a continuous trend.</p>
          <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Observation count comparison, horizontally scrollable">
            <table className="data-table"><caption>Observed aggregate count changes, not causal attribution or like-for-like estate growth</caption>
              <thead><tr><th>Measure</th><th>Earlier</th><th>Later</th><th>Arithmetic change</th></tr></thead>
              <tbody>{([
                ["Loaded P1 situations", before.critical_situations, after.critical_situations],
                ["Internet-exposed findings", before.exposed_findings, after.exposed_findings],
                ["Network gaps", before.network_gaps, after.network_gaps],
                ["Heuristic score", score(before), score(after)],
              ] as const).map(([label, left, right]) => <tr key={label}><th scope="row">{label}</th><td>{left ?? "Unavailable"}</td><td>{right ?? "Unavailable"}</td><td>{left === null || right === null ? "Unavailable" : `${right - left > 0 ? "+" : ""}${right - left}`}</td></tr>)}</tbody>
            </table>
          </div>
          <p>Counts can change because evidence, source population, pagination, or rules changed. A difference is not a new/resolved-resource count, a verified improvement, or a cause.
            Situation counts are the first 100 priority-ranked rows, not a whole-estate denominator. Compare extents and provenance before interpreting a delta.</p>
          <details><summary>Inspect both collection extents and source provenance</summary>
            {[before, after].map(row => <div key={row.observation_id}>
              <h3>{row.captured_at}</h3><p>Formula {row.formula_version}; observation {row.observation_id}</p>
              <ul>{row.sources.map(source => <li key={source.id}>{source.id}: collected {source.started_at} to {source.finished_at};
                {" "}source observation times: {source.observed_at.join(", ") || "unreported"}; tables: {source.source_tables.join(", ") || "unreported"};
                {" "}version: {source.knowledge_version || "unreported"}; loaded {source.loaded ?? "summary"}, total {source.total ?? "unreported"};
                {" "}{source.partial ? "partial page" : "extent remains source-defined"}; warnings {source.warning_count}.</li>)}</ul>
            </div>)}
          </details>
        </>}
      </>}
    </div>
  </section>;
}
