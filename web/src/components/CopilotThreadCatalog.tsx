"use client";

import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/hooks/useApi";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { copilotApi } from "@/lib/services";
import { StatePanel } from "./ui/StatePanel";

/** Explicit server-authorized discovery restores history for review, never execution. */
export function CopilotThreadCatalog({ scope }: { scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  return <details className="card copilot-history" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Find my retained conversations</summary>
    {open ? <Catalog key={JSON.stringify(scope)} scope={scope} /> : null}
  </details>;
}

function Catalog({ scope }: { scope: ScopeSelection }) {
  const [page, setPage] = useState(0);
  const result = useApi(signal => copilotApi.retainedThreads(scope, page, signal), [JSON.stringify(scope), page]);
  const data = result.data?.data;
  return <div className="card-body">
    <p>Only your currently authorized, unexpired threads are returned. Storage pages are not chronological or a stable snapshot. A page may be empty after authorization. No tools run and retention is not renewed.</p>
    <div className="button-row">
      <button type="button" className="button" disabled={result.loading} onClick={result.refetch}>Reload conversation list</button>
      <button type="button" className="button" disabled={result.loading || page === 0} onClick={() => setPage(page - 1)}>Previous storage page</button>
      <button type="button" className="button" disabled={result.loading || Boolean(result.error) || !data?.has_more} onClick={() => setPage(page + 1)}>Next storage page</button>
    </div>
    {result.loading ? <StatePanel title="Finding retained conversations" message="Reauthorizing this storage page under current scope." tone="loading" /> : result.error ? <StatePanel title="Conversation discovery unavailable" message={result.error.message} tone="error" /> : data ? <>
      <p>Storage page {page + 1} of at most 32. Storage: {data.durability === "durable" ? "Durable" : "Memory only; may disappear after restart"}.</p>
      {data.threads.length ? <ul className="copilot-history-list">{data.threads.map(thread => {
        const query = scopeToSearchParams(scope);
        query.set("thread_id", thread.thread_id);
        if (thread.thread_revision > 0) query.set("thread_revision", String(thread.thread_revision));
        return <li key={thread.thread_id}>
          <p>{thread.title_status === "visible" ? thread.question || "Retained investigation" : "Question withheld after scope narrowing, or no completed turn retained"}</p>
          <p>Thread: {thread.thread_id} · Retained revision {thread.thread_revision}</p>
          <Link className="button" href={`/copilot?${query}`}>Review conversation {thread.thread_id}</Link>
        </li>;
      })}</ul> : <StatePanel title="No authorized threads on this storage page" message="This does not prove there is no retained history. Continue to another available storage page, or reopen an exact server-issued thread link." />}
      {data.scan_limit_reached ? <StatePanel title="Discovery scan limit reached" message="Only the first 32 storage pages can be discovered here. Use an exact retained thread link for other records; no complete-history claim is made." tone="partial" /> : null}
    </> : null}
  </div>;
}
