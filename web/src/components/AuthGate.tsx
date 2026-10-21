"use client";

import { AuthenticatedTemplate, UnauthenticatedTemplate, useIsAuthenticated, useMsal } from "@azure/msal-react";
import { Button, MessageBar, MessageBarBody, MessageBarTitle, Spinner, Text, tokens } from "@fluentui/react-components";
import { EventType, InteractionStatus, type EventMessage } from "@azure/msal-browser";
import { useEffect, useState } from "react";
import { apiLoginRequest, isMsalConfigured } from "@/lib/auth";

/**
 * Gates the workbench behind sign-in when an Entra app registration is
 * configured. Falls back to a dev-token banner + pass-through when it is
 * not, so local development works without a tenant (see lib/auth.ts).
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  if (!isMsalConfigured) {
    return (
      <div>
        <MessageBar intent="warning" layout="multiline" className="dev-auth-warning">
          <MessageBarBody>
            <MessageBarTitle>Development mode</MessageBarTitle>
            No Entra ID app registration configured (NEXT_PUBLIC_ENTRA_CLIENT_ID is unset). Using
            AIOPS_DEV_TOKEN for API calls. Do not use this configuration in production.
          </MessageBarBody>
        </MessageBar>
        {children}
      </div>
    );
  }

  return (
    <>
      <AuthenticatedTemplate>
        <AuthenticatedShell>{children}</AuthenticatedShell>
      </AuthenticatedTemplate>
      <UnauthenticatedTemplate>
        <SignInPrompt />
      </UnauthenticatedTemplate>
    </>
  );
}

/**
 * Holds the app back until MSAL has finished starting up.
 *
 * `AuthenticatedTemplate` renders as soon as a cached account exists, which
 * happens before `initialize()`/`handleRedirectPromise()` have resolved on a
 * browser refresh. Pages mount and immediately fire API calls against an
 * instance that cannot yet issue tokens, so the requests go out with no
 * Authorization header and the API rejects them with "A bearer token is
 * required". Waiting for `inProgress` to settle removes that startup race.
 */
function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const { inProgress } = useMsal();

  if (inProgress === InteractionStatus.Startup || inProgress === InteractionStatus.HandleRedirect) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: tokens.spacingVerticalXXL }}>
        <Spinner label="Restoring session..." />
      </div>
    );
  }

  return <>{children}</>;
}

function SignInPrompt() {
  const { instance, inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const [loginError, setLoginError] = useState<string | null>(null);

  // This MSAL version has no LOGIN_FAILURE event at all (only
  // ACQUIRE_TOKEN_FAILURE, which covers acquireToken* calls, not the
  // redirect-response processing done by handleRedirectPromise). MsalProvider
  // calls handleRedirectPromise() internally and discards any rejection
  // unconditionally, so a real Entra error (e.g. AADSTS...) on the way back
  // from sign-in is silently thrown away and the app just falls through to
  // showing this same sign-in screen again. handleRedirectPromise() caches
  // its result on the instance, so calling it a second time here is safe
  // (returns the same settled promise) and lets us actually see the error.
  useEffect(() => {
    const callbackId = instance.addEventCallback((message: EventMessage) => {
      if (message.eventType === EventType.ACQUIRE_TOKEN_FAILURE) {
        const description = (message.error as { errorMessage?: string; errorCode?: string } | null)?.errorMessage;
        const code = (message.error as { errorCode?: string } | null)?.errorCode;
        setLoginError(description ?? code ?? "Sign-in failed for an unknown reason.");
      }
    });

    instance.handleRedirectPromise().catch((error: unknown) => {
      const err = error as { errorMessage?: string; errorCode?: string; message?: string } | null;
      setLoginError(err?.errorMessage ?? err?.errorCode ?? err?.message ?? "Sign-in redirect failed for an unknown reason.");
    });

    return () => {
      if (callbackId) instance.removeEventCallback(callbackId);
    };
  }, [instance]);

  if (isAuthenticated) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "60vh",
        gap: tokens.spacingVerticalM,
      }}
    >
      <Text size={600} weight="semibold">
        Azure AI Operations Workbench
      </Text>
      <Text>Sign in with your organizational account to continue.</Text>
      {loginError ? (
        <MessageBar intent="error" style={{ maxWidth: 640 }}>
          <MessageBarBody>
            <MessageBarTitle>Sign-in failed</MessageBarTitle>
            {loginError}
          </MessageBarBody>
        </MessageBar>
      ) : null}
      {inProgress !== InteractionStatus.None ? (
        <Spinner label="Signing in..." />
      ) : (
        <Button
          appearance="primary"
          onClick={() => {
            setLoginError(null);
            void instance.loginRedirect(apiLoginRequest);
          }}
        >
          Sign in
        </Button>
      )}
    </div>
  );
}
