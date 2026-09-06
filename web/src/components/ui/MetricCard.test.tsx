import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MetricCard } from "./MetricCard";

describe("MetricCard", () => {
  it("renders a null value as an em dash while retaining unit, detail, and completeness", () => {
    render(
      <MetricCard
        label="Secure score"
        value={null}
        unit="%"
        detail="No complete Defender score is available."
        completeness="unavailable"
      />,
    );

    expect(screen.getByLabelText("Secure score value")).toHaveTextContent("— %");
    expect(screen.getByText("No complete Defender score is available.")).toBeInTheDocument();
    expect(screen.getByText("Unavailable evidence")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("lets an explicit unavailable state override a zero-looking value", () => {
    render(
      <MetricCard
        label="Affected assets"
        value={0}
        unavailable
        unit="assets"
        detail="The source did not return usable evidence."
        completeness="partial"
      />,
    );

    expect(screen.getByLabelText("Affected assets value")).toHaveTextContent("— assets");
    expect(screen.getByText("Partial evidence")).toBeInTheDocument();
  });

  it("renders known values with their unit and textual completeness", () => {
    render(
      <MetricCard
        label="CVSS"
        value="8.8"
        unit="/10"
        detail="Base score"
        completeness="complete"
      />,
    );

    expect(screen.getByLabelText("CVSS value")).toHaveTextContent("8.8 /10");
    expect(screen.getByText("Complete evidence")).toBeInTheDocument();
  });

  it("does not expose hover/action affordance for a static metric", () => {
    const { rerender } = render(
      <MetricCard label="Findings" value={12} detail="Authorized current rows" />,
    );

    expect(screen.getByRole("article")).toHaveClass("metric-card-static");
    expect(screen.getByRole("article")).not.toHaveClass("metric-card-actionable");

    rerender(
      <MetricCard
        label="Findings"
        value={12}
        detail="Authorized current rows"
        action={<a href="/exposure">Review findings</a>}
      />,
    );

    expect(screen.getByRole("article")).toHaveClass("metric-card-actionable");
    expect(screen.getByRole("link", { name: "Review findings" })).toBeInTheDocument();
  });
});
