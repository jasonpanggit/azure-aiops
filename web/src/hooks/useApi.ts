"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/types";

interface UseApiState<T> {
  data: T | null;
  error: ApiError | Error | null;
  loading: boolean;
  refetch: () => void;
}

const REFETCH_DEBOUNCE_MS = 400;

/**
 * Fetches data through a supplied loader whenever its dependency list
 * changes (typically the global scope). Distinguishes ApiError (including
 * `isNotImplemented` for 501 contract stubs) from unexpected exceptions so
 * views can render honest empty/unavailable states instead of blank UI.
 */
export function useApi<T>(loader: () => Promise<T>, deps: React.DependencyList): UseApiState<T> {
  const [state, setState] = useState<Omit<UseApiState<T>, "refetch">>({
    data: null,
    error: null,
    loading: true,
  });
  const [refetchNonce, setRefetchNonce] = useState(0);
  const loaderRef = useRef(loader);
  const refetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  loaderRef.current = loader;

  const refetch = useCallback(() => {
    if (refetchTimerRef.current !== null) {
      clearTimeout(refetchTimerRef.current);
    }
    refetchTimerRef.current = setTimeout(() => {
      refetchTimerRef.current = null;
      setRefetchNonce((value) => value + 1);
    }, REFETCH_DEBOUNCE_MS);
  }, []);

  useEffect(
    () => () => {
      if (refetchTimerRef.current !== null) {
        clearTimeout(refetchTimerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loaderRef
      .current()
      .then((data) => {
        if (!cancelled) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            data: null,
            error: error instanceof Error ? error : new Error(String(error)),
            loading: false,
          });
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refetchNonce]);

  return { ...state, refetch };
}

export { ApiError };
