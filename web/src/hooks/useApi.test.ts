import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useApi } from "./useApi";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe("useApi refetch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns a stable refetch handle that invokes the latest loader once", async () => {
    const firstLoader = vi.fn().mockResolvedValue("first");
    const secondLoader = vi.fn().mockResolvedValue("second");
    const { result, rerender } = renderHook(
      ({ loader }: { loader: () => Promise<string> }) => useApi(loader, []),
      { initialProps: { loader: firstLoader } },
    );
    await act(async () => {
      await Promise.resolve();
    });
    const refetch = result.current.refetch;

    rerender({ loader: secondLoader });
    expect(result.current.refetch).toBe(refetch);

    act(() => {
      result.current.refetch();
      vi.advanceTimersByTime(400);
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(firstLoader).toHaveBeenCalledTimes(1);
    expect(secondLoader).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe("second");
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("coalesces two refetch requests inside the 400ms window", async () => {
    const loader = vi.fn().mockResolvedValue("value");
    const { result } = renderHook(() => useApi(loader, []));
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.refetch();
      vi.advanceTimersByTime(250);
      result.current.refetch();
      vi.advanceTimersByTime(399);
    });
    expect(loader).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("retains loaded data while a refetch is in flight", async () => {
    const pending = deferred<string>();
    const loader = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce("loaded")
      .mockImplementationOnce(() => pending.promise);
    const { result } = renderHook(() => useApi(loader, []));
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.data).toBe("loaded");

    act(() => {
      result.current.refetch();
      vi.advanceTimersByTime(400);
    });

    expect(loader).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe("loaded");
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(true);

    await act(async () => {
      pending.resolve("refreshed");
      await pending.promise;
    });
    expect(result.current.data).toBe("refreshed");
    expect(result.current.loading).toBe(false);
  });

  it("clears records immediately when request dependencies change", async () => {
    const narrow = deferred<string>();
    const loader = vi
      .fn<(scope: string) => Promise<string>>()
      .mockResolvedValueOnce("broad-scope-record")
      .mockImplementationOnce(() => narrow.promise);
    const { result, rerender } = renderHook(
      ({ scope }: { scope: string }) =>
        useApi(() => loader(scope), [scope]),
      { initialProps: { scope: "broad" } },
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.data).toBe("broad-scope-record");

    rerender({ scope: "narrow" });

    expect(loader).toHaveBeenLastCalledWith("narrow");
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);

    await act(async () => {
      narrow.resolve("narrow-scope-record");
      await narrow.promise;
    });
    expect(result.current.data).toBe("narrow-scope-record");
  });

  it("retains loaded data for an explicitly soft dependency change but still clears it across scope", async () => {
    const full = deferred<string>();
    const narrow = deferred<string>();
    const loader = vi
      .fn<(scope: string, detail: string) => Promise<string>>()
      .mockResolvedValueOnce("broad-summary")
      .mockImplementationOnce(() => full.promise)
      .mockImplementationOnce(() => narrow.promise);
    const { result, rerender } = renderHook(
      ({ scope, detail }: { scope: string; detail: string }) =>
        useApi(() => loader(scope, detail), [scope, detail], {
          retainDataOnDependencyChange: (previous, next) =>
            previous[0] === next[0],
        }),
      { initialProps: { scope: "broad", detail: "summary" } },
    );
    await act(async () => {
      await Promise.resolve();
    });

    rerender({ scope: "broad", detail: "full" });

    expect(result.current.data).toBe("broad-summary");
    expect(result.current.loading).toBe(true);

    await act(async () => {
      full.resolve("broad-full");
      await full.promise;
    });
    rerender({ scope: "narrow", detail: "full" });

    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);

    await act(async () => {
      narrow.resolve("narrow-full");
      await narrow.promise;
    });
  });

  it("aborts the active request and retains the last successful data when cancelled", async () => {
    let activeSignal: AbortSignal | undefined;
    const pending = deferred<string>();
    const loader = vi
      .fn<(signal?: AbortSignal) => Promise<string>>()
      .mockResolvedValueOnce("summary")
      .mockImplementationOnce((signal) => {
        activeSignal = signal;
        return pending.promise;
      });
    const { result } = renderHook(() => useApi(loader, []));
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.refetch();
      vi.advanceTimersByTime(400);
    });
    expect(activeSignal?.aborted).toBe(false);

    act(() => result.current.cancel());

    expect(activeSignal?.aborted).toBe(true);
    expect(result.current.data).toBe("summary");
    expect(result.current.loading).toBe(false);
  });
});
