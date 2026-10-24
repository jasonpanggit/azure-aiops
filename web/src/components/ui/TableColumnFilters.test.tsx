import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TableColumnFilters } from "./TableColumnFilters";

describe("TableColumnFilters labels", () => {
  it("uses natural default labels without changing option values or handlers", () => {
    const onChange = vi.fn();
    render(<TableColumnFilters filters={[{
      id: "health", label: "Health", value: "all",
      options: [{ value: "unknown", label: "Unknown" }], onChange,
    }]} />);
    const select = screen.getByRole("combobox", { name: "Filter by Health" });
    expect(within(select).getByRole("option", { name: "Any health" })).toHaveValue("all");
    fireEvent.change(select, { target: { value: "unknown" } });
    expect(onChange).toHaveBeenCalledWith("unknown");
  });

  it("preserves explicit all-values labels, defaults, result counts, and reset behavior", () => {
    const onReset = vi.fn();
    render(<TableColumnFilters filters={[
      { id: "type", label: "Type", value: "vm", allLabel: "All resource types", options: [{ value: "vm", label: "VM" }], onChange: vi.fn() },
      { id: "view", label: "View", value: "retained", defaultValue: "retained", options: [{ value: "retained", label: "Retained" }], onChange: vi.fn() },
    ]} onReset={onReset} resultCount={1} totalCount={2} />);
    expect(screen.getByRole("option", { name: "All resource types" })).toHaveValue("all");
    expect(within(screen.getByRole("combobox", { name: "Filter by View" })).queryByRole("option", { name: "Any view" })).not.toBeInTheDocument();
    expect(screen.getByText("1 of 2 shown")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onReset).toHaveBeenCalledOnce();
  });
});
