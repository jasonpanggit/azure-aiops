"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  investigationWorkspaceHref,
  investigationWorkspacesApi,
  type InvestigationTeamWorkspace,
  type InvestigationWorkspaceView,
} from "@/lib/investigation-workspaces";
import type { ScopeSelection } from "@/lib/scope";
import type { Envelope } from "@/lib/types";
import { StatePanel } from "./ui/StatePanel";
import { InvestigationHypothesisBoard } from "./InvestigationHypothesisBoard";
import { InvestigationRetainedEvidence } from "./InvestigationRetainedEvidence";

interface Props {
  scope: ScopeSelection;
  view: InvestigationWorkspaceView;
  initialId?: string;
  initialRevision?: number;
  onRestore: (view: InvestigationWorkspaceView) => void;
}

const validId = (value: string) => /^wrk-[0-9a-f]{32}$/.test(value);
const members = (value: string) => value.split("\n").map(line => line.trim()).filter(Boolean);
const changeLabels = { created: "Created", view_updated: "Navigation saved", access_updated: "Membership changed", hypothesis_updated: "Operator explanation saved", evidence_captured: "Source projections retained" };
const recordedTime = (value: string) => `${new Date(value).toLocaleString(undefined, { timeZone: "UTC", dateStyle: "medium", timeStyle: "medium" })} UTC`;

/** Explicit exact-scope team navigation, current ACLs and reviewed revision history. */
export function InvestigationTeamWorkspacePanel({ scope, view, initialId = "", initialRevision, onRestore }: Props) {
  const [workspaceId, setWorkspaceId] = useState(initialId);
  const [title, setTitle] = useState(view.title.slice(0, 120));
  const [workspace, setWorkspace] = useState<InvestigationTeamWorkspace | null>(null);
  const [revision, setRevision] = useState(initialRevision?.toString() ?? "");
  const [readers, setReaders] = useState("");
  const [editors, setEditors] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback(async (
    id: string, action: (signal: AbortSignal) => Promise<Envelope<InvestigationTeamWorkspace>>,
    expectedRevision?: number,
  ) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const current = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await action(abort.signal);
      if (current !== generation.current) return false;
      const matchesRevision = expectedRevision === undefined
        ? result.data.revision.revision === result.data.latest_revision
        : result.data.revision.revision === expectedRevision;
      if (result.data.workspace_id !== id || !matchesRevision) {
        throw new Error("The workspace response identity or revision did not match. Open the known identity again.");
      }
      setWorkspace(result.data);
      setTitle(result.data.revision.view.title);
      setRevision(String(result.data.revision.revision));
      setReaders(result.data.current_access.readers.join("\n"));
      setEditors(result.data.current_access.editors.join("\n"));
      return true;
    } catch (failure) {
      if (current !== generation.current) return false;
      setError(failure instanceof Error ? failure.message : "Workspace operation was not confirmed. Open its known identity and latest revision before retrying.");
      return false;
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }, []);

  useEffect(() => {
    setWorkspace(null);
    setWorkspaceId(initialId);
    setRevision(initialRevision?.toString() ?? "");
    if (initialId) void run(initialId, signal => investigationWorkspacesApi.read(initialId, scope, initialRevision, signal), initialRevision);
    return () => {
      generation.current += 1;
      controller.current?.abort();
    };
  }, [initialId, initialRevision, run, scope]);

  const create = () => {
    if (!workspaceId && typeof crypto.randomUUID !== "function") {
      setError("Secure workspace identity generation is unavailable. Use a supported secure browser or enter a valid known workspace identity.");
      return;
    }
    const id = workspaceId || `wrk-${crypto.randomUUID().replaceAll("-", "")}`;
    setWorkspaceId(id);
    void run(id, signal => investigationWorkspacesApi.create(id, { ...view, title: title.trim() }, scope, signal), 1);
  };
  const latestSelected = Boolean(workspace && workspace.revision.revision === workspace.latest_revision);
  const viewValid = Boolean(title.trim()) && title.trim().length <= 120 && view.subject.length <= 512 && !/[\0\r\n]/.test(view.subject);

  return (
    <details className="card investigation-team-workspace" aria-label="Team investigation workspace" open={initialId ? true : undefined}>
      <summary>Team workspace: open or save server-backed navigation</summary>
      <div className="card-body">
        <p>Save navigation and operator explanations for explicit collaborators. These are not provider evidence or Copilot answers. Explicit source retention below is separate. Membership does not grant platform access.</p>
        <div className="investigation-team-controls">
          <label>Workspace identity<input className="form-control" value={workspaceId} maxLength={36} placeholder="wrk- followed by 32 lowercase hex characters" disabled={busy} onChange={event => {
            setWorkspaceId(event.target.value.trim());
            setWorkspace(null);
            setRevision("");
          }} /></label>
          <button className="button button-secondary" type="button" disabled={busy || !validId(workspaceId)} onClick={() => {
            setWorkspace(null);
            void run(workspaceId, signal => investigationWorkspacesApi.read(workspaceId, scope, undefined, signal));
          }}>Open latest workspace</button>
          <label>Workspace title<input className="form-control" value={title} maxLength={120} disabled={busy} onChange={event => setTitle(event.target.value)} /></label>
          {!workspace && <button className="button button-secondary" type="button" disabled={busy || !viewValid || Boolean(workspaceId && !validId(workspaceId))} onClick={create}>Create private workspace</button>}
        </div>
        {busy && <p role="status">Waiting for workspace storage. Stopping the browser wait does not confirm a write outcome.</p>}
        {error && <StatePanel title="Workspace operation not confirmed" message={`${error} Open the known identity and latest revision before retrying; no replacement workspace is created automatically.`} tone="error" />}
        {workspace && (
          <>
            <dl className="investigation-team-metadata">
              <div><dt>Owner</dt><dd>{workspace.owner}</dd></div>
              <div><dt>Reviewed revision</dt><dd>{workspace.revision.revision} of {workspace.latest_revision}</dd></div>
              <div><dt>Recorded by</dt><dd>{workspace.revision.actor} at <time dateTime={workspace.revision.recorded_at}>{recordedTime(workspace.revision.recorded_at)}</time></dd></div>
              <div><dt>Saved subject</dt><dd>{workspace.revision.view.entry_type}: {workspace.revision.view.subject || "Current scope"}</dd></div>
            </dl>
            <p className="muted">Current membership controls every historical revision. Restoring navigation loads current authorized evidence, not historical provider conditions.</p>
            <div className="investigation-team-controls">
              <label>Saved revision<select value={revision} disabled={busy} onChange={event => setRevision(event.target.value)}>
                {workspace.history.map(row => <option key={row.revision} value={row.revision}>{row.revision} · {changeLabels[row.change]} · {row.actor} · {recordedTime(row.recorded_at)}</option>)}
              </select></label>
              <button className="button button-secondary" type="button" disabled={busy} onClick={() => {
                setWorkspace(null);
                void run(workspaceId, signal => investigationWorkspacesApi.read(workspaceId, scope, Number(revision), signal), Number(revision));
              }}>Open selected revision</button>
              <button className="button button-secondary" type="button" disabled={busy} onClick={() => onRestore(workspace.revision.view)}>Apply navigation and load current evidence</button>
              <button className="button button-secondary" type="button" disabled={busy || !workspace.can_edit || !latestSelected || !viewValid} onClick={() =>
                void run(workspaceId, signal => investigationWorkspacesApi.replace(workspaceId, workspace.revision.revision, { ...view, title: title.trim() }, scope, signal), workspace.revision.revision + 1)
              }>Save current navigation revision</button>
            </div>
            {!latestSelected && <p className="muted">Historical navigation is review-only. Open the latest workspace before saving navigation or membership.</p>}
            <p><Link href={investigationWorkspaceHref(workspace)}>Open or share this exact navigation revision</Link></p>
            <fieldset disabled={busy || !workspace.can_share || !latestSelected}>
              <legend>Owner-managed membership</legend>
              <p>Use exact authenticated principal subjects, one per line. Readers can review; editors can also save navigation and explanations. Only the owner can change membership. Removing a member revokes historical access too.</p>
              <div className="investigation-team-controls">
                <label>Reader subjects<textarea value={readers} onChange={event => setReaders(event.target.value)} rows={3} maxLength={5140} /></label>
                <label>Editor subjects<textarea value={editors} onChange={event => setEditors(event.target.value)} rows={3} maxLength={5140} /></label>
              </div>
              <button className="button button-secondary" type="button" onClick={() =>
                void run(workspaceId, signal => investigationWorkspacesApi.share(workspaceId, workspace.revision.revision, members(readers), members(editors), scope, signal), workspace.revision.revision + 1)
              }>Save membership revision</button>
            </fieldset>
            {Array.isArray(workspace.revision.hypotheses) ? <InvestigationHypothesisBoard workspace={workspace} busy={busy} onSave={(id, expectedRevision, hypothesis) =>
              run(workspaceId, signal => investigationWorkspacesApi.hypothesis(workspaceId, id, expectedRevision, hypothesis, scope, signal), expectedRevision + 1)
            } /> : <StatePanel title="Hypothesis board unavailable" message="The workspace service did not return an annotation board. Navigation remains available; reopen after the service is updated. No empty board is inferred." tone="error" />}
            {Array.isArray(workspace.captures) ? <InvestigationRetainedEvidence
              key={`${workspace.workspace_id}:${workspace.revision.revision}:${workspace.latest_revision}:${JSON.stringify(scope)}`}
              workspace={workspace} busy={busy} onRetain={id =>
                run(workspaceId, signal => investigationWorkspacesApi.retain(workspaceId, id, workspace.revision.revision, scope, signal), workspace.revision.revision + 1)
              }
            /> : <StatePanel title="Source retention unavailable" message="The workspace service did not return retention metadata. Reopen after the service is updated; no empty history is inferred." tone="error" />}
          </>
        )}
      </div>
    </details>
  );
}
