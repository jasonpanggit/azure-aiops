/**
 * Focused unit tests for `blockerCopyWithTelemetry` (WR-02 fix): the
 * centralized once-per-code unknown-blocker-code telemetry shared by every
 * `blockerCopy()` render-path call site (`WorkflowBlockers`,
 * `stepBlockerEcho`, and `RecoveryControls`'s supersede-ineligibility-reason
 * callout). Exercised directly against the module rather than through a
 * full page render so each call site's contribution to the shared
 * dedup state can be verified in isolation.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { blockerCopyWithTelemetry } from "./blockers";

describe("blockerCopyWithTelemetry", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("logs telemetry exactly once for a distinct unrecognized code even across repeated calls", () => {
    const first = blockerCopyWithTelemetry("blockers_test_unknown_a", "verify");
    const second = blockerCopyWithTelemetry("blockers_test_unknown_a", "verify");

    expect(first.message).toBe("An unrecognized workflow condition (blockers_test_unknown_a) is blocking this step.");
    expect(second.message).toBe(first.message);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith("remediation.blocker.unknown_code", { code: "blockers_test_unknown_a" });
  });

  it("logs telemetry independently per distinct unrecognized code", () => {
    blockerCopyWithTelemetry("blockers_test_unknown_b", "review");
    blockerCopyWithTelemetry("blockers_test_unknown_c", "approve");

    expect(warnSpy).toHaveBeenCalledTimes(2);
    expect(warnSpy).toHaveBeenCalledWith("remediation.blocker.unknown_code", { code: "blockers_test_unknown_b" });
    expect(warnSpy).toHaveBeenCalledWith("remediation.blocker.unknown_code", { code: "blockers_test_unknown_c" });
  });

  it("never logs telemetry for a recognized vocabulary code", () => {
    const copy = blockerCopyWithTelemetry("not_approved", "approve");

    expect(copy.message).toBe("No decision has been recorded yet.");
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("never logs telemetry when the server supplies its own message for an unknown code", () => {
    const copy = blockerCopyWithTelemetry(
      "blockers_test_unknown_d",
      "run",
      "Server-supplied explanation for this condition.",
    );

    expect(copy.message).toBe("Server-supplied explanation for this condition.");
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("dedupes across the two distinct call-site shapes (cross-step panel row vs. supersede-ineligibility-reason string) for the same code", () => {
    // Simulates WorkflowBlockers/stepBlockerEcho's row-shaped call...
    blockerCopyWithTelemetry("blockers_test_unknown_e", "verify", undefined, undefined, "warning");
    // ...followed by RecoveryControls's bare ineligibility-reason call for
    // the same underlying code reaching the recovery-control write path.
    blockerCopyWithTelemetry("blockers_test_unknown_e", "verify");

    expect(warnSpy).toHaveBeenCalledTimes(1);
  });
});
