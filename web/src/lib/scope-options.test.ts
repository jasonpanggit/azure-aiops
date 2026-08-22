import { describe, expect, it } from "vitest";
import { buildScopeOptions } from "@/lib/scope-options";
import type { SubscriptionConnection } from "@/lib/types";

const connection: SubscriptionConnection = {
  connection_id: "prod-east",
  name: "Production East",
  subscription_id: "sub-001",
  tenant_id: "tenant-001",
  scope_key: "prod-east",
  is_active: true,
  business_service: "Payments",
  application: "Checkout",
  environment: "prod",
  owner: "Platform",
  support_team: "SRE",
  criticality: "critical",
  region: "eastus",
  sync_status: "succeeded",
  health_status: "healthy",
};

describe("buildScopeOptions", () => {
  it("creates selectable values for every populated operating-context dimension", () => {
    const options = buildScopeOptions([connection]);

    expect(options.business_service).toEqual([{ value: "Payments", label: "Payments" }]);
    expect(options.subscription_connection).toEqual([
      { value: "prod-east", label: "Production East (prod-east)" },
    ]);
    expect(options.subscription).toEqual([
      { value: "sub-001", label: "Production East · sub-001" },
    ]);
    expect(options.application[0].value).toBe("Checkout");
    expect(options.owner[0].value).toBe("Platform");
    expect(options.support_team[0].value).toBe("SRE");
    expect(options.region[0].value).toBe("eastus");
  });

  it("deduplicates values case-insensitively", () => {
    const options = buildScopeOptions([
      connection,
      { ...connection, connection_id: "prod-west", name: "Production West", business_service: "payments" },
    ]);

    expect(options.business_service).toHaveLength(1);
    expect(options.subscription_connection).toHaveLength(2);
  });
});
