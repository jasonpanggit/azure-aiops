import type { FlowVerdict } from "./types";

export interface VerdictPresentation {
  intent: "success" | "error" | "warning";
  label: string;
  /** Shown when the engine refused to decide, so the UI never lets an
   * unresolved path read as permission. */
  caveat: string | null;
}

/**
 * Maps a flow verdict to its presentation.
 *
 * `indeterminate` is deliberately *not* folded into either allowed or denied:
 * it means an endpoint or a higher-priority rule could not be resolved, and
 * rendering it as "allowed" would turn a refusal to guess into a false
 * assurance on a security-facing view.
 */
export function presentVerdict(verdict: FlowVerdict): VerdictPresentation {
  switch (verdict) {
    case "allowed":
      return { intent: "success", label: "ALLOWED", caveat: null };
    case "denied":
      return { intent: "error", label: "DENIED", caveat: null };
    default:
      return {
        intent: "warning",
        label: "INDETERMINATE",
        caveat:
          "Part of the path could not be resolved, so no claim is made in either direction. This is not the same as allowed.",
      };
  }
}
