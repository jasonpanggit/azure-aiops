import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SourceSectionState, formatExposureValue } from "@/components/exposure/SourceSectionState";
import {
  type ExposureSectionResult,
  useExposureSection,
} from "@/hooks/useExposureSection";
import type {
  Envelope,
  ExposureCommonContract,
  ExposureCursorPagination,
} from "@/lib/types";
import scenario from "../../../../../tests/fixtures/exposure_authoritative.json";

interface Rows {
  items: Array<{ id: string; value?: number | null }>;
  total_count: number;
  contract: ExposureCommonContract;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function envelope(
  ids: string[],
  options: {
    state?: "complete" | "healthy-empty" | "partial" | "stale" | "unavailable";
    represented?: number;
    expected?: number;
    total?: number;
    excluded?: number;
    excludedReasons?: string[];
  } = {},
): Envelope<Rows, ExposureCursorPagination> {
  const state = options.state ?? "complete";
  const represented = options.represented ?? ids.length;
  const expected = options.expected ?? represented;
  const total = options.total ?? ids.length;
  const excluded = options.excluded ?? 0;
  return {
    data: {
      items: ids.map((id) => ({ id })),
      total_count: total,
      contract: {
        version: "1.0.0",
        query: {
          scope: { subscription: ["sub-a"] },
          generation: scenario.read_model_generation_id,
          filters: [],
          sort: { field: "priority_score", direction: "desc" },
          target_kind: "all",
        },
        counts: {
          unit: "findings",
          returned: ids.length,
          represented,
          total,
          excluded,
        },
        units: {
          finding_count: "count",
          priority_score: "score",
          secure_score: "percent",
          sla_age: "seconds",
        },
        completeness: {
          state,
          represented,
          expected,
          total,
          excluded,
          excluded_reasons: options.excludedReasons ?? [],
        },
        freshness: {
          state: state === "stale" ? "stale" : "current",
          as_of: "2026-09-06T08:00:00Z",
          source_family: "aum",
          threshold_seconds: 3600,
          thresholds: [{
            source_family: "aum",
            threshold_seconds: 3600,
          }],
        },
        evidence_refs: [{ source_family: "aum", source_id: "finding-1" }],
        deep_link_action: {
          action_id: "open_exposure_detail",
          kind: "deep_link",
          path_field: "detail_path",
          fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
        },
        safe_error: null,
      },
    },
    evidence: [],
    scope: { subscription: ["sub-a"] },
    knowledge_version: scenario.read_model_generation_id,
    pagination: { limit: 50, total, next_cursor: null },
  };
}

function Section({
  sourceName,
  section,
}: {
  sourceName: string;
  section: ExposureSectionResult<Rows>;
}) {
  return (
    <SourceSectionState
      sourceName={sourceName}
      itemLabel="findings"
      state={section}
    >
      {section.data?.items.map((row) => (
        <p key={row.id}>{row.id}</p>
      ))}
    </SourceSectionState>
  );
}

describe("Exposure independent source states", () => {
  it("uses the shared authoritative generation and source-state fixture", () => {
    expect(scenario.read_model_generation_id).toBe("exposure-generation-0001");
    expect(scenario.source_partitions.map((partition) => partition.state)).toEqual(
      expect.arrayContaining([
        "complete",
        "healthy-empty",
        "failed-with-lkg",
        "failed-without-lkg",
      ]),
    );
  });

  it("keeps healthy sibling sections usable when one source fails", async () => {
    const healthy = deferred<Envelope<Rows, ExposureCursorPagination>>();
    const unavailable = deferred<Envelope<Rows, ExposureCursorPagination>>();

    function Harness() {
      const healthySection = useExposureSection({
        queryKey: "sub-a|healthy",
        load: () => healthy.promise,
      });
      const unavailableSection = useExposureSection({
        queryKey: "sub-a|unavailable",
        load: () => unavailable.promise,
      });
      return (
        <>
          <Section sourceName="AUM findings" section={healthySection} />
          <Section sourceName="Container workloads" section={unavailableSection} />
        </>
      );
    }

    render(<Harness />);
    await act(async () => {
      healthy.resolve(envelope(["aum-row-1"]));
      unavailable.reject(new Error("Workspace unavailable"));
    });

    expect(await screen.findByText("aum-row-1")).toBeInTheDocument();
    expect(screen.getByText("Container workloads is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry Container workloads" })).toBeEnabled();
  });

  it("retains last-known-good rows only for the identical authorized scope and query", async () => {
    const refresh = deferred<Envelope<Rows, ExposureCursorPagination>>();
    const load = vi
      .fn()
      .mockResolvedValueOnce(envelope(["retained-row"]))
      .mockReturnValueOnce(refresh.promise);
    const { result, rerender } = renderHook(
      ({ refreshKey }) =>
        useExposureSection({
          queryKey: "sub-a|severity=critical",
          refreshKey,
          load,
        }),
      { initialProps: { refreshKey: 0 } },
    );

    await waitFor(() => expect(result.current.status).toBe("current"));
    rerender({ refreshKey: 1 });

    expect(result.current.data?.items[0].id).toBe("retained-row");
    expect(result.current.refreshing).toBe(true);

    await act(async () => {
      refresh.reject(new Error("Latest refresh failed"));
    });
    await waitFor(() => expect(result.current.status).toBe("stale"));
    expect(result.current.retained).toBe(true);
    expect(result.current.data?.items[0].id).toBe("retained-row");
  });

  it("clears retained rows synchronously when the authorized scope/query key changes", async () => {
    const nextScope = deferred<Envelope<Rows, ExposureCursorPagination>>();
    const load = vi.fn(({ signal }: { signal: AbortSignal }) => {
      if (load.mock.calls.length === 1) return Promise.resolve(envelope(["sub-a-row"]));
      expect(signal.aborted).toBe(false);
      return nextScope.promise;
    });
    const { result, rerender } = renderHook(
      ({ queryKey }) => useExposureSection({ queryKey, load }),
      { initialProps: { queryKey: "sub-a|all" } },
    );

    await waitFor(() => expect(result.current.data?.items[0].id).toBe("sub-a-row"));
    rerender({ queryKey: "sub-b|all" });

    expect(result.current.data).toBeNull();
    expect(result.current.status).toBe("loading");

    await act(async () => {
      nextScope.resolve(envelope(["sub-b-row"]));
    });
    await waitFor(() => expect(result.current.data?.items[0].id).toBe("sub-b-row"));
  });

  it("aborts the previous request and rejects its late response after a key change", async () => {
    const first = deferred<Envelope<Rows, ExposureCursorPagination>>();
    const second = deferred<Envelope<Rows, ExposureCursorPagination>>();
    const signals: AbortSignal[] = [];
    const load = vi.fn(({ signal }: { signal: AbortSignal }) => {
      signals.push(signal);
      return signals.length === 1 ? first.promise : second.promise;
    });
    const { result, rerender } = renderHook(
      ({ queryKey }) => useExposureSection({ queryKey, load }),
      { initialProps: { queryKey: "scope-a" } },
    );

    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    rerender({ queryKey: "scope-b" });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(signals[0].aborted).toBe(true);

    await act(async () => {
      first.resolve(envelope(["late-scope-a"]));
    });
    expect(result.current.data).toBeNull();

    await act(async () => {
      second.resolve(envelope(["current-scope-b"]));
    });
    await waitFor(() => {
      expect(result.current.data?.items[0].id).toBe("current-scope-b");
    });
  });

  it("distinguishes loading, healthy-empty, stale, partial, and unavailable locally", () => {
    const retry = vi.fn();
    const base = {
      envelope: null,
      data: null,
      error: null,
      loading: false,
      refreshing: false,
      retained: false,
      restart: { required: false, reason: "", generation: "" },
      retry,
    };
    const { rerender } = render(
      <SourceSectionState
        sourceName="AUM findings"
        itemLabel="findings"
        state={{ ...base, status: "loading", loading: true }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading AUM findings");
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");

    rerender(
      <SourceSectionState
        sourceName="AUM findings"
        itemLabel="findings"
        state={{
          ...base,
          status: "healthy-empty",
          envelope: envelope([], { state: "healthy-empty" }),
        }}
      />,
    );
    expect(screen.getByText("No findings reported by AUM findings")).toBeInTheDocument();

    rerender(
      <SourceSectionState
        sourceName="AUM findings"
        itemLabel="findings"
        state={{
          ...base,
          status: "stale",
          retained: true,
          data: envelope(["retained"]).data,
          envelope: envelope(["retained"], { state: "stale" }),
          error: new Error("Latest refresh failed"),
        }}
      >
        <p>retained</p>
      </SourceSectionState>,
    );
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText("retained")).toBeInTheDocument();

    rerender(
      <SourceSectionState
        sourceName="AUM findings"
        itemLabel="findings"
        state={{
          ...base,
          status: "partial",
          data: envelope(["represented"], {
            state: "partial",
            represented: 1,
            expected: 2,
            total: 4,
            excluded: 3,
            excludedReasons: ["connection-west unavailable"],
          }).data,
          envelope: envelope(["represented"], {
            state: "partial",
            represented: 1,
            expected: 2,
            total: 4,
            excluded: 3,
            excludedReasons: ["connection-west unavailable"],
          }),
        }}
      >
        <p>represented</p>
      </SourceSectionState>,
    );
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 connections represented/)).toBeInTheDocument();
    expect(screen.getByText(/1 represented · 4 total · 3 excluded/)).toBeInTheDocument();
    expect(screen.getByText(/connection-west unavailable/)).toBeInTheDocument();

    rerender(
      <SourceSectionState
        sourceName="AUM findings"
        itemLabel="findings"
        state={{
          ...base,
          status: "unavailable",
          error: new Error("Provider unavailable"),
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Other Exposure data remains available",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("0 findings");
  });

  it("keeps retry focus local and announces progress and completion", async () => {
    const recovered = deferred<Envelope<Rows, ExposureCursorPagination>>();
    const load = vi
      .fn()
      .mockRejectedValueOnce(new Error("AUM unavailable"))
      .mockReturnValueOnce(recovered.promise);

    function Harness() {
      const section = useExposureSection({
        queryKey: "sub-a|aum",
        load,
      });
      return <Section sourceName="AUM findings" section={section} />;
    }

    render(<Harness />);
    const retry = await screen.findByRole("button", { name: "Retry AUM findings" });
    retry.focus();
    fireEvent.click(retry);

    expect(document.activeElement).toBe(retry);
    expect(screen.getByRole("status")).toHaveTextContent("Retrying AUM findings");

    await act(async () => {
      recovered.resolve(envelope(["recovered-row"]));
    });
    expect(await screen.findByText("recovered-row")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("AUM findings is current");
  });

  it("formats known values with explicit units and never coerces unknown values to zero", () => {
    expect(formatExposureValue(null, { unit: "seconds" })).toBe("—");
    expect(formatExposureValue(undefined, { unit: "count", label: "findings" })).toBe("—");
    expect(formatExposureValue(90, { unit: "seconds" })).toBe("90 seconds");
    expect(formatExposureValue(1234, { unit: "count", label: "findings" })).toBe("1,234 findings");
    expect(formatExposureValue(0.25, { unit: "percent", ratio: true })).toBe("25.0%");
    expect(formatExposureValue(87, { unit: "risk" })).toBe("Risk score 87/100");
    expect(formatExposureValue(3, { unit: "rank" })).toBe("Rank 3");
  });

  it.todo(
    "renders all six Overview sections independently with conservative aggregate state [Plan 03.1-22]",
  );
  it.todo(
    "preserves scoped core truth when CVE or KB enrichment fails [Plan 03.1-25]",
  );
});
