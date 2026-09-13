"use client";

/** Props for the shared Operations Copilot drawer launcher. */
export interface CopilotDrawerButtonProps {
  onClick: () => void;
  label?: string;
  /** Pins the launcher to the viewport so it remains available on long pages. */
  floating?: boolean;
}

/** Compact button that opens the shared `CopilotDrawer`. */
export function CopilotDrawerButton({
  onClick,
  label = "Ask Operations Copilot",
  floating = false,
}: CopilotDrawerButtonProps) {
  return (
    <button
      type="button"
      className={`copilot-drawer-trigger${floating ? " copilot-drawer-trigger-floating" : ""}`}
      onClick={onClick}
      aria-label={label}
      title={label}
    >
      <span className="copilot-mark" aria-hidden="true">✦</span>
      <span className="copilot-drawer-trigger-label">{label}</span>
    </button>
  );
}
