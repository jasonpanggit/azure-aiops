export const HANDLER_TIMING_HEADER = "x-aiops-handler-ms";
export const SERVER_HANDLER_P95_BUDGET_MS = 1_000;
export const HTTP_P95_BUDGET_MS = 3_000;
export const LATENCY_SAMPLE_COUNT = 5;

export interface LatencyDistribution {
  samplesMs: number[];
  sortedMs: number[];
  p95Ms: number;
}

export function handlerDurationMs(value: string | undefined): number {
  if (!value || !/^(?:0|[1-9]\d*)\.\d{3}$/.test(value)) {
    throw new Error(
      `X-AIOPS-Handler-Ms must be a non-negative millisecond value with three decimal places; received ${JSON.stringify(value)}`,
    );
  }
  return Number(value);
}

export function latencyDistribution(samplesMs: number[]): LatencyDistribution {
  if (samplesMs.length !== LATENCY_SAMPLE_COUNT) {
    throw new Error(
      `Topology latency requires exactly ${LATENCY_SAMPLE_COUNT} samples; received ${samplesMs.length}`,
    );
  }
  if (
    samplesMs.some(
      (sample) => !Number.isFinite(sample) || sample < 0,
    )
  ) {
    throw new Error("Topology latency samples must be finite and non-negative");
  }

  const sortedMs = [...samplesMs].sort((left, right) => left - right);
  return {
    samplesMs: [...samplesMs],
    sortedMs,
    p95Ms: sortedMs[Math.ceil(sortedMs.length * 0.95) - 1],
  };
}
