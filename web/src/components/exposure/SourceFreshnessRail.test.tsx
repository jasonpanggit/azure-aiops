import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ExposureSectionPresentation } from "@/hooks/useExposureSection";
import { SourceFreshnessRail } from "./SourceFreshnessRail";

function state(
  status: ExposureSectionPresentation["status"],
  overrides: Partial<ExposureSectionPresentation> = {},
): ExposureSectionPresentation {
  return {
    status,
    error: null,
    loading: status === "loading",
    refreshing: false,
    retrying: false,
    retained: false,
    metadata: {
      loaded: 1,
      total: 2,
      excludedReasons: [],
      observedAt: "2026-09-14T08:00:00Z",
      freshnessState: status,
      freshnessSourceFamily: "test",
      safeErrorMessage: "",
    },
    restart: { required: false, reason: "", generation: "" },
    retry: vi.fn(),
    ...overrides,
  };
}

describe("SourceFreshnessRail", () => {
  it("renders durable fresh, queued, refreshing, LKG, partial, unavailable, and empty states", () => {
    render(
      <SourceFreshnessRail
        items={[
          { key: "fresh", label: "Fresh source", state: state("current") },
          {
            key: "queued",
            label: "Queued source",
            state: state("unavailable"),
            providerStatus: "queued",
          },
          {
            key: "refreshing",
            label: "Refreshing source",
            state: state("stale", { refreshing: true }),
            providerStatus: "refreshing",
            hasLastKnownGood: true,
          },
          {
            key: "lkg",
            label: "LKG source",
            state: state("stale"),
            providerStatus: "failed",
            hasLastKnownGood: true,
          },
          { key: "partial", label: "Partial source", state: state("partial") },
          { key: "unavailable", label: "Unavailable source", state: state("unavailable") },
          { key: "empty", label: "Empty source", state: state("healthy-empty") },
        ]}
      />,
    );

    expect(within(screen.getByRole("region", { name: "Fresh source source status" })).getByText("Fresh")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Queued source source status" })).getByText("Queued")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Refreshing source source status" })).getByText("Refreshing")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "LKG source source status" })).getByText("Last known good")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Partial source source status" })).getByText("Partial")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Unavailable source source status" })).getByText("Unavailable")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Empty source source status" })).getByText("Fresh")).toBeInTheDocument();
  });

  it("announces source transitions and exposes named retry actions", () => {
    render(
      <SourceFreshnessRail
        items={[
          {
            key: "refreshing",
            label: "EPSS",
            state: state("stale", { refreshing: true, retrying: true }),
            providerStatus: "refreshing",
            hasLastKnownGood: true,
          },
        ]}
      />,
    );

    const source = screen.getByRole("region", { name: "EPSS source status" });
    expect(within(source).getByRole("status")).toHaveAttribute("aria-live", "polite");
    expect(within(source).getByRole("button", { name: "Retry EPSS" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(source).toHaveTextContent("Last-known-good evidence remains visible");
  });
});
