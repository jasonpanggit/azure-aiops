"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { multiAgentApi } from "@/lib/services";
import type { Envelope, InvestigationJob, MultiAgentLedger } from "@/lib/types";

const TERMINAL = new Set<InvestigationJob["status"]>(["completed", "stopped", "failed"]);
const LABELS: Record<InvestigationJob["status"], string> = {
  accepted_outcome_unconfirmed: "Accepted - outcome unconfirmed",
  running: "Last reported running",
  completed: "Ledger retained",
  stopped: "New scheduling stopped",
  failed: "Execution or retention failed",
};

function assertJob(result: Envelope<InvestigationJob>, id: string, scope: ScopeSelection) {
  if (result.data.job_id !== id || !Object.prototype.hasOwnProperty.call(LABELS, result.data.status)) throw new Error("The response did not match this exact investigation request.");
  if (
    !Number.isFinite(result.data.updated_at) || !Number.isFinite(result.data.created_at)
    || result.data.updated_at < result.data.created_at
    || ((result.data.status === "completed") !== /^mai-[A-Za-z0-9_-]{1,100}$/.test(result.data.ledger_id))
  ) throw new Error("Investigation outcome metadata was invalid; no result was opened.");
  const returned = scopeToSearchParams(result.data.scope).toString();
  if (returned !== scopeToSearchParams(result.scope).toString()) throw new Error("Request and response scope did not agree.");
  for (const [dimension, requested] of Object.entries(scope)) {
    const actual = result.data.scope[dimension];
    if (requested?.length && (!actual?.length || actual.some(value => !requested.includes(value)))) {
      throw new Error("The response did not match the requested investigation scope.");
    }
  }
}

/** Single-dispatch admission, bounded metadata polling and exact-ID recovery. */
export function AgentInvestigationJob({ objective, scope, jobId, disabled, onResult, onActiveChange }: {
  objective: string;
  scope: ScopeSelection;
  jobId: string;
  disabled: boolean;
  onResult: (ledger: Envelope<MultiAgentLedger>, jobId: string) => void;
  onActiveChange: (active: boolean) => void;
}) {
  const [knownId, setKnownId] = useState(jobId);
  const [job, setJob] = useState<Envelope<InvestigationJob> | null>(null);
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const opened = useRef("");
  const polls = useRef(0);
  const mounted = useRef(true);
  const readAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; sequence.current += 1; readAbort.current?.abort(); };
  }, []);

  useEffect(() => { onActiveChange(Boolean(knownId) && (busy || !job || !TERMINAL.has(job.data.status))); }, [knownId, job, busy, onActiveChange]);

  const read = useCallback(async (id: string) => {
    const request = ++sequence.current;
    readAbort.current?.abort();
    const controller = new AbortController();
    readAbort.current = controller;
    setBusy(true);
    setError("");
    try {
      const result = await multiAgentApi.job(id, scope, { signal: controller.signal });
      if (!mounted.current || request !== sequence.current) return;
      assertJob(result, id, scope);
      setJob({ ...result });
      if (result.data.status === "completed") {
        setPolling(false);
        const retained = await multiAgentApi.ledger(result.data.ledger_id, scope);
        if (!mounted.current || request !== sequence.current) return;
        if (
          retained.data.ledger_id !== result.data.ledger_id
          || scopeToSearchParams(retained.data.scope).toString() !== scopeToSearchParams(result.data.scope).toString()
        ) throw new Error("The retained ledger did not match this exact request and scope.");
        onResult(retained, id);
      } else if (TERMINAL.has(result.data.status)) {
        setPolling(false);
      } else if (++polls.current >= 60) {
        setPolling(false);
        setError("Automatic status reads paused after 60 checks. Check this exact request again; no work was restarted or cancelled.");
      }
    } catch (reason) {
      if (mounted.current && request === sequence.current) {
        setPolling(false);
        setError(reason instanceof Error ? reason.message : "Request outcome could not be confirmed. Check the exact request; do not redispatch.");
      }
    } finally {
      if (mounted.current && request === sequence.current) setBusy(false);
    }
  }, [scope, onResult]);

  useEffect(() => {
    if (!jobId) {
      if (opened.current) {
        opened.current = "";
        sequence.current += 1;
        readAbort.current?.abort();
        setKnownId("");
        setJob(null);
        setBusy(false);
        setPolling(false);
        setError("");
      }
      return;
    }
    if (opened.current === jobId && !readAbort.current?.signal.aborted) return;
    opened.current = jobId;
    setKnownId(jobId);
    setJob(null);
    setPolling(false);
    polls.current = 0;
    void read(jobId);
  }, [jobId, read]);

  useEffect(() => {
    if (!polling || busy || !knownId || !job || TERMINAL.has(job.data.status)) return;
    const timer = window.setTimeout(() => { void read(knownId); }, 2000);
    return () => window.clearTimeout(timer);
  }, [polling, busy, knownId, job, read]);

  async function start() {
    const nextObjective = objective.trim();
    if (disabled || busy || knownId || !nextObjective || nextObjective.length > 1024) return;
    const id = `job-${crypto.randomUUID().replaceAll("-", "")}`;
    const request = ++sequence.current;
    opened.current = id;
    setKnownId(id);
    setJob(null);
    setBusy(true);
    setError("");
    polls.current = 0;
    const query = scopeToSearchParams(scope);
    query.set("job_id", id);
    window.history.replaceState(window.history.state, "", `/agents?${query}`);
    try {
      const result = await multiAgentApi.startJob(id, nextObjective, scope);
      if (!mounted.current || request !== sequence.current) return;
      assertJob(result, id, scope);
      if (result.data.objective !== nextObjective) throw new Error("The admitted objective did not match this request.");
      setJob(result);
      setPolling(!TERMINAL.has(result.data.status));
      if (result.data.status === "completed") await read(id);
    } catch (reason) {
      if (mounted.current && request === sequence.current) {
        setPolling(false);
        setError(`Admission is unconfirmed. ${reason instanceof Error ? reason.message : "The response was lost."} Check this exact request instead of starting it again.`);
      }
    } finally {
      if (mounted.current && request === sequence.current) setBusy(false);
    }
  }

  async function stop() {
    if (!knownId || busy || !job || TERMINAL.has(job.data.status) || job.data.stop_requested) return;
    const request = ++sequence.current;
    setBusy(true);
    setPolling(false);
    setError("");
    try {
      const result = await multiAgentApi.stopJob(knownId, scope);
      if (!mounted.current || request !== sequence.current) return;
      assertJob(result, knownId, scope);
      setJob(result);
      setPolling(!TERMINAL.has(result.data.status));
      if (result.data.status === "completed") await read(knownId);
    } catch (reason) {
      if (mounted.current && request === sequence.current) setError(`Stop outcome unconfirmed. ${reason instanceof Error ? reason.message : "Check this exact request."}`);
    } finally {
      if (mounted.current && request === sequence.current) setBusy(false);
    }
  }

  const query = scopeToSearchParams(scope);
  const newHref = `/agents${query.size ? `?${query}` : ""}`;
  if (knownId) query.set("job_id", knownId);
  if (jobId && knownId !== jobId) return <StatePanel title="Reading selected investigation request" message="Previous request metadata and results are hidden while the exact new selection is read." tone="loading" />;
  return <section className="card agents-job" aria-label="Background investigation">
    <div className="card-header">
      <div><h2>Background investigation</h2><p>Durable admission and last reported progress, separate from the foreground action above.</p></div>
      {job ? <StatusBadge label={LABELS[job.data.status]} tone={job.data.status === "completed" ? "success" : job.data.status === "failed" ? "critical" : "neutral"} /> : null}
    </div>
    <div className="card-body">
      <p>Stop prevents new scheduling at call boundaries. Already dispatched, nested or remote provider work may continue; provider cancellation is not supported. A running record is not proof that a worker is still alive.</p>
      {!knownId ? <button className="button button-primary" disabled={disabled || busy || !objective.trim() || objective.trim().length > 1024} onClick={() => void start()}>Start background investigation</button> : <>
        <dl><div><dt>Exact request</dt><dd>{knownId}</dd></div>
          {job ? <div><dt>Admitted objective</dt><dd>{job.data.objective}</dd></div> : null}
          <div><dt>Last reported stage</dt><dd>{job?.data.stage ?? "Admission or outcome unconfirmed"}</dd></div>
          {job ? <div><dt>Last metadata update</dt><dd>{new Date(job.data.updated_at * 1000).toISOString()} - not a source observation time</dd></div> : null}
        </dl>
        {job?.data.stop_requested ? <p role="status">Stop requested{job.data.status === "stopped" ? " and new scheduling acknowledged stopped." : ". Completion may win a late request; in-flight provider work is not cancelled."}</p> : null}
        <div className="button-row">
          <button className="button" disabled={busy} onClick={() => { polls.current = 0; setPolling(false); void read(knownId); }}>Check exact request</button>
          {job && !TERMINAL.has(job.data.status) ? <>
            <button className="button" disabled={busy} onClick={() => { polls.current = 0; setPolling(value => !value); }}>{polling ? "Pause status updates" : "Resume status updates"}</button>
            <button className="button" disabled={busy || job.data.stop_requested} onClick={() => void stop()}>Stop new scheduling</button>
          </> : null}
          <Link className="button" href={`/agents?${query}`}>Open request recovery link</Link>
          <Link className="button" href={newHref}>Start a separate investigation</Link>
        </div>
        <p>Recovery reads metadata only and never restarts a job. Admission is not guaranteed delivery; process loss may leave an unconfirmed outcome. Records expire after 24 hours without renewal. A separate request can duplicate work whose outcome is unknown.</p>
      </>}
      {busy ? <p role="status">Confirming this exact request&apos;s metadata; no provider cancellation is implied.</p> : null}
      {error ? <StatePanel title="Investigation request unconfirmed" message={error} tone="error" /> : null}
    </div>
  </section>;
}
