import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NetworkFindingReview } from "@/lib/types";
import { NetworkReviewContext } from "./NetworkReviewContext";

const api = vi.hoisted(() => ({ review: vi.fn() }));
vi.mock("@/lib/services", () => ({ networkApi: api }));
const scope = { subscription: ["sub-a", "sub-b"] };
const reference = { kind: "gap" as const, finding_id: "gap-a", reviewed_digest: "a".repeat(64) };
const review: NetworkFindingReview = {
  ...reference, title: "Missing subnet control", severity: "high", category: "inspection",
  detail: "Current source finding", recommendation: "Review the intended subnet control.",
  resource_ids: ["/subscriptions/sub-a/subnet/a"], basis: "configuration", flow_log_state: "not_ingested",
  source_observed_at: "", scope, policy_digest: "b".repeat(64), source_finding_digest: "c".repeat(64),
};

describe("Exact reauthorized Network review context", () => {
  beforeEach(() => { vi.clearAllMocks(); api.review.mockResolvedValue({ data: review }); });

  it("reauthorizes the exact reference and shows evidence limits without a write", async () => {
    const ready = vi.fn();
    render(<NetworkReviewContext scope={scope} reference={reference} onReady={ready} />);
    await screen.findByText(review.title);
    expect(ready).toHaveBeenNthCalledWith(1, null);
    expect(ready).toHaveBeenLastCalledWith(review);
    expect(api.review).toHaveBeenCalledWith(scope, reference, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText(/Source observed: Not reported/)).toBeInTheDocument();
    expect(screen.getByText(/does not generate a fix/)).toBeInTheDocument();
    const back = new URL(screen.getByRole("link", { name: "Return to current Network findings" }).getAttribute("href")!, "http://127.0.0.1");
    expect(back.searchParams.getAll("subscription")).toEqual(["sub-a", "sub-b"]);
  });

  it("withholds context on source drift and retries only the exact reference", async () => {
    api.review.mockRejectedValueOnce(new Error("Finding evidence changed"));
    const ready = vi.fn();
    render(<NetworkReviewContext scope={scope} reference={reference} onReady={ready} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Finding evidence changed.*withheld/);
    expect(ready).not.toHaveBeenCalledWith(review);
    fireEvent.click(screen.getByRole("button", { name: "Retry exact Network evidence" }));
    await screen.findByText(review.title);
    expect(api.review).toHaveBeenCalledTimes(2);
    expect(ready).toHaveBeenLastCalledWith(review);
  });

  it("aborts an unmounted source acquisition and ignores its late response", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.review.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const ready = vi.fn();
    const view = render(<NetworkReviewContext scope={scope} reference={reference} onReady={ready} />);
    await waitFor(() => expect(api.review).toHaveBeenCalledTimes(1));
    const signal: AbortSignal = api.review.mock.calls[0][2].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ data: review }));
    expect(ready).toHaveBeenCalledTimes(1);
    expect(ready).toHaveBeenCalledWith(null);
  });
});
