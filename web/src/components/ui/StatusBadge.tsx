export type StatusTone = "critical" | "high" | "warning" | "success" | "neutral" | "info" | "unknown";

export interface StatusBadgeProps {
  label: string;
  tone?: StatusTone;
  compact?: boolean;
}

/** Maps an operational state to a restrained, accessible status treatment. */
export function StatusBadge({ label, tone = "neutral", compact = false }: StatusBadgeProps) {
  return (
    <span className={`status-badge status-${tone}${compact ? " status-compact" : ""}`}>
      <span className="status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}

/** Infers a badge tone from common severity and lifecycle terms. */
export function statusTone(value?: string | null): StatusTone {
  const normalized = value?.toLowerCase() ?? "";
  if (["critical", "p1", "failed", "denied", "unhealthy", "unavailable", "public-access-enabled"].includes(normalized)) return "critical";
  if (["high", "p2", "at risk", "exposed"].includes(normalized)) return "high";
  if (["medium", "warning", "degraded", "stale", "indeterminate", "deployment-blocked", "partial", "not-analyzed", "peer-not-ingested"].includes(normalized)) return "warning";
  if (["healthy", "healthy-empty", "resolved", "allowed", "active", "succeeded", "low", "complete"].includes(normalized)) return "success";
  if (["open", "investigating", "in progress", "private-link-candidate", "peer-out-of-scope"].includes(normalized)) return "info";
  if (["unknown", "not available", "peer-resolution-unknown"].includes(normalized)) return "unknown";
  if (["retired", "dormant"].includes(normalized)) return "neutral";
  return "neutral";
}
