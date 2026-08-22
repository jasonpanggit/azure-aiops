import { describe, expect, it } from "vitest";
import { emptyScope, scopeToSearchParams, SCOPE_DIMENSIONS } from "@/lib/scope";

describe("scope", () => {
  it("has the 9 dimensions the Operations API understands", () => {
    expect(SCOPE_DIMENSIONS).toEqual([
      "business_service",
      "application",
      "environment",
      "subscription",
      "subscription_connection",
      "owner",
      "support_team",
      "region",
      "criticality",
    ]);
  });

  it("serializes an empty scope to no query params", () => {
    expect(scopeToSearchParams(emptyScope()).toString()).toBe("");
  });

  it("serializes multiple values per dimension as repeated params", () => {
    const params = scopeToSearchParams({
      subscription: ["a", "b"],
      environment: ["prod"],
    });
    expect(params.getAll("subscription")).toEqual(["a", "b"]);
    expect(params.getAll("environment")).toEqual(["prod"]);
  });

  it("drops empty string values", () => {
    const params = scopeToSearchParams({ owner: ["", "bob"] });
    expect(params.getAll("owner")).toEqual(["bob"]);
  });
});
