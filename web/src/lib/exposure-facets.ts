import { type ExposureQueryState } from "./exposure-query-state";
import { SCOPE_DIMENSIONS } from "./scope";
import type { ExposureEnvelope, ExposureFacets } from "./types";

/** Rejects aggregate evidence outside the loaded scope/generation or count bounds. */
export function validateExposureFacets(result: Pick<ExposureEnvelope<ExposureFacets>, "data" | "scope">, query: ExposureQueryState): void {
  const agrees = (scope: Record<string, string[]>) => SCOPE_DIMENSIONS.every(dimension =>
    JSON.stringify([...(scope[dimension] ?? [])].sort()) === JSON.stringify([...(query.scope[dimension] ?? [])].sort()));
  const binding = result.data.contract?.query;
  if (!binding || result.data.generation !== query.generation || !agrees(result.scope)
    || !agrees(binding.scope) || binding.generation !== query.generation) {
    throw new Error("Exposure aggregates do not match the loaded scope and generation.");
  }
  if (!Number.isSafeInteger(result.data.total_count) || result.data.total_count < 0
    || Object.values(result.data.facets).some(rows => rows.some(row => !Number.isSafeInteger(row.count) || row.count < 0)
      || new Set(rows.map(row => row.value.toLowerCase())).size !== rows.length
      || rows.reduce((sum, row) => sum + row.count, 0) > result.data.total_count)) {
    throw new Error("Exposure aggregate counts are inconsistent.");
  }
}
