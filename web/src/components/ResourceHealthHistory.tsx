"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { resourceHealthApi } from "@/lib/services";
import type { ScopeSelection } from "@/lib/scope";
import type {
  FlatInventoryResource, ResourceHealthHistory as History, RetainedHealthMetrics,
} from "@/lib/types";

interface Props {
  scope: ScopeSelection;
  resource: FlatInventoryResource;
  onClose: () => void;
}

const METRICS: { key: keyof RetainedHealthMetrics; label: string; unit: string }[] = [
  { key: "cpu_percent", label: "CPU", unit: "%" },
  { key: "memory_percent", label: "Memory", unit: "%" },
  { key: "disk_free_percent", label: "Disk free", unit: "%" },
  { key: "os_disk_queue_depth", label: "OS disk queue depth", unit: "" },
  { key: "network_in_bytes", label: "Network inbound", unit: "B" },
  { key: "network_out_bytes", label: "Network outbound", unit: "B" },
  { key: "disk_read_bytes", label: "Disk read", unit: "B" },
  { key: "disk_write_bytes", label: "Disk write", unit: "B" },
];

function valueText(value: number | null, unit: string): string {
  if (value === null) return "Not reported";
  if (unit === "B") {
    if (Math.abs(value) >= 1_073_741_824) return `${(value / 1_073_741_824).toFixed(1)} GB`;
    if (Math.abs(value) >= 1_048_576) return `${(value / 1_048_576).toFixed(1)} MB`;
    if (Math.abs(value) >= 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${value.toFixed(1)} B`;
  }
  return `${value.toFixed(1)}${unit}`;
}

/** Explicit personal utilization receipts, isolated immediately by scope and resource. */
export function ResourceHealthHistory(props: Props) {
  return <HistoryPanel key={JSON.stringify([props.scope, props.resource.resource_id])} {...props} />;
}

function HistoryPanel({ scope, resource, onClose }: Props) {
  const [history, setHistory] = useState<History | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [beforeId, setBeforeId] = useState("");
  const [afterId, setAfterId] = useState("");
  const request = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const beforeLabel = useId();
  const afterLabel = useId();

  function apply(next: History) {
    setHistory(next);
    setBeforeId(next.observations.at(-2)?.observation_id ?? "");
    setAfterId(next.observations.at(-1)?.observation_id ?? "");
  }

  const reload = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setHistory(null); setError(""); setNotice("");
    try {
      const response = await resourceHealthApi.history(resource.resource_id, scope, { signal: controller.signal });
      if (!controller.signal.aborted) apply(response.data);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Retained health is unavailable.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }, [scope, resource.resource_id]);

  useEffect(() => {
    heading.current?.focus();
    void reload();
    return () => request.current?.abort();
  }, [reload]);

  async function capture() {
    if (request.current || !history) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await resourceHealthApi.captureHistory(
        resource.resource_id, scope, history.revision, { signal: controller.signal },
      );
      if (!controller.signal.aborted) {
        apply(response.data);
        setNotice("Server collection retained. Live cards are a separate read.");
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setHistory(null);
        setError(`${reason instanceof Error ? reason.message : "Capture failed."} Capture was not confirmed. Reload before retrying.`);
      }
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  const observations = history?.observations ?? [];
  const before = observations.find(row => row.observation_id === beforeId);
  const after = observations.find(row => row.observation_id === afterId);
  const sameCollection = before && after &&
    before.resource_observed_at === after.resource_observed_at &&
    before.snapshot_observed_at === after.snapshot_observed_at;

  return <section className="card resource-health-history" aria-label={`Retained health for ${resource.resource_name}`}>
    <div className="card-header">
      <div><h2 ref={heading} tabIndex={-1}>Retained health: {resource.resource_name}</h2>
        <p>Threshold-based utilization, not availability.</p></div>
      <button type="button" className="button button-secondary" onClick={onClose}>Close retained health</button>
    </div>
    <div className="card-body">
      <p>Private to your principal and exact scope. Latest 30 explicit resource-address captures.</p>
      <div className="overview-history-controls">
        <button type="button" className="button button-primary" disabled={busy || !history} onClick={() => void capture()}>Capture available reading</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={() => void reload()}>Reload retained health</button>
      </div>
      {busy && <p role="status">Loading retained health operation…</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <p>Capture time is not metric sample time. Windows and rates are unreported; cache reuse is not new telemetry.</p>
      {history && <p>History revision {history.revision}; {observations.length}/30 receipts retained.</p>}
      {history && observations.length < 2 && <p>Two retained receipts are needed for comparison. No prior movement is inferred.</p>}
      {observations.length >= 2 && <>
        <div className="overview-history-controls">
          <div><label htmlFor={beforeLabel}>Reference receipt</label>
            <select id={beforeLabel} value={beforeId} onChange={event => setBeforeId(event.target.value)}>
              {observations.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id.slice(0, 8)}</option>)}
            </select></div>
          <div><label htmlFor={afterLabel}>Compared receipt</label>
            <select id={afterLabel} value={afterId} onChange={event => setAfterId(event.target.value)}>
              {observations.map(row => <option key={row.observation_id} value={row.observation_id}>{row.captured_at} · {row.observation_id.slice(0, 8)}</option>)}
            </select></div>
        </div>
        {before && after && beforeId !== afterId ? <>
          {sameCollection && <p role="status">These receipts have identical provider collection timestamps; do not treat them as independent samples.</p>}
          <p>Arithmetic only; no continuous trend, verified improvement or cause.</p>
          <p className="service-scroll-hint">More columns may be off-screen. Focus the table and use arrow keys to scroll.</p>
          <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Retained utilization comparison, horizontally scrollable">
            <table className="data-table"><caption>Retained utilization values; no continuous coverage claim</caption>
              <thead><tr><th>Measurement</th><th>Reference collection</th><th>Compared collection</th><th>Value difference</th></tr></thead>
              <tbody>{METRICS.map(metric => {
                const left = before.metrics[metric.key], right = after.metrics[metric.key];
                const delta = left === null || right === null ? null : right - left;
                return <tr key={metric.key}><th scope="row">{metric.label}</th>
                  <td>{valueText(left, metric.unit)}</td><td>{valueText(right, metric.unit)}</td>
                  <td>{delta === null ? "Not comparable" : `${delta > 0 ? "+" : ""}${valueText(delta, metric.unit === "%" ? " pp" : metric.unit)}`}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        </> : <p role="status">Choose two different receipts.</p>}
      </>}
      <details><summary>Retention and interpretation limits</summary>
        <p>Private to your principal, exact scope and authorized resource address. Latest 30 captures, at most 256 KiB;
          oldest replaced on capture 31. No automatic collection, historical backfill or time-based expiry.
          A deleted and recreated resource at the same address is not proven to be the same incarnation.</p>
        <p>Measurements may come from the 120-second provider cache. Capture time is not metric sample time.
          CPU classification is threshold-based, not Azure availability or an SLO.
          Original aggregation windows and rate semantics are unreported; byte values are not rates.
          Missing values are not zero. Collections may have different windows; arithmetic does not establish
          improvement, degradation or causation. A submitted capture may finish after closing.</p>
      </details>
      {observations.length > 0 && <details><summary>Inspect retained collection provenance</summary>
        <ol className="resource-health-receipts">{observations.slice().reverse().map(row => <li key={row.observation_id}>
          <h3><time dateTime={row.captured_at}>{row.captured_at}</time></h3>
          <p>Receipt {row.observation_id}; CPU classification: {row.classification}.
            {" "}{row.cached ? "Cached provider collection" : "New provider collection"}; cache TTL {row.cache_ttl_seconds}s.</p>
          <p>Resource collected <time dateTime={row.resource_observed_at}>{row.resource_observed_at}</time>;
            {" "}snapshot collected {row.snapshot_observed_at}; request {row.started_at} to {row.finished_at}.
            {" "}{row.warning_count} warnings; {row.unavailable_metric_count} unavailable metric declarations.</p>
          <dl className="resource-health-receipt-values">{METRICS.map(metric => <div key={metric.key}>
            <dt>{metric.label}</dt><dd>{valueText(row.metrics[metric.key], metric.unit)}</dd>
          </div>)}</dl>
        </li>)}</ol>
      </details>}
    </div>
  </section>;
}
