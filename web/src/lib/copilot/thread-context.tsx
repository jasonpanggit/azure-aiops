"use client";

import { EventType, type EventMessage } from "@azure/msal-browser";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { getMsalInstance, isMsalConfigured } from "@/lib/auth";
import { useScope } from "@/lib/scope-context";

/** The one same-tab storage entry used for opaque Copilot continuity. */
export const COPILOT_THREAD_STORAGE_KEY = "aiops.copilot.thread";

const OPAQUE_THREAD_PATTERN = /^thr-[a-f0-9]{32}$/;
const CONTINUITY_LOCK_PREFIX = "aiops.copilot.thread-ownership.";

/** A server-issued continuity handle. It contains no conversation or authority. */
export interface ThreadContinuity {
  threadId: string;
  threadRevision: number;
}

/** Server outcomes that deliberately discard the current continuity handle. */
export type ThreadResetReason = "not_found" | "session_end" | "manual";

/** Public operations and state exposed by the root continuity provider. */
export interface ThreadContinuityContextValue {
  thread: ThreadContinuity | null;
  requiresServerRevalidation: boolean;
  resetReason: ThreadResetReason | null;
  /** Increments whenever the current browser session discards continuity. */
  generation: number;
  acceptServerState: (
    thread: ThreadContinuity,
    expectedGeneration?: number,
  ) => boolean;
  resetContinuity: (reason?: ThreadResetReason) => void;
}

/** Props for the root-scoped, same-tab Copilot continuity provider. */
export interface ThreadContinuityProviderProps {
  children: ReactNode;
  /**
   * Storage area override for isolated tests. Production intentionally uses
   * this tab's sessionStorage and has no cross-tab or cross-device lookup.
   */
  storage?: Storage;
}

interface ProviderState {
  thread: ThreadContinuity | null;
  requiresServerRevalidation: boolean;
  resetReason: ThreadResetReason | null;
  generation: number;
}

interface StoredThread {
  thread_id: string;
  thread_revision: number;
}

const ThreadContext = createContext<ThreadContinuityContextValue | null>(null);
const pendingStoredThreads = new WeakMap<Storage, ThreadContinuity>();

function sessionStorageForThisTab(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function removeStoredThread(storage: Storage | null): void {
  if (!storage) return;
  try {
    storage.removeItem(COPILOT_THREAD_STORAGE_KEY);
  } catch {
    // Continuity is optional. A blocked storage area must not break the page.
  }
}

function parseStoredThread(storage: Storage | null): ThreadContinuity | null {
  if (!storage) return null;
  let raw: string | null;
  try {
    raw = storage.getItem(COPILOT_THREAD_STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("invalid continuity record");
    }
    const record = parsed as Partial<StoredThread> & Record<string, unknown>;
    const keys = Object.keys(record).sort();
    if (
      keys.length !== 2
      || keys[0] !== "thread_id"
      || keys[1] !== "thread_revision"
      || typeof record.thread_id !== "string"
      || !OPAQUE_THREAD_PATTERN.test(record.thread_id)
      || typeof record.thread_revision !== "number"
      || !Number.isSafeInteger(record.thread_revision)
      || record.thread_revision < 1
    ) {
      throw new Error("invalid continuity record");
    }
    return {
      threadId: record.thread_id,
      threadRevision: record.thread_revision,
    };
  } catch {
    removeStoredThread(storage);
    return null;
  }
}

function takeStoredThread(storage: Storage | null): ThreadContinuity | null {
  if (!storage) return null;
  const pending = pendingStoredThreads.get(storage);
  if (pending) return pending;
  const restored = parseStoredThread(storage);
  if (!restored) return null;
  removeStoredThread(storage);
  pendingStoredThreads.set(storage, restored);
  return restored;
}

function clearPendingStoredThread(storage: Storage | null): void {
  if (storage) pendingStoredThreads.delete(storage);
}

function persistThread(storage: Storage | null, thread: ThreadContinuity): void {
  if (!storage) return;
  const record: StoredThread = {
    thread_id: thread.threadId,
    thread_revision: thread.threadRevision,
  };
  try {
    storage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify(record));
  } catch {
    // In-memory continuity still works when sessionStorage is unavailable.
  }
}

function normalizedScopeFingerprint(scope: Record<string, string[]>): string {
  return JSON.stringify(
    Object.entries(scope)
      .filter(([, values]) => values.length > 0)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, values]) => [key, [...values].sort()]),
  );
}

function canCoordinateTabOwnership(): boolean {
  return (
    typeof navigator !== "undefined"
    && typeof navigator.locks?.request === "function"
    && typeof globalThis.crypto?.subtle?.digest === "function"
  );
}

async function continuityLockName(threadId: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(threadId),
  );
  const ownershipKey = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0")).join("");
  return `${CONTINUITY_LOCK_PREFIX}${ownershipKey}`;
}

/**
 * Carries only a server-issued opaque thread ID and revision across route
 * remounts in this browser tab. Stored state is never treated as proof of
 * ownership, scope, freshness, or authorization: a restored handle and every
 * scope change require the next server response to revalidate it.
 */
export function ThreadContinuityProvider({
  children,
  storage: suppliedStorage,
}: ThreadContinuityProviderProps) {
  const { scope } = useScope();
  const storage = suppliedStorage ?? sessionStorageForThisTab();
  const restoredThread = useRef<ThreadContinuity | null | undefined>(undefined);
  if (restoredThread.current === undefined) {
    restoredThread.current = takeStoredThread(storage);
  }
  const pendingRestore = useRef<ThreadContinuity | null>(
    restoredThread.current ?? null,
  );
  const [state, setState] = useState<ProviderState>(() => ({
    thread: null,
    requiresServerRevalidation: false,
    resetReason: null,
    generation: 0,
  }));
  const stateRef = useRef(state);
  const scopeFingerprint = normalizedScopeFingerprint(scope);
  const previousScopeFingerprint = useRef(scopeFingerprint);
  const ownershipAttempt = useRef(0);
  const heldOwnership = useRef<{
    threadId: string;
    release: () => void;
  } | null>(null);

  const replaceState = useCallback((next: ProviderState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const releaseOwnership = useCallback(() => {
    ownershipAttempt.current += 1;
    const held = heldOwnership.current;
    heldOwnership.current = null;
    held?.release();
  }, []);

  const resetContinuity = useCallback((
    reason: ThreadResetReason = "manual",
  ) => {
    pendingRestore.current = null;
    clearPendingStoredThread(storage);
    releaseOwnership();
    removeStoredThread(storage);
    const generation = stateRef.current.generation + 1;
    replaceState({
      thread: null,
      requiresServerRevalidation: false,
      resetReason: reason,
      generation,
    });
  }, [releaseOwnership, replaceState, storage]);

  const acceptServerState = useCallback((
    thread: ThreadContinuity,
    expectedGeneration?: number,
  ): boolean => {
    if (
      expectedGeneration !== undefined
      && expectedGeneration !== stateRef.current.generation
    ) {
      return false;
    }
    if (
      !OPAQUE_THREAD_PATTERN.test(thread.threadId)
      || !Number.isSafeInteger(thread.threadRevision)
      || thread.threadRevision < 1
    ) {
      resetContinuity("not_found");
      return false;
    }
    const current = stateRef.current.thread;
    if (
      current
      && current.threadId === thread.threadId
      && thread.threadRevision < current.threadRevision
    ) {
      return false;
    }
    pendingRestore.current = null;
    clearPendingStoredThread(storage);
    if (heldOwnership.current?.threadId !== thread.threadId) {
      releaseOwnership();
      removeStoredThread(storage);
    } else {
      persistThread(storage, thread);
    }
    replaceState({
      thread,
      requiresServerRevalidation: false,
      resetReason: null,
      generation: stateRef.current.generation,
    });
    return true;
  }, [releaseOwnership, replaceState, resetContinuity, storage]);

  const acquireOwnership = useCallback((
    thread: ThreadContinuity,
    restoring: boolean,
  ) => {
    if (!canCoordinateTabOwnership()) {
      if (restoring && pendingRestore.current === thread) {
        pendingRestore.current = null;
        clearPendingStoredThread(storage);
        removeStoredThread(storage);
        replaceState({
          thread: null,
          requiresServerRevalidation: false,
          resetReason: null,
          generation: stateRef.current.generation + 1,
        });
      } else {
        removeStoredThread(storage);
      }
      return;
    }
    if (heldOwnership.current?.threadId === thread.threadId) return;

    releaseOwnership();
    const attempt = ownershipAttempt.current;
    void continuityLockName(thread.threadId).then(async (lockName) => {
      if (attempt !== ownershipAttempt.current) return;
      await navigator.locks.request(
        lockName,
        { mode: "exclusive", ifAvailable: true },
        async (lock) => {
          if (attempt !== ownershipAttempt.current) return;
          if (!lock) {
            if (
              pendingRestore.current === thread
              || stateRef.current.thread?.threadId === thread.threadId
            ) {
              pendingRestore.current = null;
              clearPendingStoredThread(storage);
              removeStoredThread(storage);
              replaceState({
                thread: null,
                requiresServerRevalidation: false,
                resetReason: null,
                generation: stateRef.current.generation + 1,
              });
            }
            return;
          }

          let releaseLock: (() => void) | undefined;
          const lockLifetime = new Promise<void>((resolve) => {
            releaseLock = resolve;
          });
          heldOwnership.current = {
            threadId: thread.threadId,
            release: () => releaseLock?.(),
          };
          if (pendingRestore.current === thread) {
            pendingRestore.current = null;
            clearPendingStoredThread(storage);
            persistThread(storage, thread);
            replaceState({
              ...stateRef.current,
              thread,
              requiresServerRevalidation: true,
            });
          } else if (
            stateRef.current.thread?.threadId === thread.threadId
          ) {
            persistThread(storage, stateRef.current.thread);
          }
          await lockLifetime;
        },
      );
    }).catch(() => {
      if (attempt !== ownershipAttempt.current) return;
      removeStoredThread(storage);
      if (pendingRestore.current === thread) {
        pendingRestore.current = null;
        clearPendingStoredThread(storage);
        replaceState({
          thread: null,
          requiresServerRevalidation: false,
          resetReason: null,
          generation: stateRef.current.generation + 1,
        });
      }
    });
  }, [releaseOwnership, replaceState, storage]);

  useEffect(() => {
    const candidate = state.thread ?? pendingRestore.current;
    if (!candidate) return;
    acquireOwnership(candidate, pendingRestore.current === candidate);
  }, [acquireOwnership, state.thread]);

  useEffect(() => () => {
    releaseOwnership();
  }, [releaseOwnership]);

  useEffect(() => {
    if (previousScopeFingerprint.current === scopeFingerprint) return;
    previousScopeFingerprint.current = scopeFingerprint;
    const current = stateRef.current;
    if (!current.thread || current.requiresServerRevalidation) return;
    replaceState({
      ...current,
      requiresServerRevalidation: true,
    });
  }, [replaceState, scopeFingerprint]);

  useEffect(() => {
    if (!isMsalConfigured) return undefined;
    const instance = getMsalInstance();
    const callbackId = instance.addEventCallback((message: EventMessage) => {
      if (
        message.eventType === EventType.LOGOUT_START
        || message.eventType === EventType.LOGOUT_SUCCESS
        || message.eventType === EventType.LOGOUT_END
      ) {
        resetContinuity("session_end");
      }
    });
    return () => {
      if (callbackId) instance.removeEventCallback(callbackId);
    };
  }, [resetContinuity]);

  const value = useMemo<ThreadContinuityContextValue>(() => ({
    thread: state.thread,
    requiresServerRevalidation: state.requiresServerRevalidation,
    resetReason: state.resetReason,
    generation: state.generation,
    acceptServerState,
    resetContinuity,
  }), [acceptServerState, resetContinuity, state]);

  return <ThreadContext.Provider value={value}>{children}</ThreadContext.Provider>;
}

/**
 * Returns the same-tab opaque continuity handle and server-validation controls.
 *
 * @throws When called outside {@link ThreadContinuityProvider}.
 */
export function useThreadContinuity(): ThreadContinuityContextValue {
  const context = useContext(ThreadContext);
  if (!context) {
    throw new Error(
      "useThreadContinuity must be used within a ThreadContinuityProvider",
    );
  }
  return context;
}

/**
 * Returns the continuity provider when present, or null for isolated renders.
 *
 * Production composition always supplies {@link ThreadContinuityProvider};
 * this seam lets leaf components remain testable without weakening the strict
 * {@link useThreadContinuity} contract.
 */
export function useOptionalThreadContinuity(): ThreadContinuityContextValue | null {
  return useContext(ThreadContext);
}
