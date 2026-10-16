"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { servicePortfolioApi } from "@/lib/services";
import { comparePortfolio, portfolioDelta } from "@/lib/portfolio-comparison";
import { overviewHref } from "@/lib/overview";
import type { ScopeSelection } from "@/lib/scope";
import type { PortfolioService, ServicePortfolioHistory as History } from "@/lib/types";

function mapping(row: PortfolioService | null) {
  if (!row) return "Label absent from collection";
  if (!row.connection_rows) return "No connection mapping rows in collection";
  return `${row.mapped_rows}/${row.connection_rows} mapped; ${row.missing_owner} missing owner, ${row.missing_support_team} missing support, ${row.missing_environment} missing environment`;
}

/** Explicit server-owned portfolio collections with noncausal, extent-aware comparisons. */
export function ServicePortfolioHistory({ scope }: { scope: ScopeSelection }) {
  return <PortfolioWorkspace key={JSON.stringify(scope)} scope={scope} />;
}

function PortfolioWorkspace({ scope }: { scope: ScopeSelection }) {
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [beforeId, setBeforeId] = useState("");
  const [afterId, setAfterId] = useState("");
  const [query, setQuery] = useState("");
  const [changedOnly, setChangedOnly] = useState(false);
  const mounted = useRef(false);
  const request = useRef(0);
  function apply(next: History) {
    setHistory(next);
    setBeforeId(next.observations.at(-2)?.observation_id ?? "");
    setAfterId(next.observations.at(-1)?.observation_id ?? "");
  }
  useEffect(() => {
    mounted.current = true;
    const id = ++request.current;
    servicePortfolioApi.history(scope).then(response => {
      if (mounted.current && id === request.current) apply(response.data);
    }).catch((reason: unknown) => {
      if (mounted.current && id === request.current) setError(reason instanceof Error ? reason.message : "Service portfolio history unavailable");
    }).finally(() => {
      if (mounted.current && id === request.current) setBusy(false);
    });
    return () => { mounted.current = false; };
  }, [scope]);

  async function load(capture: boolean) {
    if (busy || (capture && !history)) return;
    setBusy(true); setError(""); setNotice("");
    const id = ++request.current;
    try {
      const response = capture && history ? await servicePortfolioApi.capture(scope, history.revision) : await servicePortfolioApi.history(scope);
      if (!mounted.current || id !== request.current) return;
      apply(response.data);
      setNotice(capture ? "Server portfolio retained. Current catalog rows are a separate read." : "Retained portfolio reloaded.");
    } catch (reason) {
      if (mounted.current && id === request.current) setError(reason instanceof Error ? reason.message : "Portfolio request failed");
    } finally {
      if (mounted.current && id === request.current) setBusy(false);
    }
  }
  const observations = history?.observations ?? [];
  const before = observations.find(row => row.observation_id === beforeId);
  const after = observations.find(row => row.observation_id === afterId);
  const chronological = before && after && Date.parse(before.captured_at) < Date.parse(after.captured_at);
  const rows = before && after ? comparePortfolio(before, after).filter(row =>
    row.name.toLowerCase().includes(query.toLowerCase().trim()) && (!changedOnly || row.changed)) : [];
  return <section className="card service-brief" aria-label="Retained service portfolio">
    <div className="card-header"><div><h2>Compare retained service portfolios</h2><p>Capture authorized registry mappings and loaded incident associations on the server, not a browser-submitted score.</p></div></div>
    <div className="card-body">
      <p>Private to your principal and exact effective scope. Latest 20 explicit captures, at most 250 labels per capture and 2 MiB per history document.
        Oldest replaced on capture 21; no automatic schedule, time-based expiry, historical backfill or continuous coverage.
        Both sources must succeed. Registry limit: 10,000 accessible connections, including disabled rows; incidents: first 100 report rows, with reported total/partial extent retained.</p>
      <div className="overview-history-controls">
        <button type="button" className="button button-primary" disabled={busy || !history} onClick={() => void load(true)}>{busy ? "Working…" : "Capture service portfolio"}</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void load(false)}>Reload service portfolios</button>
      </div>
      {error && <p role="alert">{error} No successful capture is asserted. Reload before retrying after a conflict.</p>}
      {notice && <p role="status">{notice}</p>}
      {history && <p>Portfolio revision {history.revision}; {observations.length}/20 observations retained. Only label-level aggregates and source provenance are stored, not raw connection/resource identities or credentials.</p>}
      {!busy && observations.length < 2 && <p>Two retained portfolios are needed. No prior movement is inferred.</p>}
      {observations.length >= 2 && <>
        <div className="overview-history-controls">
          <label>Earlier portfolio <select aria-label="Earlier portfolio" value={beforeId} onChange={event => setBeforeId(event.target.value)}>
            {observations.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id.slice(0, 8)}</option>)}
          </select></label>
          <label>Later portfolio <select aria-label="Later portfolio" value={afterId} onChange={event => setAfterId(event.target.value)}>
            {observations.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id.slice(0, 8)}</option>)}
          </select></label>
        </div>
        {!chronological ? <p role="status">Choose different portfolios in chronological order.</p> : <>
          <div className="overview-history-controls">
            <label>Find service label <input value={query} maxLength={256} onChange={event => setQuery(event.target.value)} /></label>
            <label className="service-checkbox"><input type="checkbox" checked={changedOnly} onChange={event => setChangedOnly(event.target.checked)} /> Only changed observations</label>
          </div>
          <p>{rows.length} matching label comparisons; at most 50 shown. Labels absent from either collection are not comparable, not zero or proof of service creation/deletion.
            Associations can overlap across services, and source populations/extents may change. No new/resolved incidents, verified improvement, availability or causation is established.</p>
          <p className="service-scroll-hint">More columns may be off-screen. Scroll horizontally, or focus the table and use arrow keys.</p>
          <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Retained service label comparisons, horizontally scrollable">
            <table className="data-table"><caption>Collection-to-collection arithmetic; no same-population or reliability claim</caption>
              <thead><tr><th>Service label</th><th>Earlier mapping</th><th>Later mapping</th><th>Mapped-row change</th><th>Incident associations, earlier → later</th><th>Association change</th></tr></thead>
              <tbody>{rows.slice(0, 50).map(row => <tr key={row.key}>
                <th scope="row"><Link href={overviewHref((row.later ?? row.earlier)?.kind === "unmapped" ? "/connections" : `/services/${encodeURIComponent(row.name)}`, scope)}>{row.name}</Link></th>
                <td>{mapping(row.earlier)}</td><td>{mapping(row.later)}</td><td>{portfolioDelta(row.earlier, row.later, "mapped_rows")}</td>
                <td>{row.earlier?.incident_associations ?? "Absent label"} → {row.later?.incident_associations ?? "Absent label"}<br />
                  Critical: {row.earlier?.critical_associations ?? "unreported"} → {row.later?.critical_associations ?? "unreported"}</td>
                <td>{portfolioDelta(row.earlier, row.later, "incident_associations")}</td>
              </tr>)}</tbody>
            </table>
          </div>
          <details><summary>Inspect both portfolio source extents and freshness</summary>
            {[before, after].map(observation => <div key={observation.observation_id}><h3>{observation.captured_at}</h3>
              <p>Receipt {observation.observation_id}; {observation.services.length} loaded labels. Receipt time is not source time or a freshness assertion.</p>
              <ul>{observation.sources.map(source => <li key={source.id}>
                {source.id}: {source.loaded} loaded / {source.total} reported; {source.partial ? "partial report" : "complete reported collection"};
                {" "}collected {source.started_at} to {source.finished_at}; source observation times: {source.observed_at.join(", ") || "unreported"};
                {" "}reported freshness: {source.reported_freshness.join(", ") || "unreported"}; tables: {source.source_tables.join(", ") || "unreported"};
                {" "}version: {source.knowledge_version || "unreported"}; warnings: {source.warning_count}.
              </li>)}</ul>
            </div>)}
          </details>
        </>}
      </>}
    </div>
  </section>;
}
