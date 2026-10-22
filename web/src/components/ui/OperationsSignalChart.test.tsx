import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CoverageDonut, OperationsSignalChart } from "./OperationsSignalChart";

describe("OperationsSignalChart", () => {
  it("renders truthful signal labels and values", () => {
    render(
      <OperationsSignalChart
        signals={[
          { label: "Priority situations", value: 2, tone: "critical" },
          { label: "Network gaps", value: 0, tone: "warning" },
        ]}
      />
    );

    expect(screen.getByRole("img", { name: "Operational signal counts: Priority situations 2, Network gaps 0" })).toBeInTheDocument();
    expect(screen.getByText("Priority situations")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows an honest empty state when there are no signals", () => {
    render(<OperationsSignalChart signals={[{ label: "Exposure", value: 0, tone: "critical" }]} />);
    expect(screen.getByText("No elevated signals in this scope.")).toBeInTheDocument();
  });
});

describe("CoverageDonut", () => {
  it("exposes healthy and attention counts", () => {
    render(<CoverageDonut healthy={4} needsAttention={1} />);
    expect(screen.getByRole("img", { name: "4 healthy connections and 1 connection needing attention" })).toBeInTheDocument();
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("1 connection needing attention")).toBeInTheDocument();
  });
});
