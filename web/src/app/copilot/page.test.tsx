import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  ask: vi.fn(), scope: {} as ScopeSelection, history: vi.fn(), receipt: vi.fn(), query: "",
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
  copilotApi: { retainedHistory: mocks.history, requestReceipt: mocks.receipt },
}));
import CopilotPage from "./page";

describe("Copilot scope continuity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/copilot");
    mocks.scope = {};
    mocks.query = "";
    mocks.continuity = null;
    mocks.history.mockResolvedValue({ data: { thread_id: `thr-${"a".repeat(32)}`, thread_revision: 1, durability: "durable", observation_status: "historical", continuation_scope_match: true, turns: [] } });
  });

  it("retries only the captured original question and exact key, never an edited draft or new admission", async () => {
    mocks.ask.mockRejectedValueOnce(new Error("Response lost")).mockRejectedValueOnce(new Error("Already accepted"));
    render(<CopilotPage />);
    fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
    expect(await screen.findByText("Request outcome unconfirmed")).toBeVisible();
    const requestKey = mocks.ask.mock.calls[0][2].requestKey;
    expect(requestKey).toMatch(/^req-[0-9]{13}-[a-f0-9]{32}$/);
    expect(new URL(window.location.href).searchParams.get("request_key")).toBe(requestKey);
    fireEvent.change(screen.getByRole("textbox", { name: "Copilot question" }), { target: { value: "Edited draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Retry original question with same request key" }));
    expect(await screen.findByText("Already accepted")).toBeVisible();
    expect(mocks.ask.mock.calls[1][0]).toBe("Review current evidence");
    expect(mocks.ask.mock.calls[1][2].requestKey).toBe(requestKey);
    expect(mocks.receipt).not.toHaveBeenCalled();
  });
  it("selects authorized history without submitting, then explicitly appends and preserves the pinned bookmark", async () => {
    const threadId = `thr-${"a".repeat(32)}`;
    mocks.query = `?thread_id=${threadId}&thread_revision=1`;
    render(<CopilotPage />);
    const select = await screen.findByRole("button", { name: "Continue from reviewed revision 1" });
    expect(mocks.ask).not.toHaveBeenCalled();
    fireEvent.click(select);
    expect(screen.getByRole("textbox", { name: "Copilot question" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
    expect(mocks.ask).not.toHaveBeenCalled();
    mocks.history.mockResolvedValue({ data: { thread_id: threadId, thread_revision: 2, durability: "durable", observation_status: "historical", turns: [] } });
    mocks.ask.mockImplementationOnce((_question, _scope, options) => Promise.resolve({ data: { request_key: options.requestKey, threadId, threadRevision: 2, narration: { text: "Selected thread result" } } }));
    fireEvent.click(screen.getByRole("button", { name: "Ask Copilot" }));
    expect(await screen.findByText("Selected thread result")).toBeVisible();
    expect(mocks.ask.mock.calls[0][2].continuation).toEqual({ threadId, threadRevision: 1 });
    expect(new URL(window.location.href).searchParams.get("thread_id")).toBe(threadId);
    expect(new URL(window.location.href).searchParams.get("thread_revision")).toBe("1");
    expect(new URL(window.location.href).searchParams.has("request_key")).toBe(false);
  });
  it("preserves the selected target when explicitly retrying an interrupted continuation", async () => {
    const threadId = `thr-${"a".repeat(32)}`;
    mocks.query = `?thread_id=${threadId}&thread_revision=1`;
    mocks.ask.mockRejectedValue(new Error("Lost response"));
    render(<CopilotPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Continue from reviewed revision 1" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Copilot question" }), { target: { value: "New scoped turn" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask Copilot" }));
    expect(await screen.findByText("Request outcome unconfirmed")).toBeVisible();
    const options = mocks.ask.mock.calls[0][2];
    fireEvent.click(screen.getByRole("button", { name: "Retry original question with same request key" }));
    await act(async () => {});
    expect(mocks.ask.mock.calls[1][2]).toMatchObject({ requestKey: options.requestKey, continuation: { threadId, threadRevision: 1 } });
  });

  it("reloads an exact request bookmark without polling, submission or restoring a question", async () => {
    const key = `req-1800000000000-${"a".repeat(32)}`;
    mocks.query = `?request_key=${key}&subscription=sub-a`;
    mocks.receipt.mockResolvedValue({ data: { request_key: key, durability: "durable", status: "completed", thread_id: `thr-${"b".repeat(32)}`, thread_revision: 3 } });
    render(<CopilotPage />);
    expect(screen.getByText("Request outcome unconfirmed")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Copilot question" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Ask Copilot" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Retry original question with same request key" })).not.toBeInTheDocument();
    expect(mocks.ask).not.toHaveBeenCalled();
    expect(mocks.receipt).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check accepted request" }));
    expect(await screen.findByRole("link", { name: "Review completed request history" })).toHaveAttribute("href", `/copilot?subscription=sub-a&thread_id=thr-${"b".repeat(32)}&thread_revision=3`);
  });

  it("clears the recovery bookmark only after a confirmed response or deliberate new question acknowledgment", async () => {
    mocks.ask.mockImplementationOnce((_question, _scope, options) => Promise.resolve({ data: { request_key: options.requestKey, threadId: `thr-${"a".repeat(32)}`, threadRevision: 1, narration: { text: "Confirmed answer" } } }));
    render(<CopilotPage />);
    fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
    expect(await screen.findByText("Confirmed answer")).toBeVisible();
    expect(new URL(window.location.href).searchParams.has("request_key")).toBe(false);
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

      it.each(["?request_key=bad", "?request_key=", `?request_key=req-1800000000000-${"a".repeat(32)}&request_key=req-1800000000000-${"b".repeat(32)}`, "?thread_id=bad", `?thread_id=thr-${"a".repeat(32)}&thread_id=thr-${"b".repeat(32)}`, "?thread_id=&subscription=sub-a", "?thread_revision=1", `?thread_id=thr-${"a".repeat(32)}&thread_revision=0`, `?thread_id=thr-${"a".repeat(32)}&thread_revision=1&thread_revision=2`])("rejects malformed or duplicate bookmark before any request: %s", query => {
        mocks.query = query;
        render(<CopilotPage />);
        expect(screen.getByText("Copilot bookmark unavailable")).toBeVisible();
        expect(mocks.ask).not.toHaveBeenCalled();
        expect(mocks.history).not.toHaveBeenCalled();
      });

      it("passes exact reviewed revision to historical reading", async () => {
        mocks.query = `?thread_id=thr-${"a".repeat(32)}&thread_revision=1`;
        render(<CopilotPage />);
        expect(await screen.findByText("No completed turns retained")).toBeVisible();
        expect(mocks.history).toHaveBeenCalledWith(`thr-${"a".repeat(32)}`, {}, { signal: expect.any(AbortSignal), expectedRevision: 1 });
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
        mocks.ask.mockImplementationOnce((_question, _scope, options) => Promise.resolve({ data: { request_key: options.requestKey, threadId, threadRevision: 1, narration: { text: "Confirmed answer" } } }));
        render(<CopilotPage />);
        fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
        expect(await screen.findByText("Confirmed answer")).toBeVisible();
        expect(accept).toHaveBeenCalledWith({ threadId, threadRevision: 1 }, 3);
      });
      it("keeps recovery pinned when a response does not confirm the exact admitted key", async () => {
        mocks.ask.mockResolvedValueOnce({ data: { request_key: "different", threadId: `thr-${"a".repeat(32)}`, threadRevision: 1, narration: { text: "Unconfirmed response" } } });
        render(<CopilotPage />);
        fireEvent.click(screen.getByRole("button", { name: /Review current evidence/ }));
        expect(await screen.findByText("Request outcome unconfirmed")).toBeVisible();
        expect(screen.queryByText("Unconfirmed response")).not.toBeInTheDocument();
        expect(new URL(window.location.href).searchParams.get("request_key")).toMatch(/^req-/);
      });
});
