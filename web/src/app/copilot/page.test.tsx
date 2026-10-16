import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  ask: vi.fn(), scope: {} as ScopeSelection,
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: mocks.scope }) }));
vi.mock("@/lib/copilot/thread-context", () => ({ useOptionalThreadContinuity: () => null }));
vi.mock("@/lib/services", () => ({
  askCanonicalInvestigation: mocks.ask,
  toCanonicalInvestigationView: (value: unknown) => value,
  ROOT_COPILOT_SESSION: "root",
  SUPPORTED_SEARCH_PHRASES: ["Review current evidence"],
}));
import CopilotPage from "./page";

describe("Copilot scope continuity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.scope = {};
  });

  it("does not publish a late response into a newly selected scope", async () => {
    let resolve!: (value: unknown) => void;
    mocks.ask.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    const view = render(<CopilotPage />);
    fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
    mocks.scope = { subscription: ["sub-b"] };
    view.rerender(<CopilotPage />);
    await act(async () => {
      resolve({
        data: { narration: { text: "Previous scope response", model: "test" } },
        evidence: [], warnings: [],
      });
    });
    expect(screen.queryByText("Previous scope response")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Review current evidence/ })).toBeEnabled();
  });
});
