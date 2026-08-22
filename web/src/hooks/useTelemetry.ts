"use client";

import { useCallback } from "react";

/**
 * Lightweight telemetry hook. Emits structured events to the console in
 * development and to `window.appInsights` (Azure Monitor Application
 * Insights JS SDK) when present, matching the API's own OpenTelemetry
 * philosophy: route/action names only, never payloads or PII.
 */

interface TelemetryEvent {
  name: string;
  properties?: Record<string, string | number | boolean>;
}

declare global {
  interface Window {
    appInsights?: {
      trackEvent: (event: { name: string }, properties?: Record<string, unknown>) => void;
      trackException: (payload: { exception: Error; properties?: Record<string, unknown> }) => void;
    };
  }
}

function emit(event: TelemetryEvent) {
  if (typeof window !== "undefined" && window.appInsights) {
    window.appInsights.trackEvent({ name: event.name }, event.properties);
    return;
  }
  if (process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.debug("[telemetry]", event.name, event.properties ?? {});
  }
}

function emitError(error: Error, properties?: Record<string, string | number | boolean>) {
  if (typeof window !== "undefined" && window.appInsights) {
    window.appInsights.trackException({ exception: error, properties });
    return;
  }
  if (process.env.NODE_ENV !== "production") {
    console.error("[telemetry:error]", error, properties ?? {});
  }
}

export function useTelemetry() {
  const trackEvent = useCallback((name: string, properties?: Record<string, string | number | boolean>) => {
    emit({ name, properties });
  }, []);

  const trackError = useCallback((error: Error, properties?: Record<string, string | number | boolean>) => {
    emitError(error, properties);
  }, []);

  return { trackEvent, trackError };
}
