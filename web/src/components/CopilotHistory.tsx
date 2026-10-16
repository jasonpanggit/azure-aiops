"use client";

import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/hooks/useApi";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { copilotApi } from "@/lib/services";
import { StatePanel } from "./ui/StatePanel";
import { StructuredData } from "./ui/StructuredData";

/** Explicit owned historical reads never attach a thread or execute its turns. */
export function CopilotHistory({ threadId, scope, pinned = false }: {
  threadId: string;
  scope: ScopeSelection;
  pinned?: boolean;
}) {
  const [open, setOpen] = useState(pinned);
  return <details className="card copilot-history" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Retained Copilot history</summary>
    {open ? threadId
      ? <HistoryRead key={`${threadId}:${JSON.stringify(scope)}`} threadId={threadId} scope={scope} pinned={pinned} />
      : <div className="card-body"><StatePanel title="No retained thread selected" message="A completed server response supplies a thread handle. No history is inferred or acquired from another session." /></div>
      : null}
  </details>;
}

function HistoryRead({ threadId, scope, pinned }: { threadId: string; scope: ScopeSelection; pinned: boolean }) {
  const report = useApi(async signal => {
    const result = await copilotApi.retainedHistory(threadId, scope, { signal });
    if (result.data.thread_id !== threadId || result.data.observation_status !== "historical") {
      throw new Error("History response did not match the exact retained historical thread. No replacement was opened.");
    }
    return result;
  }, [threadId, JSON.stringify(scope)]);
  const query = scopeToSearchParams(scope);
  const newHref = `/copilot${query.size ? `?${query}` : ""}`;
  query.set("thread_id", threadId);
  return <div className="card-body">
    <p>Exact thread: {threadId}. These are historical observations, not current evidence. Reading does not restart work, attach this thread to new questions, renew retention or authorize a change.</p>
    <div className="button-row">
      <button className="button" type="button" disabled={report.loading} onClick={report.refetch}>Reload retained history</button>
      {pinned ? <Link className="button" href={newHref}>Leave historical review</Link> : <Link className="button" href={`/copilot?${query}`}>Open exact historical thread</Link>}
    </div>
    {report.loading ? <StatePanel title="Reading retained history" message="Reauthorizing the exact thread under current scope; no tools are restarted." tone="loading" /> : report.error ? <StatePanel title="Retained history unavailable" message={report.error.message} tone="error" /> : report.data ? <>
      <p>Retained revision {report.data.data.thread_revision}. Storage: {report.data.data.durability === "durable" ? "Durable" : "Memory only; not guaranteed after a restart"}. Existing retention: latest 12 turns, at most 1 hour idle or 24 hours total; this read does not extend either limit.</p>
      {report.data.data.turns.length ? <ol className="copilot-history-list">
        {report.data.data.turns.map((turn, index) => <li key={index}>
          <h3>{turn.status === "historical_scope_restricted" ? "Historical turn withheld" : turn.question || "Retained investigation turn"}</h3>
          <p>Historical observation{turn.status ? `; recorded status: ${turn.status}` : ""}. No fresh source check was performed.</p>
          {turn.retained_at ? <p>Recorded: <time dateTime={turn.retained_at}>{turn.retained_at}</time></p> : null}
          <details><summary>Inspect retained turn evidence</summary><StructuredData value={turn} /></details>
        </li>)}
      </ol> : <StatePanel title="No completed turns retained" message="This thread has no completed retained result. An interrupted request may still be running; no automatic retry or replacement occurs." />}
      {report.data.warnings?.map((warning, index) => <p className="muted" key={`${index}:${warning}`}>{warning}</p>)}
    </> : null}
  </div>;
}
