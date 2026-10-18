"use client";

import { useState } from "react";
import type {
  InvestigationHypothesis,
  InvestigationHypothesisDraft,
  InvestigationHypothesisReference,
  InvestigationTeamWorkspace,
} from "@/lib/investigation-workspaces";

interface Props {
  workspace: InvestigationTeamWorkspace;
  busy: boolean;
  onSave: (id: string, expectedRevision: number, hypothesis: InvestigationHypothesisDraft) => Promise<boolean>;
}

const dispositions = ["proposed", "investigating", "supported", "contradicted", "inconclusive", "dismissed"] as const;
const emptyDraft = (): InvestigationHypothesisDraft => ({
  explanation: "", supporting: [], contradicting: [], unknowns: [], disposition: "proposed", rationale: "",
});
const emptyReference = (): InvestigationHypothesisReference => ({ source: "", reference: "", declared_version: "", note: "" });

function References({ label, rows }: { label: string; rows: InvestigationHypothesisReference[] }) {
  return <div>
    <h5>{label}</h5>
    {rows.length ? <ul>{rows.map((row, index) => <li key={index}>
      <strong>{row.source}</strong>: {row.reference}
      <span> · Declared version: {row.declared_version || "Not supplied"}</span>
      {row.note && <p>{row.note}</p>}
    </li>)}</ul> : <p className="muted">None recorded; absence is not evidence.</p>}
  </div>;
}

/** Explicit operator-authored hypotheses with immutable history and unverified reference text. */
export function InvestigationHypothesisBoard({ workspace, busy, onSave }: Props) {
  const [editing, setEditing] = useState<{
    id: string; expectedRevision: number; value: InvestigationHypothesisDraft; unknownText: string;
  } | null>(null);
  const [error, setError] = useState("");
  const hypotheses = workspace.revision.hypotheses;
  const historical = workspace.revision.revision !== workspace.latest_revision;
  const writable = workspace.can_edit && !historical;
  const start = (row?: InvestigationHypothesis) => {
    setError("");
    if (!row && typeof crypto.randomUUID !== "function") {
      setError("Secure hypothesis identity generation is unavailable. Use a supported secure browser.");
      return;
    }
    const value = row ? {
      explanation: row.explanation, supporting: row.supporting, contradicting: row.contradicting,
      unknowns: row.unknowns, disposition: row.disposition, rationale: row.rationale,
    } : emptyDraft();
    setEditing({
      id: row?.hypothesis_id ?? `hyp-${crypto.randomUUID().replaceAll("-", "")}`,
      expectedRevision: workspace.revision.revision, value, unknownText: value.unknowns.join("\n"),
    });
  };
  const change = (patch: Partial<InvestigationHypothesisDraft>) => {
    setEditing(current => current && ({ ...current, value: { ...current.value, ...patch } }));
  };
  const referenceChange = (kind: "supporting" | "contradicting", index: number, patch: Partial<InvestigationHypothesisReference>) => {
    if (!editing) return;
    change({ [kind]: editing.value[kind].map((row, at) => at === index ? { ...row, ...patch } : row) });
  };
  const save = async () => {
    if (!editing) return;
    setError("");
    const value = { ...editing.value, unknowns: editing.unknownText.split("\n").map(line => line.trim()).filter(Boolean) };
    if (!value.explanation.trim() || value.unknowns.length > 8 || value.unknowns.some(row => row.length > 512)
      || (value.disposition !== "proposed" && !value.rationale.trim())
      || [...value.supporting, ...value.contradicting].some(row => !row.source.trim() || !row.reference.trim())) {
      setError("Add an explanation, source and identifier for each reference, and a rationale for any non-proposed disposition. Record at most 8 unknowns of 512 characters each.");
      return;
    }
    if (await onSave(editing.id, editing.expectedRevision, value)) setEditing(null);
  };

  return <section className="investigation-hypotheses" aria-label="Operator hypothesis board">
    <h3>Operator hypothesis board</h3>
    <p>Visible team annotations, not Copilot reasoning or verified provider facts. Supporting and contradicting references are operator-declared text; they are not fetched, validated or retained evidence. Do not include secrets.</p>
    {!hypotheses.length && <p>No explanations proposed in this revision. Record competing explanations and what remains unknown; no conclusion is implied.</p>}
    <div className="investigation-hypothesis-list">
      {hypotheses.map((row, index) => <details key={row.hypothesis_id}>
        <summary>Explanation {index + 1}: {row.disposition} (operator assessment)</summary>
        <p className="investigation-hypothesis-text">{row.explanation}</p>
        <dl className="investigation-team-metadata">
          <div><dt>Original saved subject</dt><dd>{row.entry_type}: {row.subject || "Current scope"}</dd></div>
          <div><dt>Annotation identity</dt><dd>{row.hypothesis_id}</dd></div>
          <div><dt>Last updated</dt><dd>Revision {row.updated_revision} by {row.actor} at <time dateTime={row.recorded_at}>{new Date(row.recorded_at).toLocaleString(undefined, { timeZone: "UTC", dateStyle: "medium", timeStyle: "medium" })} UTC</time></dd></div>
        </dl>
        <References label="Supporting references (unverified)" rows={row.supporting} />
        <References label="Contradicting references (unverified)" rows={row.contradicting} />
        <h5>Unknowns</h5>
        {row.unknowns.length ? <ul>{row.unknowns.map((unknown, at) => <li key={at}>{unknown}</li>)}</ul> : <p className="muted">None recorded; completeness has not been established.</p>}
        <h5>Operator disposition rationale</h5>
        <p className="investigation-hypothesis-text">{row.rationale || "Not supplied for this proposal."}</p>
        <button className="button button-secondary" type="button" disabled={busy || !writable || Boolean(editing)} onClick={() => start(row)}>Edit explanation {index + 1}</button>
      </details>)}
    </div>
    {historical && <p className="muted">Historical annotations are review-only. Open the latest workspace before editing.</p>}
    {!workspace.can_edit && <p className="muted">Only the owner or an explicit editor can save explanations.</p>}
    {hypotheses.length >= 20 && <p>This workspace has reached 20 explanations. Update or dismiss an existing explanation; history is never deleted.</p>}
    {!editing && <button className="button button-secondary" type="button" disabled={busy || !writable || hypotheses.length >= 20} onClick={() => start()}>Propose explanation</button>}
    {editing && <fieldset disabled={busy || !writable} className="investigation-hypothesis-editor">
      <legend>{hypotheses.some(row => row.hypothesis_id === editing.id) ? "Edit operator explanation" : "New operator explanation"}</legend>
      <p>Saving appends one workspace revision based on reviewed revision {editing.expectedRevision}. A new explanation is anchored to that revision&apos;s saved subject, not unsaved page navigation. Dismiss rather than delete. Keep a copy of unsaved text before reopening or leaving the workspace.</p>
      <p className="muted">Known annotation identity: {editing.id}</p>
      <div className="investigation-team-controls">
        <label>Proposed explanation<textarea rows={4} maxLength={2000} value={editing.value.explanation} onChange={event => change({ explanation: event.target.value })} /></label>
        <label>Unknowns (one per line, up to 8)<textarea rows={4} maxLength={4103} value={editing.unknownText} onChange={event => setEditing({ ...editing, unknownText: event.target.value })} /></label>
        <label>Operator disposition<select value={editing.value.disposition} onChange={event => change({ disposition: event.target.value as InvestigationHypothesisDraft["disposition"] })}>
          {dispositions.map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>
        <label>Disposition rationale<textarea rows={3} maxLength={1000} value={editing.value.rationale} onChange={event => change({ rationale: event.target.value })} /></label>
      </div>
      {(["supporting", "contradicting"] as const).map(kind => <div className="investigation-hypothesis-reference-editor" key={kind}>
        <h4>{kind === "supporting" ? "Supporting" : "Contradicting"} references (unverified)</h4>
        {editing.value[kind].map((row, index) => <fieldset key={index}>
          <legend>{kind === "supporting" ? "Supporting" : "Contradicting"} reference {index + 1}</legend>
          <div className="investigation-team-controls">
            <label>Source<input maxLength={128} value={row.source} onChange={event => referenceChange(kind, index, { source: event.target.value })} /></label>
            <label>Reference identifier<input maxLength={512} value={row.reference} onChange={event => referenceChange(kind, index, { reference: event.target.value })} /></label>
            <label>Declared source version<input maxLength={128} value={row.declared_version} onChange={event => referenceChange(kind, index, { declared_version: event.target.value })} /></label>
            <label>Operator reference note<textarea rows={2} maxLength={512} value={row.note} onChange={event => referenceChange(kind, index, { note: event.target.value })} /></label>
          </div>
          <button className="button button-secondary" type="button" onClick={() => change({ [kind]: editing.value[kind].filter((_, at) => at !== index) })}>Remove {kind} reference {index + 1} from draft</button>
        </fieldset>)}
        <button className="button button-secondary" type="button" disabled={editing.value[kind].length >= 6} onClick={() => change({ [kind]: [...editing.value[kind], emptyReference()] })}>Add {kind} reference</button>
      </div>)}
      <div className="investigation-team-controls">
        <button className="button button-primary" type="button" onClick={() => void save()}>Save explanation revision</button>
        <button className="button button-secondary" type="button" onClick={() => { setEditing(null); setError(""); }}>Discard annotation draft</button>
      </div>
    </fieldset>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
