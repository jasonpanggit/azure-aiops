"use client";

import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import {
  AUDIT_CAPTURE_KINDS, downloadEvidenceJson, verifyAuditCapture,
  type AuditCaptureDetail, type AuditCaptureKind, type AuditCaptureManifest,
} from "@/lib/audit-exports";
import { formatDateTime, titleize } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { governanceApi } from "@/lib/services";

/** On-demand personal recovery stays independent of live export-kind availability. */
export function GovernanceRetainedExports({ scope }: { scope: ScopeSelection }) {
  const query = scopeToSearchParams(scope); query.sort();
  return <Workspace key={query.toString()} scope={scope} />;
}

function Workspace({ scope }: { scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  const [revisionKey, setRevisionKey] = useState(0);
  return <section className="governance-retained" aria-label="Retained audit evidence">
    <h3>Retained audit evidence</h3>
    <p>Personal, exact-scope copies of server-generated packs. Recovery does not require current evidence providers.</p>
    <button className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      {open ? "Close retained evidence" : "Open retained evidence"}
    </button>
    {open && <Collection key={revisionKey} scope={scope} reload={() => setRevisionKey(value => value + 1)} />}
  </section>;
}

function Collection({ scope, reload }: { scope: ScopeSelection; reload: () => void }) {
  const result = useApi(signal => governanceApi.retainedExports(scope, signal), []);
  if (result.loading) return <p role="status">Reading retained evidence...</p>;
  if (result.error || !result.data?.data) return <div>
    <p role="alert">{result.error?.message ?? "Retained evidence could not be read."} No empty collection has been substituted.</p>
    <button className="button" onClick={reload}>Reload retained evidence</button>
  </div>;
  return <Editor scope={scope} initial={result.data.data} reload={reload} />;
}

function Editor({ scope, initial, reload }: {
  scope: ScopeSelection;
  initial: import("@/lib/audit-exports").AuditCaptureCollection;
  reload: () => void;
}) {
  const [collection, setCollection] = useState(initial);
  const [kind, setKind] = useState<AuditCaptureKind | "">("");
  const [captureReview, setCaptureReview] = useState(false);
  const [removeReview, setRemoveReview] = useState<AuditCaptureManifest | null>(null);
  const [detail, setDetail] = useState<AuditCaptureDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const writable = Number.isSafeInteger(collection.revision)
    && collection.revision >= 0 && collection.revision < Number.MAX_SAFE_INTEGER;
  const locked = busy || blocked || !writable;

  async function mutate(action: { remove: AuditCaptureManifest } | { kind: AuditCaptureKind }) {
    if (locked || request.current || ("kind" in action && !captureReview)) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice(""); setDetail(null);
    try {
      const response = "remove" in action
        ? await governanceApi.removeExport(scope, action.remove.export_id, collection.revision, controller.signal)
        : await governanceApi.captureExport(scope, action.kind, collection.revision, controller.signal);
      if (controller.signal.aborted) return;
      setCollection(response.data); setCaptureReview(false); setRemoveReview(null);
      setNotice("remove" in action ? "Stored copy removed. Downloaded copies are not revoked." : "Current evidence captured. Source warnings and observation times are preserved.");
    } catch (failure) {
      if (!controller.signal.aborted) {
        setBlocked(true); setCaptureReview(false); setRemoveReview(null);
        setError(`${failure instanceof Error ? failure.message : "The operation was not confirmed."} Reload before another action. No request will be replayed automatically.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  async function inspect(row: AuditCaptureManifest) {
    if (busy || request.current) return;
    const controller = new AbortController(); request.current = controller;
    setBusy(true); setError(""); setNotice(""); setDetail(null); setRemoveReview(null); setCaptureReview(false);
    try {
      const response = await governanceApi.retainedExport(scope, row.export_id, controller.signal);
      if (response.data.manifest.export_id !== row.export_id || response.data.manifest.sha256 !== row.sha256) {
        throw new Error("Retained detail no longer matches the selected manifest. Reload the collection.");
      }
      await verifyAuditCapture(response.data);
      if (!controller.signal.aborted) setDetail(response.data);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Retained content could not be verified.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  function download() {
    if (!detail || busy) return;
    try {
      downloadEvidenceJson(detail.content, `audit-evidence-${detail.manifest.export_id}.json`);
      setNotice("Verified file handed to the browser. Check your downloads.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The browser could not start the download.");
    }
  }

  return <div className="governance-retained-content">
    <p>{collection.captures.length}/10 stored · Revision {collection.revision}. Each capture is limited to 512 KiB; the collection to 6 MiB. No automatic eviction or expiry.</p>
    <p>Standard secret-key redaction is not comprehensive data-loss prevention. Packs can contain sensitive access and resource details. Capturing regenerates current evidence, not a previously displayed preview, and is not an atomic cross-source snapshot, certification, or execution approval.</p>
    {error && <p role="alert">{error}</p>}
    {blocked && <p role="alert">Capture and removal are locked until you reload this collection. Retained content can still be recovered.</p>}
    {notice && <p role="status">{notice}</p>}
    {!writable && <p role="alert">This collection has no writable revision. Recovery remains available.</p>}
    <div className="governance-retained-actions">
      <button className="button" disabled={busy} onClick={reload}>Reload retained evidence</button>
      <label>Evidence kind
        <select value={kind} disabled={locked} onChange={event => {
          const value = event.target.value;
          setKind(AUDIT_CAPTURE_KINDS.find(item => item === value) ?? "");
          setCaptureReview(false); setRemoveReview(null);
        }}>
          <option value="">Select a kind</option>
          {AUDIT_CAPTURE_KINDS.map(item => <option key={item} value={item}>{titleize(item)}</option>)}
        </select>
      </label>
      <button className="button" disabled={locked || !kind || collection.captures.length >= 10}
        onClick={() => { setCaptureReview(true); setRemoveReview(null); setDetail(null); }}>
        Review capture
      </button>
    </div>
    {captureReview && <div className="governance-retained-review">
      <h4>Capture {titleize(kind)} evidence</h4>
      <p>Generate a new pack for your current effective scope and retain its standard-redacted bytes at collection revision {collection.revision}. This does not refresh any already retained pack.</p>
      <button className="button button-primary" disabled={locked} onClick={() => { if (kind) void mutate({ kind }); }}>Capture current evidence</button>
      <button className="button" disabled={busy} onClick={() => setCaptureReview(false)}>Cancel capture</button>
    </div>}
    {collection.captures.length === 0 ? <p>No retained audit evidence in this personal exact scope.</p> : <ol className="governance-retained-list">
      {collection.captures.map(row => <li key={row.export_id}>
        <h4>{titleize(row.kind)}</h4>
        <p>Captured {formatDateTime(row.captured_at)} · Generated {formatDateTime(row.generated_at)}</p>
        <p>Source observation: {row.observed_at ? formatDateTime(row.observed_at) : "Unknown"}. {row.warning_count} source warnings as captured · {row.size_bytes.toLocaleString()} bytes.</p>
        <p className="governance-retained-hash">SHA-256 {row.sha256}</p>
        <button className="button" disabled={busy} onClick={() => void inspect(row)}>Verify and open {titleize(row.kind)}</button>
        <button className="button" disabled={locked} onClick={() => {
          setRemoveReview(row); setCaptureReview(false); setDetail(null);
        }}>Review removal of {titleize(row.kind)}</button>
      </li>)}
    </ol>}
    {removeReview && <div className="governance-retained-review">
      <h4>Remove {titleize(removeReview.kind)} stored copy</h4>
      <p>Captured {formatDateTime(removeReview.captured_at)}. This removes only this personal stored copy at revision {collection.revision}; source evidence and downloaded files are unchanged.</p>
      <button className="button" disabled={locked} onClick={() => { if (removeReview) void mutate({ remove: removeReview }); }}>Confirm removal</button>
      <button className="button" disabled={busy} onClick={() => setRemoveReview(null)}>Cancel removal</button>
    </div>}
    {detail && <div>
      <h4>Verified captured content</h4>
      <p>SHA-256 and exact UTF-8 byte count match. Integrity checking does not establish authenticity or current freshness. Historical source warnings remain in the JSON.</p>
      <button className="button" disabled={busy} onClick={download}>Download verified JSON</button>
      <pre className="governance-retained-preview" tabIndex={0} aria-label="Verified captured JSON">{detail.content}</pre>
    </div>}
    {busy && <p role="status">Processing explicit evidence request...</p>}
  </div>;
}
