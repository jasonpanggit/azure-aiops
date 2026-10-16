"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { networkApi } from "@/lib/services";
import type { ScopeSelection } from "@/lib/scope";
import { scopeToSearchParams } from "@/lib/scope";
import type { NetworkIntentSuite, NetworkIntentTest } from "@/lib/types";

interface Props { scope: ScopeSelection }
type Draft = Omit<NetworkIntentTest, "test_id" | "port"> & { test_id: string; port: string };
const EMPTY: Draft = {
  test_id: "", name: "", source: "", destination: "", port: "443",
  protocol: "Tcp", expected_verdict: "allowed",
};

/** Personal, exact-scope saved expectations with explicitly acquired configuration receipts. */
export function ConnectivityIntents({ scope }: Props) {
  const query = scopeToSearchParams(scope);
  query.sort();
  return <IntentPanel key={query.toString()} scope={scope} />;
}

function IntentPanel({ scope }: Props) {
  const [suite, setSuite] = useState<NetworkIntentSuite | null>(null);
  const [tests, setTests] = useState<NetworkIntentTest[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [runId, setRunId] = useState("");
  const request = useRef<AbortController | null>(null);
  const nameInput = useRef<HTMLInputElement | null>(null);
  const id = useId();
  const dirty = suite !== null && JSON.stringify(suite.tests) !== JSON.stringify(tests);
  const pendingDraft = draft.test_id !== "" || draft.name !== "" || draft.source !== "" ||
    draft.destination !== "" || draft.port !== EMPTY.port || draft.protocol !== EMPTY.protocol ||
    draft.expected_verdict !== EMPTY.expected_verdict;

  function apply(next: NetworkIntentSuite) {
    setSuite(next); setTests(next.tests); setRunId(next.runs.at(-1)?.run_id ?? "");
  }

  const reload = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice(""); setSuite(null); setTests([]); setDraft(EMPTY);
    try {
      const response = await networkApi.intents(scope, { signal: controller.signal });
      if (!controller.signal.aborted) apply(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Saved connectivity tests are unavailable.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }, [scope]);

  useEffect(() => {
    void reload();
    return () => request.current?.abort();
  }, [reload]);

  async function mutate(action: "save" | "run") {
    if (!suite || request.current || pendingDraft) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = action === "save"
        ? await networkApi.saveIntents(scope, suite.revision, tests, { signal: controller.signal })
        : await networkApi.runIntents(scope, suite.revision, { signal: controller.signal });
      if (!controller.signal.aborted) {
        apply(response.data);
        setNotice(action === "save" ? "Declarations saved. No network analysis or infrastructure change was performed." : "Configuration analysis retained. This is not a packet probe.");
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setSuite(null); setTests([]);
        setError(`${reason instanceof Error ? reason.message : "Request failed."} Result was not confirmed. Reload saved tests before retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  function stage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!suite || busy || (!draft.test_id && tests.length >= 20)) return;
    const next: NetworkIntentTest = {
      ...draft, test_id: draft.test_id || crypto.randomUUID(),
      name: draft.name.trim(), source: draft.source.trim(), destination: draft.destination.trim(),
      port: Number(draft.port),
    };
    if (!next.name || !next.source || !next.destination) {
      setError("Name and both endpoints must contain non-space characters."); return;
    }
    setTests(current => draft.test_id
      ? current.map(test => test.test_id === draft.test_id ? next : test) : [...current, next]);
    setDraft(EMPTY); setError(""); setNotice("Local declaration staged. Save tests before running.");
    nameInput.current?.focus();
  }

  const run = suite?.runs.find(row => row.run_id === runId);
  const field = (key: "name" | "source" | "destination" | "port", label: string, maxLength: number) => (
    <label htmlFor={`${id}-${key}`}>{label}
      <input id={`${id}-${key}`} ref={key === "name" ? nameInput : undefined}
        className="form-control" required maxLength={maxLength}
        type={key === "port" ? "number" : "text"}
        min={key === "port" ? 1 : undefined} max={key === "port" ? 65535 : undefined}
        step={key === "port" ? 1 : undefined} value={draft[key]}
        onChange={event => setDraft(current => ({ ...current, [key]: event.target.value }))} />
    </label>
  );

  return <section className="network-intents network-workspace" aria-label="Saved connectivity tests" aria-busy={busy}>
    <div className="network-intents-heading">
      <div><h2>Saved connectivity tests</h2>
        <p>Declare expected rule decisions, then rerun them against current scoped configuration.</p></div>
      <button type="button" className="button button-secondary" disabled={busy} onClick={() => void reload()}>
        {dirty || pendingDraft ? "Discard local edits and reload" : "Reload saved tests"}
      </button>
    </div>
    <p>Personal to your account and exact selected scope. Up to 20 tests and the latest 10 explicit run receipts.</p>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">Loading or saving connectivity evidence…</p>}
    {suite && <>
      <form onSubmit={stage}>
        <fieldset disabled={busy} className="network-intents-form">
          <legend>{draft.test_id ? "Edit declaration" : "Add a declaration"}</legend>
          {field("name", "Test name", 80)}
          {field("source", "Source endpoint", 512)}
          {field("destination", "Destination endpoint", 512)}
          {field("port", "Destination port", 5)}
          <label htmlFor={`${id}-protocol`}>Protocol<select id={`${id}-protocol`} className="form-control"
            value={draft.protocol} onChange={event => setDraft(current => ({ ...current, protocol: event.target.value === "Udp" ? "Udp" : "Tcp" }))}>
            <option value="Tcp">TCP</option><option value="Udp">UDP</option>
          </select></label>
          <label htmlFor={`${id}-expected`}>Expected configuration verdict<select id={`${id}-expected`} className="form-control"
            value={draft.expected_verdict} onChange={event => setDraft(current => ({ ...current, expected_verdict: event.target.value === "denied" ? "denied" : "allowed" }))}>
            <option value="allowed">Allowed</option><option value="denied">Denied</option>
          </select></label>
          <div className="network-intents-actions">
            <button type="submit" className="button button-secondary" disabled={!draft.test_id && tests.length >= 20}>
              {draft.test_id ? "Stage edited test" : "Stage test"}
            </button>
            {pendingDraft && <button type="button" className="button button-ghost" onClick={() => { setDraft(EMPTY); nameInput.current?.focus(); }}>Clear form</button>}
          </div>
        </fieldset>
      </form>
      <p>Use a subnet or network-interface ARM ID, a workload with an observed NIC, an IP, or Internet. Unresolved endpoints stay indeterminate.</p>
      <div className="network-intents-table" role="region" aria-label="Connectivity declarations" tabIndex={0}>
        <table className="data-table"><caption>{tests.length} of 20 tests · {dirty ? "Unsaved local declarations" : `Saved revision ${suite.revision}`}</caption>
          <thead><tr><th>Test / endpoints</th><th>Port / protocol</th><th>Expected</th><th>Review</th></tr></thead>
          <tbody>{tests.map(test => <tr key={test.test_id}>
            <td><strong>{test.name}</strong><span>{test.source} → {test.destination}</span></td>
            <td>{test.port} / {test.protocol.toUpperCase()}</td><td>{test.expected_verdict}</td>
            <td><div className="network-intents-actions">
              <button type="button" className="button button-ghost" disabled={busy || pendingDraft}
                aria-label={`Edit ${test.name}`} onClick={() => { setDraft({ ...test, port: String(test.port) }); nameInput.current?.focus(); }}>Edit</button>
              <button type="button" className="button button-ghost" disabled={busy || pendingDraft}
                aria-label={`Remove ${test.name}`} onClick={() => { setTests(current => current.filter(row => row.test_id !== test.test_id)); setNotice("Removal staged. Save tests to persist it."); }}>Remove</button>
            </div></td>
          </tr>)}</tbody>
        </table>
      </div>
      {tests.length === 0 && <p>No declarations in this scope. Add a test before running.</p>}
      <div className="network-intents-actions">
        <button type="button" className="button button-primary" disabled={busy || !dirty || pendingDraft} onClick={() => void mutate("save")}>Save tests</button>
        <button type="button" className="button button-secondary" disabled={busy || dirty || pendingDraft || !suite.tests.length} onClick={() => void mutate("run")}>Run saved tests</button>
      </div>
      {pendingDraft && <p>Stage or clear the form before saving or running.</p>}
      {suite.runs.length > 0 && <div className="network-intents-receipts">
        <h3>Retained configuration runs</h3>
        <label htmlFor={`${id}-run`}>Run receipt<select id={`${id}-run`} className="form-control" value={runId} onChange={event => setRunId(event.target.value)}>
          {suite.runs.map(row => <option key={row.run_id} value={row.run_id}>{row.finished_at} · reviewed revision {row.reviewed_revision}</option>)}
        </select></label>
        {run && <>
          <p>Source observed: {run.source_observed_at || "Not reported"}. Started {run.started_at}; finished {run.finished_at}.</p>
          <p>These are the exact declarations tested at revision {run.reviewed_revision}, not a result for unsaved or subsequently edited tests.</p>
          <div className="network-intents-table" role="region" aria-label="Retained connectivity results" tabIndex={0}>
            <table className="data-table"><caption>Configuration-only outcomes</caption>
              <thead><tr><th>Test / tested endpoints</th><th>Expected / returned</th><th>Outcome</th><th>Evidence gaps</th></tr></thead>
              <tbody>{run.results.map(row => <tr key={row.test.test_id}>
                <td><strong>{row.test.name}</strong><span>{row.test.source} → {row.test.destination}</span><span>{row.test.protocol.toUpperCase()} {row.test.port}</span></td>
                <td>{row.test.expected_verdict} / {row.verdict}</td><td>{row.outcome}</td>
                <td>{row.unknown_count} unknowns; {row.missing_enforcement_count} missing enforcement points</td>
              </tr>)}</tbody>
            </table>
          </div>
        </>}
      </div>}
    </>}
    <details><summary>Evidence and retention boundaries</summary>
      <p>Matches are configuration expectations, not demonstrated connectivity or compliance. An unresolved verdict, unknown evidence or missing enforcement point never matches. Source generation and complete topology coverage are unreported; repeated source timestamps do not prove independent observations.</p>
      <p>No packet probes, schedules, automatic fixes, deployment approvals or global design-policy changes occur here. Receipts retain declarations and verdict counts, not raw rules or errors. Only the latest 10 runs remain; there is no historical backfill or automatic expiry.</p>
    </details>
  </section>;
}
