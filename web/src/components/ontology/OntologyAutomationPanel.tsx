"use client";

import { useMemo, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, relativeTime, titleize } from "@/lib/format";
import type { ScopeSelection } from "@/lib/scope";
import { ontologyAutomationApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import type {
  Envelope,
  OntologyAutomationStatus,
  OntologyEvaluation,
  OntologyGeneration,
  OntologyProposal,
  OntologyRun,
} from "@/lib/types";
import { useTablePagination } from "@/lib/use-table-pagination";

export interface OntologyStatusState {
  data: Envelope<OntologyAutomationStatus> | null;
  error: Error | null;
  loading: boolean;
}

interface OntologyAutomationPanelProps {
  connectionId: string;
  scope: ScopeSelection;
  refreshKey: number;
  status: OntologyStatusState;
  onRunNow: () => void;
  onRefresh: () => void;
}

const ACTIVE_RUN_STATUSES = new Set(["queued", "running", "retrying"]);

function idempotencyKey(action: string, id: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${action}:${id}:${suffix}`;
}

function display(value: string | number | null | undefined, fallback = "Not reported"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "Not reported" : `${(value * 100).toFixed(1)}%`;
}

function runStatusLabel(run: OntologyRun): string {
  if (run.cancel_requested && !["cancelled", "failed", "succeeded"].includes(run.status)) {
    return "Cancel requested";
  }
  return titleize(run.status);
}

/** Durable, connection-scoped ontology discovery and publication operating surface. */
export function OntologyAutomationPanel({
  connectionId,
  scope,
  refreshKey,
  status,
  onRunNow,
  onRefresh,
}: OntologyAutomationPanelProps) {
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [runningAction, setRunningAction] = useState("");
  const reviewButtonRef = useRef<HTMLButtonElement | null>(null);
  const scopeKey = JSON.stringify(scope);

  const runs = useApi(
    () => ontologyAutomationApi.runs(connectionId, scope),
    [connectionId, scopeKey, refreshKey],
  );
  const proposals = useApi(
    () => ontologyAutomationApi.proposals(connectionId, scope),
    [connectionId, scopeKey, refreshKey],
  );
  const generation = useApi(
    () => ontologyAutomationApi.generation(connectionId, scope),
    [connectionId, scopeKey, refreshKey],
  );
  const publications = useApi(
    () => ontologyAutomationApi.publications(connectionId, scope),
    [connectionId, scopeKey, refreshKey],
  );
  const evaluation = useApi(
    () => ontologyAutomationApi.evaluation(connectionId, scope),
    [connectionId, scopeKey, refreshKey],
  );
  const evaluationHistory = useApi(
    () => ontologyAutomationApi.evaluations(connectionId, scope),
    [connectionId, scopeKey, refreshKey],
  );

  const runRows = useMemo(() => runs.data?.data ?? [], [runs.data]);
  const proposalRows = useMemo(() => proposals.data?.data ?? [], [proposals.data]);
  const publicationRows = useMemo(() => publications.data?.data ?? [], [publications.data]);
  const proposalFilters = useColumnFilters(proposalRows, [
    { id: "predicate", label: "Predicate", getValues: (row) => row.proposal.predicate || "Not reported" },
    { id: "decision", label: "Decision", getValues: (row) => row.review.status },
    { id: "freshness", label: "Freshness", getValues: (row) => row.proposal.freshness || "unknown" },
  ]);
  const proposalPaging = useTablePagination(proposalFilters.filteredRows);
  const runFilters = useColumnFilters(runRows, [
    { id: "trigger", label: "Trigger", getValues: (row) => row.trigger },
    { id: "status", label: "Status", getValues: (row) => row.status },
    { id: "checkpoint", label: "Checkpoint", getValues: (row) => row.checkpoint.name },
  ]);
  const runPaging = useTablePagination(runFilters.filteredRows);
  const publicationPaging = useTablePagination(publicationRows);
  const durableStatus = status.data?.data ?? null;
  const currentRun = durableStatus?.current_run ?? null;
  const activeRun = currentRun && ACTIVE_RUN_STATUSES.has(currentRun.status) ? currentRun : null;
  const latestObservedRun = !status.error && !status.loading
    ? currentRun ?? (!runs.error && !runs.loading ? runRows[0] : undefined)
    : undefined;
  const completedRun = latestObservedRun?.status === "succeeded"
    ? latestObservedRun
    : undefined;
  const noObservedRun = Boolean(durableStatus && runs.data)
    && !status.error && !status.loading && !runs.error && !runs.loading
    && !currentRun && runRows.length === 0;
  const proposalEmptyMessage = noObservedRun
    ? "No completed discovery run has been observed for this connection. Run discovery to collect proposal evidence."
    : completedRun?.checkpoint.payload.proposal_count === 0
      ? "The latest completed run produced no proposals requiring a decision for this scope."
      : "No proposals are currently available for review. A completed zero-proposal result has not been verified.";

  function refreshAll() {
    onRefresh();
  }

  async function mutateRun(run: OntologyRun, action: "cancel" | "retry") {
    if (action === "cancel") {
      const confirmed = window.confirm(
        `Cancel run ${run.run_id}? Work stops at the next safe checkpoint. The active ontology generation will not change.`,
      );
      if (!confirmed) return;
    }
    setActionError("");
    setActionMessage("");
    setRunningAction(`${action}:${run.run_id}`);
    try {
      if (action === "cancel") {
        await ontologyAutomationApi.cancelRun(connectionId, run.run_id, scope, {
          expected_revision: run.revision,
          reason: "Cancellation requested from ontology automation.",
        });
        setActionMessage(`Cancellation requested for run ${run.run_id}.`);
      } else {
        await ontologyAutomationApi.retryRun(connectionId, run.run_id, scope, {
          expected_revision: run.revision,
          reason: "Retry requested from ontology automation.",
          idempotency_key: idempotencyKey("retry", run.run_id),
        });
        setActionMessage(`Retry started for run ${run.run_id}.`);
      }
      refreshAll();
    } catch (reason) {
      const safeReason = reason instanceof Error ? reason.message : "Request failed.";
      setActionError(
        action === "cancel"
          ? `Cancellation was not requested for run ${run.run_id}. ${safeReason} Refresh run status before trying again.`
          : `Retry was not started for run ${run.run_id}. ${safeReason} Refresh run eligibility before trying again.`,
      );
    } finally {
      setRunningAction("");
    }
  }

  async function reviewProposal(
    proposal: OntologyProposal,
    action: "accept" | "reject",
    button: HTMLButtonElement,
  ) {
    const reason = window.prompt(
      `${action === "accept" ? "Accept" : "Reject"} proposal ${proposal.proposal_id}. Enter a review reason:`,
    );
    if (reason === null) return;
    reviewButtonRef.current = button;
    setActionError("");
    setActionMessage("");
    setRunningAction(`${action}:${proposal.proposal_id}`);
    try {
      await ontologyAutomationApi.reviewProposal(connectionId, proposal.proposal_id, scope, {
        action,
        expected_revision: proposal.review.revision,
        reason: reason.trim() || "Reviewed from ontology automation.",
      });
      setActionMessage(`Proposal ${proposal.proposal_id} was ${action === "accept" ? "accepted" : "rejected"}.`);
      refreshAll();
    } catch (failure) {
      const safeReason = failure instanceof Error ? failure.message : "Request failed.";
      setActionError(
        `Proposal ${proposal.proposal_id} was not ${action === "accept" ? "accepted" : "rejected"}. ${safeReason} Refresh the proposal before deciding again.`,
      );
    } finally {
      setRunningAction("");
      reviewButtonRef.current?.focus();
    }
  }

  async function rollback(target: OntologyGeneration) {
    if (!target.prior_generation || !target.can_rollback) return;
    const confirmed = window.confirm(
      `Roll back to generation ${target.prior_generation}? This changes the active pointer and preserves both generations and the audit history.`,
    );
    if (!confirmed) return;
    setActionError("");
    setActionMessage("");
    setRunningAction(`rollback:${target.prior_generation}`);
    try {
      await ontologyAutomationApi.rollbackGeneration(
        connectionId,
        target.prior_generation,
        scope,
        {
          expected_etag: target.pointer_etag,
          reason: "Rollback requested from ontology automation.",
          idempotency_key: idempotencyKey("rollback", target.prior_generation),
        },
      );
      setActionMessage(`Rollback requested for generation ${target.prior_generation}.`);
      refreshAll();
    } catch (reason) {
      const safeReason = reason instanceof Error ? reason.message : "Request failed.";
      setActionError(
        `Generation ${target.prior_generation} was not activated. ${safeReason} Refresh generation history and rollback eligibility before trying again.`,
      );
    } finally {
      setRunningAction("");
    }
  }

  return (
    <section
      id="ontology-automation-panel"
      role="tabpanel"
      aria-labelledby="ontology-automation-tab"
      tabIndex={0}
      className="ontology-automation"
    >
      {status.data && (
        <EvidenceBar
          evidence={status.data.evidence}
          knowledgeVersion={status.data.knowledge_version}
          warnings={status.data.warnings}
        />
      )}

      {(actionError || actionMessage) && (
        <div
          className={`callout ${actionError ? "callout-critical" : "callout-success"}`}
          role={actionError ? "alert" : "status"}
        >
          {actionError || actionMessage}
        </div>
      )}

      {activeRun && (
        <CurrentRunCard
          run={activeRun}
          runningAction={runningAction}
          onCancel={() => void mutateRun(activeRun, "cancel")}
          onRetry={() => void mutateRun(activeRun, "retry")}
        />
      )}

      <OntologyMetrics status={status} generation={generation.data?.data} evaluation={evaluation.data?.data} />

      <SchedulerSection status={status} onRunNow={onRunNow} />

      {!activeRun && (
        <CurrentRunSection
          status={status}
          runningAction={runningAction}
          onCancel={(run) => void mutateRun(run, "cancel")}
          onRetry={(run) => void mutateRun(run, "retry")}
        />
      )}

      <IncrementalSection status={status} />

      <section className="card" aria-labelledby="ontology-proposals-heading">
        <div className="card-header">
          <div>
            <h2 id="ontology-proposals-heading">Relationship proposals</h2>
            <p>Review bounded model proposals without granting the browser publication authority.</p>
          </div>
        </div>
        <div className="card-body">
          {proposals.error ? (
            <StatePanel
              title="Relationship proposals are unavailable"
              message="Relationship proposals are unavailable. No review decision was changed. Refresh proposals before acting."
              tone="error"
            />
          ) : proposals.loading ? (
            <StatePanel title="Loading relationship proposals" message="Reading durable proposal and review revisions." tone="loading" />
          ) : proposalRows.length === 0 ? (
            <StatePanel
              title="No relationship proposals need review"
              message={proposalEmptyMessage}
            />
          ) : (
            <>
              <TableColumnFilters
                filters={proposalFilters.filters}
                onReset={proposalFilters.resetFilters}
                resultCount={proposalFilters.filteredRows.length}
                totalCount={proposalRows.length}
              />
              {proposalFilters.filteredRows.length === 0 ? (
                <StatePanel
                  title="No proposals match these filters"
                  message="Clear filters to review all relationship proposals."
                  action={<button type="button" className="button button-quiet" onClick={proposalFilters.resetFilters}>Clear filters</button>}
                />
              ) : (
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Subject</th><th>Predicate</th><th>Object</th><th>Confidence</th>
                        <th>Evidence freshness</th><th>Decision</th><th>Review action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {proposalPaging.pageRows.map((row) => (
                        <tr key={row.proposal_id}>
                          <td className="ontology-long-value">{display(row.proposal.subject_id)}</td>
                          <td>{display(row.proposal.predicate)}</td>
                          <td className="ontology-long-value">{display(row.proposal.object_id)}</td>
                          <td>{percent(row.proposal.confidence)}</td>
                          <td><StatusBadge label={titleize(display(row.proposal.freshness, "unknown"))} tone={statusTone(row.proposal.freshness)} /></td>
                          <td><StatusBadge label={titleize(row.review.status)} tone={statusTone(row.review.status)} /></td>
                          <td>
                            <div className="row-actions">
                              {row.review.status === "pending" ? (
                                <>
                                  <button
                                    type="button"
                                    className="button button-quiet"
                                    disabled={Boolean(runningAction)}
                                    onClick={(event) => void reviewProposal(row, "accept", event.currentTarget)}
                                  >
                                    Accept proposal
                                  </button>
                                  <button
                                    type="button"
                                    className="button button-quiet"
                                    disabled={Boolean(runningAction)}
                                    onClick={(event) => void reviewProposal(row, "reject", event.currentTarget)}
                                  >
                                    Reject proposal
                                  </button>
                                </>
                              ) : (
                                <span className="table-secondary">Decision recorded at revision {row.review.revision}</span>
                              )}
                            </div>
                            <details>
                              <summary>Proposal evidence</summary>
                              <StructuredData value={{
                                rationale: row.proposal.rationale,
                                source_generation: row.source_generation_id,
                                schema_version: row.schema_version,
                                policy_version: row.policy_version,
                              }} />
                            </details>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <TablePagination
                total={proposalPaging.total}
                pageRows={proposalPaging.pageRows.length}
                page={proposalPaging.page}
                onPageChange={proposalPaging.setPage}
                pageSize={proposalPaging.pageSize}
                onPageSizeChange={proposalPaging.setPageSize}
                label="relationship proposals"
              />
            </>
          )}
        </div>
      </section>

      <GenerationSection
        generation={generation}
        runningAction={runningAction}
        onRollback={(item) => void rollback(item)}
      />

      <RunHistorySection
        runs={runs}
        rows={runRows}
        filters={runFilters}
        paging={runPaging}
        runningAction={runningAction}
        onRetry={(run) => void mutateRun(run, "retry")}
      />

      <PublicationHistorySection
        publications={publications}
        rows={publicationRows}
        paging={publicationPaging}
      />

      <EvaluationSection evaluation={evaluation} historyError={evaluationHistory.error} />
    </section>
  );
}

function OntologyMetrics({
  status,
  generation,
  evaluation,
}: {
  status: OntologyStatusState;
  generation?: OntologyGeneration;
  evaluation?: OntologyEvaluation;
}) {
  const current = status.data?.data;
  return (
    <div className="metric-grid">
      <MetricCard
        label="Scheduler state"
        value={status.loading ? null : current ? titleize(current.scheduler.state) : "Unavailable"}
        detail="External durable job ownership"
        size="text"
        tone={status.error ? "critical" : "default"}
      />
      <MetricCard
        label="Last valid generation"
        value={generation?.active_generation || null}
        detail="Current Fabric ontology pointer"
        size="text"
        tone={generation?.status === "active" ? "success" : "warning"}
      />
      <MetricCard
        label="Proposals awaiting review"
        value={current?.proposals.pending_count}
        detail={`${current?.proposals.total ?? 0} durable proposals in scope`}
        tone={current?.proposals.pending_count ? "warning" : "success"}
      />
      <MetricCard
        label="Current validation status"
        value={evaluation ? titleize(evaluation.status) : null}
        detail={evaluation?.release_eligible ? "Release evidence eligible" : "Release remains disabled"}
        size="text"
        tone={evaluation?.status === "fresh" && evaluation.release_eligible ? "success" : "warning"}
      />
    </div>
  );
}

function SchedulerSection({ status, onRunNow }: { status: OntologyStatusState; onRunNow: () => void }) {
  const scheduler = status.data?.data.scheduler;
  return (
    <section className="card" aria-labelledby="ontology-scheduler-heading">
      <div className="card-header">
        <div>
          <h2 id="ontology-scheduler-heading">Scheduler state</h2>
          <p>Scheduled and manual triggers use the same durable coordinator.</p>
        </div>
        {scheduler && <StatusBadge label={titleize(scheduler.state)} tone={statusTone(scheduler.state)} />}
      </div>
      <div className="card-body">
        {status.error ? (
          <StatePanel
            title="Ontology schedule is unavailable"
            message="Ontology schedule is unavailable. Existing run and generation history remains visible. Refresh status or run discovery manually if eligible."
            tone="error"
          />
        ) : status.loading ? (
          <StatePanel title="Loading ontology schedule" message="Reading durable scheduler ownership and run eligibility." tone="loading" />
        ) : scheduler ? (
          <>
            <dl className="ontology-facts">
              <div><dt>Enabled</dt><dd>{scheduler.enabled === undefined ? "Not reported" : scheduler.enabled ? "Enabled" : "Disabled"}</dd></div>
              <div><dt>Cadence</dt><dd>{display(scheduler.cadence)}</dd></div>
              <div><dt>Next due run</dt><dd>{scheduler.next_due_at ? formatDateTime(scheduler.next_due_at) : "Not reported"}</dd></div>
              <div><dt>Last trigger</dt><dd>{scheduler.last_trigger_at ? formatDateTime(scheduler.last_trigger_at) : "Not reported"}</dd></div>
              <div><dt>Lifecycle owner</dt><dd>{scheduler.owner === "external_job" ? "External durable job" : titleize(scheduler.owner)}</dd></div>
            </dl>
            <div className="ontology-action-line">
              <button
                type="button"
                className="button button-quiet"
                aria-label="Run discovery now from scheduler card"
                disabled={!scheduler.can_run_now}
                onClick={onRunNow}
              >
                Run discovery now
              </button>
              <span>Uses the same durable coordinator as scheduled discovery. Closing this page does not stop the run.</span>
              {!scheduler.can_run_now && scheduler.run_now_disabled_reason && <strong>{scheduler.run_now_disabled_reason}</strong>}
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}

function CurrentRunSection({
  status,
  runningAction,
  onCancel,
  onRetry,
}: {
  status: OntologyStatusState;
  runningAction: string;
  onCancel: (run: OntologyRun) => void;
  onRetry: (run: OntologyRun) => void;
}) {
  if (status.error || status.loading) return null;
  const run = status.data?.data.current_run;
  return run ? (
    <CurrentRunCard run={run} runningAction={runningAction} onCancel={() => onCancel(run)} onRetry={() => onRetry(run)} />
  ) : (
    <StatePanel
      title="Ontology discovery has not run for this connection"
      message="Wait for the scheduled run or run discovery now. Existing Fabric ontology data is unchanged."
    />
  );
}

function CurrentRunCard({
  run,
  runningAction,
  onCancel,
  onRetry,
}: {
  run: OntologyRun;
  runningAction: string;
  onCancel: () => void;
  onRetry: () => void;
}) {
  return (
    <section className="card ontology-current-run" aria-labelledby="ontology-current-run-heading" aria-live="polite">
      <div className="card-header">
        <div>
          <h2 id="ontology-current-run-heading">Current discovery run</h2>
          <p>{run.run_id}</p>
        </div>
        <StatusBadge label={runStatusLabel(run)} tone={statusTone(run.status)} />
      </div>
      <div className="card-body">
        <dl className="ontology-facts">
          <div><dt>Trigger</dt><dd>{titleize(run.trigger)}</dd></div>
          <div><dt>Stage</dt><dd>{titleize(run.checkpoint.name)}</dd></div>
          <div><dt>Progress</dt><dd>{display(run.checkpoint.payload.published_count, "Not reported")} published</dd></div>
          <div><dt>Checkpoint</dt><dd>{display(run.checkpoint.name)}</dd></div>
          <div><dt>Attempt</dt><dd>{run.attempt_count} of {run.max_attempts}</dd></div>
          <div><dt>Deadline</dt><dd>{run.deadline_at ? formatDateTime(run.deadline_at) : "Not reported"}</dd></div>
          <div><dt>Lease owner</dt><dd>Not disclosed by server</dd></div>
          <div><dt>Fence</dt><dd>{display(run.fencing_token)}</dd></div>
          <div><dt>Lease expiry</dt><dd>{run.lease_expires_at ? formatDateTime(run.lease_expires_at) : "Not reported"}</dd></div>
          <div><dt>Cancellation</dt><dd>{run.cancel_requested ? "Requested; awaiting safe checkpoint" : "Not requested"}</dd></div>
        </dl>
        {run.status === "failed" && (
          <div className="callout callout-critical" role="alert">
            Ontology discovery failed at {run.checkpoint.name}. {run.message || "No safe reason was reported."} Review the attempt, then retry from the recorded checkpoint.
          </div>
        )}
        <div className="ontology-action-line">
          <button type="button" className="button button-quiet" disabled={!run.can_cancel || Boolean(runningAction)} onClick={onCancel}>
            {runningAction === `cancel:${run.run_id}` ? "Requesting cancellation…" : "Cancel run"}
          </button>
          {!run.can_cancel && run.disabled_reasons.cancel && <strong>{run.disabled_reasons.cancel}</strong>}
          <button type="button" className="button button-quiet" disabled={!run.can_retry || Boolean(runningAction)} onClick={onRetry}>
            {runningAction === `retry:${run.run_id}` ? "Starting retry…" : "Retry discovery run"}
          </button>
          {!run.can_retry && run.disabled_reasons.retry && <span>{run.disabled_reasons.retry}</span>}
        </div>
      </div>
    </section>
  );
}

function IncrementalSection({ status }: { status: OntologyStatusState }) {
  const incremental = status.data?.data.incremental;
  return (
    <section className="card" aria-labelledby="ontology-incremental-heading">
      <div className="card-header">
        <div><h2 id="ontology-incremental-heading">Incremental discovery</h2><p>Scoped deltas and unresolved relationship endpoints.</p></div>
      </div>
      <div className="card-body">
        {status.error ? (
          <StatePanel
            title="Incremental discovery details are unavailable"
            message="Incremental discovery details are unavailable. No pending relationship was removed or promoted. Refresh discovery details."
            tone="error"
          />
        ) : status.loading ? (
          <StatePanel title="Loading incremental discovery" message="Reading durable checkpoints and pending endpoints." tone="loading" />
        ) : incremental ? (
          <>
            <dl className="ontology-facts">
              <div><dt>Added</dt><dd>{display(incremental.added_count)}</dd></div>
              <div><dt>Changed</dt><dd>{display(incremental.changed_count)}</dd></div>
              <div><dt>Retired</dt><dd>{display(incremental.retired_count)}</dd></div>
              <div><dt>Unresolved</dt><dd>{display(incremental.unresolved_count, String(incremental.pending_count))}</dd></div>
              <div><dt>Stale</dt><dd>{display(incremental.stale_count)}</dd></div>
              <div><dt>Last full reconciliation</dt><dd>{incremental.last_reconciliation_at ? `${formatDateTime(incremental.last_reconciliation_at)} · ${titleize(display(incremental.last_reconciliation_result))}` : "Not reported"}</dd></div>
            </dl>
            {incremental.pending_relationships.length === 0 ? (
              <p className="muted">No relationships are waiting for unresolved endpoints.</p>
            ) : (
              <div className="table-scroll">
                <table className="operations-table">
                  <thead><tr><th>Subject</th><th>Predicate</th><th>Object</th><th>Missing endpoint</th><th>First observed</th><th>Last observed</th><th>Attempts</th><th>Status</th></tr></thead>
                  <tbody>
                    {incremental.pending_relationships.map((row) => (
                      <tr key={row.pending_id}>
                        <td className="ontology-long-value">{row.subject_id}</td>
                        <td>{row.predicate}</td>
                        <td className="ontology-long-value">{row.object_id}</td>
                        <td className="ontology-long-value">{row.missing_endpoint_ids.join(", ")}</td>
                        <td>{formatDateTime(row.created_at)}</td>
                        <td>{formatDateTime(row.updated_at)}</td>
                        <td>{row.attempts}</td>
                        <td><StatusBadge label={titleize(row.terminal_state || row.freshness)} tone={statusTone(row.terminal_state || row.freshness)} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}

function GenerationSection({
  generation,
  runningAction,
  onRollback,
}: {
  generation: ReturnType<typeof useApi<Envelope<OntologyGeneration>>>;
  runningAction: string;
  onRollback: (generation: OntologyGeneration) => void;
}) {
  const item = generation.data?.data;
  const validationObserved = item && (item.validation.observed
    ?? (item.status !== "unavailable"
      && (item.validation.passed || item.validation.errors.length > 0)));
  return (
    <section className="card" aria-labelledby="ontology-generation-heading">
      <div className="card-header">
        <div><h2 id="ontology-generation-heading">Generation and publication</h2><p>Immutable generation validation and active Fabric pointer state.</p></div>
        {item && <StatusBadge label={titleize(item.status)} tone={statusTone(item.status)} />}
      </div>
      <div className="card-body">
        {generation.error ? (
          <StatePanel
            title="Ontology generation status is unavailable"
            message="Ontology generation status is unavailable. Do not assume publication completed. Refresh generation status."
            tone="error"
          />
        ) : generation.loading ? (
          <StatePanel title="Loading ontology generation" message="Reading the active pointer, validation, and rollback eligibility." tone="loading" />
        ) : item ? (
          <>
            <dl className="ontology-facts">
              <div><dt>Active generation</dt><dd>{display(item.active_generation)}</dd></div>
              <div><dt>Source generation</dt><dd>{display(item.source_generation)}</dd></div>
              <div><dt>Validation</dt><dd>{!validationObserved ? "Not reported" : item.validation.passed ? "Passed" : "Failed"}</dd></div>
              <div><dt>Fence/version</dt><dd>{item.fence} · {display(item.pointer_etag)}</dd></div>
              <div><dt>Prior generation</dt><dd>{display(item.prior_generation)}</dd></div>
              <div><dt>Authoritative model edges</dt><dd>{item.validation.model_derived_relationships}</dd></div>
              <div><dt>Publication intent/result</dt><dd>{display(item.publication.intent)} / {display(item.publication.result)}</dd></div>
            </dl>
            {item.validation.errors.length > 0 && (
              <details><summary>Validation details</summary><StructuredData value={item.validation} /></details>
            )}
            <div className="ontology-action-line">
              <button
                type="button"
                className="button button-quiet"
                disabled={!item.can_rollback || Boolean(runningAction)}
                onClick={() => onRollback(item)}
              >
                {runningAction.startsWith("rollback:") ? "Requesting rollback…" : "Roll back generation"}
              </button>
              {!item.can_rollback && item.rollback_disabled_reason && <strong>{item.rollback_disabled_reason}</strong>}
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}

function RunHistorySection({
  runs,
  rows,
  filters,
  paging,
  runningAction,
  onRetry,
}: {
  runs: ReturnType<typeof useApi<Envelope<OntologyRun[]>>>;
  rows: OntologyRun[];
  filters: ReturnType<typeof useColumnFilters<OntologyRun>>;
  paging: ReturnType<typeof useTablePagination<OntologyRun>>;
  runningAction: string;
  onRetry: (run: OntologyRun) => void;
}) {
  return (
    <section className="card" aria-labelledby="ontology-run-history-heading">
      <div className="card-header"><div><h2 id="ontology-run-history-heading">Discovery run history</h2><p>Durable attempts reconstructed after reload.</p></div></div>
      <div className="card-body">
        {runs.error ? (
          <StatePanel title="Discovery run history is unavailable" message="Discovery run history is unavailable. Current run state was not changed. Refresh run history." tone="error" />
        ) : runs.loading ? (
          <StatePanel title="Loading discovery run history" message="Reading durable run attempts and checkpoints." tone="loading" />
        ) : rows.length === 0 ? (
          <p className="muted">No discovery run history is available for this connection.</p>
        ) : (
          <>
            <TableColumnFilters filters={filters.filters} onReset={filters.resetFilters} resultCount={filters.filteredRows.length} totalCount={rows.length} />
            <div className="table-scroll">
              <table className="operations-table">
                <thead><tr><th>Trigger</th><th>Start/end</th><th>Terminal state</th><th>Last checkpoint</th><th>Proposal / accepted / published</th><th>Source / target generation</th><th>Attempt</th><th>Failure class</th><th>Action</th></tr></thead>
                <tbody>
                  {paging.pageRows.map((run) => (
                    <tr key={run.run_id}>
                      <td>{titleize(run.trigger)}</td>
                      <td>{formatDateTime(run.created_at)}<div className="table-secondary">{formatDateTime(run.updated_at)}</div></td>
                      <td><StatusBadge label={runStatusLabel(run)} tone={statusTone(run.status)} /></td>
                      <td>{titleize(run.checkpoint.name)}</td>
                      <td>{display(run.checkpoint.payload.proposal_count, "0")} / {display(run.checkpoint.payload.accepted_count, "0")} / {display(run.checkpoint.payload.published_count, "0")}</td>
                      <td className="ontology-long-value">{display(run.source_generation_id)} / {display(run.checkpoint.payload.generation_id)}</td>
                      <td>{run.attempt_count} of {run.max_attempts}</td>
                      <td>{display(run.failure_class, "None")}</td>
                      <td>
                        <button type="button" className="button button-quiet" disabled={!run.can_retry || Boolean(runningAction)} onClick={() => onRetry(run)}>Retry discovery run</button>
                        {!run.can_retry && <div className="table-secondary">{run.disabled_reasons.retry}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TablePagination total={paging.total} pageRows={paging.pageRows.length} page={paging.page} onPageChange={paging.setPage} pageSize={paging.pageSize} onPageSizeChange={paging.setPageSize} label="discovery runs" />
          </>
        )}
      </div>
    </section>
  );
}

function PublicationHistorySection({
  publications,
  rows,
  paging,
}: {
  publications: ReturnType<typeof useApi<Envelope<OntologyRun[]>>>;
  rows: OntologyRun[];
  paging: ReturnType<typeof useTablePagination<OntologyRun>>;
}) {
  return (
    <section className="card" aria-labelledby="ontology-publication-history-heading">
      <div className="card-header"><div><h2 id="ontology-publication-history-heading">Publication attempt history</h2><p>Pointer changes remain distinct from discovery completion.</p></div></div>
      <div className="card-body">
        {publications.error ? (
          <StatePanel title="Publication attempt history is unavailable" message="Publication attempt history is unavailable. The active generation was not changed. Refresh publication history." tone="error" />
        ) : publications.loading ? (
          <StatePanel title="Loading publication attempts" message="Reading durable publication checkpoints." tone="loading" />
        ) : rows.length === 0 ? (
          <p className="muted">No ontology publication attempts are available. Existing Fabric data is unchanged.</p>
        ) : (
          <>
            <div className="table-scroll">
              <table className="operations-table">
                <thead><tr><th>Run</th><th>Checkpoint</th><th>Source generation</th><th>Target generation</th><th>Status</th><th>Attempt</th><th>Failure class</th></tr></thead>
                <tbody>
                  {paging.pageRows.map((run) => (
                    <tr key={run.run_id}>
                      <td>{run.run_id}</td>
                      <td>{titleize(run.checkpoint.name)}</td>
                      <td className="ontology-long-value">{display(run.checkpoint.payload.source_generation || run.source_generation_id)}</td>
                      <td className="ontology-long-value">{display(run.checkpoint.payload.active_generation || run.checkpoint.payload.generation_id)}</td>
                      <td><StatusBadge label={runStatusLabel(run)} tone={statusTone(run.status)} /></td>
                      <td>{run.attempt_count} of {run.max_attempts}</td>
                      <td>{display(run.failure_class, "None")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TablePagination total={paging.total} pageRows={paging.pageRows.length} page={paging.page} onPageChange={paging.setPage} pageSize={paging.pageSize} onPageSizeChange={paging.setPageSize} label="publication attempts" />
          </>
        )}
      </div>
    </section>
  );
}

function EvaluationSection({
  evaluation,
  historyError,
}: {
  evaluation: ReturnType<typeof useApi<Envelope<OntologyEvaluation>>>;
  historyError: Error | null;
}) {
  const item = evaluation.data?.data;
  const snapshot = item?.snapshot;
  const precision = snapshot?.slice_metrics.find((metric) => metric.metric === "precision");
  const recall = snapshot?.slice_metrics.find((metric) => metric.metric === "recall");
  const injection = snapshot?.slice_metrics.find((metric) => metric.metric.includes("injection"));
  const latency = snapshot?.slice_metrics.find((metric) => metric.metric.includes("latency"));
  return (
    <section className="card" aria-labelledby="ontology-evaluation-heading">
      <div className="card-header">
        <div><h2 id="ontology-evaluation-heading">Evaluation and relationship proposal agent</h2><p>Durable release evidence, governed slices, and agent degradation.</p></div>
        {item && <StatusBadge label={titleize(item.status)} tone={statusTone(item.status)} />}
      </div>
      <div className="card-body">
        {evaluation.error ? (
          <StatePanel title="Agent evaluation status is unavailable" message="Agent evaluation status is unavailable. Auto-accept remains disabled until evaluation evidence is restored." tone="error" />
        ) : evaluation.loading ? (
          <StatePanel title="Loading agent evaluation" message="Reading the durable EvaluationSnapshot and release gate." tone="loading" />
        ) : item ? (
          <>
            {item.status === "stale" && (
              <div className="callout callout-warning" role="status">
                Evaluation snapshot is stale. Release remains disabled until fresh evaluation evidence is restored.
              </div>
            )}
            {(["missing", "invalid"] as const).includes(item.status as "missing" | "invalid") && (
              <div className="callout callout-warning" role="status">
                Relationship proposal agent is unavailable. Deterministic discovery can continue; no model proposals will be promoted.
              </div>
            )}
            {snapshot ? (
              <>
                <dl className="ontology-facts">
                  <div><dt>Snapshot version</dt><dd className="ontology-long-value">{snapshot.snapshot_id}</dd></div>
                  <div><dt>Contract version</dt><dd>{snapshot.contract_version}</dd></div>
                  <div><dt>Evaluated</dt><dd>{formatDateTime(snapshot.evaluated_at)} · {relativeTime(snapshot.evaluated_at)}</dd></div>
                  <div><dt>Expires</dt><dd>{formatDateTime(snapshot.expires_at)} · {relativeTime(snapshot.expires_at)}</dd></div>
                  <div><dt>Curator version</dt><dd>{snapshot.lineage.agent_version}</dd></div>
                  <div><dt>Agent mode</dt><dd>{item.agent_mode ? titleize(item.agent_mode) : "Not reported by server"}</dd></div>
                  <div><dt>Degraded-agent status</dt><dd>{item.agent_status ? titleize(item.agent_status) : "Not reported by server"}</dd></div>
                  <div><dt>Last evaluation gate</dt><dd>{titleize(item.status)}</dd></div>
                  <div><dt>Precision</dt><dd>{percent(precision?.value)}</dd></div>
                  <div><dt>Recall</dt><dd>{percent(recall?.value)}</dd></div>
                  <div><dt>Injection test</dt><dd>{injection ? percent(injection.value) : "Not reported"}</dd></div>
                  <div><dt>Latency</dt><dd>{latency ? percent(latency.value) : "Not reported"}</dd></div>
                  <div><dt>Release eligibility</dt><dd>{item.release_eligible ? "Eligible" : `Disabled — ${item.release_disabled_reason || item.reason}`}</dd></div>
                </dl>
                <details>
                  <summary>Thresholds, slices, and failures</summary>
                  <StructuredData value={{
                    thresholds: snapshot.thresholds,
                    slice_metrics: snapshot.slice_metrics,
                    critical_failures: snapshot.critical_failures,
                    source_expiries: snapshot.source_expiries,
                  }} />
                </details>
              </>
            ) : (
              <p className="muted">No durable EvaluationSnapshot is available. Release eligibility is disabled — {item.release_disabled_reason || item.reason}.</p>
            )}
            {historyError && <p className="table-secondary">Evaluation history is unavailable; the latest durable snapshot remains visible.</p>}
          </>
        ) : null}
      </div>
    </section>
  );
}
