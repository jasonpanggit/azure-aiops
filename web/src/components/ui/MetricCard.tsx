import type { ReactNode } from "react";

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  detail: string;
  tone?: "default" | "critical" | "warning" | "success";
  action?: ReactNode;
  /** Use "text" for qualitative values so prose is not rendered at display size. */
  size?: "default" | "text";
}

/** Compact KPI card that preserves context and a clear operational implication. */
export function MetricCard({ label, value, detail, tone = "default", action, size = "default" }: MetricCardProps) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className={size === "text" ? "metric-value metric-value-text" : "metric-value"}>{value}</div>
      <div className="metric-detail">{detail}</div>
      {action && <div className="metric-action">{action}</div>}
    </article>
  );
}
