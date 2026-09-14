"use client";

import type { ExposureSectionPresentation } from "@/hooks/useExposureSection";
import { StatusBadge, type StatusTone } from "@/components/ui/StatusBadge";

export interface SourceFreshnessRailItem {
  key: string;
  label: string;
  state: ExposureSectionPresentation;
  providerStatus?: string;
  hasLastKnownGood?: boolean;
}

export interface SourceFreshnessRailProps {
  items: SourceFreshnessRailItem[];
}

function sourcePresentation(item: SourceFreshnessRailItem): {
  label: string;
  tone: StatusTone;
  detail: string;
} {
  const providerStatus = item.providerStatus?.trim().toLocaleLowerCase("en-US");
  if (item.state.refreshing || ["refreshing", "running", "in_progress"].includes(providerStatus ?? "")) {
    return {
      label: "Refreshing",
      tone: "info",
      detail: item.hasLastKnownGood
        ? "Last-known-good evidence remains visible during refresh."
        : "No retained evidence is available while refresh runs.",
    };
  }
  if (["queued", "pending", "scheduled"].includes(providerStatus ?? "")) {
    return {
      label: "Queued",
      tone: "info",
      detail: item.hasLastKnownGood
        ? "Last-known-good evidence remains visible while refresh is queued."
        : "No retained evidence is available while refresh is queued.",
    };
  }
  if (item.state.status === "stale" && item.hasLastKnownGood) {
    return {
      label: "Last known good",
      tone: "warning",
      detail: "The latest attempt did not replace the retained evidence.",
    };
  }
  if (item.state.status === "stale") {
    return {
      label: "Stale",
      tone: "warning",
      detail: "Evidence is older than its freshness contract.",
    };
  }
  if (item.state.status === "partial") {
    return {
      label: "Partial",
      tone: "warning",
      detail: "Only part of the expected evidence is represented.",
    };
  }
  if (item.state.status === "unavailable" || item.state.status === "loading") {
    return {
      label: item.state.status === "loading" ? "Loading" : "Unavailable",
      tone: item.state.status === "loading" ? "info" : "critical",
      detail:
        item.state.metadata.safeErrorMessage ||
        "No durable evidence is available for this source.",
    };
  }
  return {
    label: "Fresh",
    tone: "success",
    detail:
      item.state.status === "healthy-empty"
        ? "The source completed and reported no matching records."
        : "Evidence is within its freshness contract.",
  };
}

/** Compact, independently retryable source-state rail for Exposure detail pages. */
export function SourceFreshnessRail({ items }: SourceFreshnessRailProps) {
  return (
    <aside className="exposure-evidence-rail" aria-labelledby="source-freshness-heading">
      <div className="exposure-evidence-rail-heading">
        <p className="eyebrow">Evidence</p>
        <h2 id="source-freshness-heading">Source freshness</h2>
        <p>Durable server state only. Missing source status is never presented as current.</p>
      </div>
      <div className="exposure-source-list">
        {items.map((item) => {
          const presentation = sourcePresentation(item);
          const coverage = [
            item.state.metadata.loaded !== undefined
              ? `${item.state.metadata.loaded.toLocaleString("en-US")} loaded`
              : "",
            item.state.metadata.total !== undefined
              ? `${item.state.metadata.total.toLocaleString("en-US")} total`
              : "",
          ].filter(Boolean);
          return (
            <section
              className="exposure-source-item"
              key={item.key}
              aria-label={`${item.label} source status`}
              aria-busy={item.state.refreshing}
            >
              <div className="exposure-source-item-heading" role="status" aria-live="polite">
                <strong>{item.label}</strong>
                <StatusBadge label={presentation.label} tone={presentation.tone} compact />
              </div>
              <p>{presentation.detail}</p>
              {item.state.metadata.observedAt && (
                <p>
                  <strong>Observed</strong>{" "}
                  <time dateTime={item.state.metadata.observedAt}>
                    {item.state.metadata.observedAt}
                  </time>
                </p>
              )}
              {coverage.length > 0 && <p>{coverage.join(" · ")}</p>}
              {item.state.status !== "current" && item.state.status !== "healthy-empty" && (
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={item.state.retry}
                  aria-label={`Retry ${item.label}`}
                  aria-busy={item.state.retrying}
                >
                  {item.state.retrying ? `Retrying ${item.label}` : `Retry ${item.label}`}
                </button>
              )}
            </section>
          );
        })}
      </div>
    </aside>
  );
}
