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

  it("round-trips a retained export identity and aligned batch offset", () => {
    const params = new URLSearchParams("tab=azure&export_id=11111111-1111-4111-8111-111111111111&export_offset=49500");
    expect(parseInventoryView(inventoryViewQuery(parseInventoryView(params), {}))).toEqual(parseInventoryView(params));
  });

  it.each([
    "export_id=private", "export_offset=0", "export_id=11111111-1111-4111-8111-111111111111&export_offset=501",
    "export_id=11111111-1111-4111-8111-111111111111&export_offset=50000",
    "export_id=11111111-1111-4111-8111-111111111111&export_offset=-500",
  ])("rejects malformed retained export bookmark %s", (query) => {
    expect(() => parseInventoryView(new URLSearchParams(query))).toThrow("Invalid inventory export bookmark.");
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
