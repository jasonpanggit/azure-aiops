import type { ScopeSelection } from "./scope";
import { scopeToSearchParams } from "./scope";
import type { NetworkReviewReference } from "./types";

const keys = ["network_kind", "network_finding", "network_digest"] as const;
export type NetworkReviewBookmark =
  | { present: false; reference: null; error: null }
  | { present: true; reference: NetworkReviewReference; error: null }
  | { present: true; reference: null; error: string };

/** Validate a complete unambiguous reference; never silently discard an invalid handoff. */
export function networkReviewBookmark(params: Pick<URLSearchParams, "getAll">): NetworkReviewBookmark {
  const [kind, identity, digest] = keys.map(key => params.getAll(key));
  if (![kind, identity, digest].some(values => values.length)) return { present: false, reference: null, error: null };
  if ([kind, identity, digest].some(values => values.length !== 1) ||
      !["gap", "rule"].includes(kind[0]) || !identity[0] || identity[0].length > 256 ||
      /[\0\r\n]/.test(identity[0]) || !/^[a-f0-9]{64}$/.test(digest[0])) {
    return { present: true, reference: null, error: "The Network review bookmark is incomplete or invalid. Return to the current finding and open its review link again." };
  }
  return { present: true, reference: { kind: kind[0] === "gap" ? "gap" : "rule", finding_id: identity[0], reviewed_digest: digest[0] }, error: null };
}

/** Carry exact reference and every repeated selected scope dimension, never finding text. */
export function networkReviewHref(kind: "gap" | "rule", identity: string, digest: string | undefined, scope: ScopeSelection): string | null {
  const query = scopeToSearchParams(scope);
  query.set("network_kind", kind); query.set("network_finding", identity);
  query.set("network_digest", digest ?? "");
  return networkReviewBookmark(query).reference ? `/changes/predeploy?${query}` : null;
}
