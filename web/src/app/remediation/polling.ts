"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Bounded Polling Contract (Phase 03.6 UI-SPEC).
 *
 * Deterministic backoff sequence -- doubles each consecutive non-terminal
 * refresh of the *same* execution, capped at 30000ms. No jitter, so tests
 * can assert the exact sequence.
 */
export const POLLING_BACKOFF_SEQUENCE_MS = [1500, 3000, 6000, 12000, 24000, 30000];

/** Ceiling: stop -- permanently, until a manual check or a plan/selection
 * change resets it -- the moment either 40 consecutive poll requests have
 * been issued, or 600000ms (10 minutes) have elapsed since the first poll,
 * whichever comes first. */
export const POLLING_MAX_REQUESTS = 40;
export const POLLING_MAX_ELAPSED_MS = 600_000;

export interface UsePollingBackoffOptions {
  /** True while the execution is still queued/running/retrying -- i.e.
   * still eligible for automatic polling. */
  active: boolean;
  /** Changes whenever a fresh execution should get its own full bounded
   * polling budget (e.g. `${selectedPlanId}:${executionId}`). */
  resetKey: string;
  /** Called once per scheduled poll (and once per manual "Check now"
   * click) to perform the actual refresh. */
  onPoll: () => void;
  /** Injectable clock, used ONLY to measure elapsed time since the first
   * poll for the current execution -- never used to schedule the
   * `setTimeout` delays themselves, which remain driven by the fixed
   * backoff sequence above. Defaults to `Date.now` in production. */
  now?: () => number;
}

export interface UsePollingBackoffResult {
  /** True once the ceiling (40 requests or 600000ms elapsed) has been
   * reached -- automatic polling has stopped until a manual check or a
   * plan/execution change resets it. */
  paused: boolean;
  /** Number of automatic poll requests issued for the current
   * `resetKey`. */
  requestCount: number;
  /** Performs exactly one manual refresh. Does NOT resume the automatic
   * interval -- the operator must click again for each subsequent check
   * once paused. */
  checkNow: () => void;
}

export function usePollingBackoff({
  active,
  resetKey,
  onPoll,
  now = Date.now,
}: UsePollingBackoffOptions): UsePollingBackoffResult {
  const countRef = useRef(0);
  const firstPollAtRef = useRef<number | null>(null);
  const lastResetKeyRef = useRef(resetKey);
  const [paused, setPaused] = useState(false);
  const [requestCount, setRequestCount] = useState(0);

  useEffect(() => {
    if (lastResetKeyRef.current !== resetKey) {
      lastResetKeyRef.current = resetKey;
      countRef.current = 0;
      firstPollAtRef.current = null;
      if (paused || requestCount !== 0) {
        if (paused) setPaused(false);
        if (requestCount !== 0) setRequestCount(0);
        // Wait for the re-render reflecting the reset state before
        // scheduling -- both flags reset together, in one commit.
        return;
      }
    }
    if (!active || paused) return;
    if (firstPollAtRef.current === null) firstPollAtRef.current = now();
    const elapsed = now() - firstPollAtRef.current;
    if (countRef.current >= POLLING_MAX_REQUESTS || elapsed >= POLLING_MAX_ELAPSED_MS) {
      setPaused(true);
      return;
    }
    const delayIndex = Math.min(countRef.current, POLLING_BACKOFF_SEQUENCE_MS.length - 1);
    const delay = POLLING_BACKOFF_SEQUENCE_MS[delayIndex];
    const timer = setTimeout(() => {
      countRef.current += 1;
      setRequestCount(countRef.current);
      onPoll();
    }, delay);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, resetKey, requestCount, paused, now, onPoll]);

  const checkNow = () => {
    onPoll();
  };

  return { paused, requestCount, checkNow };
}
