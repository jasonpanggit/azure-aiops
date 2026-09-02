import { describe, expect, it } from "vitest";
import { formatDefenderAsset } from "./asset-labels";
import type { DefenderPostureFinding } from "@/lib/types";

const baseFinding: DefenderPostureFinding = {
  assessment_id: "assessment-1",
  asset_id: "",
  asset_name: "",
  resource_type: "",
  inventory_kind: "",
  defender_plan: "Defender for Cloud",
  status: "Unhealthy",
  severity: "High",
  recommendation: "Recommendation",
  description: "Description",
  remediation: "Remediation",
  last_assessed_at: "2026-09-02T00:00:00Z",
  subscription_id: "sub-1",
};

describe("formatDefenderAsset", () => {
  it("labels subscription UUIDs as subscriptions instead of bare opaque IDs", () => {
    expect(
      formatDefenderAsset({
        ...baseFinding,
        asset_id: "/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1",
        asset_name: "a87a8e64-a52a-4aa8-a760-5e8919d23cd1",
        resource_type: "microsoft.resources/subscriptions",
        inventory_kind: "Azure resource",
      })
    ).toBe("Subscription a87a8e64-a52a-4aa8-a760-5e8919d23cd1 (Subscription)");
  });

  it("falls back to the ARM resource name and friendly Azure type for UUID-like asset names", () => {
    expect(
      formatDefenderAsset({
        ...baseFinding,
        asset_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.App/containerApps/aiops-dev-api",
        asset_name: "4f92f742-20af-4f32-80bc-c186ae400120",
        resource_type: "microsoft.app/containerapps",
        inventory_kind: "Azure resource",
      })
    ).toBe("aiops-dev-api (Container app)");
  });

  it("collapses duplicated Defender container workload names", () => {
    expect(
      formatDefenderAsset({
        ...baseFinding,
        asset_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.ContainerRegistry/registries/agentic-aiops-demo",
        asset_name: "agentic-aiops-demo___agentic-aiops-demo",
        resource_type: "containerimage",
        inventory_kind: "Container workload",
      })
    ).toBe("agentic-aiops-demo (Container workload)");
  });
});
