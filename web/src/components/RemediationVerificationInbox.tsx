"use client";

import { useEffect, useState } from "react";
import { formatDateTime, titleize } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { remediationApi } from "@/lib/services";
import type { RemediationNotificationInbox } from "@/lib/remediation-notifications";
import type { Envelope } from "@/lib/types";
import { StatusBadge } from "@/components/ui/StatusBadge";

type Kind = "" | "attention" | "complete" | "cancelled";

/** On-demand in-app notifications over recorded outcomes; never provider polling. */
export function RemediationVerificationInbox({ scope }: { scope: ScopeSelection }) {
  const query = scopeToSearchParams(scope); query.sort();
  return <Workspace key={query.toString()} scope={scope} />;
}

function Workspace({ scope }: { scope: ScopeSelection }) {
  const [open, setOpen] = useState(false);
  return <section className="card remediation-verification-inbox" aria-label="Verification notifications">
    <div className="card-header"><div><h2>Verification notifications</h2><p>Latest recorded outcomes across authorized executions, including retired plans.</p></div>
      <button className="button" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "Close verification notifications" : "Open verification notifications"}</button></div>
    {open && <Inbox scope={scope} />}
  </section>;
}

function Inbox({ scope }: { scope: ScopeSelection }) {
  const [kind, setKind] = useState<Kind>("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  return <div className="card-body">
    <p>This read-only inbox does not submit, retry, cancel, acknowledge or reconcile an execution. Refresh explicitly; no live polling, email, browser notifications or background delivery is configured here.</p>
    <div className="remediation-inbox-controls"><label className="form-field"><span>Recorded outcome filter</span><select className="form-control" value={kind} onChange={event => {
      const value = event.target.value;
      setKind(value === "attention" || value === "complete" || value === "cancelled" ? value : ""); setOffset(0);
    }}><option value="">All recorded outcomes</option><option value="attention">Needs verification review</option><option value="complete">Recorded clean reconciliation</option><option value="cancelled">Recorded cancellation</option></select></label>
      <button className="button" onClick={() => { setOffset(0); setRevision(value => value + 1); }}>Refresh verification notifications</button></div>
    <NotificationRows key={`${kind}:${offset}:${revision}`} scope={scope} kind={kind} offset={offset} setOffset={setOffset} />
    <p>One latest outcome per execution, not full transition history, a personal unread count or a notification-delivery receipt. A recorded success/clean reconciliation does not certify current vulnerability clearance, whole-rollout success or rollback. Source-only Copilot excludes this inbox.</p>
  </div>;
}

function NotificationRows({ scope, kind, offset, setOffset }: { scope: ScopeSelection; kind: Kind; offset: number; setOffset: (offset: number) => void }) {
  const [result, setResult] = useState<Envelope<RemediationNotificationInbox> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void remediationApi.notifications(scope, kind, offset, controller.signal).then(response => {
      if (!controller.signal.aborted) setResult(response);
    }).catch(failure => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "Recorded verification outcomes could not be read.");
    });
    return () => controller.abort();
  }, [scope, kind, offset]);
  if (error) return <p role="alert">{error} Refresh notifications to retry this read; no execution was changed.</p>;
  if (!result) return <p role="status">Reading stored verification outcomes...</p>;
  const rows = result.data.notifications;
  const total = result.pagination?.total ?? rows.length;
  const next = result.pagination?.next_offset;
  return <>
    <p role="status">{result.data.authorized_execution_count} authorized stored execution records; {result.data.latest_outcome_count} latest outcomes across all outcome filters. {total} match this filter.</p>
    {rows.length ? <ol className="remediation-notification-list">{rows.map(row => <li key={row.notification_id}>
      <StatusBadge label={row.kind === "attention" ? "Needs review" : row.kind === "complete" ? "Recorded clean" : "Cancelled"} tone={row.kind === "attention" ? "warning" : "neutral"} />
      <h3>{row.title}</h3>
      <p>Last stored update: {row.recorded_at ? formatDateTime(row.recorded_at) : "Unreported"}. Not the time you opened this notification.</p>
      <dl className="remediation-notification-facts">
        <div><dt>Recorded execution status</dt><dd>{titleize(row.execution_status)}</dd></div>
        <div><dt>Evidence reconciliation</dt><dd>{titleize(row.reconciliation_status)}</dd></div>
      </dl>
      <details><summary>Recorded execution identifiers</summary><dl>
        <div><dt>Execution / revision</dt><dd><code>{row.execution_id}</code> / {row.revision}</dd></div>
        <div><dt>Originating plan</dt><dd><code>{row.plan_id}</code></dd></div>
        <div><dt>Recorded target identity</dt><dd><code>{row.target_id || "Unreported"}</code></dd></div>
        <div><dt>Outcome identity</dt><dd><code>{row.notification_id}</code></dd></div>
      </dl></details>
    </li>)}</ol> : <p>No stored outcome matches this filter. In-progress executions without an ambiguous submission are not completion notifications; absence does not prove a healthy estate.</p>}
    <div className="remediation-inbox-controls"><button className="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous notifications</button>
      <span>Showing {rows.length ? offset + 1 : 0}–{offset + rows.length} of {total}</span>
      <button className="button" disabled={next == null} onClick={() => { if (next != null) setOffset(next); }}>Next notifications</button></div>
  </>;
}
