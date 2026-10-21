import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ExposureSectionPresentation } from "@/hooks/useExposureSection";
import { SourceSectionState } from "./SourceSectionState";

function presentation(status: ExposureSectionPresentation["status"]): ExposureSectionPresentation {
  return {
    status,
    error: status === "stale" ? new Error("Refresh failed") : null,
    loading: false,
    refreshing: false,
    retrying: false,
    retained: status === "stale",
    metadata: {
      loaded: 2,
      represented: 1,
      expected: 2,
      total: 3,
      excluded: 1,
      excludedReasons: ["West connection unavailable"],
      observedAt: "2026-09-06T08:00:00Z",
      freshnessState: status === "stale" ? "stale" : "current",
      freshnessSourceFamily: "aum",
      freshnessThresholdSeconds: 3600,
      safeErrorMessage: "",
    },
    restart: { required: false, reason: "", generation: "" },
    retry: vi.fn(),
  };
}

describe("Exposure source details", () => {
  it.each(["current", "partial", "stale"] as const)(
    "keeps %s coverage visible and uses the correct default disclosure state",
    (status) => {
      const state = presentation(status);
      const { container } = render(
        <SourceSectionState sourceName="Test source" itemLabel="findings" state={state}>
          <p>Current task content</p>
        </SourceSectionState>,
      );
      const details = container.querySelector("details")!;
      expect(details.open).toBe(status !== "current");
      expect(screen.getByText("1 of 2 represented · 2 loaded · 3 total · 1 excluded")).toBeVisible();
      expect(screen.getByText("West connection unavailable")).toBeVisible();
      expect(screen.getByText("Current task content")).toBeVisible();
      if (status !== "current") {
        expect(screen.getByText(/Source family: aum/)).toBeVisible();
        fireEvent.click(screen.getByRole("button", { name: "Retry Test source" }));
        expect(state.retry).toHaveBeenCalledOnce();
      } else {
        expect(screen.getByText(/Source family: aum/)).not.toBeVisible();
        fireEvent.click(screen.getByText("Source freshness details"));
        expect(details.open).toBe(true);
        expect(screen.getByText(/Source family: aum/)).toBeVisible();
        expect(state.retry).not.toHaveBeenCalled();
      }
    },
  );

  it("keeps stale-data warnings outside the technical disclosure", () => {
    const { container } = render(
      <SourceSectionState sourceName="Test source" itemLabel="findings" state={presentation("stale")} />,
    );
    fireEvent.click(screen.getByText("Source freshness details"));
    expect(container.querySelector("details")!.open).toBe(false);
    expect(screen.getByText(/do not treat missing rows as resolved/)).toBeVisible();
    expect(screen.getByText("West connection unavailable")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry Test source" })).toBeVisible();
  });
});
