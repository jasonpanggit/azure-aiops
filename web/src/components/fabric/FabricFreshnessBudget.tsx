"use client";

import type { FabricFreshnessBudget as Budget } from "@/lib/types";

const SOURCE_LIMIT = 20;
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const age = (value: unknown): value is number => finite(value) && value >= 0;

function validBudget(budget: Budget): boolean {
  if (
    budget.clock !== "metadata_status_ingested_then_observed_then_timestamp" ||
    !["table_override", "defaults"].includes(budget.policy) ||
    !age(budget.threshold_seconds) || budget.threshold_seconds === 0 ||
    !age(budget.cadence_minutes) || budget.cadence_minutes === 0 ||
    !age(budget.slo_multiplier) || budget.slo_multiplier === 0 ||
    budget.threshold_seconds !== budget.cadence_minutes * budget.slo_multiplier * 60 ||
    typeof budget.evaluated_at !== "string" || !Number.isFinite(Date.parse(budget.evaluated_at)) ||
    !Array.isArray(budget.sources) || budget.source_count !== budget.sources.length ||
    !budget.sources.every(source =>
      source && typeof source.scope === "object" && source.scope !== null &&
      (source.partition_key === undefined || typeof source.partition_key === "string") &&
      Object.values(source.scope).every(values => Array.isArray(values) && values.every(value => typeof value === "string")) &&
      typeof source.status_at === "string" &&
      (source.state === "unknown"
        ? source.age_seconds === null && source.remaining_seconds === null
        : age(source.age_seconds) && finite(source.remaining_seconds) &&
          source.remaining_seconds === budget.threshold_seconds - source.age_seconds &&
          source.state === (source.age_seconds > budget.threshold_seconds ? "stale" : "fresh")),
    )
  ) return false;
  const known = budget.sources.flatMap(source => source.age_seconds === null ? [] : [source.age_seconds]);
  const state = budget.sources.some(source => source.state === "stale") ? "stale"
    : !budget.sources.length || budget.sources.some(source => source.state === "unknown") ? "unknown" : "fresh";
  const worst = known.length ? known.reduce((maximum, value) => Math.max(maximum, value)) : null;
  return budget.state === state && budget.known_clock_count === known.length &&
    budget.worst_known_age_seconds === worst &&
    budget.remaining_seconds === (known.length === budget.source_count && worst !== null ? budget.threshold_seconds - worst : null);
}

function duration(seconds: number): string {
  if (seconds < 60) return `${Number(seconds.toFixed(1))} sec`;
  if (seconds < 3600) return `${Number((seconds / 60).toFixed(1))} min`;
  return `${Number((seconds / 3600).toFixed(1))} hr`;
}

function headroom(seconds: number | null): string {
  if (seconds === null) return "Unknown headroom";
  if (seconds === 0) return "At budget boundary";
  return seconds > 0 ? `${duration(seconds)} remaining` : `${duration(-seconds)} over budget`;
}

/** Explains a server-evaluated budget without reclassifying it using the browser clock. */
export function FabricFreshnessBudget({ budget }: { budget?: Budget }) {
  if (!budget) return <p className="fabric-budget-note">Freshness budget unavailable from this response.</p>;
  if (!validBudget(budget)) return <p className="fabric-budget-note" role="alert">Freshness budget is inconsistent. Refresh Fabric health to reload its source evidence.</p>;
  return (
    <details className="fabric-freshness-budget">
      <summary>Freshness budget: {headroom(budget.remaining_seconds)}</summary>
      <p>{duration(budget.threshold_seconds)} limit = {duration(budget.cadence_minutes * 60)} cadence × {budget.slo_multiplier}. {budget.policy === "table_override" ? "Table override" : "Default policy"}.</p>
      <p>Evaluated {budget.evaluated_at}. {budget.known_clock_count}/{budget.source_count} source clocks usable. Stale sources lead; any unknown clock prevents a fresh result.</p>
      <p>Metadata ingestion time takes precedence over observation time, then status timestamp. This does not verify resource-data freshness, upstream completeness, or the next scheduled sync. Headroom is fixed at the evaluation time.</p>
      {budget.sources.length === 0 ? <p>No source-status rows recorded.</p> : (
        <ul aria-label="Source freshness budgets">
          {budget.sources.slice(0, SOURCE_LIMIT).map((source, index) => (
            <li key={index}>
              <strong>{Object.entries(source.scope).map(([key, values]) => `${key}: ${values.join(", ")}`).join(" · ") || "Scope identity unreported"}</strong>
              {source.partition_key && <div>Source partition: {source.partition_key}</div>}
              <div>{source.age_seconds === null ? "Unknown age (missing, invalid, unzoned, or future clock)" : `${duration(source.age_seconds)} old`} · {headroom(source.remaining_seconds)}</div>
              <div>Status clock: {source.status_at || "Unreported"}</div>
            </li>
          ))}
        </ul>
      )}
      {budget.source_count > SOURCE_LIMIT && <p>Showing {SOURCE_LIMIT} of {budget.source_count} source budgets. The aggregate evaluates all reported sources, not just this display.</p>}
    </details>
  );
}
