import Link from "next/link";

import {
  DEFENDER_PORTAL_ACTION_LABELS,
  isDefenderPortalActionKind,
  safeDefenderPortalHref,
  safeGovernedHandoffHref,
  type DefenderPortalAction,
  type DefenderPortalActionKind,
} from "@/lib/exposure-portal-links";

export {
  DEFENDER_PORTAL_ACTION_LABELS,
  isDefenderPortalActionKind,
  safeDefenderPortalHref,
  type DefenderPortalAction,
  type DefenderPortalActionKind,
};

export interface GovernedDefenderHandoff {
  outcome: "eligible" | "review_handoff" | "no_safe_action";
  /** Same-origin remediation destination supplied by the governed backend. */
  href?: string | null;
  representedTargets?: number;
  totalTargets?: number;
  excludedReasons?: string[];
  reason?: string | null;
}

export interface DefenderHandoffProps {
  actions: readonly DefenderPortalAction[];
  authorizedResourceIds?: readonly string[];
  governedHandoff?: GovernedDefenderHandoff | null;
}

const DEFAULT_DISABLED_GUIDANCE =
  "No safe Azure portal destination was provided. Review the evidence in Exposure.";

function PortalAction({
  action,
  authorizedResourceIds,
}: {
  action: DefenderPortalAction;
  authorizedResourceIds: readonly string[];
}) {
  const label = DEFENDER_PORTAL_ACTION_LABELS[action.kind];
  const href = safeDefenderPortalHref(action, authorizedResourceIds);
  return (
    <li>
      {href ? (
        <>
          <a
            className="table-primary-link"
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${label} (opens Azure portal in a new tab)`}
          >
            {label}
          </a>
          <span className="table-secondary">
            Opens Azure portal in a new tab.
          </span>
        </>
      ) : (
        <span aria-disabled="true">
          <span>{label}</span>
          <span className="table-secondary">
            {action.disabledReason || DEFAULT_DISABLED_GUIDANCE}
          </span>
        </span>
      )}
      {action.evidenceId && (
        <span className="table-secondary">
          {`Evidence ID: ${action.evidenceId}`}
        </span>
      )}
    </li>
  );
}

function GovernedHandoff({
  handoff,
}: {
  handoff: GovernedDefenderHandoff;
}) {
  const href = safeGovernedHandoffHref(handoff.href);
  const excludedReasons = handoff.excludedReasons ?? [];
  const coverage =
    handoff.representedTargets !== undefined &&
    handoff.totalTargets !== undefined
      ? `Handoff available for ${handoff.representedTargets.toLocaleString(
          "en-US",
        )} of ${handoff.totalTargets.toLocaleString(
          "en-US",
        )} represented targets.`
      : "";

  return (
    <div role="group" aria-label="Governed remediation handoff">
      {handoff.outcome === "no_safe_action" || !href ? (
        <>
          <strong>No safe action</strong>
          <p>
            {handoff.reason ||
              "No safe governed handoff is available for the represented evidence."}
          </p>
        </>
      ) : (
        <>
          <Link className="button" href={href}>
            Open governed remediation
          </Link>
          <p>
            {handoff.outcome === "review_handoff"
              ? "Review only. Nothing executes from Exposure."
              : "You will review the represented targets in governed remediation. Nothing executes from Exposure."}
          </p>
          {coverage && <p>{coverage}</p>}
        </>
      )}
      {excludedReasons.length > 0 && (
        <ul aria-label="Excluded handoff targets">
          {excludedReasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Named, fail-closed portal and governed-review destinations for Defender rows. */
export function DefenderHandoff({
  actions,
  authorizedResourceIds = [],
  governedHandoff,
}: DefenderHandoffProps) {
  const governedActions = actions.filter((action) =>
    isDefenderPortalActionKind(action.kind),
  );
  if (governedActions.length === 0 && !governedHandoff) return null;
  return (
    <div aria-label="Defender handoffs">
      {governedActions.length > 0 && (
        <ul>
          {governedActions.map((action, index) => (
            <PortalAction
              key={`${action.kind}:${action.evidenceId || action.resourceId || index}`}
              action={action}
              authorizedResourceIds={authorizedResourceIds}
            />
          ))}
        </ul>
      )}
      {governedHandoff && <GovernedHandoff handoff={governedHandoff} />}
    </div>
  );
}
