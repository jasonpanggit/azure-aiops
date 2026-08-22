"use client";

import { MsalProvider } from "@azure/msal-react";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { useMemo } from "react";
import { AuthGate } from "@/components/AuthGate";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { getMsalInstance, isMsalConfigured } from "@/lib/auth";

/**
 * Composition root for the app shell: MSAL auth provider, Fluent UI theming,
 * and a top-level error boundary. Rendered once from the root layout.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const msalInstance = useMemo(() => (isMsalConfigured ? getMsalInstance() : null), []);

  const content = (
    <FluentProvider theme={webLightTheme} style={{ minHeight: "100vh" }}>
      <ErrorBoundary>
        <AuthGate>{children}</AuthGate>
      </ErrorBoundary>
    </FluentProvider>
  );

  if (!msalInstance) {
    // No Entra app registration configured — render unauthenticated shell
    // (dev-token mode). AuthGate shows a configuration banner instead of
    // silently pretending sign-in succeeded.
    return content;
  }

  return <MsalProvider instance={msalInstance}>{content}</MsalProvider>;
}
