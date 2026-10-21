import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { handleTabListKeyDown } from "./tab-list";

function Tabs() {
  const [selected, setSelected] = useState(0);
  return <div role="tablist" onKeyDown={handleTabListKeyDown}>
    {["First", "Disabled", "Last"].map((label, index) => (
      <button key={label} role="tab" disabled={index === 1} aria-selected={selected === index}
        tabIndex={selected === index ? 0 : -1} onClick={() => setSelected(index)}>{label}</button>
    ))}
  </div>;
}

describe("Shared tab keyboard activation", () => {
  it("wraps enabled tabs, activates the destination and supports Home/End", () => {
    render(<Tabs />);
    const first = screen.getByRole("tab", { name: "First" });
    const last = screen.getByRole("tab", { name: "Last" });
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(last).toHaveFocus();
    expect(last).toHaveAttribute("aria-selected", "true");
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
