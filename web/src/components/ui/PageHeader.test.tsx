import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageHeader } from "./PageHeader";

const baseProps = {
  title: "Exposure",
  description: "Authorized exposure evidence.",
};

describe("PageHeader", () => {
  it("shows the live signal only for complete current evidence", () => {
    const { rerender } = render(
      <PageHeader
        {...baseProps}
        completeness={{ state: "complete", freshness: "current" }}
      />,
    );

    expect(screen.getByText("Live operational context")).toBeInTheDocument();
    expect(screen.getByTestId("page-header-signal-dot")).toHaveClass("page-header-signal-dot-live");

    rerender(
      <PageHeader
        {...baseProps}
        completeness={{ state: "complete", freshness: "stale" }}
      />,
    );

    expect(screen.queryByText("Live operational context")).not.toBeInTheDocument();
    expect(screen.getByText("Stale operational context")).toBeInTheDocument();
    expect(screen.queryByTestId("page-header-signal-dot")).not.toBeInTheDocument();
  });

  it.each([
    ["partial", "Partial operational context"],
    ["stale", "Stale operational context"],
    ["unavailable", "Unavailable operational context"],
  ] as const)("renders explicit text for %s evidence", (state, expectedText) => {
    render(
      <PageHeader
        {...baseProps}
        completeness={{ state, freshness: state === "stale" ? "stale" : "unknown" }}
      />,
    );

    expect(screen.getByText(expectedText)).toBeInTheDocument();
    expect(screen.queryByText("Live operational context")).not.toBeInTheDocument();
  });

  it("reports represented, expected, and excluded evidence without overstating freshness", () => {
    render(
      <PageHeader
        {...baseProps}
        completeness={{
          state: "partial",
          freshness: "current",
          representedConnections: 2,
          expectedConnections: 4,
          excludedCount: 17,
        }}
      />,
    );

    const status = screen.getByRole("status", { name: "Exposure evidence status" });
    expect(status).toHaveTextContent("Partial operational context");
    expect(status).toHaveTextContent("2 of 4 connections represented");
    expect(status).toHaveTextContent("17 excluded");
    expect(status).not.toHaveTextContent("Live operational context");
  });

  it("makes no live evidence claim when aggregate completeness was not supplied", () => {
    render(<PageHeader {...baseProps} />);

    expect(screen.queryByText("Live operational context")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Exposure evidence status" })).not.toBeInTheDocument();
  });
});
