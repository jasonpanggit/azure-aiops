"use client";

import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { formatDateTime } from "@/lib/format";
import type { ScopeSelection } from "@/lib/scope";
import { situationsApi } from "@/lib/services";
import type { SituationNotesState } from "@/lib/types";
import { StatePanel } from "./ui/StatePanel";

/** Exact-scope operator annotations, deliberately separate from source evidence. */
export function SituationHandoverNotes({ situationId, evidenceRunId, scope }: {
  situationId: string; evidenceRunId: string; scope: ScopeSelection;
}) {
  const [refresh, setRefresh] = useState(0);
  const result = useApi(() => situationsApi.notes(situationId, scope), [situationId, scope, refresh]);
  const [saved, setSaved] = useState<SituationNotesState | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(true);
  const state = saved ?? result.data?.data;
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  async function append() {
    if (!state?.can_append || saving || !draft.trim() || !evidenceRunId) return;
    setSaving(true); setError("");
    try {
      const response = await situationsApi.appendNote(situationId, scope, {
        expected_revision: state.revision, evidence_run_id: evidenceRunId, text: draft.trim(),
      });
      if (active.current) { setSaved(response.data); setDraft(""); }
    } catch (reason) {
      if (active.current) setError(reason instanceof Error ? reason.message : "Handover note could not be saved");
    } finally {
      if (active.current) setSaving(false);
    }
  }

  return <section className="card" aria-labelledby="handover-heading">
    <div className="card-header"><div><h2 id="handover-heading">Handover notes</h2>
      <p>Shared only within this exact authorized scope. Operator annotations are not provider facts, approvals, or execution instructions.</p>
    </div><button className="button" disabled={saving || result.loading} onClick={() => { setSaved(null); setError(""); setRefresh(value => value + 1); }}>Reload handover</button></div>
    <div className="card-body">
      {result.error ? <StatePanel title="Handover history is unavailable" message={result.error.message} tone="error" />
        : !state ? <StatePanel title="Loading handover history" message="Reading durable scope-exact annotations." tone="loading" />
        : <>
          <p>History revision {state.revision} · {state.notes.length}/200 retained notes</p>
          {state.notes.length === 0 && <p>No handover notes have been recorded for this exact scope.</p>}
          {state.notes.map(note => <article className="reasoning-card" key={note.note_id}>
            <strong>{note.actor} · revision {note.revision}</strong>
            <span>{formatDateTime(note.created_at)} · evidence run <code>{note.evidence_run_id}</code></span>
            <p style={{ whiteSpace: "pre-wrap" }}>{note.text}</p>
          </article>)}
          {state.can_append ? <form onSubmit={event => { event.preventDefault(); void append(); }}>
            <label className="form-field"><span>Handover annotation</span>
              <textarea className="form-control" value={draft} maxLength={2000} rows={4}
                onChange={event => setDraft(event.target.value)} disabled={saving} />
            </label>
            <p>{draft.length}/2000 characters. Do not include credentials or secrets. Bound to evidence run <code>{evidenceRunId || "unavailable"}</code>.</p>
            {state.notes.length >= 200 && <p>History is full. Administrative archival is required; older notes will not be silently deleted.</p>}
            <button className="button button-primary" disabled={saving || result.loading || !draft.trim() || !evidenceRunId || state.notes.length >= 200}>
              {saving ? "Saving handover..." : "Append handover note"}
            </button>
          </form> : <p>Read-only handover access. Operator authorization for the entire selected scope is required to append.</p>}
        </>}
      {error && <StatePanel title="Handover note was not saved" message={`${error}. Your draft is retained. Reload and review the current history before retrying.`} tone="error" />}
    </div>
  </section>;
}
