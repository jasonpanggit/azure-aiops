"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { MarkdownLite } from "./ui/MarkdownLite";
import { StatePanel } from "./ui/StatePanel";
import { StatusBadge } from "./ui/StatusBadge";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { isCanonicalAzureResourceId } from "@/lib/services";
import type { CanonicalCopilotCitation, CanonicalSynthesisClaim } from "@/lib/types";

/** Typed findings open returned citation metadata or exact internal resource lookups. */
export function CopilotFindings({ claims, citations, scope, threadId, threadRevision }: {
  claims: readonly CanonicalSynthesisClaim[];
  citations: readonly CanonicalCopilotCitation[];
  scope: ScopeSelection;
  threadId?: string;
  threadRevision?: number;
}) {
  const [selectedCitation, setSelectedCitation] = useState<CanonicalCopilotCitation | null>(null);
  const evidenceId = useId();
  const query = scopeToSearchParams(scope);
  const retained = threadId && /^thr-[a-f0-9]{32}$/.test(threadId) && Number.isSafeInteger(threadRevision) && (threadRevision ?? 0) > 0;
  if (retained) { query.set("thread_id", threadId); query.set("thread_revision", String(threadRevision)); }
  function citationFor(ref: string) {
    const matching = citations.filter(citation => citation.citation_id === ref);
    return matching.length === 1 ? matching[0] : null;
  }
  function currentResourceHref(citation: CanonicalCopilotCitation) {
    const resourceId = citation.resource_id;
    if (!["ok", "partial"].includes(citation.status) || !isCanonicalAzureResourceId(resourceId) || resourceId.length > 2048 || /[\u0000-\u001f\u007f]/.test(resourceId)) return null;
    const params = scopeToSearchParams(scope);
    params.set("resource_id", resourceId);
    return `/inventory/assets?${params}`;
  }
  return <section className="copilot-findings" aria-label="Structured Copilot findings">
    <h3>Structured findings</h3>
    <p>Explanatory review only. Links do not authorize changes or rerun a question. Current asset lookup is separate from retained evidence.</p>
    {claims.length ? <ol className="copilot-findings-list">{claims.map((claim, index) => {
      const refs = Array.from(new Set(claim.evidence_refs));
      const resolved = refs.map(citationFor);
      const complete = refs.length > 0 && resolved.every(citation => citation !== null && ["ok", "partial"].includes(citation.status));
      return <li key={`${claim.finding_id}:${index}`}>
        <p className="muted">Finding: {claim.finding_id}</p>
        <MarkdownLite text={claim.summary} />
        <div className="copilot-findings-meta">
          <StatusBadge label={`Confidence: ${claim.confidence}`} tone="info" compact />
          <span>Source freshness: {claim.freshness || "Not supplied"}</span>
        </div>
        {claim.uncertainty.length ? <ul aria-label="Finding uncertainty">{claim.uncertainty.map((item, itemIndex) => <li key={`${itemIndex}:${item}`}>{item}</li>)}</ul> : null}
        {!complete ? <p role="status">Evidence references are missing, ambiguous or unavailable. Navigation for this finding is withheld; no source identity is inferred.</p> : <ul className="copilot-findings-sources">{resolved.map(citation => {
          if (!citation) return null;
          const href = currentResourceHref(citation);
          return <li key={citation.citation_id}>
            <span>{citation.source} ({citation.status})</span>
            <button type="button" className="button" aria-controls={evidenceId} onClick={() => setSelectedCitation(citation)}>Inspect source {citation.citation_id}</button>
            {href ? <Link className="button" href={href}>Review current asset {citation.resource_id.split("/").filter(Boolean).at(-1)}</Link> : <span className="muted">No supported exact asset destination supplied.</span>}
          </li>;
        })}</ul>}
      </li>;
    })}</ol> : <StatePanel title="No structured findings returned" message="Tool evidence and citations remain available above. A free-form answer is not converted into typed findings or operational actions." />}
    {selectedCitation ? <section id={evidenceId} className="copilot-findings-source" aria-label="Selected finding source" aria-live="polite">
      <h4>Selected source evidence</h4>
      <dl>
        <div><dt>Citation</dt><dd>{selectedCitation.citation_id}</dd></div>
        <div><dt>Source / status</dt><dd>{selectedCitation.source} / {selectedCitation.status}</dd></div>
        <div><dt>Exact resource</dt><dd>{selectedCitation.resource_id || "Not supplied"}</dd></div>
        <div><dt>Observed</dt><dd>{selectedCitation.observed_at || "Not supplied"}</dd></div>
        <div><dt>Query version</dt><dd>{selectedCitation.query_version || "Not supplied"}</dd></div>
      </dl>
      <p>Only returned citation metadata is shown. No query is rerun and no publication generation is inferred from a query version.</p>
    </section> : null}
    {retained ? <Link className="button" href={`/copilot?${query}`}>Review retained evidence at revision {threadRevision}</Link> : <p className="muted">No exact retained thread revision supplied. Historical navigation is unavailable.</p>}
  </section>;
}
