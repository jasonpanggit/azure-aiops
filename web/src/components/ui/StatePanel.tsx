import type { ReactNode } from "react";

export interface StatePanelProps {
  title: string;
  message: string;
  tone?: "empty" | "error" | "loading" | "stale" | "partial" | "success";
  action?: ReactNode;
  busy?: boolean;
  live?: "off" | "polite" | "assertive";
}

/** Standard empty, loading, and error state for operational pages. */
export function StatePanel({
  title,
  message,
  tone = "empty",
  action,
  busy = false,
  live,
}: StatePanelProps) {
  return (
    <div
      className={`state-panel state-${tone}`}
      role={tone === "error" ? "alert" : "status"}
      aria-busy={busy}
      aria-live={live}
    >
      <div className="state-symbol" aria-hidden="true">
        {tone === "error"
          ? "!"
          : tone === "loading"
            ? "…"
            : tone === "stale" || tone === "partial"
              ? "△"
              : "○"}
      </div>
      <h2>{title}</h2>
      <p>{message}</p>
      {action && <div className="state-action">{action}</div>}
    </div>
  );
}
