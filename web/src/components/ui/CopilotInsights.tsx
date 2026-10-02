"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MarkdownLite } from "@/components/ui/MarkdownLite";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  normalizeCopilotSnapshotV2,
  type CopilotEvidenceSnapshotV2,
} from "@/lib/copilot/page-adapters";
import type { ScopeSelection } from "@/lib/scope";
import { investigateCanonical } from "@/lib/services";
import type {
  CanonicalCopilotResult,
  CanonicalInvestigationSynthesis,
  CopilotPageSnapshot,
} from "@/lib/types";

export type CopilotInsightSnapshot = CopilotPageSnapshot | CopilotEvidenceSnapshotV2;

type NarratedSynthesis = CanonicalInvestigationSynthesis & {
  mode?: string;
  narration?: string;
};

export interface InsightState {
  kind: "llm" | "deterministic" | "fallback" | "unavailable";
  narration: string;
  findings: string[];
  warning: string;
}

export interface CopilotInsightsProps {
  snapshot: CopilotInsightSnapshot;
  requestedScope?: ScopeSelection;
  contextLabel?: string;
  question?: string;
  focusCopy?: string;
  onOpenCopilot?: () => void;
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

/** Maps a canonical turn onto a display state, preferring Foundry narration. */
export function interpretInsightResult(result: CanonicalCopilotResult): InsightState {
  const synthesis = (result.synthesis ?? null) as NarratedSynthesis | null;
  const narration = synthesis?.narration?.trim() ?? "";
  const claims = (synthesis?.claims ?? [])
    .map((claim) => claim.summary?.trim())
    .filter((summary): summary is string => Boolean(summary));
  const warning = synthesis?.warning?.trim()
    || (result.policy_status === "fallback" && !narration && result.fallback_reason
      ? `Operations Copilot fallback: ${result.fallback_reason}.`
      : "");
  if (synthesis?.status === "synthesized" && narration) {
    return { kind: "llm", narration, findings: [], warning };
  }
  if (claims.length > 0) {
    return { kind: "deterministic", narration: "", findings: claims.slice(0, 3), warning };
  }
  const unavailableTools = (result.tool_results ?? [])
    .filter((toolResult) => toolResult.status !== "ok")
    .map((toolResult) => `${toolResult.tool} (${toolResult.status})`);
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
      unavailableTools.length ? `Unavailable evidence: ${unavailableTools.join(", ")}.` : "",
      result.uncertainty?.[0] ?? "",
    ].filter(Boolean).join(" ") || warning || "No grounded insight was produced for this scope.",
  };
}

async function investigateInsight(
  snapshot: CopilotInsightSnapshot,
  question: string,
  requestedScope: ScopeSelection,
): Promise<InsightState> {
  const canonical = normalizeCopilotSnapshotV2(snapshot);
  const envelope = await investigateCanonical(
    { contract_version: "1", question, requested_scope: requestedScope, snapshot: canonical },
    requestedScope,
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
    setLoading(true);
    setError("");
    investigateInsight(submitted, question, scope)
      .then((next) => {
        if (requestGeneration.current === generation) setResult(next);
      })
      .catch((reason: unknown) => {
        if (requestGeneration.current !== generation) return;
        setResult(null);
        setError(reason instanceof Error ? reason.message : "Operations Copilot insights are unavailable.");
      })
      .finally(() => {
        if (requestGeneration.current === generation) setLoading(false);
      });
    return () => {
      requestGeneration.current += 1;
    };
  }, [evidenceAvailable, question, refreshGeneration, scopeJson, snapshotJson]);

  const badge = result ? BADGES[result.kind] : BADGES.unavailable;

  return (
    <article className="callout copilot-insights" aria-live="polite" aria-busy={loading}>
      <div className="copilot-insights-heading">
        <strong>Operations Copilot insights</strong>
        <span>{focusCopy || `Grounded in ${contextLabel || "the current page"}.`}</span>
      </div>
      {loading ? (
        <p>Analyzing authoritative page evidence…</p>
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
