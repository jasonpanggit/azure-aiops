import { describe, expect, it } from "vitest";
import { inventoryViewQuery, parseInventoryView } from "../inventory-view";

describe("Grouped Inventory bookmark contracts", () => {
  it("round-trips every family filter, page and row count with selected scope", () => {
    const query = new URLSearchParams({
      tab: "azure", search: "Windows", sourceFilter: "arc", lifecycleFilter: "review",
      osNameFilter: "Windows Server", osVersionFilter: "2022",
      softwareSearch: "Widget", softwareSourceFilter: "unlinked", softwareNameFilter: "Widget Suite",
      softwarePublisherFilter: "Vendor", azureSearch: "App", azureProviderFilter: "microsoft.web",
      azureTypeFilter: "microsoft.web/sites", azureSkuFilter: "P1 / Premium",
      subscriptionFilter: "sub-a", osPage: "3", softwarePage: "2", azurePage: "1",
      osPageSize: "50", softwarePageSize: "100", azurePageSize: "20",
    });
    const view = parseInventoryView(query);
    const saved = inventoryViewQuery(view, { subscription: ["sub-a"], environment: ["prod"] });
    expect(parseInventoryView(saved)).toEqual(view);
    expect(saved.getAll("subscription")).toEqual(["sub-a"]);
    expect(saved.getAll("environment")).toEqual(["prod"]);
  });

  it("omits defaults and unrelated private query values", () => {
    const view = parseInventoryView(new URLSearchParams("private_token=secret&tab=os"));
    expect(inventoryViewQuery(view, {}).toString()).toBe("");
  });

  it.each([
    ["tab", "bogus"], ["osPage", "-1"], ["azurePage", "10001"], ["softwarePage", "2x"],
    ["osPageSize", "500"], ["softwarePageSize", "0"], ["sourceFilter", "invented"],
    ["lifecycleFilter", "certified"], ["search", "x".repeat(257)], ["osNameFilter", "x".repeat(121)],
    ["softwareSearch", "private\u0000value"],
  ])("rejects invalid %s without echoing its value", (key, value) => {
    const query = new URLSearchParams({ [key]: value });
    expect(() => parseInventoryView(query)).toThrow(`Invalid inventory bookmark field: ${key}`);
  });
});
