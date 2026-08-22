"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { copilotApi, SUPPORTED_SEARCH_PHRASES } from "@/lib/services";
import type { CopilotAnswer, CopilotToolCall } from "@/lib/services";
import type { EvidenceItem } from "@/lib/types";

interface ChatTurn {
  question: string;
  toolCalls?: CopilotToolCall[];
  narration?: CopilotAnswer | null;
  evidence?: EvidenceItem[];
  knowledgeVersion?: string;
  warnings?: string[];
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
  const searchParams = useSearchParams();
  const contextLabel = searchParams.get("situation") ?? searchParams.get("service");
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [loading, setLoading] = useState(false);
  const sessionId = useRef(`web-${Math.random().toString(36).slice(2)}-${Date.now()}`);

  const starterPrompts = useMemo(
    () =>
      contextLabel
        ? [`resources related to business service ${contextLabel}`, "resources missing ownership", "servers with failed patches"]
        : [...SUPPORTED_SEARCH_PHRASES.slice(0, 4)],
    [contextLabel]
  );

  async function ask(value = question) {
    const nextQuestion = value.trim();
    if (!nextQuestion) return;
    setQuestion("");
    setLoading(true);
    try {
      const envelope = await copilotApi.investigate(nextQuestion, scope, {
        sessionId: sessionId.current,
      });
      setTurns((current) => [
        ...current,
        {
          question: nextQuestion,
          toolCalls: envelope.data.tool_calls,
          narration: envelope.data.answer,
          evidence: envelope.evidence,
          knowledgeVersion: envelope.knowledge_version,
          warnings: envelope.warnings,
        },
      ]);
    } catch (reason) {
      setTurns((current) => [
        ...current,
        { question: nextQuestion, error: reason instanceof Error ? reason.message : "Copilot could not answer this request." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  const prefillQuestion = searchParams.get("q");
  const autoAsked = useRef(false);

  useEffect(() => {
    if (prefillQuestion && !autoAsked.current) {
      autoAsked.current = true;
      ask(prefillQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillQuestion]);

  return (
    <div className="page-container copilot-page">
      <PageHeader
        eyebrow="Evidence-based assistance"
        title="Operations Copilot"
        description="Explore governed operational context. Answers are bounded by supported intents and keep their evidence visible."
        metadata={
          <>
            <StatusBadge label="Read only" tone="info" />
            <StatusBadge label="No autonomous actions" tone="warning" />
            {contextLabel && <span>Context: {contextLabel}</span>}
          </>
        }
      />

      <div className="copilot-layout">
        <section className="copilot-thread">
          {turns.length === 0 && (
            <div className="copilot-welcome">
              <div className="copilot-mark">AI</div>
              <h2>Start with an operational question</h2>
              <p>Copilot uses the same governed knowledge and operating scope as the rest of the workbench.</p>
              <div className="copilot-prompts">
                {starterPrompts.map((prompt) => (
                  <button type="button" key={prompt} onClick={() => ask(prompt)}>
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
                      <p className="copilot-narration">{turn.narration.text}</p>
                    )}
                    {turn.toolCalls?.length ? (
                      <div className="copilot-tool-calls">
                        {turn.toolCalls.map((call, callIndex) => (
                          <div className="copilot-tool-call" key={`${call.tool}-${callIndex}`}>
                            <div className="copilot-tool-call-header">
                              <StatusBadge label={call.tool} tone="neutral" compact />
                              <StatusBadge label={call.status} tone={TOOL_STATUS_TONE[call.status] ?? "neutral"} compact />
                            </div>
                            {call.warning && <p className="copilot-tool-warning">{call.warning}</p>}
                            {call.status === "ok" && call.data != null && <StructuredData value={call.data} />}
                          </div>
                        ))}
                      </div>
                    ) : (
                      !turn.narration && <p>No matching operational context was found in this scope.</p>
                    )}
                  </>
                )}
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
          {loading && <div className="copilot-thinking"><span /><span /><span /> Correlating evidence</div>}
        </section>

        <aside className="copilot-boundary card">
          <div className="card-header"><h2>Trust boundary</h2></div>
          <div className="card-body">
            <dl>
              <div><dt>Can do</dt><dd>Plan and run governed tool calls (topology, traffic-flow, CVE/KB exposure, incidents, remediation, ontology context) for supported questions.</dd></div>
              <div><dt>Will show</dt><dd>Every tool call&apos;s status (ok / empty / unavailable / denied), evidence source, confidence, and freshness.</dd></div>
              <div><dt>Will not do</dt><dd>Invent unsupported answers, hide unknowns, treat an unavailable provider as &quot;no results&quot;, or execute remediation.</dd></div>
            </dl>
          </div>
        </aside>
      </div>

      <div className="copilot-composer">
        <textarea
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
        <button type="button" className="button button-primary" onClick={() => ask()} disabled={loading || !question.trim()}>
          Ask Copilot
        </button>
      </div>
    </div>
  );
}
