"use client";

/** Compact floating/inline button that opens the `CopilotDrawer`. Kept separate
 * from the drawer itself so pages can place it in a header/toolbar without
 * pulling in the drawer's open-state logic. */
export function CopilotDrawerButton({ onClick, label = "Ask Operations Copilot" }: { onClick: () => void; label?: string }) {
  return (
    <button type="button" className="copilot-drawer-trigger" onClick={onClick} aria-label={label} title={label}>
      <span className="copilot-mark" aria-hidden="true">✦</span>
      <span className="copilot-drawer-trigger-label">{label}</span>
    </button>
  );
}
