import type { ReactNode } from "react";

export interface StatePanelProps {
  title: string;
  message: string;
  tone?: "empty" | "error" | "loading";
  action?: ReactNode;
}

/** Standard empty, loading, and error state for operational pages. */
export function StatePanel({ title, message, tone = "empty", action }: StatePanelProps) {
  return (
    <div className={`state-panel state-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <div className="state-symbol" aria-hidden="true">
        {tone === "error" ? "!" : tone === "loading" ? "…" : "○"}
      </div>
      <h2>{title}</h2>
      <p>{message}</p>
      {action && <div className="state-action">{action}</div>}
    </div>
  );
}
