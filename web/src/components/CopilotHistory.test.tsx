import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RetainedCopilotHistory } from "@/lib/types";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import { CopilotHistory } from "./CopilotHistory";

const mocks = vi.hoisted(() => ({ read: vi.fn() }));
vi.mock("@/lib/services", () => ({ copilotApi: { retainedHistory: mocks.read } }));
const id = `thr-${"a".repeat(32)}`;
const snapshot: RetainedCopilotHistory = {
  thread_id: id, thread_revision: 2, durability: "memory_only", observation_status: "historical",
  turns: [{ question: "Retained question", status: "ok", observation_status: "historical", retained_at: "2020-01-01T00:00:00+00:00" }],
};
const envelope = (data = snapshot) => ({ data, scope: {}, warnings: [], evidence: [] });
function open() {
  const details = screen.getByText("Retained Copilot history").closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}

describe("Copilot exact historical reads", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.read.mockResolvedValue(envelope()); });

  it("loads only on demand with nine-dimensional current scope and honest historical/storage labels", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(key => [key, [`${key}-a`, `${key}-b`]]));
    render(<CopilotHistory threadId={id} scope={scope} />);
    expect(mocks.read).not.toHaveBeenCalled();
    open();
    expect(await screen.findByRole("heading", { name: "Retained question" })).toBeVisible();
    expect(mocks.read).toHaveBeenCalledWith(id, scope, { signal: expect.any(AbortSignal) });
    expect(screen.getByText(/Memory only; not guaranteed after a restart/)).toBeVisible();
    expect(screen.getByText(/Historical observation; recorded status: ok/)).toBeVisible();
    expect(screen.getByText("2020-01-01T00:00:00+00:00", { selector: "time" })).toBeVisible();
    const href = new URL(screen.getByRole("link", { name: "Open exact historical thread" }).getAttribute("href")!, "http://localhost");
    expect(href.searchParams.get("thread_id")).toBe(id);
    for (const dimension of SCOPE_DIMENSIONS) expect(href.searchParams.getAll(dimension)).toEqual(scope[dimension]);
  });

  it("does not acquire or invent a thread without a handle", () => {
    render(<CopilotHistory threadId="" scope={{}} />);
    open();
    expect(screen.getByText("No retained thread selected")).toBeVisible();
    expect(mocks.read).not.toHaveBeenCalled();
  });

  it("shows exact read error and recovers only on explicit reload", async () => {
    mocks.read.mockRejectedValueOnce(new Error("Thread not found"));
    render(<CopilotHistory threadId={id} scope={{}} pinned />);
    expect(await screen.findByText("Thread not found")).toBeVisible();
    expect(mocks.read).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Reload retained history" }));
    expect(await screen.findByRole("heading", { name: "Retained question" })).toBeVisible();
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });

  it("rejects an envelope for another exact thread", async () => {
    mocks.read.mockResolvedValueOnce(envelope({ ...snapshot, thread_id: `thr-${"b".repeat(32)}` }));
    render(<CopilotHistory threadId={id} scope={{}} pinned />);
    expect(await screen.findByText(/did not match the exact retained historical thread/)).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Retained question" })).not.toBeInTheDocument();
  });

  it("aborts and discards pending reads on scope change", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    mocks.read.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const view = render(<CopilotHistory threadId={id} scope={{ owner: ["old"] }} pinned />);
    const signal = mocks.read.mock.calls[0][2].signal as AbortSignal;
    view.rerender(<CopilotHistory threadId={id} scope={{ owner: ["new"] }} pinned />);
    expect(await screen.findByRole("heading", { name: "Retained question" })).toBeVisible();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(envelope({ ...snapshot, turns: [{ question: "Old scope secret", observation_status: "historical" }] })));
    expect(screen.queryByText("Old scope secret")).not.toBeInTheDocument();
  });

  it("displays restricted turns without inventing question, evidence or source checks", async () => {
    mocks.read.mockResolvedValueOnce(envelope({ ...snapshot, turns: [{ status: "historical_scope_restricted", observation_status: "historical", citations: [], tool_results: [] }] }));
    render(<CopilotHistory threadId={id} scope={{}} pinned />);
    expect(await screen.findByRole("heading", { name: "Historical turn withheld" })).toBeVisible();
    expect(screen.queryByText("Retained question")).not.toBeInTheDocument();
  });
});
