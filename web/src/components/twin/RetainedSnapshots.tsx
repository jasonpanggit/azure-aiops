"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StructuredData } from "@/components/ui/StructuredData";
import { TablePagination } from "@/components/ui/TablePagination";
import { formatDateTime } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { twinApi } from "@/lib/services";
import type { RetainedTwinEntity, RetainedTwinRelationship, TwinCaptureComparison, TwinDelta, TwinHistory, TwinScenarioPair } from "@/lib/twin-history";
import { useTablePagination } from "@/lib/use-table-pagination";

const SCENARIOS = ["firewall_failure", "route_change", "subscription_outage", "cve_exploitation", "patch_deployment", "architecture_remediation"];
type Declaration = RetainedTwinEntity | RetainedTwinRelationship;
interface Difference { id: string; kind: string; change: string; before?: Declaration; after?: Declaration; fields: string[] }

function differences<T extends Declaration>(delta: TwinDelta<T>, kind: string): Difference[] {
  return [
    ...delta.added.map(after => ({ id: after.id, kind, change: "Added", after, fields: [] })),
    ...delta.removed.map(before => ({ id: before.id, kind, change: "Removed", before, fields: [] })),
    ...delta.changed.map(row => ({ ...row, kind, change: "Changed" })),
  ];
}

/** Explicit durable capture, comparison and same-evidence review, isolated by exact scope. */
export function RetainedSnapshots({ scope }: { scope: ScopeSelection }) {
  const query = scopeToSearchParams(scope);
  query.sort();
  return <Workspace key={query.toString()} scope={scope} />;
}

function Workspace({ scope }: { scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  return <section className="card twin-history" aria-label="Retained Twin snapshots">
    <div className="card-header">
      <div><h2>Retained snapshots and scenario comparison</h2><p>Personal historical projections for this exact authorized scope, separate from the current request-time graph.</p></div>
      <button type="button" className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? "Close retained snapshots" : "Open retained snapshots"}
      </button>
    </div>
    {open ? <Panel scope={scope} /> : null}
  </section>;
}

function Panel({ scope }: { scope: ScopeSelection }) {
  const [state, setState] = useState<TwinHistory | null>(null);
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const [comparison, setComparison] = useState<TwinCaptureComparison | null>(null);
  const [scenarioCapture, setScenarioCapture] = useState("");
  const [target, setTarget] = useState("");
  const [left, setLeft] = useState("firewall_failure");
  const [right, setRight] = useState("patch_deployment");
  const [pair, setPair] = useState<TwinScenarioPair | null>(null);
  const [confirmDelete, setConfirmDelete] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const rows = useMemo(() => comparison ? [
    ...differences(comparison.entities, "Entity"), ...differences(comparison.relationships, "Relationship"),
  ] : [], [comparison]);
  const paging = useTablePagination(rows);
  const selectedCapture = state?.captures.find(capture => capture.snapshot_id === scenarioCapture);
  const resources = selectedCapture?.projection.entities.filter(entity => entity.kind === "resource") ?? [];

  const clear = () => {
    setBaseline(""); setCandidate(""); setComparison(null);
    setScenarioCapture(""); setTarget(""); setPair(null); setConfirmDelete("");
  };
  const reload = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setState(null); setError(""); setNotice("");
    setBaseline(""); setCandidate(""); setComparison(null);
    setScenarioCapture(""); setTarget(""); setPair(null); setConfirmDelete("");
    try {
      const response = await twinApi.snapshots(scope, controller.signal);
      if (!controller.signal.aborted) setState(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Retained snapshots could not be read.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }, [scope]);
  useEffect(() => {
    void reload();
    return () => { request.current?.abort(); request.current = null; };
  }, [reload]);

  async function mutate(removeId?: string) {
    if (!state || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); clear();
    try {
      const response = removeId
        ? await twinApi.removeSnapshot(scope, removeId, state.revision, controller.signal)
        : await twinApi.captureSnapshot(scope, state.revision, controller.signal);
      if (!controller.signal.aborted) {
        setState(response.data);
        setNotice(removeId ? "Snapshot deleted; source observations were not changed." : "A fresh server composition was retained. It is not the earlier displayed graph or an approval.");
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setState(null);
        setError(`${reason instanceof Error ? reason.message : "Snapshot operation failed."} The write was not confirmed. Reload retained snapshots before explicitly retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  async function analyze(kind: "comparison" | "scenarios") {
    if (!state || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice("");
    if (kind === "comparison") { setComparison(null); paging.setPage(0); }
    else setPair(null);
    try {
      if (kind === "comparison") {
        const response = await twinApi.compareSnapshots(scope, baseline, candidate, controller.signal);
        if (!controller.signal.aborted) setComparison(response.data);
      } else {
        const response = await twinApi.retainedScenarios(scope, scenarioCapture, left, right, target, controller.signal);
        if (!controller.signal.aborted) setPair(response.data);
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Historical review could not be confirmed; reload retained snapshots.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  const options = state?.captures.map(capture => <option key={capture.snapshot_id} value={capture.snapshot_id}>
    {capture.snapshot_id} · {formatDateTime(capture.projection.composed_at)}
  </option>);
  return <div className="card-body twin-history-body" aria-busy={busy}>
    <p>Capture a fresh server composition explicitly. Up to 10 captures, 5000 entities/20000 links and 2 MiB each, 12 MiB total; oversized data is rejected, never silently truncated or evicted. Raw tags, semantic attributes, incident text and arbitrary provider properties are excluded. History reads and comparisons do not contact current providers.</p>
    <p className="muted">Historical reviews are separate from the current-state Copilot context. Digests check consistency, not source authenticity. Deleting a capture is irreversible but does not change source resources.</p>
    {busy ? <p role="status">Reading or updating retained Twin evidence...</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    <div className="twin-history-controls">
      <button type="button" className="button" disabled={busy} onClick={() => void reload()}>Reload retained snapshots</button>
      <button type="button" className="button" disabled={busy || !state || state.captures.length >= 10} onClick={() => void mutate()}>Capture fresh scoped snapshot</button>
    </div>
    {state ? <>
      <p>Revision {state.revision}. {state.captures.length}/10 captures in this exact personal scope.</p>
      {state.captures.length === 0 ? <p>No retained snapshots in this exact personal scope.</p> : <ul className="twin-capture-list">
        {state.captures.map(capture => <li key={capture.snapshot_id}>
          <strong>Composed {formatDateTime(capture.projection.composed_at)}</strong>
          <span>Snapshot {capture.snapshot_id}</span>
          <span>{capture.projection.entities.length} entities · {capture.projection.relationships.length} relationships · retained {formatDateTime(capture.retained_at)}</span>
          <code>SHA-256 {capture.snapshot_sha256}</code>
          <details><summary>Retained source evidence</summary>
            <ul>{capture.projection.provenance.map((source, index) => <li key={`${source.source}-${index}`}>{source.source}: {source.confidence} confidence</li>)}</ul>
            {capture.projection.warnings.length ? <ul>{capture.projection.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : <p>No source warnings were reported; completeness is not established.</p>}
          </details>
          {confirmDelete === capture.snapshot_id ? <div className="twin-history-controls">
            <button className="button" type="button" disabled={busy} onClick={() => void mutate(capture.snapshot_id)}>Confirm delete snapshot {capture.snapshot_id}</button>
            <button className="button" type="button" disabled={busy} onClick={() => setConfirmDelete("")}>Cancel deletion</button>
          </div> : <button className="button" type="button" disabled={busy} onClick={() => setConfirmDelete(capture.snapshot_id)}>Delete snapshot {capture.snapshot_id}</button>}
        </li>)}
      </ul>}
      <div className="twin-history-section">
        <h3>Compare retained captures</h3>
        <div className="twin-history-selectors">
          <label>Baseline snapshot<select value={baseline} disabled={busy} onChange={event => { setBaseline(event.target.value); setComparison(null); }}><option value="">Select baseline</option>{options}</select></label>
          <label>Candidate snapshot<select value={candidate} disabled={busy} onChange={event => { setCandidate(event.target.value); setComparison(null); }}><option value="">Select candidate</option>{options}</select></label>
        </div>
        <button className="button" type="button" disabled={busy || !baseline || !candidate || baseline === candidate} onClick={() => void analyze("comparison")}>Compare selected captures</button>
        {comparison ? <>
          <p>{comparison.interpretation}</p>
          <p>{rows.length} safe declaration differences between {formatDateTime(comparison.baseline_composed_at)} and {formatDateTime(comparison.candidate_composed_at)}.</p>
          <details><summary>Baseline and candidate source warnings</summary>
            <strong>Baseline</strong>
            {comparison.warnings.baseline.length ? <ul>{comparison.warnings.baseline.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : <p>No source warnings reported; completeness is not established.</p>}
            <strong>Candidate</strong>
            {comparison.warnings.candidate.length ? <ul>{comparison.warnings.candidate.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : <p>No source warnings reported; completeness is not established.</p>}
          </details>
          <div className="twin-history-table" role="region" aria-label="Scrollable retained capture differences" tabIndex={0}>
            <table><thead><tr><th>Declaration</th><th>Difference</th><th>Identity</th><th>Safe evidence</th></tr></thead>
              <tbody>{paging.pageRows.map(row => <tr key={`${row.kind}:${row.change}:${row.id}`}>
                <td>{row.kind}</td><td>{row.change}</td><td>{row.id}</td>
                <td><details><summary>View before / after{row.fields.length ? ` (${row.fields.join(", ")})` : ""}</summary><StructuredData value={{ before: row.before ?? null, after: row.after ?? null }} /></details></td>
              </tr>)}</tbody></table>
          </div>
          {rows.length === 0 ? <p>No safe declaration differences. This does not prove no source changes occurred.</p> : null}
          <TablePagination page={paging.page} pageRows={paging.pageRows.length} total={paging.total}
            pageSize={paging.pageSize} onPageChange={paging.setPage} onPageSizeChange={paging.setPageSize}
            label="retained Twin differences" />
        </> : null}
      </div>
      <div className="twin-history-section">
        <h3>Compare scenarios on the same evidence</h3>
        <p>Two hypothetical review questions, one immutable retained graph. Related sets can be identical: no scenario-specific failure propagation or measured outcomes are inferred.</p>
        <div className="twin-history-selectors">
          <label>Scenario snapshot<select value={scenarioCapture} disabled={busy} onChange={event => { setScenarioCapture(event.target.value); setTarget(""); setPair(null); }}><option value="">Select retained evidence</option>{options}</select></label>
          <label>Retained resource<select value={target} disabled={busy || !selectedCapture} onChange={event => { setTarget(event.target.value); setPair(null); }}><option value="">Select exact retained resource</option>{resources.map(entity => <option key={entity.id} value={entity.id}>{entity.name} · {entity.id}</option>)}</select></label>
          <label>Left scenario<select value={left} disabled={busy} onChange={event => { setLeft(event.target.value); setPair(null); }}>{SCENARIOS.map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
          <label>Right scenario<select value={right} disabled={busy} onChange={event => { setRight(event.target.value); setPair(null); }}>{SCENARIOS.map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
        </div>
        <button className="button" type="button" disabled={busy || !scenarioCapture || !target || left === right} onClick={() => void analyze("scenarios")}>Compare scenarios</button>
        {pair ? <div className="twin-pair-review" aria-label="Same-evidence scenario comparison">
          <p>{pair.interpretation}</p>
          <p>Snapshot {pair.snapshot_id} · composed {formatDateTime(pair.composed_at)}.</p>
          <code>Both reviews bound to SHA-256 {pair.snapshot_sha256}</code>
          {pair.left.warnings.map((warning, index) => <p className="muted" key={index}>{warning}</p>)}
          <div className="twin-scenario-columns">
            {[pair.left, pair.right].map((result, index) => <article key={`${index}:${result.scenario}`}>
              <h4>{index === 0 ? "Left" : "Right"}: {result.scenario.replaceAll("_", " ")}</h4>
              <p>{result.likely_impact}</p>
              <p>{result.impacted_total} related entities discovered; showing {result.impacted_entities.length}. {result.truncated ? "Partial projection: traversal or display limits reached." : "Within disclosed bounds."}</p>
              <p>Measured risk delta: not established. Authority: none.</p>
              <ul>{result.assumptions.map(assumption => <li key={assumption}>{assumption}</li>)}</ul>
              <details><summary>Mapped entities and retained provenance</summary><StructuredData value={result.impacted_entities} /></details>
            </article>)}
          </div>
        </div> : null}
      </div>
    </> : null}
  </div>;
}
