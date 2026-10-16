"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ScopeSelection } from "@/lib/scope";
import { scopeToSearchParams } from "@/lib/scope";
import { networkApi } from "@/lib/services";
import type { NetworkFindingReview, NetworkReviewReference } from "@/lib/types";

interface Props {
  scope: ScopeSelection;
  reference: NetworkReviewReference;
  onReady: (review: NetworkFindingReview | null) => void;
}

/** Reacquire exact authorized evidence; an explicit checkbox separately attaches it to review. */
export function NetworkReviewContext({ scope, reference, onReady }: Props) {
  const [review, setReview] = useState<NetworkFindingReview | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const back = `/network?${scopeToSearchParams(scope)}`;
  useEffect(() => {
    const controller = new AbortController();
    setReview(null); setError(""); onReady(null);
    networkApi.review(scope, reference, { signal: controller.signal }).then(response => {
      if (!controller.signal.aborted) { setReview(response.data); onReady(response.data); }
    }).catch(reason => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Exact Network evidence is unavailable.");
    });
    return () => controller.abort();
  }, [scope, reference, onReady, attempt]);
  return <section className="network-review-context card" aria-label="Network finding review context" aria-busy={!review && !error}>
    <div className="card-header"><h2>Network finding context</h2>
      <p>Exact evidence for a separately proposed change. This does not generate a fix, validate the artifact relationship, approve or deploy anything.</p>
    </div>
    <div className="card-body">
      {error ? <><p role="alert">{error} Submission with this context is withheld.</p>
        <button type="button" className="button button-secondary" onClick={() => setAttempt(current => current + 1)}>Retry exact Network evidence</button></>
        : !review ? <p role="status">Reauthorizing current Network evidence…</p> : <>
          <h3>{review.title}</h3><p>{review.severity} · {review.category} · {review.kind}</p>
          <p><strong>Source analysis, not a verified runtime outcome: </strong>{review.detail}</p>
          <p><strong>Source recommendation, not a generated change: </strong>{review.recommendation}</p>
          <p>Source observed: {review.source_observed_at || "Not reported"}. Basis: {review.basis}. Flow-log state: {review.flow_log_state}.</p>
          <ul>{review.resource_ids.map(value => <li key={value}>{value}</li>)}</ul>
          <details><summary>Exact evidence identifiers</summary>
            <p>Finding: {review.finding_id}</p><p>Review digest: {review.reviewed_digest}</p>
            <p>Policy digest: {review.policy_digest}</p><p>Source finding digest: {review.source_finding_digest}</p>
          </details>
          <p>Evidence is rechecked on submission. A changed finding or scope blocks attachment; return to Network to review it again. Source generation and complete estate coverage are unreported.</p>
        </>}
      <Link href={back}>Return to current Network findings</Link>
    </div>
  </section>;
}
