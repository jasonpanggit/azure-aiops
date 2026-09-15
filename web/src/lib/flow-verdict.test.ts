import { describe, expect, it } from "vitest";
import {
  presentFlowReason,
  presentPathResolution,
  presentVerdict,
} from "@/lib/flow-verdict";
import type { FlowResult } from "@/lib/types";

function flowResult(overrides: Partial<FlowResult> = {}): FlowResult {
  return {
    query: {
      source: "vm-a",
      destination: "Internet",
      port: 443,
      protocol: "TCP",
      environment_scope: "",
    },
    source: {
      raw: "vm-a",
      ip_address: "10.0.0.4",
      subnet_id: "subnet-a",
      vnet_id: "vnet-a",
      nsg_id: "nsg-a",
      resource_id: "vm-a",
      environment: "prod",
      name: "vm-a",
      is_internet: false,
      resolved: true,
    },
    destination: {
      raw: "Internet",
      ip_address: "",
      subnet_id: "",
      vnet_id: "",
      nsg_id: "",
      resource_id: "",
      environment: "",
      name: "Internet",
      is_internet: true,
      resolved: true,
    },
    verdict: "allowed",
    hops: [],
    missing_enforcement_points: [],
    unknowns: [],
    path_summary: "vm-a => Internet: allowed",
    ...overrides,
  };
}

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

describe("presentPathResolution", () => {
  it("never calls an indeterminate path fully resolved", () => {
    expect(
      presentPathResolution(flowResult({ verdict: "indeterminate" })),
    ).toEqual({
      label: "Path partially resolved",
      detail:
        "The endpoints were resolved, but the observed controls were insufficient for a reachability verdict.",
      tone: "warning",
    });
  });

  it("reports explicit unknown evidence when available", () => {
    expect(
      presentPathResolution(
        flowResult({
          verdict: "indeterminate",
          unknowns: ["A higher-priority rule could not be evaluated"],
        }),
      ),
    ).toEqual({
      label: "1 item could not be determined",
      detail: "A higher-priority rule could not be evaluated",
      tone: "warning",
    });
  });
});

describe("presentFlowReason", () => {
  it("translates Azure service-tag implementation terms into plain language", () => {
    expect(
      presentFlowReason(
        "Outbound rule 'AllowVnetOutBound' allows * VirtualNetwork -> VirtualNetwork:*",
      ),
    ).toBe(
      "Outbound rule 'AllowVnetOutBound' allows * traffic between virtual networks:*",
    );
  });
});
