import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  query: "", scope: { subscription: ["sub-a"] } as ScopeSelection,
  push: vi.fn(), resources: vi.fn(), asset: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: mocks.scope }) }));
vi.mock("@/lib/services", () => ({ inventoryApi: { resources: mocks.resources, asset: mocks.asset } }));

import InventoryAssetsPage from "./page";

const resourceId = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Web/sites/app & prod";
function collection() {
  return {
    data: {
      resources: [{ family: "paas", resource_id: resourceId, resource_name: "Production app",
        resource_type: "microsoft.web/sites", subscription_id: "sub-a", resource_group: "rg", environment: "" }],
      family_availability: { paas: { family: "paas", state: "ready", row_count: 80 } },
      represented_count: 80, generation_id: "generation-2", query_version: "query-v1",
      facets: { family: [{ value: "paas", count: 80 }], resource_group: [{ value: "rg", count: 80 }],
        resource_type: [{ value: "microsoft.web/sites", count: 80 }] },
    },
    pagination: { offset: 25, limit: 25, total: 80, next_offset: 50 },
    evidence: [], warnings: [],
  };
}

describe("published inventory asset exploration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = "";
    mocks.scope = { subscription: ["sub-a"] };
    mocks.resources.mockResolvedValue(collection());
    mocks.asset.mockResolvedValue({
      data: { resource: { ...collection().data.resources[0], observed_at: "2026-10-16T06:00:00Z",
        containment: { management_group_id: null, subscription_id: "/subscriptions/sub-a", resource_group_id: "/subscriptions/sub-a/resourcegroups/rg" } },
      generation_id: "generation-2", query_version: "query-v1" },
      evidence: [], warnings: [],
    });
  });

  it("restores server filters/page, shows full authorized facets, and makes exact asset links", async () => {
    mocks.query = "family=paas&page=2&q=prod";
    render(<InventoryAssetsPage />);
    await screen.findByRole("link", { name: "Production app" });
    expect(mocks.resources).toHaveBeenCalledWith(mocks.scope, 25, 25, {
      q: "prod", family: "paas", resource_type: "", resource_group: "",
    });
    expect(screen.getByRole("option", { name: "paas (80)" })).toBeInTheDocument();
    expect(screen.getByText(/80 matching observations.*80 authorized observations/)).toBeInTheDocument();
    const target = new URL(screen.getByRole("link", { name: "Production app" }).getAttribute("href")!, "http://test");
    expect(target.searchParams.get("resource_id")).toBe(resourceId);
    expect(target.searchParams.get("subscription")).toBe("sub-a");
  });

  it("updates canonical query state, resets paging/selection, and restores browser history", async () => {
    mocks.query = "page=2&resource_id=previous";
    const view = render(<InventoryAssetsPage />);
    await screen.findByRole("link", { name: "Production app" });
    fireEvent.change(screen.getByLabelText("Family"), { target: { value: "paas" } });
    expect(mocks.push).toHaveBeenCalledWith("/inventory/assets?subscription=sub-a&family=paas");
    mocks.query = "q=restored&page=3";
    view.rerender(<InventoryAssetsPage />);
    await waitFor(() => expect(mocks.resources).toHaveBeenLastCalledWith(mocks.scope, 50, 25, expect.objectContaining({ q: "restored" })));
    expect(screen.getByLabelText("Search asset")).toHaveValue("restored");
    expect(screen.queryByRole("region", { name: "Exact inventory asset" })).not.toBeInTheDocument();
  });

  it("resolves a bookmarked exact resource independently of the list and leaves missing facts unreported", async () => {
    mocks.query = new URLSearchParams({ resource_id: resourceId }).toString();
    mocks.resources.mockResolvedValue({ ...collection(), data: { ...collection().data, resources: [] } });
    render(<InventoryAssetsPage />);
    await screen.findByRole("heading", { name: "Production app" });
    expect(mocks.asset).toHaveBeenCalledWith(resourceId, mocks.scope);
    expect(screen.getByText(/not a live resource-health assessment/)).toBeInTheDocument();
    expect(screen.getAllByText("Not reported").length).toBeGreaterThan(3);
    expect(within(screen.getByRole("region", { name: "Exact inventory asset" })).getByText(/Query contract: query-v1/)).toBeInTheDocument();
  });

  it("withholds old asset facts immediately when current scope changes", async () => {
    mocks.query = new URLSearchParams({ resource_id: resourceId }).toString();
    const view = render(<InventoryAssetsPage />);
    await screen.findByRole("heading", { name: "Production app" });
    mocks.scope = { subscription: ["sub-b"] };
    mocks.asset.mockReturnValue(new Promise(() => {}));
    mocks.resources.mockReturnValue(new Promise(() => {}));
    view.rerender(<InventoryAssetsPage />);
    expect(screen.queryByRole("heading", { name: "Production app" })).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.asset).toHaveBeenLastCalledWith(resourceId, { subscription: ["sub-b"] }));
  });

  it("makes invalid bookmarks explicit without issuing reads", () => {
    mocks.query = new URLSearchParams({ resource_id: "bad\u0000" }).toString();
    render(<InventoryAssetsPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported inventory bookmark");
    expect(mocks.resources).not.toHaveBeenCalled();
    expect(mocks.asset).not.toHaveBeenCalled();
  });

  it("retries an unchanged query after a visible provider failure", async () => {
    mocks.resources.mockRejectedValueOnce(new Error("Published inventory unavailable"));
    render(<InventoryAssetsPage />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Apply search" }));
    await screen.findByRole("link", { name: "Production app" });
    expect(mocks.resources).toHaveBeenCalledTimes(2);
  });
});
