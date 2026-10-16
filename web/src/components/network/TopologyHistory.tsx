"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ScopeSelection } from "@/lib/scope";
import { scopeToSearchParams } from "@/lib/scope";
import { networkApi } from "@/lib/services";
import type {
  NetworkTopologyHistory, NetworkTopologyComparison, RetainedTopologyCapture,
  RetainedTopologyNode, RetainedTopologyEdge,
} from "@/lib/types";

/** Explicit personal retained topology comparisons, isolated by exact selected scope. */
export function TopologyHistory({ scope }: { scope: ScopeSelection }) {
  const query = scopeToSearchParams(scope);
  query.sort();
  return <HistoryPanel key={query.toString()} scope={scope} />;
}

function projection(value: RetainedTopologyNode | RetainedTopologyEdge | null) {
  if (!value) return <p>Not observed in this projection</p>;
  return <dl className="network-history-fields">{Object.entries(value).map(([key, field]) =>
    <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>
      {field === null ? "Not applicable" : typeof field === "object"
        ? Object.entries(field).map(([name, entry]) => `${name.replaceAll("_", " ")}: ${String(entry)}`).join("; ")
        : field || "Not reported"}
    </dd></div>,
  )}</dl>;
}

function receipt(capture: RetainedTopologyCapture, label: string) {
  return <div><h3>{label}</h3>
    <p>Acquired {capture.started_at} to {capture.finished_at}.</p>
    <p>Source observed: {capture.source_observed_at || "Not reported"}.</p>
    <p>{capture.nodes.length} projected nodes; {capture.edges.length} relationships.
      {" "}{capture.omitted_boundary_peering_count} boundary peerings withheld; {capture.dropped_relationship_count} relationships not projected by the source.</p>
  </div>;
}

function HistoryPanel({ scope }: { scope: ScopeSelection }) {
  const [history, setHistory] = useState<NetworkTopologyHistory | null>(null);
  const [baseline, setBaseline] = useState("");
  const [target, setTarget] = useState("");
  const [comparison, setComparison] = useState<NetworkTopologyComparison | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const id = useId();

  function apply(next: NetworkTopologyHistory) {
    setHistory(next); setBaseline(next.captures.at(-2)?.capture_id ?? "");
    setTarget(next.captures.at(-1)?.capture_id ?? ""); setComparison(null); setOffset(0);
  }

  const reload = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setHistory(null); setComparison(null);
    try {
      const response = await networkApi.topologyHistory(scope, { signal: controller.signal });
      if (!controller.signal.aborted) apply(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Topology history is unavailable.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }, [scope]);

  useEffect(() => {
    void reload();
    return () => request.current?.abort();
  }, [reload]);

  async function capture() {
    if (!history || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setComparison(null);
    try {
      const response = await networkApi.captureTopology(scope, history.revision, { signal: controller.signal });
      if (!controller.signal.aborted) {
        apply(response.data);
        setNotice("Scoped topology projection retained. No network change or packet probe was performed.");
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setHistory(null);
        setError(`${reason instanceof Error ? reason.message : "Capture failed."} Result was not confirmed. Reload topology history before retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  const baselineIndex = history?.captures.findIndex(row => row.capture_id === baseline) ?? -1;
  const targetIndex = history?.captures.findIndex(row => row.capture_id === target) ?? -1;
  const validPair = baselineIndex >= 0 && targetIndex > baselineIndex;
  async function compare(nextOffset: number) {
    if (!validPair || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setComparison(null);
    try {
      const response = await networkApi.compareTopology(scope, baseline, target, nextOffset, { signal: controller.signal });
      if (!controller.signal.aborted) { setComparison(response.data); setOffset(nextOffset); }
    } catch (reason) {
      if (!controller.signal.aborted) setError(`${reason instanceof Error ? reason.message : "Comparison failed."} Reload history if a capture is no longer retained.`);
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  return <section className="network-history network-workspace" aria-label="Topology history" aria-busy={busy}>
    <div className="network-history-heading"><div><h2>Topology history</h2>
      <p>Retain scoped configuration projections, then compare what was represented in two captures.</p></div>
      <div className="network-history-actions">
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void reload()}>Reload topology history</button>
        <button type="button" className="button button-primary" disabled={busy || !history} onClick={() => void capture()}>Capture current topology</button>
      </div>
    </div>
    <p>Personal to your account and exact selected scope. The latest 5 explicit captures are retained, within a 2 MiB document limit. Loading history never refreshes the network.</p>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">Loading topology evidence…</p>}
    {history && <>
      <p>{history.captures.length} of 5 retained captures · history revision {history.revision}</p>
      {history.captures.length === 0 && <p>No retained topology in this scope. Capture current topology to start a history; older data is not backfilled.</p>}
      {history.captures.length === 1 && <>{receipt(history.captures[0], "Retained capture")}<p>Capture another observation before comparing.</p></>}
      {history.captures.length > 1 && <>
        <div className="network-history-selectors">
          {(["baseline", "target"] as const).map(which => <label key={which} htmlFor={`${id}-${which}`}>
            {which === "baseline" ? "Earlier capture" : "Later capture"}
            <select className="form-control" id={`${id}-${which}`} disabled={busy}
              value={which === "baseline" ? baseline : target}
              onChange={event => {
                (which === "baseline" ? setBaseline : setTarget)(event.target.value);
                setComparison(null); setOffset(0); setError(""); setNotice("");
              }}>
              {history.captures.map((row, index) => <option key={row.capture_id} value={row.capture_id}>{index + 1}. {row.finished_at} · {row.nodes.length} nodes</option>)}
            </select>
          </label>)}
          <button type="button" className="button button-secondary" disabled={busy || !validPair} onClick={() => void compare(0)}>Compare retained captures</button>
        </div>
        {!validPair && <p>Select two distinct captures in capture order.</p>}
        {validPair && <div className="network-history-receipts">
          {receipt(history.captures[baselineIndex], "Earlier projection")}
          {receipt(history.captures[targetIndex], "Later projection")}
          {history.captures[baselineIndex].source_observed_at === history.captures[targetIndex].source_observed_at &&
            <p>Source observation timestamps coincide or are both unreported. Separate capture requests do not prove independent source observations.</p>}
        </div>}
        {comparison && <>
          <p role="status">{comparison.total} projected differences: {comparison.counts.added} added, {comparison.counts.no_longer_observed} no longer observed, {comparison.counts.changed} changed.</p>
          <p>Absence means not represented in the later projection, not deleted. Differences do not prove lifecycle events, cause, remediation success or live reachability.</p>
          {comparison.total === 0 ? <p>No differences in retained fields. This is not proof that the estate did not change.</p> : <>
            <div className="network-history-table" role="region" aria-label="Retained topology differences" tabIndex={0}>
              <table className="data-table"><caption>Differences {offset + 1}–{Math.min(offset + comparison.changes.length, comparison.total)} of {comparison.total}</caption>
                <thead><tr><th>Projected element</th><th>Difference</th><th>Retained evidence</th></tr></thead>
                <tbody>{comparison.changes.map(row => <tr key={`${row.kind}:${row.id}`}>
                  <td>{row.kind}<span>{row.id}</span></td>
                  <td>{row.change.replaceAll("_", " ")}{row.changed_fields.length > 0 && <span>Fields: {row.changed_fields.join(", ")}</span>}</td>
                  <td><details><summary>Review before and after</summary><h4>Earlier projection</h4>{projection(row.before)}<h4>Later projection</h4>{projection(row.after)}</details></td>
                </tr>)}</tbody>
              </table>
            </div>
            <div className="network-history-actions">
              <button type="button" className="button button-secondary" disabled={busy || offset === 0} onClick={() => void compare(Math.max(0, offset - 50))}>Previous differences</button>
              <button type="button" className="button button-secondary" disabled={busy || offset + 50 >= comparison.total} onClick={() => void compare(offset + 50)}>Next differences</button>
            </div>
          </>}
        </>}
      </>}
    </>}
    <details><summary>Projection and evidence boundaries</summary>
      <p>Captures retain fixed node metadata, directed relationships and peering configuration flags from an untruncated summary. Raw rules, tags, arbitrary properties and boundary peering identities are excluded. Truncated sources fail capture; narrow the scope rather than treating omissions as removals.</p>
      <p>Summary detail exclusions and dropped relationships mean this is not complete estate coverage. Source generation is unreported. There is no backfill, continuous collection, automatic expiry, packet probing, deployment or inferred execution authority.</p>
    </details>
  </section>;
}
