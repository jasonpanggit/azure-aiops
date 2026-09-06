import { beforeEach, describe, expect, it, vi } from "vitest";

const redirect = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ redirect }));

import VulnerabilitiesPage from "./page";

describe("legacy vulnerability collection route", () => {
  beforeEach(() => {
    redirect.mockReset();
  });

  it("redirects to Patch priorities while retaining only canonical collection context", () => {
    VulnerabilitiesPage({
      searchParams: {
        subscription: "sub-1",
        q: "kernel",
        severity: "critical",
        sort_by: "severity",
        sort_direction: "asc",
        page_size: "25",
        row: "exposure-1",
        scroll: "640",
        generation: "generation-25",
        cursor: "must-not-cross-the-detail-boundary",
        origin: "https://evil.example/steal",
        unsafe: "discard-me",
      },
    });

    expect(redirect).toHaveBeenCalledTimes(1);
    const destination = new URL(
      redirect.mock.calls[0][0],
      "https://aiops.example",
    );
    expect(destination.pathname).toBe("/exposure/patch-priorities");
    expect(destination.searchParams.get("subscription")).toBe("sub-1");
    expect(destination.searchParams.get("q")).toBe("kernel");
    expect(destination.searchParams.get("severity")).toBe("critical");
    expect(destination.searchParams.get("sort_by")).toBe("severity");
    expect(destination.searchParams.get("sort_direction")).toBe("asc");
    expect(destination.searchParams.get("page_size")).toBe("25");
    expect(destination.searchParams.get("row")).toBe("exposure-1");
    expect(destination.searchParams.get("scroll")).toBe("640");
    expect(destination.searchParams.get("generation")).toBe("generation-25");
    expect(destination.searchParams.has("cursor")).toBe(false);
    expect(destination.searchParams.has("origin")).toBe(false);
    expect(destination.searchParams.has("unsafe")).toBe(false);
  });
});
