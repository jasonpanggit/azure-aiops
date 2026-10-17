"use client";

import { useEffect, useRef, useState } from "react";
import { downloadEvidenceJson, verifyEvidenceBytes } from "@/lib/audit-exports";
import type { ExposureQueryState } from "@/lib/exposure-query-state";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import { vulnerabilityApi } from "@/lib/services";
import type { CveEvidenceHistory, CveEvidenceReceipt, Envelope } from "@/lib/types";

const agrees = (left: Record<string, string[]>, right: Record<string, string[]>) => SCOPE_DIMENSIONS.every(dimension =>
  JSON.stringify([...(left[dimension] ?? [])].sort()) === JSON.stringify([...(right[dimension] ?? [])].sort()));
const hash = (value: string) => /^[a-f0-9]{64}$/.test(value);
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(",")}}`;
  return JSON.stringify(value);
}
function validate(result: Envelope<CveEvidenceHistory>, cveId: string, query: ExposureQueryState) {
  const data = result.data;
  if (!agrees(result.scope, query.scope) || !agrees(data.scope, query.scope) || data.cve_id !== cveId
    || data.schema_version !== 1 || !data.actor || data.revision !== data.receipts.length || data.revision > 20
    || new Set(data.receipts.map(row => row.receipt_id)).size !== data.revision
    || data.receipts.some(row => !/^cve-[a-f0-9]{32}$/.test(row.receipt_id) || row.cve_id !== cveId
      || row.actor !== data.actor || !agrees(row.scope, query.scope) || !hash(row.sha256) || !hash(row.query_fingerprint)
      || !row.generation || !Number.isFinite(Date.parse(row.captured_at)) || row.filters.weakness_id !== cveId
      || !Number.isSafeInteger(row.total_count) || row.total_count < row.findings.length
      || row.findings.length > row.page_size || row.page_size < 1 || row.page_size > 100
      || new Set(row.findings.map(item => item.exposure_id)).size !== row.findings.length
      || row.findings.some(item => item.weakness_id.toUpperCase() !== cveId || !item.target_id || !item.exposure_id
        || !["server", "container_image"].includes(item.target_kind))
      || row.sources.length > 40 || new Set(row.sources.map(item => `${item.source}:${item.identifier}`)).size !== row.sources.length)) {
    throw new Error("Retained CVE evidence does not match this identity or has inconsistent receipt metadata.");
  }
  return data;
}

/** Explicit personal evidence capture, page-bounded comparison and verified-byte export. */
export function CveEvidence({ cveId, query, ready }: { cveId: string; query: ExposureQueryState; ready: boolean }) {
  const [history, setHistory] = useState<CveEvidenceHistory | null>(null);
  const [busy, setBusy] = useState(true), [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [left, setLeft] = useState(""), [right, setRight] = useState("");
  const active = useRef(false), sequence = useRef(0);
  useEffect(() => {
    active.current = true;
    const id = ++sequence.current, controller = new AbortController();
    vulnerabilityApi.cveEvidence(cveId, query.scope, controller.signal).then(result => {
      if (active.current && id === sequence.current) setHistory(validate(result, cveId, query));
    }).catch((reason: unknown) => {
      if (active.current && id === sequence.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Retained CVE evidence unavailable.");
    }).finally(() => { if (active.current && id === sequence.current) setBusy(false); });
    return () => { active.current = false; controller.abort(); };
  }, [cveId, query]);

  async function load(capture: boolean) {
    if (busy || (capture && (!ready || !history || uncertain || !query.generation || history.revision >= 20))) return;
    const id = ++sequence.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = capture ? await vulnerabilityApi.captureCveEvidence(cveId, query, history!.revision) : await vulnerabilityApi.cveEvidence(cveId, query.scope);
      if (!active.current || id !== sequence.current) return;
      const data = validate(result, cveId, query), last = data.receipts.at(-1);
      if (history && (data.actor !== history.actor || data.revision < history.revision
        || stable(data.receipts.slice(0, history.revision)) !== stable(history.receipts))) {
        throw new Error("Retained evidence no longer preserves the previously reviewed identity/history.");
      }
      if (capture && (data.revision !== history!.revision + 1 || stable(data.receipts.slice(0, -1)) !== stable(history!.receipts)
        || last?.generation !== query.generation || last?.page_size !== query.pageSize
        || last?.sort_by !== query.sort.field || last?.sort_direction !== query.sort.direction
        || last?.cursor_page !== Boolean(query.cursor)
        || Object.entries(query.filters).some(([key, value]) => value !== undefined && last?.filters[key as keyof typeof query.filters] !== value))) {
        throw new Error("Capture response does not preserve the reviewed history or query bindings.");
      }
      setHistory(data); setUncertain(false);
      setNotice(capture ? "Server evidence receipt retained. No remediation was performed or verified." : "Retained receipts reloaded. Review before capturing again.");
    } catch (reason) {
      if (!active.current || id !== sequence.current) return;
      setError(reason instanceof Error ? reason.message : "Evidence capture outcome unconfirmed.");
      setUncertain(true);
    } finally { if (active.current && id === sequence.current) setBusy(false); }
  }

  async function download(receipt: CveEvidenceReceipt) {
    if (busy) return;
    const id = ++sequence.current;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await vulnerabilityApi.cveEvidenceBundle(cveId, receipt.receipt_id, query.scope);
      if (!active.current || id !== sequence.current) return;
      const { content, manifest } = result.data;
      if (!agrees(result.scope, query.scope) || manifest.receipt_id !== receipt.receipt_id || manifest.cve_id !== cveId
        || manifest.receipt_sha256 !== receipt.sha256 || stable(JSON.parse(content)) !== stable(receipt)) {
        throw new Error("Evidence bundle does not match the retained receipt.");
      }
      await verifyEvidenceBytes(content, manifest);
      if (!active.current || id !== sequence.current) return;
      downloadEvidenceJson(content, `${cveId}-${receipt.receipt_id}.json`);
      setNotice(`Verified UTF-8 bundle handed to the browser. SHA-256 ${manifest.sha256}. This is integrity, not a signature.`);
    } catch (reason) {
      if (active.current && id === sequence.current) setError(reason instanceof Error ? reason.message : "Evidence download failed.");
    } finally { if (active.current && id === sequence.current) setBusy(false); }
  }
  const first = history?.receipts.find(row => row.receipt_id === left), second = history?.receipts.find(row => row.receipt_id === right);
  const comparable = first && second && first.receipt_id !== second.receipt_id && first.query_fingerprint === second.query_fingerprint;
  return <section className="exposure-detail-section exposure-recovery cve-retained-evidence" aria-label="Retained CVE evidence">
    <div className="card-header"><h2>Retained CVE evidence</h2></div>
    <div className="card-body">
      <p>Explicit server-acquired query-page and public-catalog receipts, private to this principal, CVE and exact scope.
        Capture time differs from independently observed source times. Up to 20 receipts / 512 KiB; no automatic capture or eviction.</p>
      <div className="button-row">
        <button className="button" disabled={busy} onClick={() => void load(false)}>Reload CVE receipts</button>
        <button className="button button-primary" disabled={busy || !ready || !history || uncertain || history.revision >= 20 || !query.generation} onClick={() => void load(true)}>Capture CVE evidence</button>
      </div>
      {busy && <p role="status">Reading CVE evidence…</p>}
      {!ready && <p>Capture requires available current findings and catalog with the same loaded generation. Retained receipts remain readable independently.</p>}
      {error && <p role="alert">{error} No new capture success is asserted. Reload before retrying an unconfirmed capture.</p>}
      {notice && <p role="status">{notice}</p>}
      {history && <p>CVE evidence revision {history.revision}; {history.receipts.length}/20 retained receipts.</p>}
      <p>Only one bounded finding page and allowlisted public signals are retained. No complete estate, exploit path, provider signature,
        patch applicability, approval, remediation verification or continuous change history is asserted. Do not share private asset identifiers unintentionally.</p>
      {history?.receipts.map(receipt => <details className="exposure-recovery-event" key={receipt.receipt_id}>
        <summary>{receipt.receipt_id} — captured {receipt.captured_at}</summary>
        <p>Generation {receipt.generation}; {receipt.findings.length} retained / {receipt.total_count} query findings;
          {" "}{receipt.cursor_page ? "cursor page" : "first page"}; source coverage {receipt.source_completeness};
          {" "}finding source observed {receipt.source_observed_at || "unreported"}.</p>
        <p>Receipt payload SHA-256 {receipt.sha256}. Hash excludes this field; export verifies a separate hash over the exact full JSON bytes.</p>
        <details><summary>Inspect retained query bindings</summary><pre>{JSON.stringify({
          scope: receipt.scope, filters: receipt.filters, sort_by: receipt.sort_by, sort_direction: receipt.sort_direction,
          page_size: receipt.page_size, cursor_page: receipt.cursor_page, query_fingerprint: receipt.query_fingerprint,
        }, null, 2)}</pre></details>
        <ul>{receipt.sources.map(source => <li key={`${source.source}:${source.identifier}`}>{source.source} {source.identifier}: {source.status};
          {" "}{source.stale ? "stale" : "not marked stale"}; source observed {source.source_at || "unreported"};
          {" "}CVSS {source.cvss_score ?? "unknown"}, EPSS {source.epss_score ?? "unknown"}, KEV {source.kev_listed === null ? "unknown" : source.kev_listed ? "listed" : "not listed"}.</li>)}</ul>
        <button className="button" disabled={busy} onClick={() => void download(receipt)}>Download verified bundle {receipt.receipt_id}</button>
      </details>)}
      {history && !history.receipts.length && <p>No receipts retained for this exact identity.</p>}
      <h3>Compare two retained receipts</h3>
      <div className="overview-history-controls">{([["Earlier selection", left, setLeft], ["Later selection", right, setRight]] as const).map(([label, value, setter]) =>
        <label key={label}>{label}<select value={value} onChange={event => setter(event.target.value)}>
          <option value="">Choose a retained receipt</option>{history?.receipts.map(receipt =>
            <option key={receipt.receipt_id} value={receipt.receipt_id}>{receipt.captured_at} · {receipt.receipt_id}</option>)}
        </select></label>)}</div>
      {first && second && !comparable && <p role="status">Choose different receipts with identical filters, sort and page size. Different query selections cannot establish comparable movement.</p>}
      {comparable && <>
        <p>Selection order is not chronology. Captures: {first.captured_at} versus {second.captured_at}.
          Query finding count {first.total_count} → {second.total_count} (difference {second.total_count - first.total_count}).
          Coverage {first.source_completeness} → {second.source_completeness}. Different generations/provider clocks and cursor positions can change observations.</p>
        <p>{second.findings.filter(row => !first.findings.some(old => old.exposure_id === row.exposure_id)).length} retained page identities appear only in the second selection;
          {" "}{first.findings.filter(row => !second.findings.some(next => next.exposure_id === row.exposure_id)).length} only in the first.
          Page membership differences are not new/resolved findings or verified fixes.</p>
        <p>Comparison tables scroll horizontally on narrow screens. Expand a row to inspect both recorded projections.</p>
        <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Retained CVE source comparison, horizontally scrollable">
          <table className="data-table"><caption>Public source receipt differences</caption><thead><tr><th>Source identity</th><th>Comparison</th></tr></thead>
            <tbody>{Array.from(new Set([...first.sources, ...second.sources].map(row => `${row.source}:${row.identifier}`))).sort().map(key => {
              const a = first.sources.find(row => `${row.source}:${row.identifier}` === key), b = second.sources.find(row => `${row.source}:${row.identifier}` === key);
              return <tr key={key}><td>{key}</td><td>{!a ? "Only in second receipt" : !b ? "Only in first receipt" : stable(a) === stable(b) ? "Unchanged recorded fields" : "Recorded fields differ"}
                <details><summary>Inspect source comparison {key}</summary><pre className="exposure-long-value">{JSON.stringify({ first: a ?? null, second: b ?? null }, null, 2)}</pre></details></td></tr>;
            })}</tbody></table>
        </div>
        <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Retained finding comparison, horizontally scrollable">
          <table className="data-table"><caption>Bounded retained finding comparison</caption><thead><tr><th>Finding identity</th><th>Recorded fields</th></tr></thead>
            <tbody>{Array.from(new Set([...first.findings, ...second.findings].map(row => row.exposure_id))).sort().map(key => {
              const a = first.findings.find(row => row.exposure_id === key), b = second.findings.find(row => row.exposure_id === key);
              return <tr key={key}><td>{key}</td><td>{!a ? "Only in second page" : !b ? "Only in first page" : stable(a) === stable(b) ? "Unchanged retained fields" : "Retained fields differ"}
                <details><summary>Inspect finding comparison {key}</summary><pre>{JSON.stringify({ first: a ?? null, second: b ?? null }, null, 2)}</pre></details></td></tr>;
            })}</tbody></table>
        </div>
      </>}
    </div>
  </section>;
}
