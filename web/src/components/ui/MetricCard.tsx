import type { ReactNode } from "react";

export interface MetricCardProps {
  label: string;
  value: ReactNode | null | undefined;
  detail: string;
  tone?: "default" | "critical" | "warning" | "success";
  action?: ReactNode;
  /** Use "text" for qualitative values so prose is not rendered at display size. */
  size?: "default" | "text";
  /** Printed beside known and unknown values so an em dash retains its meaning. */
  unit?: string;
  /** Forces an unknown display even when a compatibility caller supplied a value. */
  unavailable?: boolean;
  completeness?: "complete" | "partial" | "stale" | "unavailable";
}

const COMPLETENESS_LABELS = {
  complete: "Complete evidence",
  partial: "Partial evidence",
  stale: "Stale evidence",
  unavailable: "Unavailable evidence",
} as const;

/** Compact KPI card that preserves context and a clear operational implication. */
export function MetricCard({
  label,
  value,
  detail,
  tone = "default",
  action,
  size = "default",
  unit,
  unavailable = false,
  completeness,
}: MetricCardProps) {
  const isUnknown = unavailable || value === null || value === undefined;
  const cardMode = action ? "metric-card-actionable" : "metric-card-static";

  return (
    <article className={`metric-card metric-${tone} ${cardMode}`}>
      <div className="metric-label">{label}</div>
      <div
        className={size === "text" ? "metric-value metric-value-text" : "metric-value"}
        aria-label={`${label} value`}
      >
        <span>{isUnknown ? "—" : value}</span>
        {unit && <span className="metric-unit">{` ${unit}`}</span>}
      </div>
      <div className="metric-detail">{detail}</div>
      {completeness && <div className="metric-completeness">{COMPLETENESS_LABELS[completeness]}</div>}
      {action && <div className="metric-action">{action}</div>}
    </article>
  );
}
