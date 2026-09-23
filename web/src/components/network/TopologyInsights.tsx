"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { NetworkCopilotSelection } from "@/lib/copilot/page-adapters";
import { copilotApi } from "@/lib/services";
import type { CopilotContextResult, CopilotPageSnapshot } from "@/lib/types";

interface TopologyInsightsProps {
  snapshot: CopilotPageSnapshot;
  selection?: NetworkCopilotSelection | null;
  ready?: boolean;
  onAskFollowUp: () => void;
}

function executiveQuestion(selection?: NetworkCopilotSelection | null): string {
  const subject = selection?.node ?? selection?.edge;
  const instructions = [
    "Name the specific affected resources and the concrete gaps or rule findings that drive the risk, rather than only aggregate counts.",
    "For each material gap, state the observed issue and the recommended remediation carried in that evidence.",
    "Close with the residual uncertainty and the next read-only check.",
  ];
  if (!subject) {
    return [
      "Provide an executive summary grounded only in this bounded Network topology snapshot.",
      ...instructions,
    ].join(" ");
  }
  const selector = selection?.node?.id ?? selection?.edge?.id ?? "";
  return [
    "Provide an executive summary grounded only in this bounded Network topology snapshot.",
    `Selected label: ${subject.label}.`,
    `Selected kind: ${subject.kind}.`,
    `Selected selector: ${selector}.`,
    ...instructions,
  ].join(" ");
}

function deterministicSummary(result: CopilotContextResult): string {
  const findings = Array.isArray(result.findings) ? result.findings : [];
  const summaries = findings
    .filter((finding) => finding.status !== "denied")
    .map((finding) => (typeof finding.summary === "string" ? finding.summary.trim() : ""))
    .filter(Boolean);
  return summaries.slice(0, 3).join(" ");
}

/** Asynchronously narrates the bounded Network snapshot without delaying page content. */
export function TopologyInsights({
  snapshot,
  selection = null,
  ready = true,
  onAskFollowUp,
}: TopologyInsightsProps) {
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [result, setResult] = useState<CopilotContextResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const requestGeneration = useRef(0);
  const question = executiveQuestion(selection);
  const requestSnapshot = useMemo(
    () => ({ ...snapshot, question }),
    [question, snapshot],
  );
  const requestKey = JSON.stringify(requestSnapshot);

  useEffect(() => {
    if (!ready) {
      setLoading(true);
      setError(null);
      return undefined;
    }
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setLoading(true);
    setError(null);

    const currentSnapshot = JSON.parse(requestKey) as CopilotPageSnapshot;
    void copilotApi.investigateContext(currentSnapshot)
      .then((response) => {
        if (requestGeneration.current !== generation) return;
        setResult(response.data);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (requestGeneration.current !== generation) return;
        setResult(null);
        setError(reason instanceof Error ? reason.message : "The insight request failed.");
        setLoading(false);
      });
    return () => {
      if (requestGeneration.current === generation) {
        requestGeneration.current += 1;
      }
    };
  }, [ready, refreshGeneration, requestKey]);

  const narration = result?.synthesis?.narration?.trim()
    || result?.synthesis?.text?.trim()
    || "";
  const fallback = result ? deterministicSummary(result) : "";
  const grounded = result?.synthesis_mode === "foundry" && narration.length > 0;

  return (
    <section className="topology-insights" aria-live="polite" aria-busy={loading}>
      <div className="topology-insights-header">
        <div>
          <p className="eyebrow">Operations Copilot</p>
          <h2>Topology insights</h2>
        </div>
        <div className="topology-insights-actions">
          <button type="button" onClick={() => setRefreshGeneration((value) => value + 1)}>
            Refresh insights
          </button>
          <button type="button" className="button-primary" onClick={onAskFollowUp}>
            Ask a follow-up
          </button>
        </div>
      </div>
      {loading ? (
        <p>Reviewing the bounded topology evidence…</p>
      ) : grounded ? (
        <>
          <strong>Grounded LLM insight</strong>
          <p>{narration}</p>
        </>
      ) : narration || fallback ? (
        <>
          <strong>Evidence-only fallback</strong>
          <p>{narration || fallback}</p>
        </>
      ) : (
        <>
          <strong>Insights unavailable</strong>
          <p>
            {error
              ? `Operations Copilot could not analyze this snapshot: ${error}`
              : "The bounded snapshot returned no supported findings or narration."}
          </p>
        </>
      )}
    </section>
  );
}
