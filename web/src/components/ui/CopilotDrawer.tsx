"use client";

import { useEffect, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MarkdownLite } from "@/components/ui/MarkdownLite";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { copilotApi } from "@/lib/services";
import type { CopilotAnswer, CopilotToolCall } from "@/lib/services";
import { buildCopilotSnapshot } from "@/lib/services";
import {
  investigateCanonical,
  type CanonicalCopilotCitation,
  type CanonicalCopilotResult,
  type CopilotEvidenceSnapshotV2,
} from "@/lib/copilot/page-adapters";
import type { ScopeSelection } from "@/lib/scope";
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
  citations?: CanonicalCopilotCitation[];
}

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

function uniqueWarnings(...groups: Array<string[] | undefined>): string[] {
  return Array.from(new Set(
    groups
      .flatMap((group) => group ?? [])
      .map((warning) => warning.trim())
      .filter(Boolean),
  ));
}

const THREAD_STORAGE_PREFIX = "aiops.copilot.thread.";
const OPAQUE_THREAD_PATTERN = /^thr-[a-f0-9]{32}$/;

function isCanonicalSnapshot(
  snapshot: CopilotDrawerProps["snapshot"],
): snapshot is CopilotEvidenceSnapshotV2 {
  return snapshot?.version === "2";
}

function readStoredThread(pageKind: string | undefined): string | null {
  if (!pageKind || typeof window === "undefined") return null;
  const value = window.sessionStorage.getItem(`${THREAD_STORAGE_PREFIX}${pageKind}`);
  return value && OPAQUE_THREAD_PATTERN.test(value) ? value : null;
}

function storeThread(pageKind: string, threadId: string): void {
  if (typeof window === "undefined" || !OPAQUE_THREAD_PATTERN.test(threadId)) return;
  window.sessionStorage.setItem(`${THREAD_STORAGE_PREFIX}${pageKind}`, threadId);
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
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState<"idle" | "loading" | "partial" | "fallback" | "error">("idle");
  const [lastSnapshot, setLastSnapshot] = useState<CopilotDrawerProps["snapshot"] | null>(null);
  const [lastQuestion, setLastQuestion] = useState("");
  const [width, setWidth] = useState(MIN_WIDTH);
  const sessionId = useRef(`drawer-${Math.random().toString(36).slice(2)}-${Date.now()}`);
  const canonicalThreadId = useRef(
    readStoredThread(isCanonicalSnapshot(snapshot) ? snapshot.page_kind : undefined),
  );
  const panelRef = useRef<HTMLDivElement>(null);
  const resizing = useRef(false);

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

  async function ask(
    value: string,
    tool?: string,
    toolArguments?: Record<string, unknown>,
    specialistId?: string,
  ) {
    const nextQuestion = value.trim();
    if (!nextQuestion) return;
    setQuestion("");
    setLoading(true);
    setStage("loading");
    const canonicalSnapshot = isCanonicalSnapshot(snapshot) ? snapshot : null;
    setLastQuestion(nextQuestion);
    try {
      if (canonicalSnapshot) {
        setLastSnapshot(canonicalSnapshot);
        const envelope = await investigateCanonical(
            {
              contract_version: "1",
              question: nextQuestion,
              requested_scope: requestedScope ?? scope,
              snapshot: canonicalSnapshot,
              ...(canonicalThreadId.current ? { thread_id: canonicalThreadId.current } : {}),
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
            requestedScope ?? scope,
          );
        const result = envelope.data;
        canonicalThreadId.current = result.thread_id;
        storeThread(canonicalSnapshot.page_kind, result.thread_id);
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
            snapshot: canonicalSnapshot,
          },
        ]);
        setStage(result.policy_status === "fallback" ? "fallback" : result.status === "partial" ? "partial" : "idle");
        return;
      }
      const legacySnapshot = snapshot?.version === "1" ? snapshot : undefined;
      const submittedSnapshot = legacySnapshot
        ? { ...legacySnapshot, question: nextQuestion }
        : buildCopilotSnapshot({ pageKind: "resource", pageId: "legacy-drawer", scope, question: nextQuestion });
      setLastSnapshot(submittedSnapshot);
      const envelope = legacySnapshot
        ? await copilotApi.investigateContext(submittedSnapshot)
        : await copilotApi.investigate(nextQuestion, scope, { sessionId: sessionId.current, tool, toolArguments });
      const result = envelope.data as typeof envelope.data & {
        answer?: CopilotAnswer | null;
        synthesis?: {
          mode?: "foundry" | "deterministic";
          narration?: string;
          warning?: string;
        } | null;
        synthesis_mode?: "foundry" | "deterministic";
        synthesis_agent?: string;
        findings?: CopilotContextFinding[];
        stages?: string[];
      };
      const contextualNarration = result.synthesis?.narration?.trim()
        ? {
            text: result.synthesis.narration,
            agent_name: result.synthesis_agent || (result.synthesis.mode === "foundry" ? "Foundry specialist" : "deterministic"),
            model: result.synthesis.mode === "foundry" ? "Foundry" : "Deterministic",
            grounded: true,
          }
        : null;
      const narration = result.answer ?? contextualNarration;
      const synthesisMode = result.synthesis_mode ?? result.synthesis?.mode;
      setTurns((current) => [
        ...current,
        {
          question: nextQuestion,
          toolCalls: envelope.data.tool_calls,
          narration,
          evidence: envelope.evidence ?? [],
          knowledgeVersion: envelope.knowledge_version,
          warnings: uniqueWarnings(envelope.warnings, result.warnings),
          findings: narration ? undefined : result.findings,
          synthesisMode,
          snapshot: submittedSnapshot,
        },
      ]);
      setStage(synthesisMode === "deterministic" ? "fallback" : result.findings?.some((finding) => finding.status !== "verified") ? "partial" : "idle");
    } catch (reason) {
      setTurns((current) => [
        ...current,
        { question: nextQuestion, error: reason instanceof Error ? reason.message : "Copilot could not answer this request." },
      ]);
      setStage("error");
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

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
          {turns.length === 0 && (
            <div className="copilot-drawer-welcome">
              <p>Ask about this view. Answers stay scoped, grounded, and reviewable.</p>
              <div className="copilot-prompts">
                {starterQuestions.map((prompt) => (
                  <button
                    type="button"
                    key={prompt.label}
                    onClick={() => ask(prompt.label, prompt.tool, prompt.toolArguments, prompt.specialistId)}
                  >
                    {prompt.label}
                    <span>→</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="copilot-live-status" role="status" aria-live="polite">
            {loading && "Gathering the visible page evidence and checking governed sources…"}
            {!loading && stage === "fallback" && "Deterministic evidence is available; Foundry narration was not produced."}
            {!loading && stage === "partial" && "Partial evidence: review freshness and source warnings before relying on this result."}
            {!loading && stage === "error" && "The request failed. Retry the same bounded page snapshot."}
          </div>
          {turns.map((turn, index) => (
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
          {loading && <div className="copilot-thinking"><span /><span /><span /> Correlating evidence and validating sources</div>}
        </div>

        <div className="copilot-drawer-composer">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                ask(question);
              }
            }}
            placeholder="Ask about this record's impact, ownership, or recommended action"
            rows={2}
          />
          <button type="button" className="button button-primary" onClick={() => ask(question)} disabled={loading || !question.trim()}>
            Send
          </button>
          {stage === "error" && lastSnapshot && (
            <button type="button" className="button" onClick={() => ask(lastQuestion)} disabled={loading}>
              Retry
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
