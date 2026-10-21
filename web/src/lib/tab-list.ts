import type { KeyboardEvent } from "react";

/** Activates enabled tabs with arrow/Home/End keys while preserving native Tab navigation. */
export function handleTabListKeyDown(event: KeyboardEvent<HTMLElement>): void {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  if (!(event.target instanceof HTMLButtonElement)) return;
  const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="tab"]:not(:disabled)'));
  const current = tabs.indexOf(event.target);
  if (current < 0) return;
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
    : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault();
  tabs[next].focus();
  tabs[next].click();
}
