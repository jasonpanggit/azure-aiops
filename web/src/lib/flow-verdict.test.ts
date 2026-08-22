import { describe, expect, it } from "vitest";
import { presentVerdict } from "@/lib/flow-verdict";

describe("presentVerdict", () => {
  it("renders an allowed flow as success with no caveat", () => {
    expect(presentVerdict("allowed")).toEqual({ intent: "success", label: "ALLOWED", caveat: null });
  });

  it("renders a denied flow as an error with no caveat", () => {
    expect(presentVerdict("denied")).toEqual({ intent: "error", label: "DENIED", caveat: null });
  });

  it("never presents indeterminate as success", () => {
    // The load-bearing assertion: an unresolved path must not read as
    // permission on a security-facing view.
    const presentation = presentVerdict("indeterminate");
    expect(presentation.intent).not.toBe("success");
    expect(presentation.label).toBe("INDETERMINATE");
  });

  it("explains why an indeterminate verdict is not an allow", () => {
    expect(presentVerdict("indeterminate").caveat).toMatch(/not the same as allowed/i);
  });
});
