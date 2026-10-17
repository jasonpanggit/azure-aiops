"use client";

import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/hooks/useApi";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { copilotApi } from "@/lib/services";
import { StatePanel } from "./ui/StatePanel";

/** Explicit receipt inspection never treats admission as running or cancellation. */
export function CopilotRequestRecovery({ requestKey, scope }: { requestKey: string; scope: ScopeSelection }) {
  const [inspect, setInspect] = useState(false);
  return <section className="card copilot-history copilot-request-recovery" aria-label="Accepted request recovery">
    <div className="card-body">
      <p>Request key: {requestKey}</p>
      <p>A receipt check does not retry, cancel or renew work. Completed requests open exact historical review, not a replay as current evidence.</p>
      {inspect ? <Receipt key={`${requestKey}:${JSON.stringify(scope)}`} requestKey={requestKey} scope={scope} /> : <button className="button" type="button" onClick={() => setInspect(true)}>Check accepted request</button>}
    </div>
  </section>;
}

function Receipt({ requestKey, scope }: { requestKey: string; scope: ScopeSelection }) {
  const result = useApi(signal => copilotApi.requestReceipt(requestKey, scope, signal), [requestKey, JSON.stringify(scope)]);
  const data = result.data?.data;
  const valid = data?.request_key === requestKey && data.durability === "durable" && (data.status === "accepted_outcome_unconfirmed" || (data.status === "completed" && /^thr-[a-f0-9]{32}$/.test(data.thread_id) && Number.isSafeInteger(data.thread_revision) && data.thread_revision > 0));
  const query = scopeToSearchParams(scope);
  if (data && valid && data.status === "completed") {
    query.set("thread_id", data.thread_id);
    query.set("thread_revision", String(data.thread_revision));
  }
  return <>
    <button type="button" className="button" onClick={result.refetch} disabled={result.loading}>Reload request receipt</button>
    {result.loading ? <StatePanel title="Checking accepted request" message="Reading one exact authorized receipt; no work is dispatched." tone="loading" /> : result.error ? <StatePanel title="Request receipt unavailable" message={`${result.error.message}. Missing or unavailable receipt data does not prove the question never ran. Retry only with the same request key, never automatically.`} tone="error" /> : !valid ? <StatePanel title="Request receipt unavailable" message="The response does not identify the exact expected request and supported outcome. No result is substituted." tone="error" /> : data?.status === "completed" ? <StatePanel title="Request completion recorded" message="The server recorded a completed turn. Its retained evidence may have expired or its thread revision may have changed; the historical read reauthorizes and checks the exact revision." action={<Link className="button" href={`/copilot?${query}`}>Review completed request history</Link>} /> : <StatePanel title="Request accepted; outcome unconfirmed" message="The server admitted this key. This is not proof work is currently running or was cancelled. This key cannot dispatch again, even after a crash or partial execution. Check retained history or reload this receipt." tone="partial" />}
  </>;
}
