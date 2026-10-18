import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Envelope } from "@/lib/types";
import { useExposureSection } from "./useExposureSection";

const receipt: Envelope<{ items: string[] }> = {
  data: { items: ["retained"] }, scope: {}, evidence: [], warnings: [],
};

describe("Exposure section acquisition prerequisites", () => {
  it("defers acquisition and synchronously hides retained data when disabled", async () => {
    const load = vi.fn().mockResolvedValue(receipt);
    const view = renderHook(({ enabled }) => useExposureSection({ queryKey: "one", enabled, load }), { initialProps: { enabled: false } });
    expect(load).not.toHaveBeenCalled();
    view.rerender({ enabled: true });
    await waitFor(() => expect(view.result.current.data).toEqual(receipt.data));
    view.rerender({ enabled: false });
    expect(view.result.current.data).toBeNull();
    expect(view.result.current.status).toBe("loading");
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("aborts an in-flight acquisition when its prerequisite disappears", async () => {
    let resolve!: (value: typeof receipt) => void;
    const load = vi.fn().mockImplementation(() => new Promise(done => { resolve = done; }));
    const view = renderHook(({ enabled }) => useExposureSection({ queryKey: "one", enabled, load }), { initialProps: { enabled: true } });
    const signal = load.mock.calls[0][0].signal;
    view.rerender({ enabled: false });
    expect(signal.aborted).toBe(true);
    await act(async () => { resolve(receipt); });
    expect(view.result.current.data).toBeNull();
  });
});
