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
  if (["critical", "p1", "failed", "timed out", "denied", "rejected", "blocked", "invalid", "unhealthy", "unavailable", "public-access-enabled"].includes(normalized)) return "critical";
  if (["high", "p2", "at risk", "exposed"].includes(normalized)) return "high";
  if (["medium", "warning", "degraded", "stale", "indeterminate", "deployment-blocked", "partial", "review pending", "not-analyzed", "peer-not-ingested"].includes(normalized)) return "warning";
  if (["healthy", "healthy-empty", "resolved", "allowed", "accepted", "valid", "active", "fresh", "succeeded", "allowlisted auto-accept", "low", "complete"].includes(normalized)) return "success";
  if (["open", "investigating", "in progress", "queued", "retrying", "discovering", "proposing", "validating", "publishing", "private-link-candidate", "peer-out-of-scope"].includes(normalized)) return "info";
  if (["unknown", "missing", "not available", "peer-resolution-unknown"].includes(normalized)) return "unknown";
  if (["retired", "cancelled", "rolled back", "superseded", "shadow mode", "dormant"].includes(normalized)) return "neutral";
  return "neutral";
}
