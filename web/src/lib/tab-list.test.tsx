import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { handleTabListKeyDown, useSelectedTabVisibility } from "./tab-list";

function Tabs({ initial = 0 }: { initial?: number }) {
  const [selected, setSelected] = useState(initial);
  const ref = useSelectedTabVisibility(String(selected));
  return <div ref={ref} role="tablist" onKeyDown={handleTabListKeyDown}>
    {["First", "Disabled", "Last"].map((label, index) => (
      <button key={label} role="tab" disabled={index === 1} aria-selected={selected === index}
        tabIndex={selected === index ? 0 : -1} onClick={() => setSelected(index)}>{label}</button>
    ))}
  </div>;
}

describe("Shared tab keyboard activation", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each([[300, 440, 240], [-80, 60, -80], [20, 160, 0]])(
    "reveals selected tab bounds %s..%s horizontally by %s on mount",
    (left, right, delta) => {
      vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
        return this.getAttribute("aria-selected") === "true"
          ? DOMRect.fromRect({ x: left, width: right - left })
          : DOMRect.fromRect({ width: 200 });
      });
      vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(200);
      render(<Tabs initial={2} />);
      expect(screen.getByRole("tablist").scrollLeft).toBe(delta);
      expect(screen.getByRole("tab", { name: "Last" })).not.toHaveFocus();
    },
  );

  it("reveals selection changes and cleans up resize handling", () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const { unmount } = render(<Tabs />);
    const list = screen.getByRole("tablist");
    const last = screen.getByRole("tab", { name: "Last" });
    vi.spyOn(list, "clientWidth", "get").mockReturnValue(200);
    vi.spyOn(last, "getBoundingClientRect").mockReturnValue(DOMRect.fromRect({ x: 300, width: 140 }));
    fireEvent.click(last);
    expect(list.scrollLeft).toBe(240);
    unmount();
    expect(remove).toHaveBeenCalledWith("resize", expect.any(Function));
  });

  it("preserves a different keyboard-focused tab on resize", () => {
    render(<Tabs initial={2} />);
    const list = screen.getByRole("tablist");
    const first = screen.getByRole("tab", { name: "First" });
    first.focus();
    list.scrollLeft = 100;
    vi.spyOn(list, "clientWidth", "get").mockReturnValue(200);
    vi.spyOn(first, "getBoundingClientRect").mockReturnValue(DOMRect.fromRect({ x: -100, width: 80 }));
    fireEvent(window, new Event("resize"));
    expect(list.scrollLeft).toBe(0);
    expect(first).toHaveFocus();
  });

  it("wraps enabled tabs, activates the destination and supports Home/End", () => {
    render(<Tabs />);
    const first = screen.getByRole("tab", { name: "First" });
    const last = screen.getByRole("tab", { name: "Last" });
    const reveal = vi.spyOn(last, "scrollIntoView");
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(last).toHaveFocus();
    expect(last).toHaveAttribute("aria-selected", "true");
    expect(reveal).toHaveBeenCalledWith({ block: "nearest", inline: "nearest", behavior: "instant" });
    fireEvent.keyDown(last, { key: "ArrowRight" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: "Home" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "End" });
    expect(last).toHaveFocus();
  });

  it("leaves native Tab behavior and non-tab events alone", () => {
    render(<Tabs />);
    const first = screen.getByRole("tab", { name: "First" });
    expect(fireEvent.keyDown(first, { key: "Tab", cancelable: true })).toBe(true);
    expect(fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight", cancelable: true })).toBe(true);
    expect(first).toHaveAttribute("aria-selected", "true");
  });
});
