import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RetainedCopilotThreads } from "@/lib/types";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import { CopilotThreadCatalog } from "./CopilotThreadCatalog";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock("@/lib/services", () => ({ copilotApi: { retainedThreads: mocks.list } }));
const id = `thr-${"a".repeat(32)}`;
const catalog: RetainedCopilotThreads = {
  threads: [{ thread_id: id, thread_revision: 3, durability: "durable", question: "Retained question", title_status: "visible" }],
  page: 0, has_more: true, scan_limit_reached: false, order: "storage_listing", durability: "durable",
};
const envelope = (data = catalog) => ({ data, scope: {}, warnings: [], evidence: [] });
function open() {
  const details = screen.getByText("Find my retained conversations").closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}

describe("Owned Copilot thread discovery", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.list.mockResolvedValue(envelope()); });
  it("loads on demand and reopens exact revision with all scope dimensions", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(key => [key, [`${key}-a`, `${key}-b`]]));
    render(<CopilotThreadCatalog scope={scope} />);
    expect(mocks.list).not.toHaveBeenCalled();
    open();
    expect(await screen.findByText("Retained question")).toBeVisible();
    expect(mocks.list).toHaveBeenCalledWith(scope, 0, expect.any(AbortSignal));
    const href = new URL(screen.getByRole("link", { name: `Review conversation ${id}` }).getAttribute("href")!, "https://local");
    expect(href.searchParams.get("thread_id")).toBe(id);
    expect(href.searchParams.get("thread_revision")).toBe("3");
    for (const key of SCOPE_DIMENSIONS) expect(href.searchParams.getAll(key)).toEqual(scope[key]);
  });
  it("pages explicitly, clears earlier records on failure, and reloads independently", async () => {
    render(<CopilotThreadCatalog scope={{}} />);
    open();
    expect(await screen.findByText("Retained question")).toBeVisible();
    mocks.list.mockRejectedValueOnce(new Error("Discovery unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Next storage page" }));
    expect(await screen.findByText("Discovery unavailable")).toBeVisible();
    expect(screen.queryByText("Retained question")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload conversation list" }));
    expect(await screen.findByText("Retained question")).toBeVisible();
    expect(mocks.list).toHaveBeenLastCalledWith({}, 1, expect.any(AbortSignal));
  });
  it("withholds restricted questions and labels empty/scan-boundary honestly", async () => {
    mocks.list.mockResolvedValueOnce(envelope({ ...catalog, threads: [], has_more: false, scan_limit_reached: true, durability: "memory_only" }));
    render(<CopilotThreadCatalog scope={{}} />);
    open();
    expect(await screen.findByText("No authorized threads on this storage page")).toBeVisible();
    expect(screen.getByText("Discovery scan limit reached")).toBeVisible();
    expect(screen.getByText(/Memory only/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Next storage page" })).toBeDisabled();
  });
  it("never renders a withheld question even if a malformed provider includes its text", async () => {
    mocks.list.mockResolvedValueOnce(envelope({ ...catalog, threads: [{ ...catalog.threads[0], title_status: "withheld_or_empty", question: "Must not render" }] }));
    render(<CopilotThreadCatalog scope={{}} />);
    open();
    expect(await screen.findByText(/Question withheld after scope narrowing/)).toBeVisible();
    expect(screen.queryByText("Must not render")).not.toBeInTheDocument();
  });
  it("aborts old scope and discards late private results", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    mocks.list.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const view = render(<CopilotThreadCatalog scope={{ owner: ["old"] }} />);
    open();
    await waitFor(() => expect(mocks.list).toHaveBeenCalledOnce());
    const signal = mocks.list.mock.calls[0][2] as AbortSignal;
    view.rerender(<CopilotThreadCatalog scope={{ owner: ["new"] }} />);
    expect(await screen.findByText("Retained question")).toBeVisible();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(envelope({ ...catalog, threads: [{ ...catalog.threads[0], question: "Old scope secret" }] })));
    expect(screen.queryByText("Old scope secret")).not.toBeInTheDocument();
  });
});
