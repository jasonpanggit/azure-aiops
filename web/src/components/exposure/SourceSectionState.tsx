"use client";

import type { ReactNode } from "react";

import type { ExposureSectionPresentation } from "@/hooks/useExposureSection";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";

type ExposureDisplayUnit =
  | "count"
  | "seconds"
  | "percent"
  | "score"
  | "risk"
  | "rank";

export function formatExposureValue(
  value: number | null | undefined,
  {
    unit,
    label = "items",
    ratio = false,
  }: {
    unit: ExposureDisplayUnit;
    label?: string;
    ratio?: boolean;
  },
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  switch (unit) {
    case "count":
      return `${value.toLocaleString("en-US")} ${label}`;
    case "seconds":
      return `${value.toLocaleString("en-US")} seconds`;
    case "percent":
      return `${(ratio ? value * 100 : value).toFixed(1)}%`;
    case "score":
      return `${value.toLocaleString("en-US")}/100`;
    case "risk":
      return `Risk score ${value.toLocaleString("en-US")}/100`;
    case "rank":
      return `Rank ${value.toLocaleString("en-US")}`;
  }
}

export interface SourceSectionStateProps {
  sourceName: string;
  itemLabel: string;
  state: ExposureSectionPresentation;
  children?: ReactNode;
}

function observedCopy(value: string): string {
  return value || "an unknown time";
}

function RetryButton({
  sourceName,
  state,
}: {
  sourceName: string;
  state: ExposureSectionPresentation;
}) {
  return (
    <button
      type="button"
      className="button"
      onClick={state.retry}
      aria-label={`Retry ${sourceName}`}
      aria-busy={state.retrying}
    >
      {state.retrying ? `Retrying ${sourceName}` : `Retry ${sourceName}`}
    </button>
  );
}

function coverageCopy(state: ExposureSectionPresentation): string {
  const { represented, total, excluded } = state.metadata;
  const parts: string[] = [];
  if (represented !== undefined) parts.push(`${represented.toLocaleString("en-US")} represented`);
  if (total !== undefined) parts.push(`${total.toLocaleString("en-US")} total`);
  if (excluded !== undefined) parts.push(`${excluded.toLocaleString("en-US")} excluded`);
  return parts.join(" · ");
}

function FreshnessDetail({ state }: { state: ExposureSectionPresentation }) {
  const { freshnessSourceFamily, freshnessThresholdSeconds, observedAt } = state.metadata;
  if (!freshnessSourceFamily && freshnessThresholdSeconds === undefined && !observedAt) {
    return null;
  }
  return (
    <p className="source-section-freshness">
      {freshnessSourceFamily
        ? `Source family: ${freshnessSourceFamily}. `
        : ""}
      {freshnessThresholdSeconds !== undefined
        ? `Freshness threshold: ${freshnessThresholdSeconds.toLocaleString("en-US")} seconds. `
        : ""}
      {observedAt ? `Observed: ${observedAt}.` : ""}
    </p>
  );
}

/** Shared local-state boundary for one independently useful Exposure source. */
export function SourceSectionState({
  sourceName,
  itemLabel,
  state,
  children,
}: SourceSectionStateProps) {
  const retry = <RetryButton sourceName={sourceName} state={state} />;

  if (state.status === "loading" && !state.refreshing) {
    return (
      <StatePanel
        title={state.retrying ? `Retrying ${sourceName}` : `Loading ${sourceName}`}
        message={`Loading ${sourceName}. Other Exposure sections remain available.`}
        tone="loading"
        busy
        live="polite"
        action={state.retrying ? retry : undefined}
      />
    );
  }

  if (state.status === "healthy-empty") {
    return (
      <StatePanel
        title={`No ${itemLabel} reported by ${sourceName}`}
        message={`${sourceName} completed successfully and returned no ${itemLabel} for this authorized scope as of ${observedCopy(state.metadata.observedAt)}. Other source states are shown separately.`}
        tone="empty"
        action={retry}
        live="polite"
      />
    );
  }

  if (state.status === "unavailable") {
    const restartCopy = state.restart.required
      ? " The retained generation expired; restart from the first page."
      : "";
    return (
      <StatePanel
        title={`${sourceName} is unavailable`}
        message={`${sourceName} is unavailable. Other Exposure data remains available. Retry ${sourceName}, or review the last successful checkpoint if one exists.${restartCopy}`}
        tone="error"
        action={retry}
        live="assertive"
      />
    );
  }

  const coverage = coverageCopy(state);
  const statusLabel =
    state.status === "stale"
      ? "Stale"
      : state.status === "partial"
        ? "Partial"
        : "Current";
  const statusTone =
    state.status === "current" ? "success" : "warning";
  const stateMessage =
    state.status === "stale"
      ? `Showing last successful ${sourceName} data from ${observedCopy(state.metadata.observedAt)}. The latest refresh failed, so do not treat missing rows as resolved.`
      : state.status === "partial"
        ? `Showing ${state.metadata.represented ?? "—"} of ${state.metadata.expected ?? "—"} connections represented. Results and totals exclude unavailable connections.`
        : `${sourceName} is current.`;

  return (
    <section
      className={`source-section-state source-section-${state.status}`}
      aria-busy={state.refreshing}
      aria-label={`${sourceName} state`}
    >
      <div className="source-section-state-header" role="status" aria-live="polite">
        <StatusBadge label={statusLabel} tone={statusTone} />
        <span>{state.refreshing ? `Refreshing ${sourceName}. ${stateMessage}` : stateMessage}</span>
      </div>
      {coverage && <p className="source-section-coverage">{coverage}</p>}
      {state.metadata.excludedReasons.length > 0 && (
        <ul className="source-section-exclusions" aria-label={`${sourceName} exclusion reasons`}>
          {state.metadata.excludedReasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      <FreshnessDetail state={state} />
      {(state.status === "stale" || state.status === "partial") && retry}
      <div className="source-section-content">{children}</div>
    </section>
  );
}
