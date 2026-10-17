import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import { CopilotRequestRecovery } from "./CopilotRequestRecovery";

const mocks = vi.hoisted(() => ({ receipt: vi.fn() }));
vi.mock("@/lib/services", () => ({ copilotApi: { requestReceipt: mocks.receipt } }));
const key = `req-1800000000000-${"a".repeat(32)}`, thread = `thr-${"b".repeat(32)}`;
const completed = { data: { request_key: key, status: "completed", durability: "durable", thread_id: thread, thread_revision: 4 } };
describe("Accepted Copilot request recovery", () => {
  beforeEach(() => { vi.resetAllMocks(); mocks.receipt.mockResolvedValue(completed); });
  it("checks only explicitly and reviews exact historical revision under all nine scope dimensions", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(name => [name, [`${name}-a`, `${name}-b`]]));
    render(<CopilotRequestRecovery requestKey={key} scope={scope} />);
    expect(mocks.receipt).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check accepted request" }));
    const link = await screen.findByRole("link", { name: "Review completed request history" });
    const href = new URL(link.getAttribute("href")!, "https://local");
    expect(href.searchParams.get("thread_id")).toBe(thread);
    expect(href.searchParams.get("thread_revision")).toBe("4");
    for (const name of SCOPE_DIMENSIONS) expect(href.searchParams.getAll(name)).toEqual(scope[name]);
    expect(mocks.receipt).toHaveBeenCalledWith(key, scope, expect.any(AbortSignal));
  });
  it("never equates accepted admission with running, successful, or cancelled work", async () => {
    mocks.receipt.mockResolvedValue({ data: { ...completed.data, status: "accepted_outcome_unconfirmed", thread_id: "", thread_revision: 0 } });
    render(<CopilotRequestRecovery requestKey={key} scope={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Check accepted request" }));
    expect(await screen.findByText("Request accepted; outcome unconfirmed")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Review completed request history" })).not.toBeInTheDocument();
    expect(screen.getByText(/not proof work is currently running or was cancelled/)).toBeVisible();
  });
  it("shows unavailable reads and clears stale links before an explicit reload", async () => {
    render(<CopilotRequestRecovery requestKey={key} scope={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Check accepted request" }));
    expect(await screen.findByRole("link", { name: "Review completed request history" })).toBeVisible();
    mocks.receipt.mockRejectedValueOnce(new Error("Storage unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Reload request receipt" }));
    expect(await screen.findByText("Request receipt unavailable")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Review completed request history" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload request receipt" }));
    expect(await screen.findByRole("link", { name: "Review completed request history" })).toBeVisible();
  });
  it.each([
    { request_key: `${key}wrong` }, { thread_id: "wrong" },
    { thread_revision: 0 }, { thread_revision: 1.5 }, { status: "running" }, { durability: "memory_only" },
  ])("withholds malformed or mismatched completion identity %j", async invalid => {
    mocks.receipt.mockResolvedValue({ data: { ...completed.data, ...invalid } });
    render(<CopilotRequestRecovery requestKey={key} scope={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Check accepted request" }));
    expect(await screen.findByText("Request receipt unavailable")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
  it("aborts and withholds the old-scope receipt after replacement", async () => {
    let finish!: (result: unknown) => void;
    mocks.receipt.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<CopilotRequestRecovery requestKey={key} scope={{ owner: ["a"] }} />);
    fireEvent.click(screen.getByRole("button", { name: "Check accepted request" }));
    const signal = mocks.receipt.mock.calls[0][2] as AbortSignal;
    mocks.receipt.mockResolvedValue({ data: { ...completed.data, status: "accepted_outcome_unconfirmed", thread_id: "", thread_revision: 0 } });
    view.rerender(<CopilotRequestRecovery requestKey={key} scope={{ owner: ["b"] }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => finish(completed));
    expect(await screen.findByText("Request accepted; outcome unconfirmed")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
