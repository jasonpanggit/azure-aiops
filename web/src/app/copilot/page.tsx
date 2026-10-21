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
import { CopilotFindings } from "@/components/CopilotFindings";
import { CopilotThreadCatalog } from "@/components/CopilotThreadCatalog";
import { CopilotRequestRecovery } from "@/components/CopilotRequestRecovery";
import { useScope } from "@/lib/scope-context";
import { ScopeBookmarkError, scopedBookmark, scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import {
  askCanonicalInvestigation,
  toCanonicalInvestigationView,
  ROOT_COPILOT_SESSION,
  SUPPORTED_SEARCH_PHRASES,
} from "@/lib/services";
import type { CanonicalCopilotCitation, CanonicalSynthesisClaim, EvidenceItem } from "@/lib/types";
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
  claims?: CanonicalSynthesisClaim[];
  threadId?: string;
  threadRevision?: number;
}

interface SelectedThread { threadId: string; threadRevision: number }

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
  const rawRevision = search.get("thread_revision");
  const revision = rawRevision === null ? undefined : Number(rawRevision);
  const bookmarkedRequestKey = search.get("request_key") ?? "";
  const validRequestKey = !search.has("request_key") || (search.getAll("request_key").length === 1 && /^req-[0-9]{13}-[a-f0-9]{32}$/.test(bookmarkedRequestKey));
  const validRevision = rawRevision === null || (Boolean(threadId) && search.getAll("thread_revision").length === 1 && /^[1-9]\d*$/.test(rawRevision) && Number.isSafeInteger(revision));
  const valid = validRequestKey && validRevision && (!search.has("thread_id") || (search.getAll("thread_id").length === 1 && /^thr-[a-f0-9]{32}$/.test(threadId)));
  const query = scopeToSearchParams(effectiveScope);
  if (!valid) return <main className="page-container"><StatePanel title="Copilot bookmark unavailable" message="Use one exact retained thread or request identity and a valid revision." tone="error" /><Link className="button" href={`/copilot${query.size ? `?${query}` : ""}`}>Clear historical thread selection</Link></main>;
  return <CopilotWorkspace key={`${JSON.stringify(effectiveScope)}:${threadId}:${revision}:${continuity?.generation ?? 0}`} scope={effectiveScope} pinnedThreadId={threadId} pinnedRevision={revision} bookmarkedRequestKey={bookmarkedRequestKey} />;
}

function CopilotWorkspace({ scope, pinnedThreadId, pinnedRevision, bookmarkedRequestKey }: { scope: ScopeSelection; pinnedThreadId: string; pinnedRevision?: number; bookmarkedRequestKey: string }) {
  const searchParams = useSearchParams();
  const threadContinuity = useOptionalThreadContinuity();
  const contextLabel = searchParams.get("situation") ?? searchParams.get("service");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const [recovery, setRecovery] = useState(bookmarkedRequestKey ? "This bookmark retains an interrupted request identity, not its question or outcome. Check the authorized receipt before starting another question. No request is automatically submitted." : "");
  const [acceptedRequestKey, setAcceptedRequestKey] = useState(bookmarkedRequestKey);
  const [lastThreadId, setLastThreadId] = useState("");
  const [selectedThread, setSelectedThread] = useState<SelectedThread | null>(null);
  const reviewing = Boolean(pinnedThreadId) && !selectedThread;
  const requestId = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const submittedQuestion = useRef("");
  const retryRequest = useRef<{ question: string; key: string; continuation: SelectedThread | null } | null>(null);

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

  function bookmarkRequest(key: string) {
    const query = scopeToSearchParams(scope);
    if (pinnedThreadId) query.set("thread_id", pinnedThreadId);
    if (pinnedRevision !== undefined) query.set("thread_revision", String(pinnedRevision));
    if (key) query.set("request_key", key);
    window.history.replaceState(window.history.state, "", `/copilot${query.size ? `?${query}` : ""}`);
  }

  async function ask(value = question, retryKey?: string) {
    const nextQuestion = value.trim();
    if (!nextQuestion || loading || reviewing || (recovery && !retryKey)) return;
    const retry = retryRequest.current;
    if (retryKey && (!retry || retry.key !== retryKey || retry.question !== nextQuestion)) return;
    const id = ++requestId.current;
    const key = retryKey ?? `req-${Date.now()}-${crypto.randomUUID().replaceAll("-", "")}`;
    const continuation = retryKey ? retry?.continuation ?? null : selectedThread;
    retryRequest.current = { question: nextQuestion, key, continuation };
    setAcceptedRequestKey(key);
    bookmarkRequest(key);
    setRecovery("");
    const controller = new AbortController();
    activeRequest.current = controller;
    submittedQuestion.current = nextQuestion;
    setQuestion("");
    setLoading(true);
    try {
      const envelope = await askCanonicalInvestigation(nextQuestion, scope, {
        sessionId: ROOT_COPILOT_SESSION,
        signal: controller.signal,
        requestKey: key,
        ...(continuation ? { continuation } : {}),
      });
      if (id !== requestId.current) return;
      const view = toCanonicalInvestigationView(envelope.data);
      if (envelope.data.request_key !== key || !view.threadId || !/^thr-[a-f0-9]{32}$/.test(view.threadId) || !Number.isSafeInteger(view.threadRevision) || !view.threadRevision || view.threadRevision < 1) {
        throw new Error("The response did not confirm this exact admitted request and retained thread revision. Check its receipt; no result was substituted.");
      }
      if (continuation && (view.threadId !== continuation.threadId || view.threadRevision !== continuation.threadRevision + 1)) {
        throw new Error("The response did not append the exact selected thread and revision. Check its receipt; no replacement conversation was accepted.");
      }
      if (view.threadId && view.threadRevision) {
        if (threadContinuity && !threadContinuity.acceptServerState(
          { threadId: view.threadId, threadRevision: view.threadRevision }, threadContinuity.generation,
        )) return;
      }
      if (view.threadId) setLastThreadId(view.threadId);
      if (continuation) setSelectedThread({ threadId: view.threadId, threadRevision: view.threadRevision });
      setAcceptedRequestKey("");
      retryRequest.current = null;
      bookmarkRequest("");
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
          claims: view.synthesis?.claims ?? [],
          threadId: view.threadId,
          threadRevision: view.threadRevision,
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
    <div className="page-container operational-page copilot-page">
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

      <CopilotHistory threadId={selectedThread?.threadId || pinnedThreadId || lastThreadId || threadContinuity?.thread?.threadId || ""} scope={scope} pinned={Boolean(pinnedThreadId)} expectedRevision={selectedThread?.threadRevision ?? pinnedRevision} onContinue={reviewing && !loading && !recovery ? selection => { setSelectedThread(selection); setQuestion(""); } : undefined} />
      <CopilotThreadCatalog scope={scope} />
      {reviewing ? <StatePanel title="Historical review only" message="Reading does not attach or resume this thread. After an authorized durable history read, explicitly choose Continue from reviewed revision to compose a new scoped turn. No question runs until Ask Copilot; leaving historical review returns to the current active conversation." /> : selectedThread ? <StatePanel title="Selected conversation ready for a new turn" message={`New questions target ${selectedThread.threadId} at reviewed revision ${selectedThread.threadRevision}. Historical observations remain historical. Submission reauthorizes scope and revision; concurrent changes cause conflict, never a replacement thread.`} /> : null}
      {recovery ? <>
        <StatePanel title="Request outcome unconfirmed" message={recovery} tone="partial" action={<button className="button" onClick={() => { setRecovery(""); setAcceptedRequestKey(""); retryRequest.current = null; bookmarkRequest(""); }}>I reviewed the outcome; enable a deliberate new question</button>} />
        {acceptedRequestKey ? <CopilotRequestRecovery key={acceptedRequestKey} requestKey={acceptedRequestKey} scope={scope} /> : null}
        {retryRequest.current ? <button className="button" type="button" onClick={() => { const retry = retryRequest.current; if (retry) void ask(retry.question, retry.key); }}>Retry original question with same request key</button> : null}
      </> : null}

      <nav className="section-nav" aria-label="Copilot sections">
        <a href="#copilot-conversation">Conversation</a>
        <a href="#copilot-composer">Ask a question</a>
        <a href="#copilot-trust">Trust boundary</a>
      </nav>

      <div className="copilot-layout">
        <section id="copilot-conversation" className="copilot-thread" aria-labelledby="copilot-conversation-heading">
          <div className="section-heading">
            <div><h2 id="copilot-conversation-heading">Conversation</h2><p>Review answers, uncertainty and sources before acting.</p></div>
          </div>
          {turns.length === 0 && (
            <div className="copilot-welcome">
              <div className="copilot-mark">AI</div>
              <h3>Start with an operational question</h3>
              <p>Copilot uses the same governed knowledge and operating scope as the rest of the workbench.</p>
              <div className="copilot-prompts">
                {starterPrompts.map((prompt) => (
                  <button className="button button-ai" type="button" key={prompt} disabled={loading || reviewing || Boolean(recovery)} onClick={() => selectedThread ? setQuestion(prompt) : ask(prompt)}>
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
                  <p role="alert">{turn.error}</p>
                ) : (
                  <>
                    {turn.narration && (
                      <MarkdownLite text={turn.narration.text} />
                    )}
                    {!turn.toolCalls?.length && !turn.narration && <p>No matching operational context was found in this scope.</p>}
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
                {!turn.error ? <CopilotFindings claims={turn.claims ?? []} citations={turn.citations ?? []} scope={scope} threadId={turn.threadId} threadRevision={turn.threadRevision} /> : null}
                {!turn.error && (
                  <EvidenceBar
                    evidence={turn.evidence}
                    knowledgeVersion={turn.knowledgeVersion}
                    warnings={turn.warnings}
                  />
                )}
                {!turn.error && turn.toolCalls?.length ? (
                  <div className="copilot-tool-calls">
                    {turn.toolCalls.map((call, callIndex) => (
                      <div className="copilot-tool-call" key={`${call.tool}-${callIndex}`}>
                        <div className="copilot-tool-call-header">
                          <StatusBadge label={call.tool} tone="neutral" compact />
                          <StatusBadge label={call.status} tone={TOOL_STATUS_TONE[call.status] ?? "neutral"} compact />
                        </div>
                        {call.warning && <p className="copilot-tool-warning">{call.warning}</p>}
                        {call.status === "ok" && call.data != null && (
                          <details className="technical-disclosure">
                            <summary>Inspect tool output</summary>
                            <div className="copilot-tool-output" tabIndex={0} role="region" aria-label={`Output from ${call.tool}`}>
                              <StructuredData value={call.data} />
                            </div>
                          </details>
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
          {loading && <div className="copilot-thinking" role="status"><span /><span /><span /> Reviewing evidence</div>}
        </section>

        <aside id="copilot-trust" className="copilot-boundary card" aria-label="Trust boundary">
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

      <form id="copilot-composer" className="copilot-composer" aria-label="Ask Operations Copilot" onSubmit={(event) => { event.preventDefault(); ask(); }}>
        <textarea
          aria-label="Copilot question"
          disabled={reviewing}
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
        {loading ? <button type="button" className="button button-secondary" aria-label="Stop waiting for this response" onClick={stopWaiting}>Stop waiting</button> : <button type="submit" className="button button-ai" disabled={reviewing || Boolean(recovery) || !question.trim()}>
          Ask Copilot
        </button>}
      </form>
    </div>
  );
}
