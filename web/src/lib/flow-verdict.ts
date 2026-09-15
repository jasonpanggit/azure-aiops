import type { FlowResult, FlowVerdict } from "./types";

export interface VerdictPresentation {
  intent: "success" | "error" | "warning";
  label: string;
  /** Shown when the engine refused to decide, so the UI never lets an
   * unresolved path read as permission. */
  caveat: string | null;
}

/** Truthful summary of how completely the engine resolved a flow path. */
export interface PathResolutionPresentation {
  label: string;
  detail: string;
  tone: "success" | "warning";
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

/**
 * Describes path resolution independently from the reachability verdict.
 *
 * An indeterminate verdict always remains partial or unresolved, even when an
 * older or degraded backend response does not include explicit unknown text.
 */
export function presentPathResolution(
  result: FlowResult,
): PathResolutionPresentation {
  if (result.unknowns.length > 0) {
    const count = result.unknowns.length;
    return {
      label: `${count} reported unknown${count === 1 ? "" : "s"}`,
      detail: result.unknowns.join(", "),
      tone: "warning",
    };
  }

  const endpointsResolved = result.source.resolved && result.destination.resolved;
  const unknownControls = result.hops.filter((hop) => hop.decision === "unknown");
  if (unknownControls.length > 0) {
    return {
      label: "Path partially resolved",
      detail: unknownControls
        .map((hop) => hop.reason)
        .filter(Boolean)
        .join(", ") || "One or more observed controls could not be evaluated.",
      tone: "warning",
    };
  }

  if (result.verdict === "indeterminate") {
    const partial =
      result.source.resolved || result.destination.resolved || result.hops.length > 0;
    return {
      label: partial ? "Path partially resolved" : "Path unresolved",
      detail: endpointsResolved
        ? "The endpoints were resolved, but the observed controls were insufficient for a reachability verdict."
        : "The available evidence was insufficient to resolve the complete path or reachability verdict.",
      tone: "warning",
    };
  }

  if (!endpointsResolved) {
    return {
      label: "Path partially resolved",
      detail: "At least one endpoint was not resolved from the observed topology.",
      tone: "warning",
    };
  }

  return {
    label: "Path fully resolved",
    detail: "No unresolved path elements were reported.",
    tone: "success",
  };
}

/**
 * Converts Azure service-tag implementation notation into operator-facing
 * language while preserving rule names and the rest of the evidence.
 */
export function presentFlowReason(reason: string): string {
  return reason.replace(
    /VirtualNetwork\s*->\s*VirtualNetwork/g,
    "traffic between virtual networks",
  );
}
