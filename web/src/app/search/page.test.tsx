import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  scope: {} as ScopeSelection,
  query: "",
}));
vi.mock("@/lib/services", () => ({
  contextApi: { search: mocks.search }, SUPPORTED_SEARCH_PHRASES: [],
}));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: mocks.scope }) }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
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
  });

  it("ignores older results when a newer search completes first", async () => {
    let resolveOld!: (value: ReturnType<typeof result>) => void;
    mocks.search.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    render(<SearchPage />);
    const input = screen.getByRole("textbox", { name: "Operational search intent" });
    fireEvent.change(input, { target: { value: "old" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "current" } });
    fireEvent.keyDown(input, { key: "Enter" });
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
    await waitFor(() => expect(mocks.search).toHaveBeenLastCalledWith("second", { subscription: ["sub-b"] }));
    expect(await screen.findByText("Scoped search unavailable")).toBeInTheDocument();
    expect(screen.queryByText("current result")).not.toBeInTheDocument();
  });
});
