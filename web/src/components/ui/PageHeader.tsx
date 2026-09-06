import type { ReactNode } from "react";

export type AggregateCompleteness = "complete" | "partial" | "stale" | "unavailable";
export type EvidenceFreshness = "current" | "stale" | "unknown";

export interface PageHeaderCompleteness {
  state: AggregateCompleteness;
  freshness: EvidenceFreshness;
  representedConnections?: number;
  expectedConnections?: number;
  representedCount?: number;
  totalCount?: number;
  excludedCount?: number;
  excludedReasons?: string[];
}

export interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
  metadata?: ReactNode;
  /** Aggregate server evidence. Omit for pages that do not make an evidence claim. */
  completeness?: PageHeaderCompleteness;
}

const COMPLETENESS_LABELS: Record<AggregateCompleteness, string> = {
  complete: "Complete operational context",
  partial: "Partial operational context",
  stale: "Stale operational context",
  unavailable: "Unavailable operational context",
};

function completenessCopy(completeness: PageHeaderCompleteness): string {
  if (completeness.state === "complete" && completeness.freshness === "current") {
    return "Live operational context";
  }
  if (completeness.state === "complete" && completeness.freshness === "stale") {
    return "Stale operational context";
  }
  if (completeness.state === "complete") return "Unavailable operational context";
  return COMPLETENESS_LABELS[completeness.state];
}

function coverageCopy(completeness: PageHeaderCompleteness): string[] {
  const details: string[] = [];
  const {
    representedConnections,
    expectedConnections,
    representedCount,
    totalCount,
    excludedCount,
    excludedReasons = [],
  } = completeness;

  if (representedConnections !== undefined && expectedConnections !== undefined) {
    details.push(
      `${representedConnections.toLocaleString()} of ${expectedConnections.toLocaleString()} ${
        expectedConnections === 1 ? "connection" : "connections"
      } represented`,
    );
  }
  if (excludedCount !== undefined) {
    details.push(`${excludedCount.toLocaleString()} excluded`);
  }
  if (representedCount !== undefined) {
    details.push(`${representedCount.toLocaleString()} represented`);
  }
  if (totalCount !== undefined) {
    details.push(`${totalCount.toLocaleString()} total`);
  }
  details.push(...excludedReasons);
  return details;
}

/** Consistent title block for operational workbench pages. */
export function PageHeader({ eyebrow, title, description, actions, metadata, completeness }: PageHeaderProps) {
  const isLive = completeness?.state === "complete" && completeness.freshness === "current";
  const coverage = completeness ? coverageCopy(completeness) : [];

  return (
    <header className="page-header">
      <div className="page-header-copy">
        {completeness && (
          <div
            className={`page-header-signal page-header-signal-${isLive ? "live" : completeness.state}`}
            role="status"
            aria-label={`${title} evidence status`}
          >
            {isLive && (
              <span
                className="page-header-signal-dot page-header-signal-dot-live"
                data-testid="page-header-signal-dot"
                aria-hidden="true"
              />
            )}
            <span>{completenessCopy(completeness)}</span>
            {coverage.map((detail) => (
              <span className="page-header-signal-detail" key={detail}>
                {detail}
              </span>
            ))}
          </div>
        )}
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        <p>{description}</p>
        {metadata && <div className="page-header-metadata">{metadata}</div>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
}
