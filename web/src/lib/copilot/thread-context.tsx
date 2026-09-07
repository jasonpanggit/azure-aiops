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
  acceptServerState: (thread: ThreadContinuity) => boolean;
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
}

interface StoredThread {
  thread_id: string;
  thread_revision: number;
}

const ThreadContext = createContext<ThreadContinuityContextValue | null>(null);

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
  const restoredThread = useRef<ThreadContinuity | undefined>(undefined);
  if (restoredThread.current === undefined) {
    restoredThread.current = parseStoredThread(storage) ?? null;
  }
  const [state, setState] = useState<ProviderState>(() => ({
    thread: restoredThread.current ?? null,
    requiresServerRevalidation: Boolean(restoredThread.current),
    resetReason: null,
  }));
  const stateRef = useRef(state);
  const scopeFingerprint = normalizedScopeFingerprint(scope);
  const previousScopeFingerprint = useRef(scopeFingerprint);

  const replaceState = useCallback((next: ProviderState) => {
    stateRef.current = next;
    setState(next);
  }, []);

  const resetContinuity = useCallback((
    reason: ThreadResetReason = "manual",
  ) => {
    removeStoredThread(storage);
    replaceState({
      thread: null,
      requiresServerRevalidation: false,
      resetReason: reason,
    });
  }, [replaceState, storage]);

  const acceptServerState = useCallback((thread: ThreadContinuity): boolean => {
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
    persistThread(storage, thread);
    replaceState({
      thread,
      requiresServerRevalidation: false,
      resetReason: null,
    });
    return true;
  }, [replaceState, resetContinuity, storage]);

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
