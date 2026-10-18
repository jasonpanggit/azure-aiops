"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MarkdownLite } from "@/components/ui/MarkdownLite";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  normalizeCopilotSnapshotV2,
  type CopilotEvidenceSnapshotV2,
} from "@/lib/copilot/page-adapters";
import type { ScopeSelection } from "@/lib/scope";
import { investigateCanonical, retainedCopilotAnswer } from "@/lib/services";
import type {
  CanonicalCopilotResult,
  CopilotPageSnapshot,
} from "@/lib/types";

export type CopilotInsightSnapshot = CopilotPageSnapshot | CopilotEvidenceSnapshotV2;

export interface InsightState {
  kind: "llm" | "deterministic" | "fallback" | "unavailable";
  narration: string;
  findings: string[];
  warning: string;
  /** Lowest claim confidence reported by synthesis, when any claims were cited. */
  confidence?: string;
  /** Specialists the coordinator actually ran for this turn. */
  specialists?: string[];
  /** Provider-reported provenance for a retained compatibility narration. */
  provider?: { agent: string; version: string; model: string };
}

/** Debounce window that coalesces snapshot churn while page queries settle. */
export const INSIGHT_DEBOUNCE_MS = 400;

export interface CopilotInsightsProps {
  snapshot: CopilotInsightSnapshot;
  requestedScope?: ScopeSelection;
  contextLabel?: string;
  question?: string;
  focusCopy?: string;
  onOpenCopilot?: () => void;
  /**
   * False while the page's primary data is still loading. The panel waits for
   * a settled snapshot instead of synthesizing over partial early evidence.
   */
  ready?: boolean;
}

function defaultInsightQuestion(contextLabel?: string): string {
  const context = contextLabel?.trim() || "this operational view";
  return (
    `Give me a concise executive insight for ${context}. Name the most important `
    + "current finding with the specific affected resources, the evidence uncertainty, "
    + "and the next read-only operator check in 2-4 sentences. Use only the supplied page evidence."
  );
}

function hasEvidence(snapshot: CopilotInsightSnapshot | null | undefined): boolean {
  if (!snapshot) return false;
  if ((snapshot.evidence?.length ?? 0) > 0) return true;
  return snapshot.version === "2" && (snapshot.coverage?.total_count ?? 0) > 0;
}

const CONFIDENCE_RANK: Record<string, number> = { low: 0, medium: 1, high: 2 };

function lowestConfidence(values: Array<string | undefined>): string | undefined {
  const known = values
    .map((value) => value?.trim().toLowerCase())
    .filter((value): value is string => Boolean(value) && value! in CONFIDENCE_RANK);
  if (known.length === 0) return undefined;
  return known.reduce((lowest, value) => (
    CONFIDENCE_RANK[value] < CONFIDENCE_RANK[lowest] ? value : lowest
  ));
}

/** Maps a canonical turn onto a display state, preferring Foundry narration. */
export function interpretInsightResult(result: CanonicalCopilotResult): InsightState {
  const base = interpretInsightKind(result);
  const synthesis = result.synthesis;
  const confidence = lowestConfidence((synthesis?.claims ?? []).map((claim) => claim.confidence));
  const specialists = (result.selected_specialists ?? []).filter(Boolean);
  return {
    ...base,
    ...(confidence ? { confidence } : {}),
    ...(specialists.length ? { specialists } : {}),
  };
}

function interpretInsightKind(result: CanonicalCopilotResult): InsightState {
  const synthesis = result.synthesis;
  const answer = retainedCopilotAnswer(synthesis);
  const agent = answer?.agent_name?.trim() ?? "";
  const version = answer?.agent_version?.trim() ?? "";
  const model = answer?.model?.trim() ?? "";
  const compatibilityNarration = answer && model.toLowerCase() !== "deterministic"
    ? answer.text?.trim() ?? "" : "";
  const narration = synthesis?.narration?.trim() ?? "";
  const claims = (synthesis?.claims ?? [])
    .map((claim) => claim.summary?.trim())
    .filter((summary): summary is string => Boolean(summary));
  const unavailableTools = (result.tool_results ?? [])
    .filter((toolResult) => toolResult.status !== "ok")
    .map((toolResult) => `${toolResult.tool} (${toolResult.status})`);
  const warning = Array.from(new Set([
    synthesis?.warning?.trim() ?? "",
    ...(result.uncertainty ?? []),
    unavailableTools.length ? `Unavailable evidence: ${unavailableTools.join(", ")}.` : "",
    result.policy_status === "fallback" && !narration && !compatibilityNarration && result.fallback_reason
      ? `Operations Copilot fallback: ${result.fallback_reason}.`
      : "",
  ].filter(Boolean))).join(" ");
  if (compatibilityNarration && answer) {
    return {
      kind: "llm", narration: compatibilityNarration, findings: [], warning,
      provider: { agent, version, model },
    };
  }
  if (synthesis?.status === "synthesized" && synthesis.mode === "foundry" && narration) {
    return { kind: "llm", narration, findings: [], warning };
  }
  if (answer?.grounded === true && model.toLowerCase() === "deterministic" && answer.text?.trim()) {
    return { kind: "deterministic", narration: "", findings: [answer.text.trim()], warning };
  }
  if (claims.length > 0) {
    return { kind: "deterministic", narration: "", findings: claims.slice(0, 3), warning };
  }
  const reason = synthesis?.reason === "no_cited_findings"
    ? "No cited findings were returned for this scope."
    : synthesis?.reason
      ? `Synthesis ${synthesis.status}: ${synthesis.reason}.`
      : "";
  return {
    kind: "unavailable",
    narration: "",
    findings: [],
    warning: [
      reason,
      warning,
    ].filter(Boolean).join(" ") || "No grounded insight was produced for this scope.",
  };
}

async function investigateInsight(
  snapshot: CopilotInsightSnapshot,
  question: string,
  requestedScope: ScopeSelection,
  signal: AbortSignal,
): Promise<InsightState> {
  const canonical = normalizeCopilotSnapshotV2(snapshot);
  const envelope = await investigateCanonical(
    { contract_version: "1", question, requested_scope: requestedScope, snapshot: canonical },
    requestedScope,
    signal,
  );
  return interpretInsightResult(envelope.data);
}

const BADGES: Record<InsightState["kind"], { label: string; tone: "success" | "info" | "warning" }> = {
  llm: { label: "LLM insight · Foundry", tone: "success" },
  deterministic: { label: "Grounded findings · deterministic", tone: "info" },
  fallback: { label: "Evidence-only fallback", tone: "warning" },
  unavailable: { label: "Insight unavailable", tone: "warning" },
};

/** Top-of-page Operations Copilot insight grounded in one page's bounded evidence snapshot. */
export function CopilotInsights({
  snapshot,
  requestedScope = {},
  contextLabel,
  question: questionOverride,
  focusCopy,
  onOpenCopilot,
  ready = true,
}: CopilotInsightsProps) {
  const [result, setResult] = useState<InsightState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const requestGeneration = useRef(0);
  const question = useMemo(
    () => questionOverride || defaultInsightQuestion(contextLabel),
    [contextLabel, questionOverride],
  );
  const snapshotJson = useMemo(() => JSON.stringify(snapshot ?? null), [snapshot]);
  const scopeJson = useMemo(() => JSON.stringify(requestedScope ?? {}), [requestedScope]);
  const evidenceAvailable = useMemo(() => hasEvidence(snapshot), [snapshot]);

  const refresh = useCallback(() => setRefreshGeneration((current) => current + 1), []);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    if (!ready) {
      setResult(null);
      setLoading(true);
      setError("");
      return () => {
        requestGeneration.current += 1;
      };
    }
    if (!evidenceAvailable) {
      setResult({
        kind: "unavailable",
        narration: "",
        findings: [],
        warning: "No page evidence is available for a grounded insight yet.",
      });
      setLoading(false);
      setError("");
      return () => {
        requestGeneration.current += 1;
      };
    }
    const submitted = JSON.parse(snapshotJson) as CopilotInsightSnapshot;
    const scope = JSON.parse(scopeJson) as ScopeSelection;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const timer = setTimeout(() => {
      investigateInsight(submitted, question, scope, controller.signal)
        .then((next) => {
          if (requestGeneration.current === generation) setResult(next);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted || requestGeneration.current !== generation) return;
          setResult(null);
          setError(reason instanceof Error ? reason.message : "Operations Copilot insights are unavailable.");
        })
        .finally(() => {
          if (requestGeneration.current === generation) setLoading(false);
        });
    }, INSIGHT_DEBOUNCE_MS);
    return () => {
      requestGeneration.current += 1;
      clearTimeout(timer);
      controller.abort();
    };
  }, [evidenceAvailable, question, ready, refreshGeneration, scopeJson, snapshotJson]);

  const badge = result ? BADGES[result.kind] : BADGES.unavailable;

  return (
    <article className="callout copilot-insights" aria-live="polite" aria-busy={loading}>
      <div className="copilot-insights-heading">
        <strong>Operations Copilot insights</strong>
        <span>{focusCopy || `Grounded in ${contextLabel || "the current page"}.`}</span>
      </div>
      {loading ? (
        <p>{ready ? "Analyzing authoritative page evidence…" : "Waiting for page evidence to load…"}</p>
      ) : result?.kind === "llm" ? (
        <>
          <StatusBadge label={badge.label} tone={badge.tone} compact />
          <div className="copilot-insights-narration">
            <MarkdownLite text={result.narration} />
          </div>
        </>
      ) : result && result.findings.length > 0 ? (
        <>
          <StatusBadge label={badge.label} tone={badge.tone} compact />
          <ul className="copilot-insights-findings">
            {result.findings.map((finding) => <li key={finding}>{finding}</li>)}
          </ul>
        </>
      ) : (
        <>
          <StatusBadge label={BADGES.unavailable.label} tone="warning" compact />
          <p>{error || result?.warning || "No grounded insight was produced for this scope."}</p>
        </>
      )}
      {!loading && result?.warning && (result.kind === "llm" || result.findings.length > 0) && (
        <small>{result.warning}</small>
      )}
      {!loading && result && (result.confidence || result.specialists?.length || result.provider) ? (
        <small className="copilot-insights-provenance">
          {[
            result.confidence ? `Synthesis confidence: ${result.confidence}` : "",
            result.specialists?.length ? `Specialists: ${result.specialists.join(", ")}` : "",
            result.provider ? `Foundry agent: ${result.provider.agent}:${result.provider.version} · Model: ${result.provider.model}` : "",
          ].filter(Boolean).join(" · ")}
        </small>
      ) : null}
      <div className="button-row">
        <button type="button" className="button-secondary" onClick={refresh}>
          Refresh insights
        </button>
        {onOpenCopilot && (
          <button type="button" className="button-secondary" onClick={onOpenCopilot}>
            Ask a follow-up
          </button>
        )}
      </div>
    </article>
  );
}
