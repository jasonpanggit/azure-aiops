"use client";

import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  type DialogOpenChangeData,
  type DialogOpenChangeEvent,
} from "@fluentui/react-components";
import {
  type FormEvent,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";

import type {
  RemediationExecution,
  RemediationWorkflow,
} from "@/lib/services";
import type { RemediationDecision } from "@/lib/types";

/**
 * Exact existing governance objects are passed through rather than projected
 * into a smaller dialog-owned shape. The mutation boundary can therefore
 * retain approval, submission, lineage, blocker, verification, and
 * reconciliation facts without the presentation component overwriting them.
 */
export interface RiskExceptionGovernanceContext {
  decision?: RemediationDecision | null;
  workflow?: RemediationWorkflow | null;
  execution?: RemediationExecution | null;
}

export interface RiskExceptionRecordDetails {
  cveId: string;
  targetScope: string;
  affectedMetrics: readonly string[];
  evidenceFreshness: string;
  sessionApprover: string;
  initialExpiry?: string;
}

export interface RiskExceptionRecordRequest {
  cveId: string;
  targetScope: string;
  affectedMetrics: readonly string[];
  evidenceFreshness: string;
  reason: string;
  expiresAt: string | null;
  /** Read-only authenticated-session identity, never operator-entered text. */
  approver: string;
  governance?: RiskExceptionGovernanceContext;
}

export interface RiskExceptionRecordSuccess {
  status: "success";
  auditId: string;
  effectiveScope: string;
  expiresAt: string | null;
  canRevoke: boolean;
  governance?: RiskExceptionGovernanceContext;
}

export interface RiskExceptionMutationFailure {
  status: "failure";
  message: string;
}

export type RiskExceptionRecordResult =
  | RiskExceptionRecordSuccess
  | RiskExceptionMutationFailure;

export interface RiskExceptionSelection {
  id: string;
  label: string;
  targetScope: string;
}

export interface RiskExceptionRevokeRequest {
  exceptionIds: string[];
  representedScope: string;
  governance?: RiskExceptionGovernanceContext;
}

export type RiskExceptionRevokeOutcomeStatus =
  | "succeeded"
  | "failed"
  | "not_attempted";

export interface RiskExceptionRevokeOutcome {
  exceptionId: string;
  status: RiskExceptionRevokeOutcomeStatus;
  message?: string;
}

export type RiskExceptionRevokeResult =
  | {
      status: "success" | "partial";
      auditId?: string;
      outcomes: RiskExceptionRevokeOutcome[];
      governance?: RiskExceptionGovernanceContext;
    }
  | {
      status: "failure";
      message: string;
      outcomes?: RiskExceptionRevokeOutcome[];
    };

interface RiskExceptionDialogCommonProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocusRef?: RefObject<HTMLElement>;
  governance?: RiskExceptionGovernanceContext;
  /** Refreshes caller-owned counts after the mutation has been recorded. */
  onRefresh?: () => Promise<void>;
}

interface RiskExceptionRecordDialogProps
  extends RiskExceptionDialogCommonProps {
  mode: "record";
  record: RiskExceptionRecordDetails;
  onRecord: (
    request: RiskExceptionRecordRequest,
  ) => Promise<RiskExceptionRecordResult>;
  onRequestRevoke?: (auditId: string) => void;
  exceptions?: never;
  representedScope?: never;
  onRevoke?: never;
  onSelectionChange?: never;
}

interface RiskExceptionRevokeDialogProps
  extends RiskExceptionDialogCommonProps {
  mode: "revoke";
  exceptions: readonly RiskExceptionSelection[];
  representedScope: string;
  onRevoke: (
    request: RiskExceptionRevokeRequest,
  ) => Promise<RiskExceptionRevokeResult>;
  onSelectionChange?: (remainingIds: string[]) => void;
  record?: never;
  onRecord?: never;
  onRequestRevoke?: never;
}

export type RiskExceptionDialogProps =
  | RiskExceptionRecordDialogProps
  | RiskExceptionRevokeDialogProps;

type Feedback =
  | {
      kind: "record-success";
      result: RiskExceptionRecordSuccess;
      refreshFailed: boolean;
    }
  | {
      kind: "revoke-result";
      result: RiskExceptionRevokeResult & {
        outcomes: RiskExceptionRevokeOutcome[];
      };
    }
  | { kind: "error"; message: string }
  | null;

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "The request could not be completed. Review the selection and try again.";
}

function revokeSummary(outcomes: readonly RiskExceptionRevokeOutcome[]): string {
  const succeeded = outcomes.filter((outcome) => outcome.status === "succeeded").length;
  const failed = outcomes.filter((outcome) => outcome.status === "failed").length;
  const notAttempted = outcomes.filter(
    (outcome) => outcome.status === "not_attempted",
  ).length;
  return `${succeeded} revoked, ${failed} failed, ${notAttempted} not attempted. Failed and unattempted items remain selected.`;
}

function outcomeCopy(outcome: RiskExceptionRevokeOutcome): string {
  const labels: Record<RiskExceptionRevokeOutcomeStatus, string> = {
    succeeded: "Revoked",
    failed: "Failed",
    not_attempted: "Not attempted",
  };
  const suffix = outcome.message ? `: ${outcome.message}` : "";
  return `${outcome.exceptionId} — ${labels[outcome.status]}${suffix}`;
}

/**
 * Governed record/revoke confirmation built on Fluent UI v9's modal Dialog.
 * Mutation callbacks own transport and authorization; this component owns
 * exact confirmation copy, retry-safe feedback, and deterministic focus.
 */
export function RiskExceptionDialog(props: RiskExceptionDialogProps) {
  const {
    open,
    onOpenChange,
    returnFocusRef,
    governance,
    onRefresh,
  } = props;
  const [reason, setReason] = useState("");
  const [expiry, setExpiry] = useState(
    props.mode === "record" ? props.record.initialExpiry ?? "" : "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const alertRef = useRef<HTMLDivElement>(null);
  const successRef = useRef<HTMLDivElement>(null);
  const fallbackInvokerRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (open && !wasOpenRef.current) {
      fallbackInvokerRef.current =
        returnFocusRef?.current ??
        (document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null);
      setFeedback(null);
      setSubmitting(false);
      setReason("");
      setExpiry(props.mode === "record" ? props.record.initialExpiry ?? "" : "");
      const initialTarget =
        props.mode === "record" ? reasonRef.current : headingRef.current;
      initialTarget?.focus();
    }

    if (!open && wasOpenRef.current) {
      const invoker = returnFocusRef?.current ?? fallbackInvokerRef.current;
      queueMicrotask(() => invoker?.focus());
    }
    wasOpenRef.current = open;
  }, [open, props.mode, returnFocusRef]);

  useEffect(() => {
    if (feedback?.kind === "error") {
      alertRef.current?.focus();
    } else if (feedback?.kind === "record-success") {
      successRef.current?.focus();
    } else if (feedback?.kind === "revoke-result") {
      const hasFailures = feedback.result.outcomes.some(
        (outcome) => outcome.status !== "succeeded",
      );
      (hasFailures ? alertRef.current : successRef.current)?.focus();
    }
  }, [feedback]);

  const restoreAndClose = () => {
    if (submitting) return;
    onOpenChange(false);
    const invoker = returnFocusRef?.current ?? fallbackInvokerRef.current;
    queueMicrotask(() => invoker?.focus());
  };

  const handleOpenChange = (
    _event: DialogOpenChangeEvent,
    data: DialogOpenChangeData,
  ) => {
    if (!data.open) restoreAndClose();
  };

  const submitRecord = async (event: FormEvent) => {
    event.preventDefault();
    if (props.mode !== "record" || submitting || !reason.trim()) return;

    setSubmitting(true);
    setFeedback(null);
    try {
      const result = await props.onRecord({
        cveId: props.record.cveId,
        targetScope: props.record.targetScope,
        affectedMetrics: props.record.affectedMetrics,
        evidenceFreshness: props.record.evidenceFreshness,
        reason: reason.trim(),
        expiresAt: expiry || null,
        approver: props.record.sessionApprover,
        governance,
      });
      if (result.status === "failure") {
        setFeedback({ kind: "error", message: result.message });
        return;
      }

      let refreshFailed = false;
      if (onRefresh) {
        try {
          await onRefresh();
        } catch {
          refreshFailed = true;
        }
      }
      setFeedback({ kind: "record-success", result, refreshFailed });
    } catch (error) {
      setFeedback({ kind: "error", message: errorMessage(error) });
    } finally {
      setSubmitting(false);
    }
  };

  const submitRevoke = async (event: FormEvent) => {
    event.preventDefault();
    if (props.mode !== "revoke" || submitting || props.exceptions.length === 0) {
      return;
    }

    setSubmitting(true);
    setFeedback(null);
    try {
      const result = await props.onRevoke({
        exceptionIds: props.exceptions.map((exception) => exception.id),
        representedScope: props.representedScope,
        governance,
      });
      if (result.status === "failure" && !result.outcomes?.length) {
        setFeedback({ kind: "error", message: result.message });
        return;
      }

      const outcomes = result.outcomes ?? [];
      props.onSelectionChange?.(
        outcomes
          .filter((outcome) => outcome.status !== "succeeded")
          .map((outcome) => outcome.exceptionId),
      );
      setFeedback({
        kind: "revoke-result",
        result: {
          ...result,
          outcomes,
        },
      });
      if (result.status !== "failure" && onRefresh) {
        try {
          await onRefresh();
        } catch {
          // The item-level outcomes remain authoritative even if counts lag.
        }
      }
    } catch (error) {
      setFeedback({ kind: "error", message: errorMessage(error) });
    } finally {
      setSubmitting(false);
    }
  };

  const recordTitle = "Record risk exception";
  const revokeTitle = `Revoke ${props.mode === "revoke" ? props.exceptions.length : 0} ${
    props.mode === "revoke" && props.exceptions.length === 1
      ? "risk exception"
      : "risk exceptions"
  }`;
  const title = props.mode === "record" ? recordTitle : revokeTitle;

  return (
    <Dialog open={open} modalType="modal" onOpenChange={handleOpenChange}>
      <DialogSurface className="risk-exception-dialog">
        <DialogBody>
          <DialogTitle ref={headingRef} tabIndex={-1}>
            {title}
          </DialogTitle>
          <DialogContent>
            {props.mode === "record" ? (
              feedback?.kind === "record-success" ? (
                <div
                  ref={successRef}
                  className="callout"
                  role="status"
                  aria-live="polite"
                  tabIndex={-1}
                >
                  <h3>Risk exception recorded</h3>
                  <p>Audit ID: <code>{feedback.result.auditId}</code></p>
                  <p>Effective scope: {feedback.result.effectiveScope}</p>
                  <p>Expiry: {feedback.result.expiresAt || "No expiry"}</p>
                  {feedback.refreshFailed && (
                    <p>Exception recorded; updated exposure counts could not be refreshed</p>
                  )}
                </div>
              ) : (
                <form
                  id="risk-exception-record-form"
                  aria-busy={submitting}
                  onSubmit={submitRecord}
                >
                  <p>
                    Record an audited exception for <strong>{props.record.cveId}</strong>.
                  </p>
                  <dl>
                    <div>
                      <dt>Target scope</dt>
                      <dd>{props.record.targetScope}</dd>
                    </div>
                    <div>
                      <dt>Evidence freshness</dt>
                      <dd>{props.record.evidenceFreshness}</dd>
                    </div>
                    <div>
                      <dt>Metrics affected</dt>
                      <dd>
                        <ul>
                          {props.record.affectedMetrics.map((metric) => (
                            <li key={metric}>{metric}</li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                  </dl>
                  <label className="form-field">
                    <span>Session approver</span>
                    <input
                      aria-label="Session approver"
                      value={props.record.sessionApprover}
                      readOnly
                    />
                  </label>
                  <label className="form-field">
                    <span>Reason</span>
                    <textarea
                      ref={reasonRef}
                      value={reason}
                      disabled={submitting}
                      required
                      aria-describedby="risk-exception-reason-hint"
                      onChange={(event) => setReason(event.target.value)}
                    />
                  </label>
                  <p id="risk-exception-reason-hint">
                    Required. Explain the compensating control or accepted risk.
                  </p>
                  <label className="form-field">
                    <span>Expiry (optional)</span>
                    <input
                      type="datetime-local"
                      value={expiry}
                      disabled={submitting}
                      onChange={(event) => setExpiry(event.target.value)}
                    />
                  </label>
                </form>
              )
            ) : feedback?.kind === "revoke-result" ? (
              <div
                ref={
                  feedback.result.outcomes.some(
                    (outcome) => outcome.status !== "succeeded",
                  )
                    ? alertRef
                    : successRef
                }
                className="callout"
                role={
                  feedback.result.outcomes.some(
                    (outcome) => outcome.status !== "succeeded",
                  )
                    ? "alert"
                    : "status"
                }
                aria-live="polite"
                tabIndex={-1}
              >
                <h3>Risk exception revocation result</h3>
                <p>{revokeSummary(feedback.result.outcomes)}</p>
                {"auditId" in feedback.result && feedback.result.auditId && (
                  <p>Audit ID: <code>{feedback.result.auditId}</code></p>
                )}
                <ul>
                  {feedback.result.outcomes.map((outcome) => (
                    <li key={outcome.exceptionId}>{outcomeCopy(outcome)}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <form
                id="risk-exception-revoke-form"
                aria-busy={submitting}
                onSubmit={submitRevoke}
              >
                <p>
                  Revoke {props.exceptions.length}{" "}
                  {props.exceptions.length === 1
                    ? "risk exception"
                    : "risk exceptions"}
                  ? Revoked findings will return to open-exposure and priority
                  metrics. This action is audited.
                </p>
                <p><strong>Selected on this page</strong></p>
                <p>{props.representedScope}</p>
                <ul>
                  {props.exceptions.map((exception) => (
                    <li key={exception.id}>
                      <strong>{exception.label}</strong>
                      <span> — {exception.targetScope}</span>
                    </li>
                  ))}
                </ul>
                <div aria-live="polite">
                  {submitting && `Revoking ${props.exceptions.length} risk exceptions.`}
                </div>
              </form>
            )}

            {feedback?.kind === "error" && (
              <div
                ref={alertRef}
                className="callout callout-warning"
                role="alert"
                tabIndex={-1}
              >
                <h3>
                  {props.mode === "record"
                    ? "Risk exception was not recorded"
                    : "Risk exceptions were not revoked"}
                </h3>
                <p>{feedback.message}</p>
              </div>
            )}
          </DialogContent>

          <DialogActions>
            {props.mode === "record" ? (
              feedback?.kind === "record-success" ? (
                <>
                  {feedback.result.canRevoke && (
                    <button
                      type="button"
                      className="button button-danger"
                      disabled={!props.onRequestRevoke}
                      onClick={() =>
                        props.onRequestRevoke?.(feedback.result.auditId)
                      }
                    >
                      Revoke risk exception
                    </button>
                  )}
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={restoreAndClose}
                  >
                    Close
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="button button-quiet"
                    disabled={submitting}
                    onClick={restoreAndClose}
                  >
                    Keep reviewing
                  </button>
                  <button
                    type="submit"
                    form="risk-exception-record-form"
                    className="button button-primary"
                    disabled={submitting || !reason.trim()}
                  >
                    {submitting ? "Recording exception…" : "Record exception"}
                  </button>
                </>
              )
            ) : feedback?.kind === "revoke-result" ? (
              <>
                {feedback.result.outcomes.some(
                  (outcome) => outcome.status !== "succeeded",
                ) && (
                  <button
                    type="button"
                    className="button button-danger"
                    disabled={submitting}
                    onClick={() => {
                      setFeedback(null);
                      queueMicrotask(() => headingRef.current?.focus());
                    }}
                  >
                    Retry remaining exceptions
                  </button>
                )}
                <button
                  type="button"
                  className="button button-primary"
                  onClick={restoreAndClose}
                >
                  Close
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={submitting}
                  onClick={restoreAndClose}
                >
                  Keep exceptions
                </button>
                <button
                  type="submit"
                  form="risk-exception-revoke-form"
                  className="button button-danger"
                  disabled={submitting || props.exceptions.length === 0}
                >
                  {submitting ? "Revoking exceptions…" : "Revoke exceptions"}
                </button>
              </>
            )}
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
