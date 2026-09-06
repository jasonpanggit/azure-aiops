"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { exposureRestartFromError, type ExposureRestartState } from "@/lib/exposure-query-state";
import type {
  Envelope,
  ExposureCommonContract,
  ExposureCompleteness,
  ExposureCursorPagination,
  ExposureFreshness,
} from "@/lib/types";

export type ExposureSectionStatus =
  | "loading"
  | "current"
  | "healthy-empty"
  | "stale"
  | "partial"
  | "unavailable";

export interface ExposureSectionMetadata {
  loaded?: number;
  represented?: number;
  expected?: number;
  total?: number;
  excluded?: number;
  excludedReasons: string[];
  observedAt: string;
  freshnessState: string;
  freshnessSourceFamily: string;
  freshnessThresholdSeconds?: number;
  safeErrorMessage: string;
}

export interface ExposureSectionPresentation {
  status: ExposureSectionStatus;
  error: Error | null;
  loading: boolean;
  refreshing: boolean;
  retrying: boolean;
  retained: boolean;
  metadata: ExposureSectionMetadata;
  restart: ExposureRestartState;
  retry: () => void;
}

export interface ExposureSectionResult<T> extends ExposureSectionPresentation {
  envelope: Envelope<T, ExposureCursorPagination> | null;
  data: T | null;
}

export interface UseExposureSectionOptions<T> {
  /** Includes effective authorized scope plus every server query binding. */
  queryKey: string;
  /**
   * Excludes only opaque page position. Keeping this stable allows current
   * rows to remain visible while a next/previous cursor request is pending.
   */
  retentionKey?: string;
  load: (request: {
    signal: AbortSignal;
    queryKey: string;
  }) => Promise<Envelope<T, ExposureCursorPagination>>;
  refreshKey?: string | number;
  isEmpty?: (data: T) => boolean;
}

interface RequestState<T> {
  queryKey: string;
  retentionKey: string;
  envelope: Envelope<T, ExposureCursorPagination> | null;
  error: Error | null;
  loading: boolean;
  retrying: boolean;
}

const EMPTY_METADATA: ExposureSectionMetadata = {
  excludedReasons: [],
  observedAt: "",
  freshnessState: "unknown",
  freshnessSourceFamily: "",
  safeErrorMessage: "",
};

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function contractFrom<T>(
  envelope: Envelope<T, ExposureCursorPagination> | null,
): ExposureCommonContract | null {
  const data = record(envelope?.data);
  return (record(data?.contract) as ExposureCommonContract | null) ?? null;
}

function completenessFrom<T>(
  envelope: Envelope<T, ExposureCursorPagination> | null,
): ExposureCompleteness {
  const data = record(envelope?.data);
  const contract = contractFrom(envelope);
  return (
    (record(contract?.completeness) as ExposureCompleteness | null) ??
    (record(data?.completeness) as ExposureCompleteness | null) ??
    { state: "unknown" }
  );
}

function freshnessFrom<T>(
  envelope: Envelope<T, ExposureCursorPagination> | null,
): ExposureFreshness {
  const data = record(envelope?.data);
  const contract = contractFrom(envelope);
  return (
    (record(contract?.freshness) as ExposureFreshness | null) ??
    (record(data?.freshness) as ExposureFreshness | null) ??
    { state: "unknown" }
  );
}

function metadataFrom<T>(
  envelope: Envelope<T, ExposureCursorPagination> | null,
): ExposureSectionMetadata {
  if (!envelope) return EMPTY_METADATA;
  const contract = contractFrom(envelope);
  const completeness = completenessFrom(envelope);
  const freshness = freshnessFrom(envelope);
  const safeError = record(contract?.safe_error);
  const firstThreshold = Array.isArray(freshness.thresholds)
    ? freshness.thresholds[0]
    : undefined;
  const excludedReasons = Array.isArray(completeness.excluded_reasons)
    ? completeness.excluded_reasons.filter(
        (reason): reason is string => typeof reason === "string" && Boolean(reason),
      )
    : [];
  return {
    loaded: finiteNumber(contract?.counts.returned),
    represented:
      finiteNumber(completeness.represented) ??
      finiteNumber(completeness.represented_count) ??
      finiteNumber(completeness.represented_connections) ??
      finiteNumber(contract?.counts.represented),
    expected:
      finiteNumber(completeness.expected) ??
      finiteNumber(completeness.expected_count) ??
      finiteNumber(completeness.expected_connections),
    total:
      finiteNumber(completeness.total) ??
      finiteNumber(completeness.total_count) ??
      finiteNumber(contract?.counts.total),
    excluded:
      finiteNumber(completeness.excluded) ??
      finiteNumber(completeness.excluded_count) ??
      finiteNumber(contract?.counts.excluded),
    excludedReasons,
    observedAt: stringValue(freshness.as_of),
    freshnessState: stringValue(freshness.state) || "unknown",
    freshnessSourceFamily:
      stringValue(freshness.source_family) ||
      stringValue(firstThreshold?.source_family),
    freshnessThresholdSeconds:
      finiteNumber(freshness.threshold_seconds) ??
      finiteNumber(firstThreshold?.threshold_seconds),
    safeErrorMessage: stringValue(safeError?.message),
  };
}

function defaultIsEmpty(value: unknown): boolean {
  if (Array.isArray(value)) return value.length === 0;
  const data = record(value);
  if (!data) return false;
  const total = finiteNumber(data.total_count);
  if (total !== undefined) return total === 0;
  for (const key of ["items", "findings", "rows"]) {
    if (Array.isArray(data[key])) return data[key].length === 0;
  }
  return false;
}

function successfulStatus<T>(
  envelope: Envelope<T, ExposureCursorPagination>,
  isEmpty: (data: T) => boolean,
): ExposureSectionStatus {
  const contract = contractFrom(envelope);
  const completeness = completenessFrom(envelope);
  const freshness = freshnessFrom(envelope);
  const completenessState = stringValue(completeness.state).toLowerCase();
  const freshnessState = stringValue(freshness.state).toLowerCase();
  const safeError = record(contract?.safe_error);
  const empty = isEmpty(envelope.data);

  if (completenessState === "unavailable") {
    return empty ? "unavailable" : "partial";
  }
  if (
    completenessState === "partial" ||
    freshnessState === "partial" ||
    safeError
  ) {
    return "partial";
  }
  if (
    completenessState === "stale" ||
    freshnessState === "stale" ||
    freshnessState === "aging"
  ) {
    return empty ? "unavailable" : "stale";
  }
  if (
    empty &&
    (completenessState === "healthy-empty" ||
      (completenessState === "complete" &&
        ["current", "fresh", "reported"].includes(freshnessState)))
  ) {
    return "healthy-empty";
  }
  if (empty) return "unavailable";
  return completenessState === "complete" &&
    ["current", "fresh", "reported"].includes(freshnessState)
    ? "current"
    : "partial";
}

function errorValue(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

/**
 * Loads one independently useful Exposure section.
 *
 * Retained rows are visible only while the exact query key is still active.
 * Key changes hide previous data synchronously, abort the old request, and
 * sequence-guard late responses even if the transport ignores AbortSignal.
 */
export function useExposureSection<T>({
  queryKey,
  retentionKey = queryKey,
  load,
  refreshKey = 0,
  isEmpty = defaultIsEmpty,
}: UseExposureSectionOptions<T>): ExposureSectionResult<T> {
  const [requestState, setRequestState] = useState<RequestState<T>>({
    queryKey: "",
    retentionKey: "",
    envelope: null,
    error: null,
    loading: true,
    retrying: false,
  });
  const [retryNonce, setRetryNonce] = useState(0);
  const requestIdRef = useRef(0);
  const loadRef = useRef(load);
  const isEmptyRef = useRef(isEmpty);
  loadRef.current = load;
  isEmptyRef.current = isEmpty;

  const retry = useCallback(() => {
    setRetryNonce((value) => value + 1);
  }, []);

  useEffect(() => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    const controller = new AbortController();

    setRequestState((previous) => {
      const sameRetentionBoundary = previous.retentionKey === retentionKey;
      return {
        queryKey,
        retentionKey,
        envelope: sameRetentionBoundary ? previous.envelope : null,
        error: null,
        loading: true,
        retrying:
          previous.queryKey === queryKey && previous.error !== null,
      };
    });

    loadRef
      .current({ signal: controller.signal, queryKey })
      .then((envelope) => {
        if (controller.signal.aborted || requestIdRef.current !== requestId) return;
        setRequestState({
          queryKey,
          retentionKey,
          envelope,
          error: null,
          loading: false,
          retrying: false,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || requestIdRef.current !== requestId) return;
        setRequestState((previous) => ({
          queryKey,
          retentionKey,
          envelope:
            previous.retentionKey === retentionKey ? previous.envelope : null,
          error: errorValue(error),
          loading: false,
          retrying: false,
        }));
      });

    return () => {
      controller.abort();
    };
  }, [queryKey, retentionKey, refreshKey, retryNonce]);

  const activeEnvelope =
    requestState.retentionKey === retentionKey ? requestState.envelope : null;
  const activeError =
    requestState.queryKey === queryKey ? requestState.error : null;
  const loading =
    requestState.queryKey !== queryKey || requestState.loading;
  const retained = Boolean(activeEnvelope && activeError);
  const status: ExposureSectionStatus = (() => {
    if (activeError) return activeEnvelope ? "stale" : "unavailable";
    if (!activeEnvelope) return "loading";
    return successfulStatus(activeEnvelope, isEmptyRef.current);
  })();

  return {
    envelope: activeEnvelope,
    data: activeEnvelope?.data ?? null,
    error: activeError,
    loading,
    refreshing: loading && activeEnvelope !== null,
    retrying:
      requestState.queryKey === queryKey && requestState.retrying,
    retained,
    status,
    metadata: metadataFrom(activeEnvelope),
    restart: exposureRestartFromError(activeError),
    retry,
  };
}
