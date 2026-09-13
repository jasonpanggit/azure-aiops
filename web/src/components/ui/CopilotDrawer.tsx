"use client";

import { useEffect, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MarkdownLite } from "@/components/ui/MarkdownLite";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import {
  type ThreadContinuityContextValue,
  useOptionalThreadContinuity,
} from "@/lib/copilot/thread-context";
import { useScope } from "@/lib/scope-context";
import type { CopilotAnswer, CopilotToolCall } from "@/lib/services";
import { buildCopilotSnapshot } from "@/lib/services";
import {
  investigateCanonical,
  normalizeCopilotSnapshotV2,
  type CanonicalCopilotCitation,
  type CanonicalCopilotResult,
  type CopilotEvidenceSnapshotV2,
} from "@/lib/copilot/page-adapters";
import type { ScopeSelection } from "@/lib/scope";
import { ApiError } from "@/lib/types";
import type { CopilotContextFinding, EvidenceItem } from "@/lib/types";

interface ChatTurn {
  question: string;
  toolCalls?: CopilotToolCall[];
  narration?: CopilotAnswer | null;
  evidence?: EvidenceItem[];
  knowledgeVersion?: string;
  warnings?: string[];
  error?: string;
  findings?: CopilotContextFinding[];
  synthesisMode?: "foundry" | "deterministic";
  snapshot?: ReturnType<typeof buildCopilotSnapshot> | CopilotEvidenceSnapshotV2;
  policyStatus?: CanonicalCopilotResult["policy_status"];
  fallbackReason?: string;
  uncertainty?: string[];
  coverage?: CanonicalCopilotResult["coverage"];
  citations?: ServerSuppliedCitation[];
}

type ServerSuppliedCitation = CanonicalCopilotCitation & {
  observation_status?: unknown;
};

const TOOL_STATUS_TONE: Record<string, "success" | "warning" | "critical" | "info"> = {
  ok: "success",
  empty: "info",
  unavailable: "warning",
  denied: "critical",
};

/** A starter question that may bypass the planner with a known tool + arguments,
 * so the drawer's first turn is deterministically grounded in the record the
 * caller opened it from (e.g. this exact CVE id) rather than left to a
 * keyword-based guess. */
export interface CopilotStarterQuestion {
  label: string;
  specialistId?: string;
  tool?: string;
  toolArguments?: Record<string, unknown>;
}

export interface CopilotDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Short label shown in the drawer header, e.g. "CVE-2024-12345". */
  contextLabel?: string;
  /** Context-aware starter questions, optionally pre-bound to a known tool. */
  starterQuestions: CopilotStarterQuestion[];
  /** Exact bounded state rendered by the calling page. */
  snapshot?: ReturnType<typeof buildCopilotSnapshot> | CopilotEvidenceSnapshotV2;
  /** Scope observed by the page; the server independently reauthorizes it. */
  requestedScope?: ScopeSelection;
}

/**
 * Slide-in Operations Copilot panel usable from any page. Unlike the
 * standalone `/copilot` page, this keeps the caller's page visible so an
 * operator can ask about the exact record they are looking at (a CVE, a
 * service, a change) without losing their place. Starter questions can pin a
 * known governed tool (e.g. `cve_detail`) so the first answer is grounded in
 * that specific record and its ontology-derived dependencies rather than a
 * generic keyword search.
 */
const MIN_WIDTH = 420;
const MAX_WIDTH = 1100;
const WIDE_WIDTH = 760;
const THREAD_RESET_MESSAGE = "This investigation is no longer available. Start a new investigation to continue.";
const INERT_THREAD_CONTINUITY: ThreadContinuityContextValue = {
  thread: null,
  requiresServerRevalidation: false,
  resetReason: null,
  generation: 0,
  acceptServerState: () => true,
  resetContinuity: () => undefined,
};

function uniqueWarnings(...groups: Array<string[] | undefined>): string[] {
  return Array.from(new Set(
    groups
      .flatMap((group) => group ?? [])
      .map((warning) => warning.trim())
      .filter(Boolean),
  ));
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableJson).sort().join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function serverEvidenceState(observationStatus: unknown): {
  label: string;
  tone: "success" | "warning" | "info";
} | null {
  if (typeof observationStatus !== "string") return null;
  switch (observationStatus.trim().toLowerCase()) {
    case "historical":
    case "historical_scope_restricted":
      return { label: "Historical evidence", tone: "warning" };
    case "revalidated":
    case "rechecked":
      return { label: "Revalidated evidence", tone: "success" };
    case "current":
      return { label: "Current evidence", tone: "info" };
    default:
      return null;
  }
}

function ServerEvidenceStateBadge({
  observationStatus,
}: {
  observationStatus: unknown;
}) {
  const state = serverEvidenceState(observationStatus);
  return state
    ? <StatusBadge label={state.label} tone={state.tone} compact />
    : null;
}

export function CopilotDrawer({
  open,
  onClose,
  contextLabel,
  starterQuestions,
  snapshot,
  requestedScope,
}: CopilotDrawerProps) {
  const { scope } = useScope();
  const providedThreadContinuity = useOptionalThreadContinuity();
  const threadContinuity = providedThreadContinuity ?? INERT_THREAD_CONTINUITY;
  const effectiveRequestedScope = requestedScope ?? scope;
  const canonicalSnapshot = snapshot
    ? normalizeCopilotSnapshotV2(snapshot)
    : null;
  const contextFingerprint = stableJson({
    scope: effectiveRequestedScope,
    snapshot: snapshot ?? null,
  });
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [transcriptFingerprint, setTranscriptFingerprint] = useState(contextFingerprint);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<"idle" | "loading" | "partial" | "fallback" | "error">("idle");
  const [lastSnapshot, setLastSnapshot] = useState<CopilotDrawerProps["snapshot"] | null>(null);
  const [lastQuestion, setLastQuestion] = useState("");
  const [width, setWidth] = useState(MIN_WIDTH);
  const contextFingerprintRef = useRef(contextFingerprint);
  const requestGeneration = useRef(0);
  const requestInFlight = useRef(false);
  const activeRequestFingerprint = useRef<string | null>(null);
  const liveContinuityGeneration = useRef(threadContinuity.generation);
  const appliedContinuityGeneration = useRef(threadContinuity.generation);
  const panelRef = useRef<HTMLDivElement>(null);
  const resizing = useRef(false);
  if (liveContinuityGeneration.current !== threadContinuity.generation) {
    liveContinuityGeneration.current = threadContinuity.generation;
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    if (open) {
      document.addEventListener("keydown", onKeyDown);
      panelRef.current?.focus();
    }
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  useEffect(() => () => {
    requestGeneration.current += 1;
    requestInFlight.current = false;
    activeRequestFingerprint.current = null;
  }, []);

  useEffect(() => {
    function onPointerMove(event: PointerEvent) {
      if (!resizing.current) return;
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth - event.clientX));
      setWidth(next);
    }
    function onPointerUp() {
      resizing.current = false;
    }
    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp);
    return () => {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };
  }, []);

  useEffect(() => {
    if (contextFingerprintRef.current === contextFingerprint) return;
    requestGeneration.current += 1;
    contextFingerprintRef.current = contextFingerprint;
    requestInFlight.current = false;
    activeRequestFingerprint.current = null;
    setTurns([]);
    setTranscriptFingerprint(contextFingerprint);
    setQuestion("");
    setLastSnapshot(null);
    setLastQuestion("");
    setLoading(false);
    setStage("idle");
  }, [contextFingerprint]);

  useEffect(() => {
    if (
      appliedContinuityGeneration.current
      === threadContinuity.generation
    ) {
      return;
    }
    appliedContinuityGeneration.current = threadContinuity.generation;
    requestGeneration.current += 1;
    requestInFlight.current = false;
    activeRequestFingerprint.current = null;
    setTurns([]);
    setTranscriptFingerprint(contextFingerprint);
    setQuestion("");
    setLastSnapshot(null);
    setLastQuestion("");
    setLoading(false);
    setStage("idle");
  }, [contextFingerprint, threadContinuity.generation]);

  async function ask(
    value: string,
    tool?: string,
    toolArguments?: Record<string, unknown>,
    specialistId?: string,
  ) {
    const nextQuestion = value.trim();
    if (!nextQuestion || requestInFlight.current) return;
    requestInFlight.current = true;
    setQuestion("");
    setLoading(true);
    setStage("loading");
    setTranscriptFingerprint(contextFingerprint);
    const submittedContextFingerprint = contextFingerprint;
    const submittedGeneration = requestGeneration.current;
    const submittedContinuityGeneration = liveContinuityGeneration.current;
    activeRequestFingerprint.current = submittedContextFingerprint;
    const requestIsCurrent = () => (
      requestGeneration.current === submittedGeneration
      && contextFingerprintRef.current === submittedContextFingerprint
      && liveContinuityGeneration.current === submittedContinuityGeneration
    );
    setLastQuestion(nextQuestion);
    try {
      const submittedSnapshot = canonicalSnapshot
        ?? normalizeCopilotSnapshotV2(
          buildCopilotSnapshot({
            pageKind: "resource",
            pageId: "legacy-drawer",
            scope,
            question: nextQuestion,
          }),
        );
      setLastSnapshot(submittedSnapshot);
      const envelope = await investigateCanonical(
        {
          contract_version: "1",
          question: nextQuestion,
          requested_scope: effectiveRequestedScope,
          snapshot: submittedSnapshot,
          ...(threadContinuity.thread
            ? {
                thread_id: threadContinuity.thread.threadId,
                expected_thread_revision: threadContinuity.thread.threadRevision,
              }
            : {}),
          ...(specialistId && tool
            ? {
                hint: {
                  specialist_id: specialistId,
                  tool,
                  arguments: toolArguments ?? {},
                },
              }
            : {}),
        },
        effectiveRequestedScope,
      );
      if (!requestIsCurrent()) return;
      const result = envelope.data;
      if (!threadContinuity.acceptServerState(
        {
          threadId: result.thread_id,
          threadRevision: result.thread_revision,
        },
        submittedContinuityGeneration,
      )) {
        return;
      }
      setTurns((current) => [
        ...current,
        {
          question: nextQuestion,
          toolCalls: result.tool_results.map((call) => ({
            tool: call.tool,
            arguments: {},
            status: call.status === "partial" ? "unavailable" : call.status,
            data: call.data,
            evidence: [],
            warning: call.warning,
          })),
          evidence: envelope.evidence ?? [],
          knowledgeVersion: envelope.knowledge_version,
          warnings: uniqueWarnings(envelope.warnings),
          policyStatus: result.policy_status,
          fallbackReason: result.fallback_reason,
          uncertainty: result.uncertainty,
          coverage: result.coverage,
          citations: result.citations,
          narration: result.synthesis?.claims?.length
            ? {
                text: result.synthesis.claims
                  .map(
                    (claim) =>
                      `${claim.summary}\n\nEvidence: ${claim.evidence_refs.join(", ")}`,
                  )
                  .join("\n\n"),
                agent_name:
                  result.synthesis.status === "synthesized"
                    ? "Executive synthesis"
                    : "Deterministic page evidence",
                model:
                  result.synthesis.status === "synthesized"
                    ? "Foundry"
                    : "Deterministic",
                grounded: true,
              }
            : null,
          synthesisMode:
            result.synthesis?.status === "synthesized"
              ? "foundry"
              : "deterministic",
          snapshot: submittedSnapshot,
        },
      ]);
      setStage(result.policy_status === "fallback"
        ? "fallback"
        : result.status === "partial"
          ? "partial"
          : "idle");
    } catch (reason) {
      if (!requestIsCurrent()) return;
      const isThreadReset = (
        reason instanceof ApiError
        && reason.status === 404
        && reason.code === "not_found"
        && reason.details?.field === "thread_id"
      );
      if (isThreadReset) {
        threadContinuity.resetContinuity("not_found");
        if (providedThreadContinuity) return;
      }
      setTurns((current) => [
        ...current,
        {
          question: nextQuestion,
          error: isThreadReset
            ? THREAD_RESET_MESSAGE
            : reason instanceof Error
              ? reason.message
              : "Copilot could not answer this request.",
        },
      ]);
      setStage("error");
    } finally {
      if (requestIsCurrent()) {
        requestInFlight.current = false;
        activeRequestFingerprint.current = null;
        setLoading(false);
      }
    }
  }

  if (!open) return null;
  const visibleTurns = transcriptFingerprint === contextFingerprint ? turns : [];
  const visibleLoading = loading
    && activeRequestFingerprint.current === contextFingerprint;
  const visibleStage = transcriptFingerprint === contextFingerprint ? stage : "idle";

  return (
    <>
      <button className="copilot-drawer-backdrop" aria-label="Close Operations Copilot" onClick={onClose} />
      <aside
        className="copilot-drawer"
        role="dialog"
        aria-label="Operations Copilot"
        aria-modal="false"
        ref={panelRef}
        tabIndex={-1}
        style={{ width }}
      >
        <div
          className="copilot-drawer-resize-handle"
          onPointerDown={(event) => {
            event.preventDefault();
            resizing.current = true;
          }}
          title="Drag to resize"
        />
        <div className="copilot-drawer-header">
          <div className="copilot-drawer-title">
            <span className="copilot-mark">AI</span>
            <div>
              <h2>Operations Copilot</h2>
              {contextLabel && <p>{contextLabel}</p>}
            </div>
          </div>
          <div className="copilot-drawer-header-actions">
            <button
              type="button"
              className="copilot-drawer-expand"
              aria-label={width > MIN_WIDTH + 40 ? "Narrow panel" : "Widen panel"}
              title={width > MIN_WIDTH + 40 ? "Narrow panel" : "Widen panel"}
              onClick={() => setWidth((current) => (current > MIN_WIDTH + 40 ? MIN_WIDTH : WIDE_WIDTH))}
            >
              {width > MIN_WIDTH + 40 ? "⤡" : "⤢"}
            </button>
            <button type="button" className="copilot-drawer-close" aria-label="Close" onClick={onClose}>
              ×
            </button>
          </div>
        </div>

        <div className="copilot-drawer-body">
          {visibleTurns.length === 0 && (
            <div className="copilot-drawer-welcome">
              <p>Ask about this view. Answers stay scoped, grounded, and reviewable.</p>
              <div className="copilot-prompts">
                {starterQuestions.map((prompt) => (
                  <button
                    type="button"
                    key={prompt.label}
                    onClick={() => ask(prompt.label, prompt.tool, prompt.toolArguments, prompt.specialistId)}
                    disabled={visibleLoading}
                  >
                    {prompt.label}
                    <span>→</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="copilot-live-status" role="status" aria-live="polite">
            {visibleLoading && "Gathering the visible page evidence and checking governed sources…"}
            {!visibleLoading && visibleStage === "fallback" && "Deterministic evidence is available; Foundry narration was not produced."}
            {!visibleLoading && visibleStage === "partial" && "Partial evidence: review freshness and source warnings before relying on this result."}
            {!visibleLoading && visibleStage === "error" && "The request failed. Retry the same bounded page snapshot."}
          </div>
          {providedThreadContinuity?.resetReason === "not_found" && (
            <p className="copilot-fallback-note" role="alert">
              {THREAD_RESET_MESSAGE}
            </p>
          )}
          {visibleTurns.map((turn, index) => (
            <div className="copilot-turn" key={`${turn.question}-${index}`}>
              <div className="copilot-question"><span>You</span><p>{turn.question}</p></div>
              <div className={`copilot-answer${turn.error ? " copilot-answer-error" : ""}`}>
                <div className="copilot-answer-label">
                  <span className="copilot-mark">AI</span>
                  <strong>Copilot</strong>
                  {turn.narration && <StatusBadge label={turn.narration.model || turn.narration.agent_name} tone="success" compact />}
                </div>
                {turn.error ? (
                  <p>{turn.error}</p>
                ) : (
                  <>
                    {turn.narration && (
                      <>
                        {turn.synthesisMode === "foundry" && <p className="copilot-synthesis-mode">Narrated by {turn.narration.agent_name}.</p>}
                        <MarkdownLite text={turn.narration.text} />
                      </>
                    )}
                    {!turn.narration && turn.toolCalls?.some((call) => call.status === "ok") && (
                      <p className="copilot-fallback-note">
                        {turn.policyStatus
                          ? "Showing governed results directly because optional narration is unavailable."
                          : "Showing governed tool results directly because narration is unavailable."}
                      </p>
                    )}
                    {turn.coverage && (
                      <div className="copilot-coverage" aria-label="Investigation coverage">
                        <strong>{turn.coverage.visible_count} of {turn.coverage.total_count} visible records</strong>
                        <span>{turn.coverage.complete ? "Complete visible coverage" : "Partial visible coverage"}</span>
                      </div>
                    )}
                    {turn.uncertainty?.length ? (
                      <div className="copilot-uncertainty" aria-label="Investigation uncertainty">
                        <strong>Uncertainty</strong>
                        <ul>
                          {turn.uncertainty.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      </div>
                    ) : null}
                    {turn.findings?.length ? (
                      <div className="copilot-findings" aria-label="Context findings">
                        {turn.findings.map((finding) => (
                          <article className={`copilot-finding copilot-finding-${finding.status}`} key={finding.finding_id}>
                            <strong>{finding.status === "verified" ? "Verified finding" : finding.status === "hypothesis" ? "Hypothesis" : "Evidence status"}</strong>
                            <p>{finding.summary}</p>
                            <small>Check {finding.check_id} · Evidence: {finding.evidence_refs.join(", ") || "not named"} · {finding.next_check}</small>
                          </article>
                        ))}
                      </div>
                    ) : turn.toolCalls?.length ? (
                      <div className="copilot-tool-calls">
                        {turn.toolCalls.map((call, callIndex) => (
                          <details className="copilot-tool-call" key={`${call.tool}-${callIndex}`} open={callIndex === 0}>
                            <summary>
                              <StatusBadge label={call.tool} tone="neutral" compact />
                              <StatusBadge label={call.status} tone={TOOL_STATUS_TONE[call.status] ?? "neutral"} compact />
                            </summary>
                            {call.warning && <p className="copilot-tool-warning">{call.warning}</p>}
                            {call.status === "ok" && call.data != null && (
                              <div className="copilot-tool-result">
                                <StructuredData value={call.data} />
                              </div>
                            )}
                          </details>
                        ))}
                      </div>
                    ) : (
                      !turn.narration && <p>No matching context was found in this scope.</p>
                    )}
                    {turn.citations?.length ? (
                      <div className="copilot-citations" aria-label="Investigation citations">
                        <strong>Citations</strong>
                        <ul>
                          {turn.citations.map((citation) => (
                            <li key={citation.citation_id}>
                              <code>{citation.citation_id}</code>
                              <span>{citation.source}</span>
                              <ServerEvidenceStateBadge
                                observationStatus={citation.observation_status}
                              />
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </>
                )}
                {!turn.error && (
                  <EvidenceBar evidence={turn.evidence} knowledgeVersion={turn.knowledgeVersion} warnings={turn.warnings} />
                )}
              </div>
            </div>
          ))}
          {visibleLoading && <div className="copilot-thinking"><span /><span /><span /> Correlating evidence and validating sources</div>}
        </div>

        <div className="copilot-drawer-composer">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            disabled={visibleLoading}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !visibleLoading) {
                event.preventDefault();
                ask(question);
              }
            }}
            placeholder="Ask about this record's impact, ownership, or recommended action"
            rows={2}
          />
          <button type="button" className="button button-primary" onClick={() => ask(question)} disabled={visibleLoading || !question.trim()}>
            Send
          </button>
          {visibleStage === "error" && lastSnapshot && (
            <button type="button" className="button" onClick={() => ask(lastQuestion)} disabled={visibleLoading}>
              Retry
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
