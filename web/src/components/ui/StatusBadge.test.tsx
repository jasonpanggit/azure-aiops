import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge, statusTone } from "./StatusBadge";

const prePhase10Mappings = {
  critical: "critical",
  p1: "critical",
  failed: "critical",
  denied: "critical",
  unhealthy: "critical",
  high: "high",
  p2: "high",
  "at risk": "high",
  exposed: "high",
  medium: "warning",
  warning: "warning",
  degraded: "warning",
  stale: "warning",
  indeterminate: "warning",
  healthy: "success",
  resolved: "success",
  allowed: "success",
  active: "success",
  succeeded: "success",
  low: "success",
  open: "info",
  investigating: "info",
  "in progress": "info",
  unknown: "unknown",
  "not available": "unknown",
} as const;

describe("statusTone", () => {
  it("maps healthy-empty to success", () => {
    expect(statusTone("healthy-empty")).toBe("success");
  });

  it("maps unavailable to critical while preserving unavailable copy distinctly from failed", () => {
    expect(statusTone("unavailable")).toBe("critical");

    const { rerender } = render(<StatusBadge label="Unavailable" tone={statusTone("unavailable")} />);
    expect(screen.getByText("Unavailable")).toHaveClass("status-critical");
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();

    rerender(<StatusBadge label="Failed" tone={statusTone("failed")} />);
    expect(screen.getByText("Failed")).toHaveClass("status-critical");
    expect(screen.queryByText("Unavailable")).not.toBeInTheDocument();
  });

  it("keeps stale and degraded mapped to warning", () => {
    expect(statusTone("stale")).toBe("warning");
    expect(statusTone("degraded")).toBe("warning");
  });

  it("maps retired and dormant to the neutral lifecycle tone", () => {
    expect(statusTone("retired")).toBe("neutral");
    expect(statusTone("dormant")).toBe("neutral");
  });

  it("maps deployment-blocked to warning", () => {
    expect(statusTone("deployment-blocked")).toBe("warning");
  });

  it("preserves every pre-Phase-10 keyword mapping", () => {
    for (const [keyword, tone] of Object.entries(prePhase10Mappings)) {
      expect(statusTone(keyword), keyword).toBe(tone);
    }
  });
});
