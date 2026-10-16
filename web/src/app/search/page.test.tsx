import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  scope: {} as ScopeSelection,
  query: "",
  push: vi.fn(),
  capabilities: vi.fn(),
}));
vi.mock("@/lib/services", () => ({
  contextApi: { search: mocks.search, searchCapabilities: mocks.capabilities },
}));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: mocks.scope }) }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
  useRouter: () => ({ push: mocks.push }),
}));
import SearchPage from "./page";

const result = (name: string) => ({
  data: { results: [{ name, id: name, entity_type: "VirtualMachine" }], count: 1 },
  evidence: [], scope: {}, warnings: [], knowledge_version: "search-test",
});

describe("Scoped operational search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.scope = {};
    mocks.query = "";
    mocks.search.mockResolvedValue(result("current result"));
    mocks.capabilities.mockResolvedValue({ data: {
      live: { state: "configured", can_query: true, phrases: ["show list of VMs"], prerequisite: "Active connection required." },
      semantic: { state: "deferred", can_query: false, phrases: ["production applications"], prerequisite: "Published semantic snapshot required." },
      identity: { state: "configured", prerequisite: "Exact principal identifier required." },
    } });
  });

  it("ignores older results when a newer search completes first", async () => {
    let resolveOld!: (value: ReturnType<typeof result>) => void;
    mocks.search.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    mocks.query = "q=old";
    const view = render(<SearchPage />);
    const input = screen.getByRole("textbox", { name: "Operational search intent" });
    fireEvent.change(input, { target: { value: "current" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mocks.push).toHaveBeenLastCalledWith("/search?q=current", { scroll: false });
    mocks.query = "q=current";
    view.rerender(<SearchPage />);
    expect((await screen.findAllByText("current result")).length).toBeGreaterThan(0);
    await act(async () => { resolveOld(result("stale result")); });
    expect(screen.queryByText("stale result")).not.toBeInTheDocument();
  });

  it("reruns deep links on scope or URL changes and clears old evidence", async () => {
    mocks.query = "q=first";
    const view = render(<SearchPage />);
    expect((await screen.findAllByText("current result")).length).toBeGreaterThan(0);
    mocks.scope = { subscription: ["sub-b"] };
    mocks.query = "q=second";
    mocks.search.mockRejectedValueOnce(new Error("Scoped search unavailable"));
    view.rerender(<SearchPage />);
    await waitFor(() => expect(mocks.search).toHaveBeenLastCalledWith("second", { subscription: ["sub-b"] }, {
      offset: 0, limit: 25, entity_type: "", source: "",
    }));
    expect(await screen.findByText("Scoped search unavailable")).toBeInTheDocument();
    expect(screen.queryByText("current result")).not.toBeInTheDocument();
  });

  it("labels deferred intents before submission and never assumes readiness after failure", async () => {
    const view = render(<SearchPage />);
    expect(await screen.findByRole("button", { name: "production applications" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "show list of VMs" }));
    expect(mocks.push).toHaveBeenLastCalledWith("/search?q=show+list+of+VMs", { scroll: false });
    mocks.scope = { subscription: ["sub-b"] };
    mocks.capabilities.mockRejectedValueOnce(new Error("Readiness failed"));
    view.rerender(<SearchPage />);
    expect(await screen.findByText("Readiness failed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "show list of VMs" })).not.toBeInTheDocument();
  });

  it("uses server facets/pagination in bookmarkable URLs and reruns on browser navigation", async () => {
    mocks.query = "q=first&entity_type=VirtualMachine&source=ARG&offset=25";
    mocks.search.mockResolvedValue({
      ...result("row"), data: { ...result("row").data,
        truncated: true, represented_count: 60,
        facets: { entity_type: { VirtualMachine: 60 }, source: { ARG: 60 } },
      },
      pagination: { offset: 25, limit: 25, total: 60, next_offset: 50 },
    });
    const view = render(<SearchPage />);
    expect(await screen.findByText("60 matching authorized records")).toBeInTheDocument();
    expect(screen.getByText(/source result is truncated/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next results" }));
    expect(mocks.push).toHaveBeenLastCalledWith("/search?q=first&entity_type=VirtualMachine&source=ARG&offset=50", { scroll: false });
    fireEvent.change(screen.getByRole("combobox", { name: "Entity type" }), { target: { value: "" } });
    expect(mocks.push).toHaveBeenLastCalledWith("/search?q=first&source=ARG", { scroll: false });
    mocks.query = "q=previous";
    view.rerender(<SearchPage />);
    await waitFor(() => expect(mocks.search).toHaveBeenLastCalledWith("previous", {}, {
      offset: 0, limit: 25, entity_type: "", source: "",
    }));
  });

  it("resubmits an unchanged query instead of waiting for a URL change that will never happen", async () => {
    mocks.query = "q=retry";
    mocks.search.mockRejectedValueOnce(new Error("Temporary provider failure"));
    render(<SearchPage />);
    await screen.findByText("Temporary provider failure");
    const attempts = mocks.search.mock.calls.length;
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Operational search intent" }), { key: "Enter" });
    expect((await screen.findAllByText("current result")).length).toBeGreaterThan(0);
    expect(mocks.search).toHaveBeenCalledTimes(attempts + 1);
    expect(mocks.push).not.toHaveBeenCalled();
  });
});
