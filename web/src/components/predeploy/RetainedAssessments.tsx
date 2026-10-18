"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TablePagination } from "@/components/ui/TablePagination";
import { downloadJson } from "@/lib/download-json";
import { formatDateTime, titleize } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { predeployApi } from "@/lib/services";
import { useTablePagination } from "@/lib/use-table-pagination";
import type { AssessmentComparison, AssessmentHistory, AssessmentReceipt } from "@/lib/predeploy-history";
import type { Envelope } from "@/lib/types";

interface Props {
  scope: ScopeSelection;
  current: { assessment_id: string; artifact?: { sha256: string } } | null;
}

/** Explicit personal receipt retention/recovery, isolated to the selected scope. */
export function RetainedAssessments(props: Props) {
  const query = scopeToSearchParams(props.scope);
  query.sort();
  return <Workspace key={query.toString()} {...props} />;
}

function Workspace(props: Props) {
  const [open, setOpen] = useState(false);
  return <section className="card predeploy-history" aria-label="Retained assessment receipts">
    <div className="card-header">
      <div><h2>Retained assessment receipts</h2><p>Personal historical summaries for your exact authorized scope, separate from recent process-local history.</p></div>
      <button type="button" className="button button-secondary" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        {open ? "Close retained assessments" : "Open retained assessments"}
      </button>
    </div>
    {open && <Panel {...props} />}
  </section>;
}

function Panel({ scope, current }: Props) {
  const [state, setState] = useState<AssessmentHistory | null>(null);
  const [comparison, setComparison] = useState<AssessmentComparison | null>(null);
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  const deltaRows = useMemo(() => comparison ? [
    ...comparison.added_declared_rows.map(row => ({ ...row, difference: "Added declared row" })),
    ...comparison.removed_declared_rows.map(row => ({ ...row, difference: "Removed declared row" })),
  ] : [], [comparison]);
  const paging = useTablePagination(deltaRows);
  const clearSelection = () => { setBaseline(""); setCandidate(""); setComparison(null); };
  const sourceBefore = state?.receipts.find(row => row.assessment_id === baseline)?.source;
  const sourceAfter = state?.receipts.find(row => row.assessment_id === candidate)?.source;
  const comparable = Boolean(baseline && candidate && baseline !== candidate && sourceBefore === sourceAfter);
  const currentDigest = current?.artifact?.sha256;
  const alreadyRetained = state?.receipts.some(row => row.assessment_id === current?.assessment_id);

  const reload = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setState(null);
    setBaseline(""); setCandidate(""); setComparison(null);
    try {
      const response = await predeployApi.retained(scope, controller.signal);
      if (!controller.signal.aborted) setState(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Retained assessments could not be read.");
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
    let send: (signal: AbortSignal) => Promise<Envelope<AssessmentHistory>>;
    let message: string;
    if (removeId) {
      send = signal => predeployApi.removeRetained(scope, removeId, state.revision, signal);
      message = "Retained receipt deleted. The source assessment and artifact were not changed.";
    } else if (current && currentDigest) {
      const id = current.assessment_id;
      send = signal => predeployApi.retain(scope, id, currentDigest, state.revision, signal);
      message = `Assessment ${id} retained as a historical summary, not approval.`;
    } else {
      setError("Assess an inspected artifact before retaining its displayed analysis.");
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); clearSelection();
    try {
      const response = await send(controller.signal);
      if (!controller.signal.aborted) {
        setState(response.data);
        setNotice(message);
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setState(null);
        setError(`${reason instanceof Error ? reason.message : "Retention failed."} The write was not confirmed. Reload retained assessments before explicitly retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  async function compare() {
    if (!state || request.current || !comparable) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setComparison(null); paging.setPage(0);
    try {
      const response = await predeployApi.compareRetained(scope, baseline, candidate, controller.signal);
      if (!controller.signal.aborted) setComparison(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Comparison could not be read; reload retained assessments.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  async function exportReview(receipt: AssessmentReceipt) {
    if (!state || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await predeployApi.reviewContract(scope, receipt.assessment_id, receipt.artifact_sha256, controller.signal);
      if (!controller.signal.aborted) {
        downloadJson(`predeploy-ci-review-${receipt.assessment_id}.json`, response.data);
        setNotice(`CI review contract exported: ${response.data.disposition}. This summary is not deployment approval or a signed CI attestation.`);
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "CI review contract could not be exported.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  return <div className="card-body predeploy-history-body" aria-busy={busy}>
    <p>Up to 20 receipts, 256 KiB each and 4 MiB total. Retention is explicit; nothing is automatically evicted. Receipts preserve normalized declared rows and analysis summaries, not raw artifacts or full analysis. No current provider is contacted when recovering or comparing. Export a digest-bound CI review contract for a retained receipt; the read-only CI client separately checks the local artifact and checkout. The CI identity must own the same personal receipt.</p>
    {busy && <p role="status">Reading or updating retained assessment receipts...</p>}
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    <button type="button" className="button button-secondary" disabled={busy} onClick={() => void reload()}>Reload retained assessments</button>
    {state && <>
      <p>Revision {state.revision}. {state.receipts.length}/20 receipts in this exact personal scope.</p>
      {!currentDigest && <p>Assess an inspected artifact before retaining its displayed analysis.</p>}
      <button type="button" className="button button-secondary" disabled={busy || !currentDigest || alreadyRetained || state.receipts.length >= 20} onClick={() => void mutate()}>
        {alreadyRetained ? "Displayed assessment already retained" : "Retain displayed assessment"}
      </button>
      {state.receipts.length === 0 ? <p>No retained assessment receipts in this exact personal scope.</p> : <ul className="predeploy-history-list">
        {state.receipts.map(row => <li key={row.assessment_id}>
          <details><summary>{row.title || row.change_id} · {titleize(row.risk_level)} risk · {titleize(row.verdict)}</summary>
            <p>Assessment {row.assessment_id}. Source: {titleize(row.source)}.</p>
            <p>Assessed {formatDateTime(row.assessed_at)}; retained {formatDateTime(row.retained_at)}.</p>
            <p>Artifact SHA-256 <code>{row.artifact_sha256}</code>.</p>
            <p>Risk {row.risk_score}; {row.confidence} confidence. {row.changes.length} declared rows; {row.impacted_resource_ids.length} represented impacted identities{row.traversal_truncated ? " (traversal truncated)" : ""}.</p>
            <p>{row.unknowns.length} declared unknowns.</p>
            {row.unknowns.length > 0 && <ul>{row.unknowns.map((unknown, index) => <li key={index}>{unknown}</li>)}</ul>}
          </details>
          <div className="predeploy-history-actions"><button type="button" className="button button-ghost" disabled={busy}
            aria-label={`Delete retained assessment ${row.assessment_id}`} onClick={() => void mutate(row.assessment_id)}>Delete receipt</button>
          <button type="button" className="button button-secondary" disabled={busy}
            aria-label={`Export CI review contract ${row.assessment_id}`} onClick={() => void exportReview(row)}>Export CI review contract</button></div>
        </li>)}
      </ul>}
      <div className="predeploy-history-selectors">
        {[{ label: "Baseline receipt", value: baseline, set: setBaseline }, { label: "Candidate receipt", value: candidate, set: setCandidate }].map(({ label, value, set }) =>
          <label className="form-field" key={label}><span>{label}</span>
            <select className="form-control" value={value} disabled={busy} onChange={event => { set(event.target.value); setComparison(null); }}>
              <option value="">Select a retained assessment</option>
              {state.receipts.map(row => <option key={row.assessment_id} value={row.assessment_id}>{row.change_id} · {row.assessment_id}</option>)}
            </select>
          </label>)}
      </div>
      <p>Select two different receipts of the same source format. A changed digest does not establish revision lineage or an applied fix.</p>
      <button type="button" className="button button-secondary" disabled={busy || !comparable} onClick={() => void compare()}>Compare retained assessments</button>
    </>}
    {comparison && <section className="predeploy-history-comparison" aria-label="Declared assessment comparison">
      <h3>Declared assessment comparison</h3>
      <p>{comparison.interpretation}</p>
      <p>{comparison.same_artifact ? "Same submitted artifact digest." : "Different submitted artifact digests."} Risk score difference: {comparison.risk_score_delta}. This is not a runtime reliability change.</p>
      <dl>{[{ label: "Baseline", row: comparison.baseline }, { label: "Candidate", row: comparison.candidate }].map(({ label, row }) =>
        <div key={label}><dt>{label}: {row.assessment_id}</dt><dd>SHA-256 {row.artifact_sha256}; assessed {formatDateTime(row.assessed_at)}; retained {formatDateTime(row.retained_at)}; {row.confidence} confidence; {titleize(row.verdict)}.</dd></div>)}</dl>
      <p>{comparison.added_impacted_resource_ids.length} added and {comparison.removed_impacted_resource_ids.length} removed represented impacted identities. Scope, observation gaps and traversal limits still apply.</p>
      <div className="table-scroll" role="region" aria-label="Declared row differences" tabIndex={0}><table className="data-table"><thead><tr><th>Difference</th><th>Declared address</th><th>Action</th><th>Property names</th></tr></thead>
        <tbody>{paging.pageRows.map((row, index) => <tr key={`${row.difference}-${index}`}><td>{row.difference}</td><td>{row.address}</td><td>{row.action}</td><td>{row.changed_properties.join(", ") || "None declared"}</td></tr>)}</tbody>
      </table></div>
      {!deltaRows.length && <p>No normalized declared-row differences. This does not prove identical raw artifacts or runtime effects.</p>}
      <TablePagination pageRows={paging.pageRows.length} page={paging.page} onPageChange={paging.setPage} total={paging.total} pageSize={paging.pageSize} onPageSizeChange={paging.setPageSize} label="declared row differences" />
    </section>}
  </div>;
}
