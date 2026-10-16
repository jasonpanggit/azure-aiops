"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { CopilotCitations } from "@/components/ui/CopilotCitations";
import { MarkdownLite } from "@/components/ui/MarkdownLite";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { StatePanel } from "@/components/ui/StatePanel";
import { CopilotHistory } from "@/components/CopilotHistory";
import { useScope } from "@/lib/scope-context";
import { ScopeBookmarkError, scopedBookmark, scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import {
  askCanonicalInvestigation,
  toCanonicalInvestigationView,
  ROOT_COPILOT_SESSION,
  SUPPORTED_SEARCH_PHRASES,
} from "@/lib/services";
import type { CanonicalCopilotCitation, EvidenceItem } from "@/lib/types";
import type { CopilotAnswer, CopilotToolCall } from "@/lib/services";
import { useOptionalThreadContinuity } from "@/lib/copilot/thread-context";

interface ChatTurn {
  question: string;
  toolCalls?: CopilotToolCall[];
  narration?: CopilotAnswer | null;
  evidence?: EvidenceItem[];
  knowledgeVersion?: string;
  warnings?: string[];
  degraded?: boolean;
  degradationNote?: string;
  citations?: CanonicalCopilotCitation[];
  uncertainty?: string[];
  error?: string;
}

const TOOL_STATUS_TONE: Record<string, "success" | "warning" | "critical" | "info"> = {
  ok: "success",
  empty: "info",
  unavailable: "warning",
  denied: "critical",
};

/** Contextual operational Copilot with a prerender-safe query-context boundary. */
export default function CopilotPage() {
  return (
    <Suspense fallback={<div className="page-container"><div className="state-panel state-loading">Preparing Operations Copilot…</div></div>}>
      <CopilotContent />
    </Suspense>
  );
}

function CopilotContent() {
  const { scope } = useScope();
  const continuity = useOptionalThreadContinuity();
  const search = useSearchParams();
  let effectiveScope: ScopeSelection;
  try { effectiveScope = scopedBookmark(search, scope); }
  catch (error) {
    if (!(error instanceof ScopeBookmarkError)) throw error;
    return <main className="page-container"><StatePanel title="Copilot bookmark unavailable" message={error.message} tone="error" /><Link className="button" href="/copilot">Clear Copilot bookmark</Link></main>;
  }
  const threadId = search.get("thread_id") ?? "";
  const valid = !search.has("thread_id") || (search.getAll("thread_id").length === 1 && /^thr-[a-f0-9]{32}$/.test(threadId));
  const query = scopeToSearchParams(effectiveScope);
  if (!valid) return <main className="page-container"><StatePanel title="Copilot bookmark unavailable" message="Use one exact server-issued thread identifier." tone="error" /><Link className="button" href={`/copilot${query.size ? `?${query}` : ""}`}>Clear historical thread selection</Link></main>;
  return <CopilotWorkspace key={`${JSON.stringify(effectiveScope)}:${threadId}:${continuity?.generation ?? 0}`} scope={effectiveScope} pinnedThreadId={threadId} />;
}

function CopilotWorkspace({ scope, pinnedThreadId }: { scope: ScopeSelection; pinnedThreadId: string }) {
  const searchParams = useSearchParams();
  const threadContinuity = useOptionalThreadContinuity();
  const contextLabel = searchParams.get("situation") ?? searchParams.get("service");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [recovery, setRecovery] = useState("");
  const [lastThreadId, setLastThreadId] = useState("");
  const requestId = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const submittedQuestion = useRef("");

  useEffect(() => () => {
    requestId.current += 1;
    activeRequest.current?.abort();
  }, []);

  const starterPrompts = useMemo(
    () =>
      contextLabel
        ? [`resources related to business service ${contextLabel}`, "resources missing ownership", "servers with failed patches"]
        : [...SUPPORTED_SEARCH_PHRASES.slice(0, 4)],
    [contextLabel]
  );

  async function ask(value = question) {
    const nextQuestion = value.trim();
    if (!nextQuestion || loading || pinnedThreadId || recovery) return;
    const id = ++requestId.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    submittedQuestion.current = nextQuestion;
    setQuestion("");
    setLoading(true);
    try {
      // Standalone requests may omit page context; the shared canonical helper
      // submits through the root thread so this surface shares one authorized,
      // principal-scoped thread with the workspace and drawer.
      const envelope = await askCanonicalInvestigation(nextQuestion, scope, {
        sessionId: ROOT_COPILOT_SESSION,
        signal: controller.signal,
      });
      if (id !== requestId.current) return;
      const view = toCanonicalInvestigationView(envelope.data);
      if (view.threadId && view.threadRevision) {
        if (threadContinuity && !threadContinuity.acceptServerState(
          { threadId: view.threadId, threadRevision: view.threadRevision }, threadContinuity.generation,
        )) return;
      }
      if (view.threadId) setLastThreadId(view.threadId);
      setTurns((current) => [
        ...current,
        {
          question: nextQuestion,
          toolCalls: view.toolCalls,
          narration: view.narration,
          evidence: envelope.evidence,
          knowledgeVersion: envelope.knowledge_version,
          warnings: envelope.warnings,
          degraded: view.degraded,
          degradationNote: view.degradationNote,
          citations: view.citations,
          uncertainty: view.uncertainty,
        },
      ]);
    } catch (reason) {
      if (id !== requestId.current) return;
      setQuestion(nextQuestion);
      setRecovery("The request did not return a confirmed result. The server may still have completed it. Review retained history before deliberately submitting another question; nothing is retried automatically.");
      setTurns((current) => [
        ...current,
        { question: nextQuestion, error: reason instanceof Error ? reason.message : "Copilot could not answer this request." },
      ]);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }

  function stopWaiting() {
    requestId.current += 1;
    activeRequest.current?.abort();
    setQuestion(submittedQuestion.current);
    setLoading(false);
    setRecovery("Stopped waiting in this browser. This does not cancel provider work: the server outcome is unknown. Review retained history before deliberately submitting another question.");
  }

  const prefillQuestion = searchParams.get("q");
  useEffect(() => {
    if (prefillQuestion && !pinnedThreadId) setQuestion(prefillQuestion);
  }, [prefillQuestion, pinnedThreadId]);

  return (
    <div className="page-container copilot-page">
      <PageHeader
        eyebrow="Evidence-based assistance"
        title="Operations Copilot"
        description="Ask a scoped operational question and review the evidence behind the answer."
        metadata={
          <>
            <StatusBadge label="Read only" tone="info" />
            {contextLabel && <span>Context: {contextLabel}</span>}
          </>
        }
      />

      <CopilotHistory threadId={pinnedThreadId || lastThreadId || threadContinuity?.thread?.threadId || ""} scope={scope} pinned={Boolean(pinnedThreadId)} />
      {pinnedThreadId ? <StatePanel title="Historical review only" message="New questions are disabled while an exact historical thread is selected. Leave historical review to use the current active conversation; this read does not attach or resume the selected thread." /> : null}
      {recovery ? <StatePanel title="Request outcome unconfirmed" message={recovery} tone="partial" action={<button className="button" onClick={() => setRecovery("")}>I reviewed the outcome; enable a deliberate new question</button>} /> : null}

      <div className="copilot-layout">
        <section className="copilot-thread">
          {turns.length === 0 && (
            <div className="copilot-welcome">
              <div className="copilot-mark">AI</div>
              <h2>Start with an operational question</h2>
              <p>Copilot uses the same governed knowledge and operating scope as the rest of the workbench.</p>
              <div className="copilot-prompts">
                {starterPrompts.map((prompt) => (
                  <button type="button" key={prompt} disabled={loading || Boolean(pinnedThreadId) || Boolean(recovery)} onClick={() => ask(prompt)}>
                    {prompt}
                    <span>→</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, index) => (
            <div className="copilot-turn" key={`${turn.question}-${index}`}>
              <div className="copilot-question"><span>You</span><p>{turn.question}</p></div>
              <div className={`copilot-answer${turn.error ? " copilot-answer-error" : ""}`}>
                <div className="copilot-answer-label"><span className="copilot-mark">AI</span><strong>Operations Copilot</strong>{turn.narration && <StatusBadge label={turn.narration.model || turn.narration.agent_name} tone="success" compact />}</div>
                {turn.error ? (
                  <p>{turn.error}</p>
                ) : (
                  <>
                    {turn.narration && (
                      <MarkdownLite text={turn.narration.text} />
                    )}
                    {turn.toolCalls?.length ? (
                      <div className="copilot-tool-calls">
                        {turn.toolCalls.map((call, callIndex) => (
                          <details className="copilot-tool-call" key={`${call.tool}-${callIndex}`} open={callIndex === 0}>
                            <summary className="copilot-tool-call-header">
                              <StatusBadge label={call.tool} tone="neutral" compact />
                              <StatusBadge label={call.status} tone={TOOL_STATUS_TONE[call.status] ?? "neutral"} compact />
                            </summary>
                            {call.warning && <p className="copilot-tool-warning">{call.warning}</p>}
                            {call.status === "ok" && call.data != null && <StructuredData value={call.data} />}
                          </details>
                        ))}
                      </div>
                    ) : (
                      !turn.narration && <p>No matching operational context was found in this scope.</p>
                    )}
                  </>
                )}
                {!turn.error && turn.degraded && turn.degradationNote && (
                  <p className="copilot-fallback-note" role="alert" aria-label="Copilot degradation">
                    {turn.degradationNote}
                  </p>
                )}
                {!turn.error && turn.uncertainty?.length ? (
                  <div className="copilot-uncertainty" aria-label="Copilot uncertainty">
                    <StatusBadge label="Uncertainty" tone="warning" compact />
                    <ul>
                      {turn.uncertainty.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                ) : null}
                {!turn.error ? (
                  <CopilotCitations
                    citations={turn.citations ?? []}
                    ariaLabel="Copilot citations"
                  />
                ) : null}
                {!turn.error && (
                  <EvidenceBar
                    evidence={turn.evidence}
                    knowledgeVersion={turn.knowledgeVersion}
                    warnings={turn.warnings}
                  />
                )}
              </div>
            </div>
          ))}
          {loading && <div className="copilot-thinking"><span /><span /><span /> Reviewing evidence</div>}
        </section>

        <aside className="copilot-boundary card">
          <details className="copilot-boundary-details" open>
            <summary>
              <span>
                <strong>Trust boundary</strong>
                <small>What Copilot can and cannot do</small>
              </span>
            </summary>
            <div className="card-body">
              <dl>
                <div><dt>Grounded</dt><dd>Uses supported, governed tools in the selected scope.</dd></div>
                <div><dt>Transparent</dt><dd>Shows status, evidence, confidence, and freshness.</dd></div>
                <div><dt>Advisory</dt><dd>Does not invent answers or execute remediation.</dd></div>
              </dl>
            </div>
          </details>
        </aside>
      </div>

      <div className="copilot-composer">
        <textarea
          aria-label="Copilot question"
          disabled={Boolean(pinnedThreadId)}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              ask();
            }
          }}
          placeholder="Ask about applications, ownership, failed patches, critical infrastructure, or business service context"
          rows={2}
        />
        {loading ? <button type="button" className="button" aria-label="Stop waiting for this response" onClick={stopWaiting}>Stop waiting</button> : <button type="button" className="button button-primary" onClick={() => ask()} disabled={Boolean(pinnedThreadId) || Boolean(recovery) || !question.trim()}>
          Ask Copilot
        </button>}
      </div>
    </div>
  );
}
