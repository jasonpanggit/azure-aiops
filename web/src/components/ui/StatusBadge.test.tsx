import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge, statusTone, type StatusTone } from "./StatusBadge";

const STATUS_TONES = [
  "critical",
  "high",
  "warning",
  "success",
  "neutral",
  "info",
  "unknown",
] as const satisfies readonly StatusTone[];

type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
const statusToneUnionIsExact: Exact<StatusTone, (typeof STATUS_TONES)[number]> = true;

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

const completePrePhase12Mappings = {
  ...prePhase10Mappings,
  "healthy-empty": "success",
  unavailable: "critical",
  "deployment-blocked": "warning",
  retired: "neutral",
  dormant: "neutral",
} as const;

const phase12Mappings = {
  complete: "success",
  partial: "warning",
  "not-analyzed": "warning",
  "private-link-candidate": "info",
  "public-access-enabled": "critical",
  "peer-not-ingested": "warning",
  "peer-out-of-scope": "info",
  "peer-resolution-unknown": "unknown",
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

  it("pins the seven-member tone union and every pre-Phase-12 keyword mapping", () => {
    expect(statusToneUnionIsExact).toBe(true);
    expect(STATUS_TONES).toHaveLength(7);
    expect([...STATUS_TONES].sort()).toEqual([
      "critical",
      "high",
      "info",
      "neutral",
      "success",
      "unknown",
      "warning",
    ]);
    expect(
      Object.fromEntries(
        Object.keys(completePrePhase12Mappings).map((keyword) => [
          keyword,
          statusTone(keyword),
        ]),
      ),
    ).toEqual(completePrePhase12Mappings);
  });

  it("maps every Phase-12 status keyword without adding a tone", () => {
    expect(
      Object.fromEntries(
        Object.keys(phase12Mappings).map((keyword) => [
          keyword,
          statusTone(keyword),
        ]),
      ),
    ).toEqual(phase12Mappings);
    expect(STATUS_TONES).toHaveLength(7);
  });
});
