"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { downloadCsv, serializeCsv } from "@/lib/csv";
import type { ScopeSelection } from "@/lib/scope";
import { inventoryExportApi } from "@/lib/services";
import type { InventoryExportBatch, InventoryExportManifest } from "@/lib/types";
import { StatePanel } from "./ui/StatePanel";

const COLUMNS = [
  "family", "resource_name", "resource_type", "resource_id", "subscription_id",
  "resource_group", "environment", "location", "observed_at",
];

type Props = {
  scope: ScopeSelection;
  generationId: string;
  viewQuery: string;
  initialId: string;
  initialOffset: number;
};

function validateManifest(manifest: InventoryExportManifest) {
  if (!manifest || !/^[0-9a-f-]{36}$/.test(manifest.export_id) || !manifest.generation_id ||
    !/^[0-9a-f]{64}$/.test(manifest.sha256) || manifest.batch_size !== 500 ||
    !Number.isInteger(manifest.total) || manifest.total < 1 || manifest.total > 50_000 ||
    !Number.isInteger(manifest.revision) || manifest.revision < 1 ||
    !["ready", "cancelled", "expired"].includes(manifest.status) ||
    !Number.isFinite(Date.parse(manifest.expires_at)) ||
    JSON.stringify(manifest.columns) !== JSON.stringify(COLUMNS)) {
    throw new Error("The export manifest is invalid. Reload the capture before downloading.");
  }
}

function validateBatch(batch: InventoryExportBatch, manifest: InventoryExportManifest, offset: number) {
  validateManifest(batch.manifest);
  const end = Math.min(offset + 500, manifest.total);
  if (batch.manifest.export_id !== manifest.export_id || batch.manifest.generation_id !== manifest.generation_id ||
    batch.manifest.sha256 !== manifest.sha256 || batch.manifest.revision !== manifest.revision ||
    batch.manifest.total !== manifest.total || batch.manifest.status !== "ready" ||
    JSON.stringify(batch.manifest.scope) !== JSON.stringify(manifest.scope) ||
    batch.offset !== offset || batch.next_offset !== (end < manifest.total ? end : null) ||
    !Array.isArray(batch.resources) || batch.resources.length !== end - offset ||
    batch.resources.some(row => !row || Object.keys(row).length !== COLUMNS.length ||
      COLUMNS.some(key => typeof row[key] !== "string"))) {
    throw new Error("The returned batch does not match this capture. Reload before downloading.");
  }
}

/** Resume only a retained exact-scope capture; never mix active-generation pages. */
export function InventoryExport(props: Props) {
  return <Capture key={`${JSON.stringify(props.scope)}:${props.initialId}:${props.initialOffset}`} {...props} />;
}

function Capture({ scope, generationId, viewQuery, initialId, initialOffset }: Props) {
  const [manifest, setManifest] = useState<InventoryExportManifest | null>(null);
  const [offset, setOffset] = useState(initialOffset);
  const [busy, setBusy] = useState<"load" | "capture" | "download" | "cancel" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState("");
  const run = useRef(0);
  const loadCurrent = useRef<(() => void) | null>(null);

  useEffect(() => {
    let mounted = true;
    async function load(ignoreBookmark = false) {
      const request = ++run.current;
      setBusy("load");
      setError(null);
      setManifest(null);
      setReceipt("");
      try {
        const result = (await inventoryExportApi.current(scope)).data.export;
        if (!mounted || request !== run.current) return;
        if (result) validateManifest(result);
        if (!ignoreBookmark && initialId && result?.export_id !== initialId) {
          throw new Error("The bookmarked capture is unavailable for your current identity and scope. Reload current capture to recover.");
        }
        if (result && !ignoreBookmark && initialOffset >= result.total) {
          throw new Error("The bookmarked batch is outside this capture. Reload current capture to recover.");
        }
        setManifest(result);
        setOffset(ignoreBookmark ? 0 : initialOffset);
      } catch (reason) {
        if (mounted && request === run.current) setError(reason instanceof Error ? reason.message : "Export recovery failed.");
      } finally {
        if (mounted && request === run.current) setBusy(null);
      }
    }
    loadCurrent.current = () => { void load(true); };
    void load();
    return () => { mounted = false; run.current += 1; };
  }, [scope, initialId, initialOffset]);

  async function capture() {
    const request = ++run.current;
    setBusy("capture");
    setError(null);
    setReceipt("");
    try {
      const result = (await inventoryExportApi.create(scope, generationId)).data.export;
      if (request !== run.current) return;
      validateManifest(result);
      if (result.generation_id !== generationId || result.status !== "ready") {
        throw new Error("The captured generation does not match the reviewed inventory. Reload current capture.");
      }
      setManifest(result);
      setOffset(0);
    } catch (reason) {
      if (request === run.current) setError(reason instanceof Error ? reason.message : "Capture failed. Reload current capture before retrying.");
    } finally {
      if (request === run.current) setBusy(null);
    }
  }

  async function download() {
    if (!manifest) return;
    const request = ++run.current;
    setBusy("download");
    setError(null);
    setReceipt("");
    try {
      const batch = (await inventoryExportApi.batch(scope, manifest.export_id, offset)).data;
      if (request !== run.current) return;
      validateBatch(batch, manifest, offset);
      downloadCsv(serializeCsv(batch.resources, COLUMNS), `inventory-${manifest.export_id}-${offset}.csv`);
      setReceipt(`Rows ${offset + 1}–${offset + batch.resources.length} offered for download. This is not a saved-file receipt.`);
      if (batch.next_offset !== null) setOffset(batch.next_offset);
    } catch (reason) {
      if (request === run.current) setError(reason instanceof Error ? reason.message : "Batch unavailable. Retry the same batch or reload current capture.");
    } finally {
      if (request === run.current) setBusy(null);
    }
  }

  async function cancel() {
    if (!manifest) return;
    const request = ++run.current;
    setBusy("cancel");
    setError(null);
    setReceipt("");
    try {
      const result = (await inventoryExportApi.cancel(scope, manifest.export_id, manifest.revision)).data.export;
      if (request !== run.current) return;
      validateManifest(result);
      if (result.export_id !== manifest.export_id || result.status !== "cancelled" || result.revision !== manifest.revision + 1) {
        throw new Error("Cancellation was not confirmed. Reload current capture.");
      }
      setManifest(result);
    } catch (reason) {
      if (request === run.current) {
        setManifest(null);
        setError(reason instanceof Error ? reason.message : "Cancellation failed. Reload current capture.");
      }
    } finally {
      if (request === run.current) setBusy(null);
    }
  }

  const ready = manifest?.status === "ready";
  const query = new URLSearchParams(viewQuery);
  query.set("tab", "azure");
  if (manifest) {
    query.set("export_id", manifest.export_id);
    query.set("export_offset", String(offset));
  }
  return <section className="inventory-export-capture" aria-label="Retained inventory export" aria-busy={busy !== null}>
    <div className="inventory-export-bar">
      <div>
        <strong>Retained resource export</strong>
        <span className="muted">Capture all authorized OS and platform resource observations, independently of table filters.</span>
      </div>
      <button className="button button-primary" type="button" disabled={busy !== null || ready || !generationId || !!error} onClick={() => void capture()}>
        {busy === "capture" ? "Capturing inventory…" : "Capture resource export"}
      </button>
      <button className="button" type="button" disabled={busy === "cancel" || busy === "capture" || busy === "load"} onClick={() => loadCurrent.current?.()}>
        Reload current capture
      </button>
    </div>
    <p className="muted">One capture per identity and exact effective scope; up to 50,000 rows and 16 MiB. This is published-observation evidence, not complete-estate or live-health certification. Access expires after 24 hours.
      {" "}Expiry removes rows on next access, not on a scheduled purge. Capture metadata remains.
      {" "}Cancellation removes retained rows and blocks future batches, but cannot revoke in-flight requests or downloaded files.</p>
    {!generationId && <p className="muted">A published generation is required to create a capture. Existing retained batches can still be recovered.</p>}
    {busy === "load" && <p role="status">Recovering retained export…</p>}
    {manifest && <>
      <dl className="inventory-export-metadata">
        <div><dt>Capture</dt><dd>{manifest.export_id}</dd></div>
        <div><dt>Status</dt><dd>{manifest.status} · {manifest.total.toLocaleString()} captured observations</dd></div>
        <div><dt>Generation</dt><dd>{manifest.generation_id}</dd></div>
        <div><dt>SHA-256</dt><dd>{manifest.sha256}</dd></div>
        <div><dt>Observed</dt><dd>{manifest.observed_at || "Unreported"}</dd></div>
        <div><dt>Access expires</dt><dd>{manifest.expires_at}</dd></div>
      </dl>
      {ready && <div className="inventory-export-controls">
        <label>Captured batch
          <select aria-label="Captured batch" value={offset} disabled={busy !== null} onChange={event => { setOffset(Number(event.target.value)); setReceipt(""); }}>
            {Array.from({ length: Math.ceil(manifest.total / 500) }, (_, index) => <option key={index} value={index * 500}>
              Rows {index * 500 + 1}–{Math.min(index * 500 + 500, manifest.total)}
            </option>)}
          </select>
        </label>
        <button className="button button-primary" type="button" disabled={busy !== null} onClick={() => void download()}>{busy === "download" ? "Reading captured batch…" : "Download selected batch (CSV)"}</button>
        <Link className="button" href={`/inventory?${query}`}>Resume selected batch in URL</Link>
        <button className="button button-danger" type="button" disabled={busy === "cancel" || busy === "load" || busy === "capture"} onClick={() => void cancel()}>
          {busy === "cancel" ? "Cancelling capture…" : "Cancel retained export"}
        </button>
      </div>}
    </>}
    {receipt && <p role="status">{receipt}</p>}
    {error && <StatePanel title="Resource export unavailable" message={error} tone="error" />}
  </section>;
}
