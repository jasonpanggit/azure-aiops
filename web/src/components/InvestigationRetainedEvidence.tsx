"use client";

import { useEffect, useRef, useState } from "react";
import {
  investigationWorkspacesApi,
  type InvestigationCapturedSource,
  type InvestigationEvidenceCapture,
  type InvestigationEvidenceComparison,
  type InvestigationTeamWorkspace,
} from "@/lib/investigation-workspaces";
import { StatePanel } from "./ui/StatePanel";
import { StructuredData } from "./ui/StructuredData";

interface Props {
  workspace: InvestigationTeamWorkspace;
  busy: boolean;
  onRetain: (id: string) => Promise<boolean>;
}

const validId = (id: string) => /^cap-[0-9a-f]{32}$/.test(id);
const recordedTime = (value: string) => `${new Date(value).toLocaleString(undefined, { timeZone: "UTC", dateStyle: "medium", timeStyle: "medium" })} UTC`;

function SourceProjection({ source }: { source: InvestigationCapturedSource }) {
  const observed = source.evidence.map(item => item.timestamp).filter(Boolean);
  return <details className="investigation-source-projection">
    <summary>{source.tool}: {source.status}</summary>
    <p>Collection: {recordedTime(source.started_at)} to {recordedTime(source.finished_at)}. Source observation: {observed.length ? observed.join(", ") : "Unreported"}. Knowledge version: {source.knowledge_version}.</p>
    {source.warning && <p role="note">{source.warning}</p>}
    {source.status === "ok" || source.status === "empty" ? <StructuredData value={source.data} /> : <p>No decisive source payload available; this does not mean no findings.</p>}
    <details><summary>Recorded source provenance (freshness as captured)</summary><StructuredData value={source.evidence} /></details>
  </details>;
}

/** Explicit retained-source inspection and current comparison, independent from page/Copilot evidence. */
export function InvestigationRetainedEvidence({ workspace, busy, onRetain }: Props) {
  const [identity, setIdentity] = useState(workspace.revision.capture_id ?? "");
  const [receipt, setReceipt] = useState<InvestigationEvidenceCapture | null>(null);
  const [comparison, setComparison] = useState<InvestigationEvidenceComparison | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => {
    generation.current += 1;
    controller.current?.abort();
  }, []);
  const pending = busy || waiting;
  const writable = workspace.can_edit && workspace.revision.revision === workspace.latest_revision;
  const known = workspace.captures.some(row => row.capture_id === identity);
  const select = (id: string) => {
    generation.current += 1;
    controller.current?.abort();
    setIdentity(id);
    setReceipt(null);
    setComparison(null);
    setError("");
  };
  const retain = async () => {
    setError("");
    if (!identity && typeof crypto.randomUUID !== "function") {
      setError("Secure capture identity generation is unavailable. Use a supported secure browser or enter a valid known identity.");
      return;
    }
    const id = identity || `cap-${crypto.randomUUID().replaceAll("-", "")}`;
    setIdentity(id);
    setWaiting(true);
    try { await onRetain(id); } finally { setWaiting(false); }
  };
  const inspect = async (compare: boolean) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const current = ++generation.current;
    setWaiting(true);
    setError("");
    setComparison(null);
    if (!compare) setReceipt(null);
    try {
      if (compare) {
        const result = await investigationWorkspacesApi.compare(
          workspace.workspace_id, identity, workspace.revision.revision, workspace.latest_revision, workspace.scope, abort.signal,
        );
        if (current !== generation.current) return;
        if (result.data.workspace_id !== workspace.workspace_id || result.data.capture_id !== identity
          || result.data.reviewed_revision !== workspace.revision.revision || result.data.expected_revision !== workspace.latest_revision
          || result.data.retained.capture_id !== identity || result.data.retained.workspace_id !== workspace.workspace_id) {
          throw new Error("The comparison identity or reviewed revision did not match.");
        }
        setReceipt(result.data.retained);
        setComparison(result.data);
      } else {
        const result = await investigationWorkspacesApi.evidence(workspace.workspace_id, identity, workspace.revision.revision, workspace.scope, abort.signal);
        if (current !== generation.current) return;
        const reference = workspace.captures.find(row => row.capture_id === identity);
        if (result.data.workspace_id !== workspace.workspace_id || result.data.capture_id !== identity
          || !reference || result.data.workspace_revision !== reference.workspace_revision) {
          throw new Error("The retained receipt identity or linked revision did not match.");
        }
        setReceipt(result.data);
      }
    } catch (failure) {
      if (current !== generation.current) return;
      setError(failure instanceof Error ? failure.message : "Retained evidence operation was not confirmed.");
    } finally {
      if (current === generation.current) setWaiting(false);
    }
  };

  return <section className="investigation-hypotheses" aria-label="Retained source evidence">
    <h3>Retained source evidence</h3>
    <p>Retain a new server acquisition for the reviewed saved navigation, not this browser&apos;s current evidence or unsaved subject. Reopening a version makes no provider calls. Comparing explicitly acquires current projections for that retained subject and writes no history.</p>
    <p className="muted">This is a bounded governed-read subset, not a full page or estate snapshot. Tool lists may already be limited to 25 rows. Coverage, atomic cross-source consistency and unreported versions/timestamps remain unknown. Environment, connection, network-gap and remediation-plan entries use scope-level projections. Source failures stay explicit; stored freshness is as captured.</p>
    <div className="investigation-team-controls">
      <label>Retained source version<select value={known ? identity : ""} disabled={pending} onChange={event => select(event.target.value)}>
        <option value="">New capture or unconfirmed identity</option>
        {workspace.captures.map(row => <option key={row.capture_id} value={row.capture_id}>Revision {row.workspace_revision} · {recordedTime(row.recorded_at)} · {row.actor}</option>)}
      </select></label>
      <label>Capture identity<input maxLength={36} value={identity} disabled={pending} onChange={event => select(event.target.value.trim())} placeholder="Generated securely before retention" /></label>
      <button className="button button-secondary" type="button" disabled={pending || !writable || known || workspace.captures.length >= 5 || workspace.latest_revision >= 40 || Boolean(identity && !validId(identity))} onClick={() => void retain()}>Retain current source projections</button>
      <button className="button button-secondary" type="button" disabled={pending || !known} onClick={() => void inspect(false)}>Reopen retained source version</button>
      <button className="button button-secondary" type="button" disabled={pending || !known || !receipt} onClick={() => void inspect(true)}>Acquire current and compare projections</button>
    </div>
    {!workspace.captures.length && <p>No source versions linked in this reviewed workspace revision. Navigation and annotations are not retained source evidence.</p>}
    {workspace.captures.length >= 5 && <p>Five retained versions reached; administrative archival is required before another capture. Existing receipts remain readable.</p>}
    {pending && <p role="status">Waiting for evidence storage or acquisition. A stopped browser wait does not establish whether retention committed.</p>}
    {error && <StatePanel title="Retained evidence unavailable" message={`${error} Reopen the latest workspace to inspect the known capture identity before retrying retention; no automatic retry or replacement occurs.`} tone="error" />}
    {receipt && <div>
      <h4>Retained projection: revision {receipt.workspace_revision}</h4>
      <p>{receipt.view.entry_type}: {receipt.view.subject || "Current scope"} · Retained by {receipt.actor} at <time dateTime={receipt.recorded_at}>{recordedTime(receipt.recorded_at)}</time>. Source observations below may be older than retention.</p>
      {receipt.sources.map(source => <SourceProjection key={source.tool} source={source} />)}
    </div>}
    {comparison && <div>
      <h4>Current comparison (not retained)</h4>
      <p>Collected at <time dateTime={comparison.current.finished_at}>{recordedTime(comparison.current.finished_at)}</time>. Unchanged projections do not establish unchanged estate conditions. Unknown means at least one source could not provide decisive data.</p>
      <ul>{comparison.differences.map(row => <li key={row.tool}>
        <strong>{row.tool}</strong>: {row.data_changed === null ? "Unknown" : row.data_changed ? "Bounded payload changed" : "Same bounded payload"} · {row.retained_status} to {row.current_status} · Provenance {row.provenance_changed ? "changed" : "unchanged"} · Versions {row.retained_knowledge_version} to {row.current_knowledge_version}
      </li>)}</ul>
      {comparison.current.sources.map(source => <SourceProjection key={source.tool} source={source} />)}
    </div>}
  </section>;
}
