import { describe, expect, it } from "vitest";

import {
  HANDLER_TIMING_HEADER,
  HTTP_P95_BUDGET_MS,
  LATENCY_SAMPLE_COUNT,
  SERVER_HANDLER_P95_BUDGET_MS,
  handlerDurationMs,
  latencyDistribution,
} from "./network-topology-latency";

describe("network topology latency acceptance", () => {
  it("calculates independent five-sample server and HTTP p95 distributions", () => {
    const server = latencyDistribution([430.5, 610.25, 590, 720.75, 680]);
    const http = latencyDistribution([1_646, 1_794, 1_702, 1_688, 1_731]);

    expect(server).toEqual({
      samplesMs: [430.5, 610.25, 590, 720.75, 680],
      sortedMs: [430.5, 590, 610.25, 680, 720.75],
      p95Ms: 720.75,
    });
    expect(http).toEqual({
      samplesMs: [1_646, 1_794, 1_702, 1_688, 1_731],
      sortedMs: [1_646, 1_688, 1_702, 1_731, 1_794],
      p95Ms: 1_794,
    });
  });

  it("keeps both budgets strict at their exact boundaries", () => {
    expect(LATENCY_SAMPLE_COUNT).toBe(5);
    expect(999.999).toBeLessThan(SERVER_HANDLER_P95_BUDGET_MS);
    expect(1_000).not.toBeLessThan(SERVER_HANDLER_P95_BUDGET_MS);
    expect(2_999.999).toBeLessThan(HTTP_P95_BUDGET_MS);
    expect(3_000).not.toBeLessThan(HTTP_P95_BUDGET_MS);
  });

  it.each([
    [[]],
    [[1, 2, 3, 4]],
    [[1, 2, 3, 4, 5, 6]],
  ])("rejects a distribution with %s samples", (samples) => {
    expect(() => latencyDistribution(samples)).toThrow(
      /exactly 5 samples/,
    );
  });

  it("accepts only the non-negative decimal handler header contract", () => {
    expect(HANDLER_TIMING_HEADER).toBe("x-aiops-handler-ms");
    expect(handlerDurationMs("0.000")).toBe(0);
    expect(handlerDurationMs("987.654")).toBe(987.654);

    for (const malformed of [
      undefined,
      "",
      "-1.000",
      "1000",
      "1e3",
      "NaN",
      "Infinity",
      " 1.000",
    ]) {
      expect(() => handlerDurationMs(malformed)).toThrow(
        /X-AIOPS-Handler-Ms/,
      );
    }
  });
});
