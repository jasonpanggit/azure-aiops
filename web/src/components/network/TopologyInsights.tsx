"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { MarkdownLite } from "@/components/ui/MarkdownLite";
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
  return summaries.slice(0, 3).join("\n\n");
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
  const executive = result?.synthesis?.executive;
  const claims = (Array.isArray(executive?.claims) ? executive.claims : [])
    .filter((claim) => typeof claim.summary === "string" && claim.summary.trim());
  const hasContent = claims.length > 0 || Boolean(narration || fallback);
  const grounded = result?.synthesis_mode === "foundry"
    && (!executive?.mode || executive.mode === "foundry")
    && (claims.length > 0 || narration.length > 0);
  const warning = executive?.warning || result?.synthesis?.warning || result?.warnings?.[0];

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
      ) : hasContent ? (
        <>
          <strong>{grounded ? "Grounded LLM insight" : "Evidence-only fallback"}</strong>
          {grounded && executive?.agent && <p>Agent: {executive.agent}</p>}
          {!grounded && warning && <p role="status">{warning}</p>}
          {claims.length > 0 ? (
            <ol className="topology-insights-findings" aria-label="Topology findings">
              {claims.map((claim, index) => (
                <li key={`${claim.finding_id}-${index}`}>
                  <MarkdownLite text={claim.summary} />
                  {claim.next_check && (
                    <div>
                      <strong>Next read-only check</strong>
                      <MarkdownLite text={claim.next_check} />
                    </div>
                  )}
                  {Array.isArray(claim.uncertainty) && claim.uncertainty.length > 0 && (
                    <div>
                      <strong>Uncertainty</strong>
                      <ul>
                        {claim.uncertainty.map((item, itemIndex) => (
                          <li key={itemIndex}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {Array.isArray(claim.evidence_refs) && claim.evidence_refs.length > 0 && (
                    <details>
                      <summary>Cited evidence ({claim.evidence_refs.length})</summary>
                      <ul>
                        {claim.evidence_refs.map((ref, refIndex) => (
                          <li key={refIndex}><code>{ref}</code></li>
                        ))}
                      </ul>
                    </details>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <MarkdownLite text={narration || fallback} />
          )}
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
