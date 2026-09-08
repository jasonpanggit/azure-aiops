"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/types";

interface UseApiState<T> {
  data: T | null;
  dataDependencies: React.DependencyList | null;
  error: ApiError | Error | null;
  loading: boolean;
  refetch: () => void;
  cancel: () => void;
}

interface UseApiOptions {
  retainDataOnDependencyChange?: (
    previous: React.DependencyList,
    next: React.DependencyList,
  ) => boolean;
}

const REFETCH_DEBOUNCE_MS = 400;

/**
 * Fetches data through a supplied loader whenever its dependency list
 * changes (typically the global scope). Distinguishes ApiError (including
 * `isNotImplemented` for 501 contract stubs) from unexpected exceptions so
 * views can render honest empty/unavailable states instead of blank UI.
 */
export function useApi<T>(
  loader: (signal?: AbortSignal) => Promise<T>,
  deps: React.DependencyList,
  options: UseApiOptions = {},
): UseApiState<T> {
  const [state, setState] = useState<
    Omit<UseApiState<T>, "refetch" | "cancel">
  >({
    data: null,
    dataDependencies: null,
    error: null,
    loading: true,
  });
  const [refetchNonce, setRefetchNonce] = useState(0);
  const loaderRef = useRef(loader);
  const optionsRef = useRef(options);
  const activeControllerRef = useRef<AbortController | null>(null);
  const refetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previousDepsRef = useRef<React.DependencyList | null>(null);
  loaderRef.current = loader;
  optionsRef.current = options;

  const refetch = useCallback(() => {
    if (refetchTimerRef.current !== null) {
      clearTimeout(refetchTimerRef.current);
    }
    refetchTimerRef.current = setTimeout(() => {
      refetchTimerRef.current = null;
      setRefetchNonce((value) => value + 1);
    }, REFETCH_DEBOUNCE_MS);
  }, []);

  const cancel = useCallback(() => {
    activeControllerRef.current?.abort();
    setState((prev) => ({ ...prev, loading: false, error: null }));
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
    const controller = new AbortController();
    activeControllerRef.current = controller;
    const previousDeps = previousDepsRef.current;
    const dependencyChanged =
      previousDeps === null ||
      previousDeps.length !== deps.length ||
      deps.some((dependency, index) => !Object.is(dependency, previousDeps[index]));
    const retainData =
      dependencyChanged &&
      previousDeps !== null &&
      Boolean(
        optionsRef.current.retainDataOnDependencyChange?.(
          previousDeps,
          deps,
        ),
      );
    previousDepsRef.current = [...deps];
    setState((prev) => ({
      data: dependencyChanged && !retainData ? null : prev.data,
      dataDependencies:
        dependencyChanged && !retainData ? null : prev.dataDependencies,
      loading: true,
      error: null,
    }));
    loaderRef
      .current(controller.signal)
      .then((data) => {
        if (!cancelled && !controller.signal.aborted) {
          setState({
            data,
            dataDependencies: [...deps],
            error: null,
            loading: false,
          });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled && !controller.signal.aborted) {
          setState((prev) => ({
            data: retainData ? prev.data : null,
            dataDependencies: retainData ? prev.dataDependencies : null,
            error: error instanceof Error ? error : new Error(String(error)),
            loading: false,
          }));
        }
      });
    return () => {
      cancelled = true;
      controller.abort();
      if (activeControllerRef.current === controller) {
        activeControllerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refetchNonce]);

  return { ...state, refetch, cancel };
}

export { ApiError };
