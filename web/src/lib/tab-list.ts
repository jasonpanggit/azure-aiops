import { useEffect, useRef, type KeyboardEvent } from "react";

/** Keeps the selected or keyboard-focused tab visible without moving document scroll or focus. */
export function useSelectedTabVisibility(selected: string) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const list = ref.current;
    if (!list) return;
    const reveal = () => {
      const focused = document.activeElement;
      const tab = focused instanceof HTMLButtonElement && focused.getAttribute("role") === "tab" && list.contains(focused)
        ? focused
        : list.querySelector<HTMLButtonElement>('button[role="tab"][aria-selected="true"]');
      if (!tab) return;
      const bounds = list.getBoundingClientRect();
      const left = bounds.left + list.clientLeft;
      const right = left + list.clientWidth;
      const rect = tab.getBoundingClientRect();
      if (rect.left < left) list.scrollLeft += rect.left - left;
      else if (rect.right > right) list.scrollLeft += rect.right - right;
    };
    reveal();
    window.addEventListener("resize", reveal);
    return () => window.removeEventListener("resize", reveal);
  }, [selected]);
  return ref;
}

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
  tabs[next].scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
}
