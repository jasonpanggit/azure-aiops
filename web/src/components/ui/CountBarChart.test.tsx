import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CountBarChart } from "./CountBarChart";

describe("CountBarChart quantitative labels", () => {
  it("preserves existing count labels and number formatting", () => {
    render(<CountBarChart unit="target" data={[{ id: "a", label: "Target A", value: 1200 }]} />);
    expect(screen.getByRole("list", { name: "Counts by target" })).toHaveTextContent("Target A1,200");
  });

  it("exposes monetary units without calling the values counts", () => {
    render(<CountBarChart
      data={[{ id: "a", label: "Advisor", value: 12.25 }, { id: "b", label: "Other", value: 0 }]}
      ariaLabel="Identified annual savings in USD"
      formatValue={value => `${value} USD`}
    />);
    expect(screen.getByRole("list", { name: "Identified annual savings in USD" })).toHaveTextContent("Advisor12.25 USDOther0 USD");
    const rows = screen.getAllByRole("listitem");
    expect(rows[0].querySelector(".count-bar-fill")).toHaveStyle({ width: "100%" });
    expect(rows[1].querySelector(".count-bar-fill")).toHaveStyle({ width: "0%" });
  });
});
