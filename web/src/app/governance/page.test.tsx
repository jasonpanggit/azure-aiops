import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  scope: {} as ScopeSelection,
  accessReview: vi.fn(),
  settings: vi.fn(),
}));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: mocks.scope }) }));
vi.mock("@/lib/services", () => ({
  governanceApi: {
    accessReviewKinds: async () => ({ data: { audiences: ["security"] } }),
    exportKinds: async () => ({ data: { kinds: [] } }),
    settings: mocks.settings,
    accessReview: mocks.accessReview,
  },
}));
vi.mock("@/lib/copilot/page-adapters", () => ({
  buildGovernanceCopilotContext: () => ({
    snapshot: {}, requestedScope: {}, starterQuestions: [],
  }),
}));
vi.mock("@/components/ui/CopilotInsights", () => ({ CopilotInsights: () => null }));
vi.mock("@/components/ui/CopilotDrawer", () => ({ CopilotDrawer: () => null }));

import GovernancePage from "./page";

describe("Governance pack scope continuity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.scope = {};
    mocks.settings.mockResolvedValue({ data: { roles: [] }, evidence: [], warnings: [] });
  });

  it("does not publish a pack generated for a previous scope", async () => {
    let resolve!: (value: unknown) => void;
    mocks.accessReview.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    const view = render(<GovernancePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate" }));
    mocks.scope = { subscription: ["sub-b"] };
    view.rerender(<GovernancePage />);
    await act(async () => { resolve({ data: { marker: "previous scope pack" } }); });
    expect(screen.queryByText("previous scope pack")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate" })).toBeEnabled();
  });
});
