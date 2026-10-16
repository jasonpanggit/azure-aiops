import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  ask: vi.fn(), scope: {} as ScopeSelection, history: vi.fn(), query: "",
  continuity: null as null | { thread: { threadId: string; threadRevision: number } | null; generation: number; acceptServerState: ReturnType<typeof vi.fn> },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(mocks.query) }));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope: mocks.scope }) }));
vi.mock("@/lib/copilot/thread-context", () => ({ useOptionalThreadContinuity: () => mocks.continuity }));
vi.mock("@/lib/services", () => ({
  askCanonicalInvestigation: mocks.ask,
  toCanonicalInvestigationView: (value: unknown) => value,
  ROOT_COPILOT_SESSION: "root",
  SUPPORTED_SEARCH_PHRASES: ["Review current evidence"],
  copilotApi: { retainedHistory: mocks.history },
}));
import CopilotPage from "./page";

describe("Copilot scope continuity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.scope = {};
    mocks.query = "";
    mocks.continuity = null;
    mocks.history.mockResolvedValue({ data: { thread_id: `thr-${"a".repeat(32)}`, thread_revision: 1, durability: "durable", observation_status: "historical", turns: [] } });
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

      it("uses q only as a draft, never automatically submits on reload or scope replacement", () => {
        mocks.query = "?q=Review+payroll";
        const view = render(<CopilotPage />);
        expect(screen.getByRole("textbox", { name: "Copilot question" })).toHaveValue("Review payroll");
        mocks.scope = { owner: ["new-owner"] };
        view.rerender(<CopilotPage />);
        expect(mocks.ask).not.toHaveBeenCalled();
      });

      it("aborts only the wait, preserves the question and requires explicit recovery before another request", async () => {
        let resolve!: (value: unknown) => void;
        mocks.ask.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
        render(<CopilotPage />);
        fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
        const signal = mocks.ask.mock.calls[0][2].signal as AbortSignal;
        fireEvent.click(screen.getByRole("button", { name: "Stop waiting for this response" }));
        expect(signal.aborted).toBe(true);
        expect(screen.getByRole("textbox", { name: "Copilot question" })).toHaveValue("Review current evidence");
        expect(screen.getByText(/does not cancel provider work/)).toBeVisible();
        expect(screen.getByRole("button", { name: "Ask Copilot" })).toBeDisabled();
        await act(async () => resolve({ data: { narration: { text: "Late unconfirmed answer" } } }));
        expect(screen.queryByText("Late unconfirmed answer")).not.toBeInTheDocument();
        expect(mocks.ask).toHaveBeenCalledTimes(1);
        fireEvent.click(screen.getByRole("button", { name: /I reviewed the outcome/ }));
        expect(screen.getByRole("button", { name: "Ask Copilot" })).toBeEnabled();
        expect(mocks.ask).toHaveBeenCalledTimes(1);
      });

      it("shows a failed transport as an unknown outcome instead of retrying", async () => {
        mocks.ask.mockRejectedValueOnce(new Error("Lost response"));
        render(<CopilotPage />);
        fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
        expect(await screen.findByText("Request outcome unconfirmed")).toBeVisible();
        expect(screen.getByText("Lost response")).toBeVisible();
        expect(screen.getByRole("button", { name: "Ask Copilot" })).toBeDisabled();
        expect(mocks.ask).toHaveBeenCalledTimes(1);
      });

      it("pins exact scope-authorized history as review only, never attaching or submitting", async () => {
        const threadId = `thr-${"a".repeat(32)}`;
        mocks.query = `?thread_id=${threadId}&subscription=sub-a&q=Do+not+submit`;
        mocks.continuity = { thread: { threadId: `thr-${"b".repeat(32)}`, threadRevision: 2 }, generation: 0, acceptServerState: vi.fn() };
        render(<CopilotPage />);
        expect(await screen.findByText("No completed turns retained")).toBeVisible();
        expect(mocks.history).toHaveBeenCalledWith(threadId, { subscription: ["sub-a"] }, { signal: expect.any(AbortSignal) });
        expect(screen.getByRole("textbox", { name: "Copilot question" })).toBeDisabled();
        expect(screen.getByRole("textbox", { name: "Copilot question" })).toHaveValue("");
        expect(screen.getByRole("link", { name: "Leave historical review" })).toHaveAttribute("href", "/copilot?subscription=sub-a");
        expect(mocks.ask).not.toHaveBeenCalled();
        expect(mocks.continuity.acceptServerState).not.toHaveBeenCalled();
      });

      it.each(["?thread_id=bad", `?thread_id=thr-${"a".repeat(32)}&thread_id=thr-${"b".repeat(32)}`, "?thread_id=&subscription=sub-a"])("rejects malformed or duplicate bookmark before any request: %s", query => {
        mocks.query = query;
        render(<CopilotPage />);
        expect(screen.getByText("Copilot bookmark unavailable")).toBeVisible();
        expect(mocks.ask).not.toHaveBeenCalled();
        expect(mocks.history).not.toHaveBeenCalled();
      });

      it("rejects bookmarked scope outside selected scope", () => {
        mocks.scope = { subscription: ["sub-a"] };
        mocks.query = `?thread_id=thr-${"a".repeat(32)}&subscription=sub-b`;
        render(<CopilotPage />);
        expect(screen.getByText("Copilot bookmark unavailable")).toBeVisible();
        expect(mocks.history).not.toHaveBeenCalled();
      });

      it("discards and aborts pending answers after continuity generation reset", async () => {
        let resolve!: (value: unknown) => void;
        const accept = vi.fn().mockReturnValue(true);
        mocks.continuity = { thread: null, generation: 0, acceptServerState: accept };
        mocks.ask.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
        const view = render(<CopilotPage />);
        fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
        const signal = mocks.ask.mock.calls[0][2].signal as AbortSignal;
        mocks.continuity = { ...mocks.continuity, generation: 1 };
        view.rerender(<CopilotPage />);
        expect(signal.aborted).toBe(true);
        await act(async () => resolve({ data: { threadId: `thr-${"a".repeat(32)}`, threadRevision: 1, narration: { text: "Old generation answer" } } }));
        expect(accept).not.toHaveBeenCalled();
        expect(screen.queryByText("Old generation answer")).not.toBeInTheDocument();
      });

      it("accepts a completed thread only with its submitted continuity generation", async () => {
        const accept = vi.fn().mockReturnValue(true);
        const threadId = `thr-${"a".repeat(32)}`;
        mocks.continuity = { thread: null, generation: 3, acceptServerState: accept };
        mocks.ask.mockResolvedValueOnce({ data: { threadId, threadRevision: 1, narration: { text: "Confirmed answer" } } });
        render(<CopilotPage />);
        fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
        expect(await screen.findByText("Confirmed answer")).toBeVisible();
        expect(accept).toHaveBeenCalledWith({ threadId, threadRevision: 1 }, 3);
      });
});
